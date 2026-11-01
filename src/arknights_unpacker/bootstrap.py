from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time
import traceback

from . import __version__
from .contracts import ExportFormat, ReportOptions, as_jsonable
from .paths import atomic_json, validate_data_root, validate_output


def verify_installation(services, root: str, target: Path) -> dict:
    """Exercise production services with real inputs; records no browser claims."""
    target = validate_output(validate_data_root(target), root)
    target.mkdir(parents=True, exist_ok=True)
    events = []
    def progress(event):
        events.append(as_jsonable(event))
    start = time.monotonic()
    scan = services.scan(root, emit=progress)
    data = services.load_data(root, emit=progress)
    rows = services.operators()
    available = {row['id'] for row in rows}
    char_id = next((name for name in ('char_103_angel', 'char_4231_clemnt') if name in available), rows[0]['id'])
    profile = services.operator_profile(char_id)
    modules = services.modules()
    module_ids = [row['id'] for row in modules[:4]]
    # One scan/data load exercises both export themes through the actual services.
    report_runs = {}
    for theme in ('dark', 'light'):
        artifacts = services.export([char_id], module_ids, str(target / 'reports' / theme),
                                    {ExportFormat.PNG, ExportFormat.HTML},
                                    options=ReportOptions(theme=theme), emit=progress)
        module_collection = None
        if module_ids:
            from PIL import Image
            pngs = [item for item in artifacts if item.format == 'png' and Path(item.path).name.startswith('modules_')]
            htmls = [item for item in artifacts if item.format == 'html' and Path(item.path).name == 'modules.html']
            if len(pngs) != 1 or pngs[0].pages != 1 or len(htmls) != 1:
                raise RuntimeError('模组合集验收必须生成一张完整PNG和一个HTML')
            with Image.open(pngs[0].path) as picture:
                image_size = picture.size
                picture.verify()
            module_collection = {'module_ids': module_ids, 'png': pngs[0].path, 'html': htmls[0].path,
                                 'image_size': image_size, 'pages': 1,
                                 'scope': 'Manually selected current modules; no server update observed.'}
        report_runs[theme] = {'artifacts': as_jsonable(artifacts), 'module_collection': module_collection}
    extraction_checks = []
    def sample_path(relative):
        for layer in ("hot", "base"):
            source = services.installation.source_roots.get(layer)
            if source and (Path(source) / relative).is_file():
                return Path(source) / relative
        return None
    # These are opt-in local acceptance samples, not a source selection rule.
    samples = [("chararts/char_002_amiya.ab", ["image", "spine"]),
               ("arts/dynchars/char_003_kalts_boc#6.ab", ["audio"]),
               ("raw/video/01.usm", ["video"])]
    for relative, kinds in samples:
        source = sample_path(relative)
        if source is None:
            extraction_checks.append({"sample": relative, "status": "not_installed"})
            continue
        object_ids = {}
        if kinds == ["audio"]:
            objects = services.objects(str(source), emit=progress)
            clips = [item for item in objects if item["type"] == "AudioClip"]
            if not clips:
                raise RuntimeError("音频验收样本不含 AudioClip")
            object_ids[str(source)] = [clips[0]["id"]]
        result = services.extract([str(source)], str(target / "extraction" / kinds[0]),
                                  kinds=kinds, object_ids=object_ids, emit=progress)
        if result.errors or not result.outputs:
            raise RuntimeError(f"资源验收失败 {relative}: {result.errors or result.skipped}")
        checks = {"sample": relative, "status": result.status, "result": as_jsonable(result)}
        if "image" in kinds:
            from PIL import Image
            alpha_ranges = []
            for output in result.outputs:
                if Path(output["path"]).suffix.lower() == ".png":
                    with Image.open(output["path"]) as picture:
                        picture.load()
                        alpha_ranges.append(picture.convert("RGBA").getchannel("A").getextrema())
            if (0, 255) not in alpha_ranges:
                raise RuntimeError("图片验收未发现明确配对的透明通道")
            checks["alpha_ranges"] = alpha_ranges
        if "audio" in kinds:
            import wave
            waves = [out for out in result.outputs if Path(out["path"]).suffix.lower() == ".wav"]
            if not waves:
                raise RuntimeError("音频验收没有生成 WAV")
            with wave.open(waves[0]["path"], "rb") as stream:
                checks["wav"] = {"channels": stream.getnchannels(), "sample_rate": stream.getframerate(),
                                 "frames": stream.getnframes()}
        if "video" in kinds and not any(out["kind"] == "video_stream" for out in result.outputs):
            raise RuntimeError("视频验收没有分离视频流")
        extraction_checks.append(checks)
    receipt = {"version": __version__, "scan_complete": scan["snapshot"].complete,
               "files": len(scan["snapshot"].files), "resource_count": len(scan["catalog"].resources),
               "data_complete": data.complete, "data_version": data.version,
               "resource_version": data.resource_version, "operators": len(rows), "modules": len(modules),
               "profile": as_jsonable(profile), "artifacts": report_runs['dark']['artifacts'],
               "module_collection": report_runs['dark']['module_collection'], "report_runs": report_runs,
               "extraction_checks": extraction_checks,
               "elapsed_seconds": round(time.monotonic() - start, 2), "events": events,
               "evidence": "Production service and isolated worker flow; browser offline rendering not exercised."}
    atomic_json(target / "verification.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="明日方舟 PC 资源与资料工作台")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--game-root", default="")
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--smoke-test", metavar="JSON", help=argparse.SUPPRESS)
    parser.add_argument("--preview-source", help=argparse.SUPPRESS)
    parser.add_argument("--preview-kind", choices=('image', 'audio', 'video', 'text'), default='image', help=argparse.SUPPRESS)
    parser.add_argument("--headless-verify", metavar="DIR", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.preview_source and not args.smoke_test:
        parser.error('--preview-source requires --smoke-test')
    from .application import AppServices
    try:
        services = AppServices(args.data_dir, output_root=args.output_dir)
    except (OSError, ValueError) as error:
        if args.smoke_test or args.headless_verify:
            if sys.stderr is not None:
                print(str(error), file=sys.stderr)
        else:
            from PySide6.QtWidgets import QApplication, QMessageBox
            from .ui.styles import apply_theme
            app = QApplication.instance() or QApplication(sys.argv[:1])
            apply_theme(app)
            QMessageBox.critical(None, '无法读取或保存程序数据', str(error))
        return 1
    if args.headless_verify:
        safe_target = None
        try:
            root = args.game_root or services.config.get("game_root")
            if not root:
                raise ValueError("验证需要 --game-root")
            safe_target = validate_output(validate_data_root(Path(args.headless_verify)), root)
            verify_installation(services, root, safe_target)
            return 0
        except Exception as exc:
            failure_path = (safe_target / "failure.json") if safe_target else (services.data_root / "verification-failure.json")
            atomic_json(failure_path, {"error": str(exc), "traceback": traceback.format_exc()})
            return 1
        finally:
            services.shutdown()
    from PySide6.QtCore import QTimer, qVersion
    from PySide6.QtWidgets import QApplication
    from .ui.main_window import MainWindow
    app = QApplication(sys.argv[:1])
    app.setApplicationName("ArknightsUnpacker")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("ArknightsUnpacker")
    window = MainWindow(services, initial_root=args.game_root)
    app.aboutToQuit.connect(services.shutdown)
    window.show()
    if args.smoke_test and args.preview_source:
        from .ui.preview_smoke import PreviewSmoke
        receipt = validate_output(validate_data_root(Path(args.smoke_test)),
                                  args.game_root or services.config.get('game_root'))
        window._preview_smoke = PreviewSmoke(app, window, args.preview_source, receipt, args.preview_kind)
    elif args.smoke_test:
        from PySide6.QtGui import QPixmap
        from .paths import resource_root
        receipt = validate_output(validate_data_root(Path(args.smoke_test)),
                                  args.game_root or services.config.get("game_root"))
        smoke_started = time.monotonic()
        def record():
            if window.queue.busy or window._restore_pending:
                if time.monotonic() - smoke_started < 25:
                    QTimer.singleShot(100, record)
                    return
            try:
                image_path = receipt.with_suffix(".png")
                image_path.parent.mkdir(parents=True, exist_ok=True)
                window.grab().save(str(image_path))
                atomic_json(receipt, {"version": __version__, "qt_version": qVersion(),
                                      "visible": window.isVisible(), "width": window.width(), "height": window.height(),
                                      "tabs": [window.tabs.tabText(i) for i in range(window.tabs.count())],
                                      "screenshot": str(image_path), "frozen": bool(getattr(sys, "frozen", False)),
                                      "qt_platform": app.platformName(), "data_root": str(services.data_root),
                                      "output_root": services.config.get("output_root"),
                                      "output_directory_exists": Path(services.config["output_root"]).is_dir(),
                                      "settings_output": window.settings.output.text(),
                                      "module_image_layout": window.settings.report_options().module_image_layout,
                                      "report_theme": window.settings.report_options().theme,
                                      "report_theme_options": [window.settings.theme.itemData(i) for i in range(window.settings.theme.count())],
                                      "report_theme_labels": [window.settings.theme.itemText(i) for i in range(window.settings.theme.count())],
                                      "queue_idle": not window.queue.busy,
                                      "successful_jobs": sum(job.status == '成功' for job in window.queue.jobs),
                                      "preview_cleanup": window.preview_cache.last_cleanup,
                                      "preview_cleanup_warnings": window.preview_cache.warnings,
                                      "scan_id": getattr(services.scan_snapshot, 'snapshot_id', None),
                                      "gamedata_id": getattr(services.gamedata, 'snapshot_id', None),
                                      "operators": len(services.operators()), "modules": len(services.modules()),
                                      "operator_changes_filter_hidden": window.operators.only_changes.isHidden() if window.operators else None,
                                      "operator_details_text": window.operators.details.toPlainText() if window.operators else '',
                                      "module_changes_filter_hidden": window.modules.only_changes.isHidden() if window.modules else None,
                                      "module_details_text": window.modules.details.toPlainText() if window.modules else '',
                                      "explorer_file_types": [window.explorer.file_type.itemData(i) for i in range(window.explorer.file_type.count())] if window.explorer else [],
                                      "explorer_file_type": window.explorer.file_type.currentData() if window.explorer else None,
                                      "explorer_folder": window.explorer.folder if window.explorer else None,
                                      "explorer_recursive": window.explorer.recursive.isChecked() if window.explorer else False,
                                      "explorer_directory_enabled": window.explorer.tree.isEnabled() if window.explorer else False,
                                      "explorer_recursive_enabled": window.explorer.recursive.isEnabled() if window.explorer else False,
                                      "explorer_breadcrumb": window.explorer.breadcrumb.text() if window.explorer else '',
                                      "explorer_records": window.explorer.model.rowCount() if window.explorer else 0,
                                      "explorer_categories": sorted({row.get('category') or '未知用途' for row in window.explorer.model.rows}) if window.explorer else [],
                                      "update_file_types": [window.updates.file_type.itemData(i) for i in range(window.updates.file_type.count())] if window.updates else [],
                                      "update_exclude_deleted": window.updates.exclude_deleted.isChecked() if window.updates else None,
                                      "entity_comparison_version": getattr(services.entity_changes, 'comparison_version', None),
                                      "new_operators": sum(row.get('status') in ('added', 'new') for row in services.operators()),
                                      "new_modules": sum(row.get('status') in ('added', 'new') for row in services.modules()),
                                      "changed_modules": len(services.entity_changes.modules) if services.entity_changes else 0,
                                      "palette_window": app.palette().window().color().name(),
                                      "theme_icons": {name: not QPixmap(str(resource_root() / 'resources/ui' / name)).isNull()
                                                      for name in ('arrow-down.svg', 'arrow-up.svg', 'check.svg')},
                                      "jobs": [{"job_id": job.job_id, "title": job.title, "status": job.status} for job in window.queue.jobs]})
            finally:
                window.close()
        QTimer.singleShot(1800, record)
        QTimer.singleShot(30000, lambda: app.exit(1))
    return app.exec()
