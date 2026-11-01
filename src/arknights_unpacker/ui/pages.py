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
REQUIRED_PAGES = frozenset(('jobs', 'settings'))


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

        job = self.window.queue.submit('查看资料 · ' + entity_id, call, done)

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


class JobsPage(PageController):
    view_module = '.jobs'

    def create_view(self):
        from .jobs import JobsView
        return JobsView(self.window.queue)

    def connect(self):
        self.view.artifacts_requested.connect(self.window.show_report_artifacts)

    def queue_changed(self):
        queue = self.window.queue
        waiting = sum(job.status == '排队中' for job in queue.jobs)
        count = waiting + int(queue.busy)
        index = self.window.tabs.indexOf(self.widget)
        if index >= 0:
            self.window.tabs.setTabText(index, f'导出任务 ({count})' if count else '导出任务')


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
    PageDefinition('jobs', '导出任务', JobsPage),
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
