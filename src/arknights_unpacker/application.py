"""Application use cases shared by the desktop and the command-line verifier."""
from __future__ import annotations

from dataclasses import fields, replace
import json
from pathlib import Path
import sqlite3
import time
import uuid

from .contracts import (BuildSpec, CancelToken, DecodedTable, EntityChangeSet,
                        ExportFormat, ExtractionRequest, ExtractionResult,
                        GameDataSnapshot, ReportOptions, ReportSelection, ResourceCatalog,
                        ScanOptions, SourceRef, TableSourceSet, as_jsonable,
                        null_progress)
from .jobs import WorkerRunner
from .paths import (atomic_json, default_data_root, default_output_root, migrate_legacy_data,
                    validate_data_root, validate_output)


def _dataclass_from_dict(cls, value):
    keys = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in value.items() if k in keys})


def table_sources_from_dict(value):
    tables = {}
    for name, item in value.get("tables", {}).items():
        item = dict(item)
        item["source"] = _dataclass_from_dict(SourceRef, item.get("source", {}))
        tables[name] = _dataclass_from_dict(DecodedTable, item)
    return TableSourceSet(tables=tables, version=value.get("version", "unknown"),
                          resource_version=value.get("resource_version", "unknown"),
                          complete=value.get("complete", False), diagnostics=value.get("diagnostics", []),
                          locale=value.get("locale", "unknown"))


class AppServices:
    def __init__(self, data_root: str | Path | None = None, output_root: str | Path | None = None):
        from .library import CatalogStore
        self.data_root = validate_data_root(Path(data_root) if data_root else default_data_root())
        try:
            if data_root is None:
                migrate_legacy_data(self.data_root)
            self.data_root.mkdir(parents=True, exist_ok=True)
            probe = self.data_root / ('.write-test-' + uuid.uuid4().hex)
            with probe.open('xb'):
                pass
            probe.unlink()
            self.store = CatalogStore(self.data_root / "catalog.sqlite3")
            self.runner = WorkerRunner(self.data_root / "jobs")
        except (OSError, sqlite3.Error) as error:
            raise PermissionError(f"无法读写运行数据目录 {self.data_root}：{error}。请将程序放在可写目录，或使用 --data-dir 指定可写目录。") from error
        self.config_file = self.data_root / "settings.json"
        self.config = {"game_root": "", "output_root": str(default_output_root()),
                       "hours": 24.0, "report_width": 1200, "report_font_size": 28,
                       "report_theme": "dark", "report_font_path": "", "report_font_index": 0, "monitor": False,
                       "formats": ["png", "html"], "extraction_mode": "auto",
                       "data_locale": "unknown",
                       "extraction_kinds": ["image", "text", "audio", "spine"]}
        if self.config_file.exists():
            try:
                self.config.update(json.loads(self.config_file.read_text(encoding="utf-8")))
            except (ValueError, OSError):
                pass
        saved_output = self.config.get("output_root")
        default_output = default_output_root()
        legacy_output = Path.home() / "Documents" / "ArknightsExports"
        if output_root is not None:
            self.config["output_root"] = str(Path(output_root).expanduser().resolve())
        elif not saved_output or not str(saved_output).strip() or Path(saved_output).expanduser().resolve() == legacy_output.resolve():
            self.config["output_root"] = str(default_output)
        if Path(self.config["output_root"]).expanduser().resolve() == default_output.resolve():
            output = validate_output(validate_data_root(default_output), self.config.get("game_root"))
            try:
                output.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                raise PermissionError(f"无法创建默认输出目录 {output}：{error}。请将程序放在可写目录。") from error
        if self.config.get("output_root") != saved_output:
            self.save_config()
        self.installation = None
        self.scan_snapshot = None
        self.file_changes = None
        self.catalog = None
        self.gameplay_catalog = None
        self.gamedata = None
        self.entity_changes = None
        self.baseline = None

    def save_config(self):
        try:
            atomic_json(self.config_file, self.config)
        except OSError as error:
            raise PermissionError(f"无法保存运行数据到 {self.data_root}：{error}。请使用可写目录或 --data-dir。") from error

    def _select_installation(self, installation):
        validate_output(self.data_root, installation.root)
        if self.installation is None or self.installation.profile_id != installation.profile_id:
            self.scan_snapshot = None
            self.file_changes = None
            self.catalog = None
            self.gameplay_catalog = None
            self.gamedata = None
            self.entity_changes = None
            self.baseline = None
        self.installation = installation
        self.store.save_installation(installation)
        self.config["game_root"] = str(installation.root)
        self.save_config()
        return installation

    def _installation(self, root):
        from .library import discover_installation
        return self._select_installation(discover_installation(Path(root)))

    def restore(self, root, emit=null_progress, cancel=None):
        """Restore the last visible observation and diff without scanning/decoding.

        Complete baseline queries remain separate, so reopening a partial result
        cannot make it the reference for the next scan or table read.
        """
        from .library import discover_installation, resolve_resources
        from .gamedata import compare_entities
        from .gamedata.diff import COMPARISON_VERSION
        cancel = cancel or CancelToken()
        cancel.check()
        emit({"type": "progress", "message": "正在恢复已保存的扫描与解析结果…"})
        installation = self.store.get_installation(root)
        if installation is None:
            installation = discover_installation(Path(root))
        snapshot, changes = self.store.latest_scan_result(installation.profile_id)
        cancel.check()
        data, entity_changes, baseline = self.store.latest_data_result(installation.profile_id)
        cancel.check()
        if data is not None and (entity_changes is None or entity_changes.comparison_version != COMPARISON_VERSION):
            comparison_baseline = baseline
            if comparison_baseline is None and entity_changes and entity_changes.baseline_id:
                comparison_baseline = self.store.get_data_snapshot(entity_changes.baseline_id,
                                                                   profile_id=installation.profile_id)
            # Re-evaluate saved results after comparison-rule fixes. An automatic
            # baseline remains automatic; only explicit selections set self.baseline.
            if comparison_baseline is not None or not entity_changes or not entity_changes.baseline_id:
                emit({"type": "progress", "message": "正在重新核对已保存资料的新增与变化…"})
                entity_changes = replace(compare_entities(comparison_baseline, data), current_id=data.snapshot_id)
                cancel.check()
                self.store.save_data_changes(installation.profile_id, data, entity_changes, baseline=baseline)
            cancel.check()
        catalog = resolve_resources(snapshot) if snapshot is not None else ResourceCatalog(installation)
        catalog.installation = installation
        cancel.check()
        self._select_installation(installation)
        self.scan_snapshot, self.file_changes, self.catalog = snapshot, changes, catalog
        self.gameplay_catalog = snapshot.manifest_versions.get('gameplay') if snapshot is not None else None
        self.gamedata, self.entity_changes, self.baseline = data, entity_changes, baseline
        emit({"type": "progress", "message": "已恢复保存结果；重新扫描时将与完整基线比较。"})
        return {"snapshot": snapshot, "changes": changes, "catalog": catalog,
                "gamedata": data, "entity_changes": entity_changes}

    def scan(self, root, hours=24.0, strict=False, emit=null_progress, cancel=None):
        from .extraction.gameplay import discover_gameplay
        from .library import scan_installation, compare_files, resolve_resources
        cancel = cancel or CancelToken()
        installation = self._installation(root)
        previous = self.store.latest_scan(installation.profile_id)
        snapshot = scan_installation(installation, ScanOptions(float(hours), bool(strict)), emit, cancel, baseline=previous)
        change_set = compare_files(previous, snapshot)
        catalog = resolve_resources(snapshot)
        catalog.installation = installation
        gameplay = discover_gameplay(snapshot, catalog, cancel)
        cancel.check()
        snapshot.manifest_versions['gameplay'] = gameplay
        self.store.save_scan(snapshot, change_set)
        self.scan_snapshot, self.file_changes, self.catalog = snapshot, change_set, catalog
        self.gameplay_catalog = gameplay
        self.config["hours"] = float(hours)
        self.save_config()
        return {"snapshot": snapshot, "changes": change_set, "catalog": catalog}

    def _gameplay_mode(self, root, mode_id, resource_version):
        catalog = self.gameplay_catalog
        if (catalog is None or catalog['resource_version'] != resource_version
                or Path(catalog['root']) != Path(root).resolve()):
            raise ValueError('当前玩法清单与游戏目录或资源版本不一致，请重新扫描。')
        mode = next((entry for entry in catalog['modes'] if entry['id'] == mode_id), None)
        if mode_id != 'autochess' or mode is None or not mode['supported']:
            raise ValueError('当前玩法详情待适配。')
        return mode

    def load_gameplay(self, root, mode_id, resource_version, emit=null_progress, cancel=None):
        mode = self._gameplay_mode(root, mode_id, resource_version)
        if not mode['available']:
            raise ValueError('玩法数据表未安装，请下载游戏资源后重新扫描。')
        logical_path = mode.get('detail_resource') or mode['resources'][0]
        return self.runner.run('gameplay', {'root': str(root), 'logical_path': logical_path,
                                            'resource_version': resource_version}, emit, cancel)

    def load_gameplay_level(self, root, logical_path, resource_version, emit=null_progress, cancel=None):
        mode = self._gameplay_mode(root, 'autochess', resource_version)
        if logical_path not in mode['level_paths']:
            raise ValueError('关卡不在当前扫描的卫戍协议资源中，请重新扫描。')
        return self.runner.run('gameplay_level', {'root': str(root), 'logical_path': logical_path,
                                                  'resource_version': resource_version}, emit, cancel)

    def load_data(self, root, emit=null_progress, cancel=None):
        from .gamedata import load_gamedata, compare_entities
        cancel = cancel or CancelToken()
        installation = self._installation(root)
        previous = self.baseline or self.store.latest_data_snapshot(installation.profile_id)
        value = self.runner.run("tables", {"root": str(installation.root),
                                           "cache_dir": str(self.data_root / "tables")}, emit, cancel)
        cancel.check()
        sources = table_sources_from_dict(value)
        sources.locale = self.config.get("data_locale", "unknown")
        emit({"type": "progress", "message": "正在核对核心数据表与引用…"})
        data = load_gamedata(sources)
        data.sources["_installation"] = {"profile_id": installation.profile_id,
                                         "locale": data.locale,
                                         "locale_evidence": "user_declared" if data.locale != "unknown" else "unknown"}
        if not data.created_at:
            data.created_at = time.time()
        changes = compare_entities(previous, data)
        cancel.check()
        data = self.store.save_data_snapshot(installation.profile_id, data, changes, baseline=self.baseline)
        changes = replace(changes, current_id=data.snapshot_id)
        self.gamedata, self.entity_changes = data, changes
        # Entity checks only need the verified core tables. Inventorying every
        # resource here delays their presentation and repeats the next scan.
        # Preserve the last captured catalog; a file scan refreshes it explicitly.
        if self.catalog is None:
            self.catalog = ResourceCatalog(installation, diagnostics=['资源清单尚未扫描；核心资料已可使用。'])
        emit({"type": "progress", "message": f"核心数据已读取：{len(self.operators())} 名干员，{len(self.modules())} 个模组"})
        return data

    def _need_data(self):
        if self.gamedata is None:
            raise ValueError("请先点击“解析核心数据”。")
        return self.gamedata

    def operators(self, query="", changes_only=False):
        if self.gamedata is None:
            return []
        table = self.gamedata.tables.get("character_table", {})
        ids = self.gamedata.tables.get("_indexes", {}).get("operators")
        if ids is None:
            ids = [k for k, v in table.items() if isinstance(v, dict) and k.startswith("char_")]
        changes = {c.get("char_id", c.get("id")): c for c in (self.entity_changes.operators if self.entity_changes else [])}
        needle = query.casefold()
        result = []
        for char_id in ids:
            item = table.get(char_id, {})
            if changes_only and char_id not in changes:
                continue
            if needle and needle not in (char_id + " " + item.get("name", "") + " " + item.get("appellation", "")).casefold():
                continue
            result.append({"id": char_id, "name": item.get("name", char_id), "rarity": item.get("rarity", ""),
                           "profession": item.get("profession", ""),
                           "status": changes.get(char_id, {}).get("kind", "current"),
                           "obtainable": not item.get("isNotObtainable", False)})
        return sorted(result, key=lambda x: (str(x["name"]), x["id"]))

    def modules(self, query="", changes_only=False):
        if self.gamedata is None:
            return []
        from .gamedata.repository import equipment, is_badge
        table = self.gamedata.tables.get("character_table", {})
        changes = {c.get("equip_id", c.get("id")): c for c in (self.entity_changes.modules if self.entity_changes else [])}
        result = []
        for equip_id, item in equipment(self.gamedata.tables).items():
            if is_badge(item) or (changes_only and equip_id not in changes):
                continue
            char_id = item.get("charId", "")
            name = item.get("uniEquipName", equip_id)
            char_name = table.get(char_id, {}).get("name", char_id)
            if query and query.casefold() not in f"{equip_id} {name} {char_name}".casefold():
                continue
            result.append({"id": equip_id, "char_id": char_id, "char_name": char_name, "name": name,
                           "type": f"{item.get('typeName1', '')}-{item.get('typeName2') or ''}".strip("-"),
                           "status": changes.get(equip_id, {}).get("kind", "current")})
        return sorted(result, key=lambda x: (str(x["char_name"]), x["id"]))

    def operator_profile(self, char_id, spec=None):
        from .gamedata import build_operator
        return build_operator(self._need_data(), char_id, spec or BuildSpec())

    def module_profile(self, equip_id, spec=None):
        from .gamedata import build_module
        return build_module(self._need_data(), equip_id, spec or BuildSpec())

    def objects(self, path, emit=null_progress, cancel=None):
        return self.runner.run("objects", {"path": str(path)}, emit, cancel, reusable=True)

    def character_catalog(self, path, emit=null_progress, cancel=None):
        return self.runner.run("character_catalog", {"path": str(path)}, emit, cancel, reusable=True)

    def extract(self, paths, output, kinds=None, object_ids=None, mode="auto", emit=null_progress, cancel=None, *, remember_output=True, character_options=None):
        root = str(self.installation.root) if self.installation else self.config.get("game_root", "")
        if root:
            source = Path(root).resolve()
            for path in paths:
                candidate = Path(path).resolve()
                if candidate != source and source not in candidate.parents:
                    raise ValueError("所选文件不在当前游戏目录内，请重新扫描后选择。")
        target = validate_output(output, root)
        target.mkdir(parents=True, exist_ok=True)
        request_id = uuid.uuid4().hex
        task_target = target / ("extract-" + time.strftime("%Y%m%d-%H%M%S") + "-" + request_id[:10])
        task_target.mkdir(exist_ok=False)
        emit({"type": "progress", "stage": "extraction_task", "output_root": str(task_target),
              "request_id": request_id, "message": "解包输出：" + str(task_target)})
        request = ExtractionRequest([str(p) for p in paths], str(task_target), mode,
                                    kinds or ["image", "text", "audio", "spine"], root,
                                    object_ids or {}, request_id, character_options)
        if remember_output:
            value = self.runner.run("extract", as_jsonable(request), emit, cancel)
        else:
            value = self.runner.run("extract", as_jsonable(request), emit, cancel, reusable=True)
        value["output_root"] = str(task_target)
        if remember_output:
            self.config["output_root"] = str(target)
            self.save_config()
        return _dataclass_from_dict(ExtractionResult, value)

    def export(self, operator_ids, module_ids, output, formats, spec=None, options=None, emit=null_progress, cancel=None, *, remember_output=True):
        from .reports import compose_report, export_report
        cancel = cancel or CancelToken()
        data = self._need_data()
        root = self.installation.root if self.installation else self.config.get("game_root", "")
        target = validate_output(output, root)
        spec = spec or BuildSpec()
        options = options or ReportOptions()
        selected = ReportSelection()
        total = len(operator_ids) + len(module_ids)
        for i, char_id in enumerate(operator_ids):
            cancel.check()
            selected.operators.append(self.operator_profile(char_id, spec))
            emit({"type": "progress", "current": i + 1, "total": total, "message": selected.operators[-1].name})
        for i, equip_id in enumerate(module_ids):
            cancel.check()
            selected.modules.append(self.module_profile(equip_id, spec))
            emit({"type": "progress", "current": len(operator_ids) + i + 1, "total": total, "message": selected.modules[-1].name})
        if not selected.operators and not selected.modules:
            raise ValueError("请选择要导出的干员或模组。")
        document = compose_report(selected, options)
        document.metadata.update({"source_root": str(root), "snapshot_id": data.snapshot_id,
                                  "version": data.version, "resource_version": data.resource_version,
                                  "locale": data.locale,
                                  "complete": data.complete})
        cancel.check()
        result = export_report(document, target, set(formats) | {ExportFormat.JSON, ExportFormat.TXT},
                               cancel=cancel, emit=emit)
        if remember_output:
            self.config["output_root"] = str(target)
            self.save_config()
        return result

    def import_baseline(self, path):
        from .library import load_snapshot
        from .gamedata import compare_entities
        baseline = load_snapshot(path)
        if not isinstance(baseline, GameDataSnapshot):
            raise ValueError("请选择核心数据快照JSON，而不是文件扫描快照。")
        declared = self.config.get("data_locale", "unknown")
        if baseline.locale == "unknown" and declared != "unknown":
            baseline = replace(baseline, locale=declared,
                               sources={**baseline.sources, "_locale_evidence": "user_declared_import"})
        self.baseline = baseline
        self.entity_changes = compare_entities(baseline, self._need_data())
        if self.installation:
            self.store.save_data_changes(self.installation.profile_id, self.gamedata,
                                         self.entity_changes, baseline=baseline)
        return self.entity_changes

    def export_snapshot(self, path):
        from .library import dumps_snapshot
        output = validate_output(path, self.installation.root if self.installation else None)
        if any(output.is_relative_to(self.data_root / name) for name in ('preview', 'previews')):
            raise ValueError('临时预览目录会自动回收，请将数据快照保存到正式输出目录。')
        if output.exists():
            raise ValueError("该文件已存在，请选择一个新文件名。")
        output.parent.mkdir(parents=True, exist_ok=True)
        temp = output.with_name(output.name + ".tmp")
        temp.write_text(dumps_snapshot(self._need_data()), encoding="utf-8")
        temp.replace(output)
        return str(output)

    def compare_snapshot(self, snapshot_id):
        from .gamedata import compare_entities
        profile_id = self.installation.profile_id if self.installation else None
        baseline = self.store.get_data_snapshot(snapshot_id, profile_id=profile_id)
        if baseline is None:
            raise ValueError("找不到该历史快照。")
        self.baseline = baseline
        self.entity_changes = compare_entities(baseline, self._need_data())
        if self.installation:
            self.store.save_data_changes(self.installation.profile_id, self.gamedata,
                                         self.entity_changes, baseline=baseline)
        return self.entity_changes

    def shutdown(self):
        self.runner.shutdown()
