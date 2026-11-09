"""Built-in workbench pages and their UI lifecycle.

The registry is deliberately local: adding a page means adding one definition.
Concrete views are imported only when that definition is assembled.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from importlib import import_module
from pathlib import Path
from typing import Callable

from arknights_unpacker.contracts import BuildSpec
from .models import selected_records, value


# Numeric tabs saved before page IDs always refer to this original order.
LEGACY_PAGE_ORDER = ('explorer', 'updates', 'operators', 'modules', 'jobs', 'settings')
REQUIRED_PAGES = frozenset(('settings',))


class PageController:
    """Small lifecycle shared by the built-in pages; no view dependency at import."""
    view_module = ''
    view_class = ''

    def __init__(self, window):
        self.window = window
        self.view = self.create_view()
        self.widget = self.view

    def create_view(self):
        module = import_module(self.view_module, package=__package__)
        return getattr(module, self.view_class)()

    def connect(self):
        pass

    def set_root(self, root):
        pass

    def scanned(self, snapshot, changes, catalog):
        pass

    def data_loaded(self):
        pass

    def refresh_entities(self):
        pass

    def hours_changed(self):
        pass

    def queue_changed(self):
        pass

    def save_state(self):
        return {}

    def legacy_state(self, state):
        return {}

    def restore_state(self, state):
        pass


class ExplorerPage(PageController):
    view_module = '.explorer'
    view_class = 'ExplorerView'

    def connect(self):
        self.view.extract_requested.connect(self.window.extract)
        self.view.objects_requested.connect(self.window.objects)
        self.view.expressions_requested.connect(self.window.character_workbench)

    def set_root(self, root):
        if self.view.root != Path(root):
            self.view.set_root(str(root))

    def scanned(self, snapshot, changes, catalog):
        root = value(snapshot, 'root')
        if root:
            self.set_root(root)
        self.view.set_data(snapshot, changes, catalog)

    def data_loaded(self):
        services = self.window.services
        root = value(services.installation, 'root')
        if root:
            root_changed = self.view.root != Path(root)
            if root_changed:
                self.set_root(root)
            physical = services.scan_snapshot
            matches = physical is not None and Path(value(physical, 'root', '')) == Path(root)
            snapshot = physical if matches else None
            if root_changed or self.view.snapshot is not snapshot or self.view.catalog is not services.catalog:
                self.view.set_data(snapshot, services.file_changes if matches else None, services.catalog)

    def save_state(self):
        return {'folder': self.view.folder, 'recursive': self.view.recursive.isChecked(),
                'ab_only': self.view.ab_only.isChecked(), 'search': self.view.search.text(),
                'file_type': self.view.file_type.currentData()}

    def legacy_state(self, state):
        return {'folder': state.get('explorer_folder', ''), 'recursive': state.get('explorer_recursive', False),
                'ab_only': state.get('explorer_ab', False), 'search': state.get('explorer_search', ''),
                'file_type': None}

    def restore_state(self, state):
        self.view.recursive.setChecked(bool(state.get('recursive', False)))
        self.view.ab_only.setChecked(bool(state.get('ab_only', False)))
        category = state.get('file_type')
        if not isinstance(category, str) or not category.strip():
            category = None
        if category is not None and self.view.file_type.findData(category) < 0:
            self.view.file_type.addItem(category, category)
        self.view.file_type.setCurrentIndex(max(0, self.view.file_type.findData(category)))
        self.view.search.setText(state.get('search', ''))
        folder = str(state.get('folder', ''))
        if (self.view.root / folder).resolve().is_relative_to(self.view.root.resolve()):
            self.view.folder = folder
            self.view.refresh()


class UpdatesPage(PageController):
    view_module = '.updates'
    view_class = 'UpdatesView'

    def connect(self):
        self.view.extract_requested.connect(self.window.extract)
        self.view.images_requested.connect(lambda paths: self.window.extract(paths, kinds=['image'], mode='auto'))
        self.view.objects_requested.connect(self.window.objects)

    def scanned(self, snapshot, changes, catalog):
        self.view.set_data(snapshot, changes, self.window.hours.value())

    def data_loaded(self):
        root = value(self.window.services.installation, 'root')
        physical = self.view.snapshot
        if root and (physical is None or Path(value(physical, 'root', '')) != Path(root)):
            self.view.set_data(None, None, self.window.hours.value())
            self.view.summary.setText('当前安装的核心数据已解析；文件更新记录需要重新扫描。')
            self.view.empty.setText('核心资料已可查看。点击“扫描 / 检查更新”建立当前目录的文件更新记录。')

    def hours_changed(self):
        if self.view.snapshot:
            self.view.hours = self.window.hours.value()
            self.view.refresh()

    def save_state(self):
        return {'mode': self.view.mode.currentIndex(), 'ab_only': self.view.ab_only.isChecked(),
                'search': self.view.search.text(), 'file_type': self.view.file_type.currentData(),
                'exclude_deleted': self.view.exclude_deleted.isChecked()}

    def legacy_state(self, state):
        return {'mode': state.get('update_mode', 2), 'ab_only': state.get('update_ab', False),
                'search': state.get('update_search', '')}

    def restore_state(self, state):
        self.view.mode.setCurrentIndex(max(0, min(3, int(state.get('mode', 2)))))
        self.view.ab_only.setChecked(bool(state.get('ab_only', False)))
        category = state.get('file_type')
        if category and self.view.file_type.findData(category) < 0:
            self.view.file_type.addItem(category, category)
        self.view.file_type.setCurrentIndex(max(0, self.view.file_type.findData(category)))
        self.view.exclude_deleted.setChecked(bool(state.get('exclude_deleted', True)))
        self.view.search.setText(state.get('search', ''))


class EntityPage(PageController):
    kind = ''
    profile_method = ''

    def __init__(self, window):
        self._display_identity = None
        self._profile_pending = set()
        self._restored_module_choices = {}
        super().__init__(window)

    def connect(self):
        self.view.load_requested.connect(self.window.load_data)
        self.view.profile_requested.connect(self.profile)
        self.view.export_requested.connect(partial(self.window.export, self.kind))
        self.view.preview_requested.connect(partial(self.window.preview_reports, self.kind))

    def refresh_entities(self):
        services = self.window.services
        identity = (value(services.installation, 'profile_id'), value(services.gamedata, 'snapshot_id'))
        if services.gamedata is None or identity != self._display_identity:
            self.view.clear_data()
            self._restored_module_choices.clear()
        self._display_identity = identity if services.gamedata is not None else None
        if services.gamedata is not None:
            self.view.set_rows(getattr(services, self.kind)(), services.entity_changes, services.gamedata)

    def profile(self, entity_id, spec):
        key = (entity_id, spec.module_id)
        if key in self._profile_pending:
            return
        self._profile_pending.add(key)
        method = getattr(self.window.services, self.profile_method)

        def call(**kw):
            kw['cancel'].check()
            return method(entity_id, spec)

        def done(result):
            self._profile_pending.discard(key)
            rows = selected_records(self.view.table)
            if (len(rows) == 1 and str(rows[0]['id']) == entity_id
                    and self.view.module_choice.currentData() == spec.module_id):
                self.view.set_profile(result)
                module_id = self._restored_module_choices.pop(entity_id, None)
                if module_id:
                    index = self.view.module_choice.findData(module_id)
                    if index >= 0:
                        self.view.module_choice.setCurrentIndex(index)

        job = self.window.queue.submit('查看资料 · ' + entity_id, call, done, show_in_tasks=False)

        def cleanup():
            if job.status not in ('运行中', '排队中', '正在取消'):
                self._profile_pending.discard(key)
        self.window.queue.changed.connect(cleanup)

    def report_spec(self, ids):
        return BuildSpec(module_id=self.view.module_choice.currentData()) if self.kind == 'operators' and len(ids) == 1 else BuildSpec()

    def save_state(self):
        rows = selected_records(self.view.table)
        state = {'search': self.view.search.text(), 'only_new': self.view.only_new.isChecked(),
                 'selected_id': str(rows[0]['id']) if len(rows) == 1 else None,
                 'module_id': self.view.module_choice.currentData()}
        return state

    def legacy_state(self, state):
        return state.get(self.kind, {})

    def restore_state(self, state):
        self.view.search.setText(state.get('search', ''))
        self.view.only_changes.setChecked(False)
        self.view.only_new.setChecked(bool(state.get('only_new', False)))
        for index, row in enumerate(self.view.model.rows):
            if str(row['id']) == state.get('selected_id'):
                if self.kind == 'operators' and state.get('module_id'):
                    self._restored_module_choices[str(row['id'])] = state['module_id']
                self.view.table.selectRow(index)
                break


class OperatorsPage(EntityPage):
    view_module = '.operator_view'
    view_class = 'OperatorView'
    kind = 'operators'
    profile_method = 'operator_profile'


class ModulesPage(EntityPage):
    view_module = '.module_view'
    view_class = 'ModuleView'
    kind = 'modules'
    profile_method = 'module_profile'


class GameplayPage(PageController):
    view_module = '.gameplay_page'
    view_class = 'GameplayView'

    def create_view(self):
        module = import_module(self.view_module, package=__package__)
        return getattr(module, self.view_class)(self.window)

    def connect(self):
        self.view.connect()

    def set_root(self, root):
        self.view.set_root(root)

    def scanned(self, snapshot, changes, catalog):
        root = value(snapshot, 'root')
        if root:
            self.set_root(root)
        self.view.set_catalog(getattr(self.window.services, 'gameplay_catalog', None))

    def data_loaded(self):
        services = self.window.services
        root = value(services.installation, 'root')
        if root:
            self.set_root(root)
        self.view.set_catalog(getattr(services, 'gameplay_catalog', None))

    def save_state(self):
        return self.view.save_state()

    def restore_state(self, state):
        self.view.restore_state(state)


class LevelCatalogPage(PageController):
    view_module = '.level_catalog_page'
    view_class = 'LevelCatalogView'

    def __init__(self, window):
        self.root = None
        self._catalog = None
        self._metadata = None
        self._metadata_job = None
        self._tags_job = None
        self._tags_dialog = None
        self._applied_tags = {}
        self._preview_dialog = None
        self._map_job = None
        super().__init__(window)

    def connect(self):
        self.window.tabs.currentChanged.connect(self._load_metadata)
        self.window.queue.settled.connect(self._metadata_settled)
        self.window.queue.settled.connect(self._tags_settled)
        self.view.tags_requested.connect(self._load_tags)
        self.view.preview_requested.connect(self._open_preview)

    def set_root(self, root):
        root = Path(root).resolve()
        if root != self.root:
            self.root = root
            self._set_catalog(None)

    def scanned(self, snapshot, changes, catalog):
        self.data_loaded()

    def data_loaded(self):
        services = self.window.services
        root = value(services.installation, 'root')
        if root:
            self.set_root(root)
        levels = getattr(services, 'level_catalog', None)
        self._set_catalog(levels if levels and Path(levels['root']).resolve() == self.root else None)

    def _set_catalog(self, catalog):
        if catalog is self._catalog:
            return
        if self._identity(catalog) != self._identity(self._catalog):
            self._applied_tags.clear()
            if self._metadata_job is not None:
                self._metadata_job.token.cancel()
                self._metadata_job = None
            if self._tags_job is not None:
                self._tags_job.token.cancel()
                self._tags_job = None
            if self._tags_dialog is not None:
                self._tags_dialog.close()
            if self._preview_dialog is not None:
                self._preview_dialog.close()
            if self._map_job is not None:
                self._map_job.token.cancel()
            self._metadata = None
        self._catalog = catalog
        self._render()
        self._load_metadata()

    @staticmethod
    def _identity(catalog):
        return (catalog['root'], catalog['resource_version']) if catalog and catalog['levels'] else None

    def _render(self):
        catalog = self._catalog
        if catalog is not None:
            metadata = self._metadata or {}
            by_level = metadata.get('levels', {})
            chapters = metadata.get('chapters', {})
            clips = self._clips()
            catalog = {
                **catalog,
                'levels': [
                    {**self._with_metadata(row, by_level, chapters), 'preview_ready': row['id'] in clips}
                    for row in catalog['levels']
                ],
                'diagnostics': [*catalog['diagnostics'], *metadata.get('diagnostics', ())],
            }
        self.view.set_catalog(catalog)

    def _clips(self):
        identity = self._identity(self._catalog)
        find = getattr(self.window.services, 'level_preview_clips', None)
        return find(*identity) if identity is not None and find is not None else {}

    def _open_preview(self, path):
        if self._preview_dialog is not None:
            return
        if self._catalog is None:
            return
        row = next((item for item in self._catalog['levels'] if item['id'] == path), None)
        if row is None:
            return
        metadata = self._metadata['levels'].get(path, {}) if self._metadata else {}
        caption = ' · '.join(filter(None, (metadata.get('code'), metadata.get('name')))) or row['name']
        clip = self._clips().get(path)
        dialog = self._show_preview(clip, caption)
        if clip is not None:
            status = '原资源动画试渲染'
        elif row.get('map_image'):
            status = '游戏原图 · 关卡动画待适配'
            dialog.show_message('正在读取游戏原图…')
            self._load_map_image(path, dialog)
        elif row['available']:
            status = '关卡动画待适配'
            dialog.show_message('当前关卡还没有可播放动画或游戏原图。')
        else:
            status = '关卡资源未安装'
            dialog.show_message('请在游戏客户端下载关卡资源，然后重新扫描。')
        dialog.show_detail(status)
        if row['available']:
            info_job = self._load_preview_info(path, dialog, status)
            self._configure_replay(path, caption, dialog, info_job)

    def _configure_replay(self, path, caption, dialog, info_job):
        load = getattr(self.window.services, 'load_level_replay', None)
        identity = self._identity(self._catalog)
        if identity is None or load is None:
            return
        from ..level_preview_server import LevelPreviewServer, missing_preview_runtime
        from ..paths import resource_root

        root, version = identity
        runtime = self.window.services.data_root / 'level-preview-runtime'
        player = resource_root() / 'scripts' / 'level_preview'
        native_project = player / 'native_player'
        native_engine = native_project / 'Godot.exe'
        native_button = None
        if path == 'gamedata/levels/obt/campaign/level_camp_r_16' and native_engine.is_file():
            from PySide6.QtWidgets import QDialogButtonBox, QPushButton

            native_button = QPushButton('原生回放（试验）…', dialog)
            dialog.buttons.addButton(native_button, QDialogButtonBox.ButtonRole.ActionRole)
        server = None

        def set_ready(ready):
            dialog.replay_button.setEnabled(ready)
            if native_button is not None:
                native_button.setEnabled(ready)

        def play(*, native=False):
            if not native and server is not None:
                dialog.toggle_replay()
                return
            if not native and missing_preview_runtime(runtime):
                dialog.show_replay_status(f'缺少本机播放组件。配置目录为 {runtime}')
                return
            tags, archive = self._applied_tags.get(path, (None, None))
            try:
                cached = self.window.services.cached_native_level_replay(
                    root, path, version, caption=caption, tag_ids=tags, crisis_info_path=archive) if native else None
                lease = self.window.preview_cache.allocate('objects')
            except (OSError, ValueError) as error:
                dialog.show_replay_status(str(error))
                return
            set_ready(False)
            dialog.show_replay_status('正在准备游戏原场景、角色和波次…' if not native
                                      else '正在准备原生场景、角色动画和波次…')
            if info_job is not None and info_job.status in ('排队中', '运行中'):
                info_job.token.cancel()
            shown = False
            native_session = None
            job = None

            def native_closed(*_):
                nonlocal native_session
                native_session = None
                lease.release()

            def done(result):
                nonlocal server, shown, native_session
                if ((job is not None and job.token.cancelled) or self._preview_dialog is not dialog or
                        self._identity(self._catalog) != identity):
                    return
                if result['level_id'] != path or result['resource_version'] != version:
                    raise ValueError('回放来源与当前关卡不匹配。')
                if native:
                    from PySide6.QtCore import Qt
                    from .level_native_dialog import NativeLevelReplayDialog

                    native_session = NativeLevelReplayDialog(dialog, caption, engine=native_engine,
                                                              project=native_project, assets=result['native_assets'],
                                                              log_dir=lease.path)
                    native_session.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
                    self.window._track_dialog(native_session)
                    native_session.finished.connect(native_closed)
                    native_session.open()
                else:
                    session = LevelPreviewServer(lease.path, player, runtime)
                    try:
                        dialog.show_replay(session.url)
                    except Exception:
                        session.close()
                        raise
                    server = session
                shown = True
                dialog.show_replay_status(f"无部署出怪预览 · {result['spawns']} 次出怪 · {result['duration']:.1f} 秒")
                details = list(result.get('diagnostics') or ())
                if 'seed' in result:
                    details.insert(0, f"本次回放的随机种子为 {result['seed']}")
                if result.get('native_cache_hit'):
                    details.insert(0, '已复用本机准备的原版关卡和动画。')
                dialog.replay_status.setToolTip('\n'.join(details))

            def settled(completed):
                if completed is not job:
                    return
                self.window.queue.settled.disconnect(settled)
                lease.finish()
                if not shown:
                    lease.release()
                if self._preview_dialog is dialog:
                    set_ready(True)
                    if not shown:
                        reason = [line for line in job.last_error.strip().splitlines()
                                  if line and not line.startswith('诊断日志：')]
                        message = reason[-1] if reason else ''
                        message = message.removeprefix('RuntimeError: ').removeprefix('ValueError: ')
                        dialog.show_replay_status(message or '出怪预览暂不可用。')

            def close(*_):
                nonlocal server
                if job is not None:
                    job.token.cancel()
                if native_session is not None:
                    native_session.close()
                if not native and server is not None:
                    server.close()
                    server = None
                lease.release()

            if cached is not None:
                try:
                    done(cached)
                except (OSError, ValueError, RuntimeError) as error:
                    dialog.show_replay_status(str(error))
                finally:
                    lease.finish()
                    set_ready(True)
                    if not shown:
                        close()
                dialog.finished.connect(close)
                return

            backend = {'native': True} if native else {}
            job = self.window.queue.submit('准备关卡出怪预览', lambda **kw: load(
                root, path, version, lease.path, caption=caption, tag_ids=tags, crisis_info_path=archive, **backend, **kw),
                done, show_in_tasks=False)
            self.window.queue.settled.connect(settled)
            dialog.finished.connect(close)

        dialog.replay_button.clicked.connect(play)
        dialog.replay_button.show()
        if native_button is not None:
            native_button.clicked.connect(lambda: play(native=True))

    def _show_preview(self, path, caption):
        from PySide6.QtCore import Qt
        from .level_preview_dialog import LevelPreviewDialog

        dialog = LevelPreviewDialog(path, caption, self.view)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.window._track_dialog(dialog)
        self._preview_dialog = dialog

        def closed(*_):
            self._preview_dialog = None

        dialog.finished.connect(closed)
        dialog.open()
        return dialog

    def _load_map_image(self, path, dialog):
        identity = self._identity(self._catalog)
        load = getattr(self.window.services, 'load_level_map_preview', None)
        if identity is None or load is None:
            return
        root, version = identity
        try:
            lease = self.window.preview_cache.allocate('objects')
        except (OSError, ValueError) as error:
            dialog.show_message(str(error))
            return
        def done(result):
            if (job.token.cancelled or self.window._closing or self._identity(self._catalog) != identity
                    or self._preview_dialog is not dialog or result['resource_version'] != version):
                return
            media = Path(result['path']).resolve()
            if media.parent != lease.path or media.suffix != '.png' or not media.is_file():
                raise ValueError('原版地图图像未生成到预览目录。')
            dialog.show_media(media)

        def settled(completed):
            if completed is not job:
                return
            self.window.queue.settled.disconnect(settled)
            if self._map_job is job:
                self._map_job = None
            lease.finish()
            if job.status != '成功' and self._preview_dialog is dialog:
                dialog.show_message('读取游戏原图失败，请检查游戏资源后重试。')

        job = self.window.queue.submit('读取游戏原版地图', lambda **kw: load(root, path, version, lease.path, **kw),
                                       done, show_in_tasks=False)
        self._map_job = job
        self.window.queue.settled.connect(settled)
        dialog.finished.connect(lambda *_: job.token.cancel())
        dialog.finished.connect(lambda *_: lease.release())

    def _load_preview_info(self, path, dialog, status):
        load = getattr(self.window.services, 'load_level_preview_info', None)
        identity = self._identity(self._catalog)
        if load is None or identity is None:
            return
        root, version = identity

        def done(info):
            if self._preview_dialog is not dialog or info['resource_version'] != version:
                return
            rows, columns = info['map_size']
            size = f'地图 {rows}×{columns} · ' if rows and columns else ''
            dialog.show_detail(f"{status} · {size}{info['wave_count']} 波 · {info['route_count']} 条路线")

        job = self.window.queue.submit('读取关卡脚本', lambda **kw: load(root, path, version, **kw),
                                       done, show_in_tasks=False)
        dialog.finished.connect(lambda *_: job.token.cancel())
        return job

    @staticmethod
    def _with_metadata(row, by_level, chapters):
        folder = row['id'].rsplit('/', 1)[0]
        while folder:
            chapter = chapters.get(folder + '/')
            if chapter:
                row = {**row, **chapter}
                break
            folder = folder.rpartition('/')[0]
        exact = by_level.get(row['id'], {})
        return {**row, **{key: value for key, value in exact.items() if value}}

    def _load_metadata(self, *_):
        if self.window.tabs.currentWidget() is not self.view:
            return
        identity = self._identity(self._catalog)
        load = getattr(self.window.services, 'load_level_metadata', None)
        if identity is None or load is None or self._metadata is not None or self._metadata_job is not None:
            return
        root, version = identity

        def done(result):
            if self._metadata_job is job and result['resource_version'] == version:
                self._metadata = result
                self._render()

        job = self.window.queue.submit('读取关卡名称和章节', lambda **kw: load(root, version, **kw),
                                       done, show_in_tasks=False)
        self._metadata_job = job

    def _metadata_settled(self, job):
        if job is not self._metadata_job:
            return
        self._metadata_job = None
        if job.status != '成功' and self._catalog is not None and not self.window._closing:
            self._metadata = {'levels': {}, 'diagnostics': ['章节与关卡名称读取失败，当前显示资源代号。']}
            self._render()

    def _load_tags(self, path, caption):
        identity = self._identity(self._catalog)
        load = getattr(self.window.services, 'load_level_tag_options', None)
        if identity is None or load is None or self._tags_job is not None or self._tags_dialog is not None:
            return
        root, version = identity
        options = {}
        if path.startswith('gamedata/levels/obt/crisis/'):
            from PySide6.QtWidgets import QFileDialog

            archive, _ = QFileDialog.getOpenFileName(self.window, '导入危机合约赛季指标', '',
                                                     '指标数据 (*.json)')
            if not archive:
                return
            options['crisis_info_path'] = archive

        def done(result):
            if self._tags_job is not job or result['resource_version'] != version:
                return
            if not result['tags']:
                self.window.show_status('；'.join(result['diagnostics']) or '此关卡没有作战指标。')
                return
            from PySide6.QtCore import Qt
            from .level_tags_dialog import LevelTagsDialog

            archive = options.get('crisis_info_path')
            previous = self._applied_tags.get(path)
            if previous is not None and previous[1] == archive:
                selected = set(previous[0])
                result = {**result, 'tags': [{**tag, 'selected': tag['id'] in selected} for tag in result['tags']]}
            dialog = LevelTagsDialog(result, caption, self.view)
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            self._tags_dialog = dialog
            dialog.variant_applied.connect(lambda ids: self._applied_tags.__setitem__(path, (ids, archive)))
            dialog.finished.connect(lambda *_: setattr(self, '_tags_dialog', None))
            dialog.open()

        job = self.window.queue.submit('读取关卡作战指标', lambda **kw: load(root, path, version, **options, **kw),
                                       done, show_in_tasks=False)
        self._tags_job = job

    def _tags_settled(self, job):
        if job is self._tags_job:
            self._tags_job = None

    def save_state(self):
        return self.view.save_state()

    def restore_state(self, state):
        self.view.restore_state(state)


class SettingsPage(PageController):
    view_module = '.settings'

    def create_view(self):
        from .settings import SettingsView
        return SettingsView(self.window.services.config, Path(self.window.services.data_root))

    def connect(self):
        self.view.changed.connect(self.window.save_settings)
        self.view.output.textChanged.connect(lambda text: self.window.output_label.setText('输出：' + text))


@dataclass(frozen=True)
class PageDefinition:
    page_id: str
    title: str
    controller: Callable[[object], PageController]


PAGE_DEFINITIONS = (
    PageDefinition('explorer', '资源浏览', ExplorerPage),
    PageDefinition('updates', '更新记录', UpdatesPage),
    PageDefinition('operators', '干员资料', OperatorsPage),
    PageDefinition('modules', '模组更新', ModulesPage),
    PageDefinition('gameplay', '玩法资料', GameplayPage),
    PageDefinition('levels', '关卡预览', LevelCatalogPage),
    PageDefinition('settings', '设置', SettingsPage),
)


class PageComposition:
    """Assemble the local registry and dispatch lifecycle work to present pages."""
    def __init__(self, window, definitions=None):
        self.window = window
        self._pages = {}
        definitions = tuple(PAGE_DEFINITIONS if definitions is None else definitions)
        ids = [page.page_id for page in definitions]
        if len(ids) != len(set(ids)):
            raise ValueError('页面 ID 不能重复。')
        missing = REQUIRED_PAGES.difference(ids)
        if missing:
            raise ValueError('缺少必要页面：' + ', '.join(sorted(missing)))
        # Keep the established script/test entry points even in a reduced build.
        for page_id in LEGACY_PAGE_ORDER:
            setattr(window, page_id, None)
        for definition in definitions:
            try:
                page = definition.controller(window)
            except ModuleNotFoundError as error:
                module = getattr(definition.controller, 'view_module', '')
                expected = __package__ + module if module.startswith('.') else module
                # Only absence of the optional page itself is recoverable here.
                # Broken imports inside an existing page still surface normally.
                if definition.page_id in REQUIRED_PAGES or error.name != expected:
                    raise
                continue
            self._pages[definition.page_id] = page
            page.widget.setProperty('pageId', definition.page_id)
            window.tabs.addTab(page.widget, definition.title)
            if definition.page_id in LEGACY_PAGE_ORDER:
                setattr(window, definition.page_id, page.view)

    def widget(self, page_id):
        page = self._pages.get(page_id)
        return page.widget if page else None

    def current_id(self):
        current = self.window.tabs.currentWidget()
        return next((page_id for page_id, page in self._pages.items() if page.widget is current), None)

    def select(self, page_id):
        widget = self.widget(page_id)
        if widget is not None:
            self.window.tabs.setCurrentWidget(widget)

    def connect(self):
        for page in self._pages.values():
            page.connect()

    def set_root(self, root):
        for page in self._pages.values():
            page.set_root(root)

    def scanned(self, snapshot, changes, catalog):
        for page in self._pages.values():
            page.scanned(snapshot, changes, catalog)

    def data_loaded(self):
        for page in self._pages.values():
            page.data_loaded()

    def refresh_entities(self):
        for page in self._pages.values():
            page.refresh_entities()

    def hours_changed(self):
        for page in self._pages.values():
            page.hours_changed()

    def queue_changed(self):
        for page in self._pages.values():
            page.queue_changed()

    def profile(self, kind, entity_id, spec):
        page = self._pages.get(kind)
        if isinstance(page, EntityPage):
            page.profile(entity_id, spec)

    def report_spec(self, kind, ids):
        page = self._pages.get(kind)
        return page.report_spec(ids) if isinstance(page, EntityPage) else BuildSpec()

    def save_state(self, previous):
        state = dict(previous)
        saved_pages = dict(state.get('pages', {}))
        for page_id, page in self._pages.items():
            saved_pages[page_id] = page.save_state()
        state.update(tab=self.current_id(), pages=saved_pages)
        return state

    def restore_state(self, state):
        saved_pages = state.get('pages', {})
        for page_id, page in self._pages.items():
            page.restore_state(saved_pages.get(page_id, page.legacy_state(state)))
        page_id = state.get('tab', 'explorer')
        if isinstance(page_id, int) or (isinstance(page_id, str) and page_id.isdigit()):
            page_id = LEGACY_PAGE_ORDER[max(0, min(len(LEGACY_PAGE_ORDER) - 1, int(page_id)))]
        if page_id not in self._pages:
            page_id = 'explorer' if 'explorer' in self._pages else next(iter(self._pages))
        self.select(page_id)
