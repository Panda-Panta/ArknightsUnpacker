from __future__ import annotations

from functools import partial
from dataclasses import replace
from pathlib import Path
import uuid
import os
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QCloseEvent, QFontDatabase, QFont
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QLineEdit, QPushButton, QFileDialog, QDoubleSpinBox, QCheckBox, QTabWidget,
    QComboBox, QMessageBox, QScrollArea)
from arknights_unpacker.contracts import BuildSpec, ExportFormat, ReportOptions, ExtractionResult, as_jsonable
from .models import value, selected_records
from .explorer import ExplorerView
from .updates import UpdatesView
from .operator_view import OperatorView
from .module_view import ModuleView
from .jobs import JobQueue, JobsView
from .settings import SettingsView
from .report_preview import ObjectsDialog, ReportArtifactsDialog
from .styles import apply_theme
from .job_history import remaining_extraction


class MainWindow(QMainWindow):
    """Native workbench; all expensive services run in a serial cancellable queue."""
    def __init__(self, services, initial_root: str = ''):
        super().__init__()
        apply_theme(QApplication.instance())
        self.services = services
        self._scan_pending = False
        self._load_pending = False
        self._monitor_stamp = None
        self._dialogs = []
        self._profile_pending = set()
        self._restored_module_choices = {}
        self._closing = False
        self._restore_pending = False
        self._view_state_ready = False
        self._display_data_identity = None
        if not QFontDatabase.families():
            # The offscreen Qt platform has no system font discovery on Windows.
            font_path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'
            if font_path.is_file():
                font_id = QFontDatabase.addApplicationFont(str(font_path))
                families = QFontDatabase.applicationFontFamilies(font_id)
                if families:
                    self.setFont(QFont(families[0], 10))
        self.setWindowTitle('明日方舟 · 资源与资料工作台')
        self.resize(1450, 930)
        self.setMinimumSize(1050, 700)
        self.queue = JobQueue(self, history_root=Path(services.data_root) / 'queue', resume_handler=self.prepare_recovery)
        self.queue.message.connect(self.show_status)
        self.queue.changed.connect(self._queue_changed)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(14, 12, 14, 10)
        layout.setSpacing(10)
        header = QFrame()
        header.setObjectName('header')
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 14)
        header_layout.setSpacing(10)
        title_row = QHBoxLayout()
        title = QLabel('ARKNIGHTS // 资源与资料工作台')
        title.setObjectName('appTitle')
        title_row.addWidget(title)
        title_row.addStretch()
        subtitle = QLabel('PRTS TERMINAL · 资源索引 / 资料档案 / 原图导出')
        subtitle.setObjectName('subtitle')
        title_row.addWidget(subtitle)
        header_layout.addLayout(title_row)
        root_row = QHBoxLayout()
        root_row.setSpacing(8)
        root_row.addWidget(QLabel('游戏目录'))
        self.root_edit = QLineEdit(initial_root or str(services.config.get('game_root', '')))
        self.root_edit.setObjectName('gameRoot')
        self.root_edit.setPlaceholderText('选择游戏根目录、Arknights_Data 或单层资源目录')
        self.root_edit.returnPressed.connect(self.scan)
        root_row.addWidget(self.root_edit, 1)
        self.choose_root_button = QPushButton('选择目录…')
        self.choose_root_button.clicked.connect(self.choose_root)
        root_row.addWidget(self.choose_root_button)
        self.scan_button = QPushButton('扫描 / 检查更新')
        self.scan_button.setToolTip('与程序旁已保存的完整扫描比较，不会删除原有历史结果。')
        self.scan_button.setProperty('primary', True)
        self.scan_button.setObjectName('scanButton')
        self.scan_button.clicked.connect(self.scan)
        root_row.addWidget(self.scan_button)
        root_row.addWidget(QLabel('最近'))
        self.hours = QDoubleSpinBox()
        self.hours.setObjectName('recentHours')
        self.hours.setRange(0.01, 876000)
        self.hours.setDecimals(2)
        self.hours.setValue(float(services.config.get('hours', 24)))
        self.hours.setSuffix(' 小时')
        self.hours.setFixedWidth(130)
        self.hours.valueChanged.connect(self._hours_changed)
        root_row.addWidget(self.hours)
        self.strict = QCheckBox('严格校验')
        self.strict.setToolTip('重新计算所选资源范围的完整摘要；耗时更长，可取消。')
        root_row.addWidget(self.strict)
        header_layout.addLayout(root_row)
        self.session_label = QLabel('扫描和解析结果会自动保存在程序旁；下次启动直接读取。')
        self.session_label.setObjectName('sessionStatus')
        self.session_label.setWordWrap(True)
        header_layout.addWidget(self.session_label)
        layout.addWidget(header)
        baseline_row = QHBoxLayout()
        baseline_row.addWidget(QLabel('资料对照'))
        self.history = QComboBox()
        self.history.setMinimumWidth(350)
        self.history.addItem('解析核心数据后可选择历史快照', None)
        baseline_row.addWidget(self.history, 1)
        compare = QPushButton('与选中快照比较')
        compare.clicked.connect(self.compare_history)
        baseline_row.addWidget(compare)
        import_button = QPushButton('导入历史基线…')
        import_button.clicked.connect(self.import_baseline)
        baseline_row.addWidget(import_button)
        export_button = QPushButton('导出当前数据快照…')
        export_button.clicked.connect(self.export_snapshot)
        baseline_row.addWidget(export_button)
        layout.addLayout(baseline_row)
        self.tabs = QTabWidget()
        self.tabs.setObjectName('mainTabs')
        self.explorer = ExplorerView()
        self.updates = UpdatesView()
        self.operators = OperatorView()
        self.modules = ModuleView()
        self.jobs = JobsView(self.queue)
        self.settings = SettingsView(services.config, Path(services.data_root))
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setWidget(self.settings)
        for view, name in [(self.explorer, '资源浏览'), (self.updates, '更新记录'),
                           (self.operators, '干员资料'), (self.modules, '模组更新'),
                           (self.jobs, '导出任务'), (settings_scroll, '设置')]:
            self.tabs.addTab(view, name)
        layout.addWidget(self.tabs, 1)
        footer = QHBoxLayout()
        self.output_label = QLabel('输出：' + self.settings.output.text())
        self.output_label.setObjectName('subtitle')
        footer.addWidget(self.output_label, 1)
        open_output = QPushButton('打开输出')
        open_output.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.settings.output.text())))
        footer.addWidget(open_output)
        self.cancel_button = QPushButton('取消当前任务')
        self.cancel_button.clicked.connect(self.queue.cancel)
        self.cancel_button.setEnabled(False)
        footer.addWidget(self.cancel_button)
        layout.addLayout(footer)
        self.statusBar().showMessage('选择游戏目录开始，或读取上次保存的扫描与资料。')
        self.explorer.extract_requested.connect(self.extract)
        self.updates.extract_requested.connect(self.extract)
        self.updates.images_requested.connect(lambda paths: self.extract(paths, kinds=['image'], mode='auto'))
        self.explorer.objects_requested.connect(self.objects)
        self.settings.changed.connect(self.save_settings)
        self.settings.output.textChanged.connect(lambda text: self.output_label.setText('输出：' + text))
        self.operators.load_requested.connect(self.load_data)
        self.modules.load_requested.connect(self.load_data)
        self.operators.profile_requested.connect(partial(self.profile, 'operators'))
        self.modules.profile_requested.connect(partial(self.profile, 'modules'))
        self.operators.export_requested.connect(partial(self.export, 'operators'))
        self.modules.export_requested.connect(partial(self.export, 'modules'))
        self.operators.preview_requested.connect(partial(self.preview_reports, 'operators'))
        self.modules.preview_requested.connect(partial(self.preview_reports, 'modules'))
        self.jobs.artifacts_requested.connect(self.show_report_artifacts)
        self.monitor_timer = QTimer(self)
        self.monitor_timer.setInterval(15000)
        self.monitor_timer.timeout.connect(self.check_manifests)
        self.monitor_timer.start()
        self._queue_changed()
        if self.root_edit.text().strip():
            QTimer.singleShot(0, self.restore_previous)

    def restore_previous(self):
        if self._closing or self._restore_pending or self.queue.busy:
            return
        root = self.root_edit.text().strip()
        if not root:
            return
        self._restore_pending = True
        job = self.queue.submit('读取上次扫描与解析结果',
                                lambda **kw: self.services.restore(root, **kw), self.restored)
        def cleanup():
            if job.status not in ('排队中', '运行中', '正在取消'):
                self._restore_pending = False
        self.queue.changed.connect(cleanup)

    def restored(self, result):
        if result.get('snapshot') is not None:
            self.scanned(result)
        elif self.services.gamedata is not None:
            self.data_loaded(self.services.gamedata)
        else:
            self.refresh_entities()
            self.refresh_history()
        self.restore_view_state()
        self._view_state_ready = True
        has_results = self.services.scan_snapshot is not None or self.services.gamedata is not None
        self.refresh_session_label(restored=has_results)
        if has_results:
            self.show_status('已读取上次保存的结果。点击“扫描 / 检查更新”与已保存基线比较；核心资料可直接查看和导出。')
        else:
            self.show_status('当前目录尚无保存结果。点击“扫描 / 检查更新”，再按需解析核心数据。')

    def refresh_session_label(self, *, restored=False):
        scan = self.services.scan_snapshot
        data = self.services.gamedata
        parts = ['已恢复保存结果' if restored else '结果已自动保存']
        if scan is not None:
            from .models import time_text
            parts.append(f'{len(value(scan, "files", [])):,} 个文件 · {time_text(value(scan, "finished_at"))}')
        if data is not None:
            parts.append(f'资料 {value(data, "version", "未知版本")} · {len(self.services.operators()):,} 项干员资料')
        if len(parts) == 1:
            parts = ['当前目录暂无保存结果，扫描后自动记录。']
        self.session_label.setText('　|　'.join(parts))
        self.session_label.setToolTip('保存位置：' + str(self.services.data_root))

    def remember_view_state(self):
        # Cancelling startup must not save the empty defaults over the user's
        # previous filters, selected operator or tab before they were restored.
        if not self._view_state_ready:
            return
        root = value(self.services.installation, 'root') or self.root_edit.text().strip()
        if not root:
            return
        def selected_id(view):
            rows = selected_records(view.table)
            return str(rows[0]['id']) if len(rows) == 1 else None
        state = {'root': str(Path(root).resolve()), 'tab': self.tabs.currentIndex(),
                 'explorer_folder': self.explorer.folder, 'explorer_recursive': self.explorer.recursive.isChecked(),
                 'explorer_ab': self.explorer.ab_only.isChecked(), 'explorer_search': self.explorer.search.text(),
                 'update_mode': self.updates.mode.currentIndex(), 'update_ab': self.updates.ab_only.isChecked(),
                 'update_search': self.updates.search.text()}
        for key, view in (('operators', self.operators), ('modules', self.modules)):
            state[key] = {'search': view.search.text(), 'only_changes': view.only_changes.isChecked(),
                          'only_new': view.only_new.isChecked(), 'selected_id': selected_id(view),
                          'module_id': view.module_choice.currentData()}
        states = self.services.config.setdefault('view_states', {})
        states[state['root']] = state

    def restore_view_state(self):
        root = value(self.services.installation, 'root') or self.root_edit.text().strip()
        if not root:
            return
        state = self.services.config.get('view_states', {}).get(str(Path(root).resolve()), {})
        if not state:
            return
        self.explorer.recursive.setChecked(bool(state.get('explorer_recursive', False)))
        self.explorer.ab_only.setChecked(bool(state.get('explorer_ab', False)))
        self.explorer.search.setText(state.get('explorer_search', ''))
        folder = str(state.get('explorer_folder', ''))
        if (self.explorer.root / folder).resolve().is_relative_to(self.explorer.root.resolve()):
            self.explorer.folder = folder
            self.explorer.refresh()
            self.explorer.breadcrumb.setText(str(self.explorer.root / folder))
        self.updates.mode.setCurrentIndex(max(0, min(3, int(state.get('update_mode', 2)))))
        self.updates.ab_only.setChecked(bool(state.get('update_ab', False)))
        self.updates.search.setText(state.get('update_search', ''))
        for key, view in (('operators', self.operators), ('modules', self.modules)):
            saved = state.get(key, {})
            view.search.setText(saved.get('search', ''))
            view.only_changes.setChecked(bool(saved.get('only_changes', False)))
            view.only_new.setChecked(bool(saved.get('only_new', False)))
            for index, row in enumerate(view.model.rows):
                if str(row['id']) == saved.get('selected_id'):
                    if key == 'operators' and saved.get('module_id'):
                        self._restored_module_choices[(key, str(row['id']))] = saved['module_id']
                    view.table.selectRow(index)
                    break
        self.tabs.setCurrentIndex(max(0, min(self.tabs.count() - 1, int(state.get('tab', 0)))))

    def show_status(self, message):
        self.statusBar().showMessage(str(message)[-450:])

    def _queue_changed(self):
        self.cancel_button.setEnabled(self.queue.busy)
        self.root_edit.setEnabled(not self.queue.busy)
        self.choose_root_button.setEnabled(not self.queue.busy)
        waiting = sum(j.status == '排队中' for j in self.queue.jobs)
        self.tabs.setTabText(4, f'导出任务 ({waiting + int(self.queue.busy)})' if self.queue.busy or waiting else '导出任务')
        if self._closing and not self.queue.busy:
            QTimer.singleShot(0, self.close)

    def choose_root(self):
        root = QFileDialog.getExistingDirectory(self, '选择游戏目录', self.root_edit.text())
        if root:
            self.root_edit.setText(root)
            self.scan()

    def scan(self):
        if self._scan_pending:
            self.show_status('扫描已在队列中。')
            return
        root = self.root_edit.text().strip()
        if not root:
            self.show_status('请先选择游戏目录。')
            return
        if not Path(root).is_dir():
            self.show_status('游戏目录不存在或无法访问：' + root)
            return
        self.remember_view_state()
        hours, strict = self.hours.value(), self.strict.isChecked()
        self.services.config.update(game_root=root, hours=hours)
        self.services.save_config()
        self.explorer.set_root(root)
        self._scan_pending = True
        self.scan_button.setEnabled(False)
        job = self.queue.submit('扫描游戏目录' + ('（严格校验）' if strict else ''),
                               lambda **kw: self.services.scan(root, hours=hours, strict=strict, **kw),
                               self.scanned, request={'operation': 'scan', 'root': root, 'hours': hours, 'strict': strict})
        # Failure and cancellation must also release the scan button.
        self.queue.changed.connect(self._scan_state)
        self._scan_job = job

    def _scan_state(self):
        job = getattr(self, '_scan_job', None)
        if job and job.status not in ('排队中', '运行中', '正在取消'):
            self._scan_pending = False
            self.scan_button.setEnabled(True)

    def scanned(self, result):
        snapshot = result.get('snapshot', self.services.scan_snapshot)
        changes = result.get('changes', self.services.file_changes)
        catalog = result.get('catalog', self.services.catalog)
        normalized_root = value(snapshot, 'root')
        if normalized_root:
            self.root_edit.setText(str(normalized_root))
            if self.explorer.root != Path(normalized_root):
                self.explorer.set_root(str(normalized_root))
        self.explorer.set_data(snapshot, changes, catalog)
        self.updates.set_data(snapshot, changes, self.hours.value())
        self._monitor_stamp = self.manifest_stamp()
        self.refresh_history()
        self.refresh_entities()
        self.refresh_session_label()
        self.restore_view_state()
        self._view_state_ready = True
        self.show_status(f'扫描{"完成" if value(snapshot, "complete") else "存在未完成项"}：{len(value(snapshot, "files", [])):,} 个文件。')

    def _hours_changed(self):
        if self.updates.snapshot:
            self.updates.hours = self.hours.value()
            self.updates.refresh()

    def load_data(self):
        root = self.root_edit.text().strip()
        if not root or not Path(root).is_dir():
            self.show_status('请先选择可访问的游戏目录。')
            return
        if self._load_pending:
            self.show_status('核心数据解析已在队列中。')
            return
        self.settings.commit()
        self.remember_view_state()
        self._load_pending = True
        self._load_job = self.queue.submit('解析核心数据', lambda **kw: self.services.load_data(root, **kw), self.data_loaded,
                                          request={'operation': 'load_data', 'root': root, 'locale': self.services.config.get('data_locale', 'unknown')})
        self.queue.changed.connect(self._load_state)

    def _load_state(self):
        job = getattr(self, '_load_job', None)
        if job and job.status not in ('排队中', '运行中', '正在取消'):
            self._load_pending = False

    def data_loaded(self, snapshot):
        installation_root = value(self.services.installation, 'root')
        if installation_root:
            self.root_edit.setText(str(installation_root))
            if self.explorer.root != Path(installation_root):
                self.explorer.set_root(str(installation_root))
                physical = self.services.scan_snapshot
                matches = physical is not None and Path(value(physical, 'root', '')) == Path(installation_root)
                self.explorer.set_data(physical if matches else None,
                                       self.services.file_changes if matches else None, self.services.catalog)
                if not matches:
                    self.updates.snapshot = self.updates.changes = None
                    self.updates.model.replace([])
                    self.updates.summary.setText('当前安装的核心数据已解析；文件更新记录需要重新扫描。')
                    self.updates.empty.clear()
        self.refresh_entities()
        self.refresh_history()
        self.refresh_session_label()
        self.restore_view_state()
        self._view_state_ready = True
        self.show_status('核心资料已解析。首次快照的历史状态未知；可导入完整历史基线比较。')

    def refresh_entities(self):
        if self.services.gamedata is None:
            self.operators.clear_data()
            self.modules.clear_data()
            self._display_data_identity = None
            return
        identity = (value(self.services.installation, 'profile_id'), value(self.services.gamedata, 'snapshot_id'))
        if identity != self._display_data_identity:
            self.operators.clear_data()
            self.modules.clear_data()
            self._restored_module_choices.clear()
        self._display_data_identity = identity
        changes = self.services.entity_changes
        self.operators.set_rows(self.services.operators(), changes, self.services.gamedata)
        self.modules.set_rows(self.services.modules(), changes, self.services.gamedata)

    def profile(self, kind, entity_id, spec):
        key = (kind, entity_id, spec.module_id)
        if key in self._profile_pending:
            return
        self._profile_pending.add(key)
        view = self.operators if kind == 'operators' else self.modules
        method = self.services.operator_profile if kind == 'operators' else self.services.module_profile
        def call(**kw):
            kw['cancel'].check()
            return method(entity_id, spec)
        def done(result):
            self._profile_pending.discard(key)
            rows = selected_records(view.table)
            if len(rows) == 1 and str(rows[0]['id']) == entity_id and view.module_choice.currentData() == spec.module_id:
                view.set_profile(result)
                module_id = self._restored_module_choices.pop((kind, entity_id), None)
                if module_id:
                    index = view.module_choice.findData(module_id)
                    if index >= 0:
                        view.module_choice.setCurrentIndex(index)
        job = self.queue.submit('查看资料 · ' + entity_id, call, done)
        def cleanup():
            if job.status not in ('运行中', '排队中', '正在取消'):
                self._profile_pending.discard(key)
        self.queue.changed.connect(cleanup)

    def output_root(self):
        text = self.settings.output.text().strip()
        if not text:
            self.show_status('请在设置中选择独立输出目录。')
            return None
        output = Path(text).resolve()
        root = self.root_edit.text().strip()
        if root and output.is_relative_to(Path(root).resolve()):
            self.show_status('输出目录不能位于游戏目录中。请在设置中选择独立目录。')
            return None
        return str(output)

    def extract(self, paths, object_ids=None, preview_dialog=None, *, kinds=None, mode=None):
        output = str(Path(self.services.data_root) / 'preview' / uuid.uuid4().hex) if preview_dialog else self.output_root()
        if output is None:
            return
        kinds = list(kinds) if kinds is not None else [key for key, check in self.settings.kinds.items() if check.isChecked()]
        mode = mode if mode is not None else self.settings.mode.currentData()
        if not kinds:
            self.show_status('请在设置中至少选择一种资源类型。')
            return
        self.show_status(f'加入解包队列：{len(paths)} 个文件 · {mode} · {output}')
        def done(result):
            errors = value(result, 'errors', [])
            if errors and self.queue.active:
                failed_paths = list(dict.fromkeys(str(e.get('source')) for e in errors if e.get('source')))
                failed_ids = {}
                for path in failed_paths:
                    failures = [e for e in errors if str(e.get('source')) == path]
                    if all(e.get('object_id') is not None for e in failures):
                        failed_ids[path] = [str(e['object_id']) for e in failures]
                if failed_paths:
                    self.queue.active.retry_call = lambda **kw: self.services.extract(failed_paths, output, kinds=kinds,
                                                                                     object_ids=failed_ids, mode=mode, **kw)
            if preview_dialog:
                outputs = value(result, 'outputs', [])
                for item in outputs:
                    path = item.get('path', item.get('output_path', item.get('output', ''))) if isinstance(item, dict) else str(item)
                    if path and Path(path).is_file():
                        preview_dialog.show_file(path)
                        break
                else:
                    preview_dialog.status.setText('未生成可预览文件。请在任务页查看失败或跳过原因。')
        title = '预览对象' if preview_dialog else '导出包内原图' if kinds == ['image'] and mode == 'auto' else '解包所选'
        self.queue.submit(title + f' · {len(paths)} 个文件',
                          lambda **kw: self.services.extract(paths, output, kinds=kinds, object_ids=object_ids, mode=mode, **kw), done, output,
                          request={'operation': 'extract', 'root': str(value(self.services.installation, 'root') or self.root_edit.text().strip()), 'paths': list(paths),
                                   'output': output, 'kinds': kinds, 'object_ids': object_ids or {}, 'mode': mode})

    def objects(self, path):
        dialog = ObjectsDialog(path, self)
        self._dialogs.append(dialog)
        dialog.extract_requested.connect(lambda source, ids, preview: self.extract([source], {source: ids}, dialog if preview else None))
        dialog.show()
        self.queue.submit('读取内部对象 · ' + Path(path).name,
                          lambda **kw: self.services.objects(path, **kw), dialog.set_objects)

    def export(self, kind, ids, only_new=False, *, preview=False, report_spec=None, report_options=None):
        output = str(Path(self.services.data_root) / 'previews' / uuid.uuid4().hex) if preview else self.output_root()
        formats = self.settings.selected_formats()
        if preview:
            formats = formats | {ExportFormat.PNG}
        if output is None:
            return
        if not formats:
            self.show_status('请在设置中至少选择一种导出格式。')
            return
        if only_new and not value(self.services.entity_changes, 'baseline_id'):
            self.show_status('没有可比较的历史数据基线，不能认定本次新增。')
            return
        operators, modules = (ids, []) if kind == 'operators' else ([], ids)
        # A single chosen module may enter the static panel; never combine modules.
        spec = report_spec or (BuildSpec(module_id=self.operators.module_choice.currentData()) if kind == 'operators' and len(ids) == 1 else BuildSpec())
        options = report_options or self.settings.report_options()
        if kind == 'modules' and only_new and not options.title:
            options = replace(options, title='本次新增模组')
        def done(artifacts):
            if preview:
                # AppServices records its target; preview cache must not become the saved user output.
                self.services.config['output_root'] = self.settings.output.text().strip()
                self.services.save_config()
            self.show_status(f'资料{"预览" if preview else "导出"}完成：{len(artifacts)} 个产物。')
            self.show_report_artifacts(artifacts, preview_only=preview,
                                       export_action=(lambda: self.export(kind, ids, report_spec=spec, report_options=options)) if preview else None)
        self.queue.submit(f'{"预览" if preview else "导出"}{"新增" if only_new else "选中"}资料 · {len(ids)} 项',
                          lambda **kw: self.services.export(operators, modules, output, formats, spec=spec, options=options, **kw),
                          done, output, request={'operation': 'report', 'root': self.root_edit.text().strip(),
                          'snapshot_id': value(self.services.gamedata, 'snapshot_id'), 'operators': operators, 'modules': modules,
                          'output': output, 'formats': [fmt.value for fmt in formats], 'spec': as_jsonable(spec),
                          'options': as_jsonable(options), 'preview': preview})
        self.tabs.setCurrentWidget(self.jobs)

    def preview_reports(self, kind, ids):
        self.export(kind, ids, preview=True)

    def prepare_recovery(self, job):
        """Resolve declarative history only after the user explicitly presses retry."""
        request = job.request or {}
        operation = request.get('operation')
        if operation == 'scan':
            return (lambda **kw: self.services.scan(request['root'], hours=request.get('hours', 24),
                    strict=request.get('strict', False), **kw)), self.scanned
        if operation == 'load_data':
            if request.get('locale', 'unknown') != self.services.config.get('data_locale', 'unknown'):
                raise ValueError('历史解析任务的区服声明与当前设置不同。请确认设置后，从资料页重新解析。')
            return (lambda **kw: self.services.load_data(request['root'], **kw)), self.data_loaded
        if operation == 'extract':
            root = request.get('root', '')
            evidence = self.queue.history.evidence(job) if self.queue.history else [{'result': job.result}]
            scan_result = []
            def call(**kw):
                current = value(self.services.installation, 'root')
                if root and (not current or Path(current).resolve() != Path(root).resolve()):
                    kw['emit']({'message': '正在恢复任务原来的只读游戏目录…'})
                    scan_result.append(self.services.scan(root, **kw))
                paths, ids = remaining_extraction(request, evidence, self.services.objects, kw['emit'], kw['cancel'])
                if not paths:
                    return ExtractionResult(status='succeeded', skipped=[{'reason': '原请求已全部完成，保留已有产物。'}])
                kw['emit']({'message': f'恢复 {len(paths)} 个未完成来源；已完成对象不再导出。未知完整性的组按未完成组处理，已有产物保留。'})
                return self.services.extract(paths, request['output'], kinds=request.get('kinds'), object_ids=ids,
                                             mode=request.get('mode', 'auto'), **kw)
            def done(result):
                if scan_result:
                    self.scanned(scan_result[-1])
                self.show_status(f'恢复任务完成：{len(value(result, "outputs", []))} 个新产物；原有产物保留。')
            return call, done
        if operation == 'report':
            self.check_report_binding(request)
            spec = BuildSpec(**request.get('spec', {}))
            options = ReportOptions(**request.get('options', {}))
            formats = {ExportFormat(fmt) for fmt in request.get('formats', [])}
            def call(**kw):
                # Earlier queued tasks may have loaded another snapshot/installation.
                self.check_report_binding(request)
                return self.services.export(request.get('operators', []), request.get('modules', []), request['output'],
                                            formats, spec=spec, options=options, **kw)
            def done(artifacts):
                if request.get('preview'):
                    self.services.config['output_root'] = self.settings.output.text().strip()
                    self.services.save_config()
                self.show_report_artifacts(artifacts)
            return call, done
        raise ValueError('此任务类型没有恢复入口，请从对应页面重新操作；历史产物仍保留。')

    def check_report_binding(self, request):
        if self.services.gamedata is None:
            raise ValueError('请先解析历史任务对应的核心数据，再手动重试报告。已生成的历史产物可直接预览。')
        if value(self.services.gamedata, 'snapshot_id') != request.get('snapshot_id'):
            raise ValueError('当前数据快照与历史报告任务不同。请从资料页重新选择导出，避免将当前资料冒充旧快照。')
        root = request.get('root')
        if root:
            current = value(self.services.installation, 'root')
            if not current or Path(current).resolve() != Path(root).resolve():
                raise ValueError('当前游戏安装与历史报告来源不同。请先解析原安装的核心数据，或从当前资料页重新导出。')

    def show_report_artifacts(self, artifacts, *, preview_only=False, export_action=None):
        dialog = ReportArtifactsDialog(artifacts, self, preview_only=preview_only)
        dialog.html_open_requested.connect(lambda path: QDesktopServices.openUrl(QUrl.fromLocalFile(path)))
        if export_action:
            dialog.export_requested.connect(export_action)
        self._dialogs.append(dialog)
        dialog.show()

    def refresh_history(self):
        installation = self.services.installation
        if installation is None:
            return
        current = self.history.currentData()
        self.history.clear()
        self.history.addItem('选择完整历史数据快照', None)
        for item in self.services.store.list_data_snapshots(value(installation, 'profile_id')):
            snapshot_id = item.get('snapshot_id', item.get('id'))
            label = f'{item.get("version", "未知版本")} · {snapshot_id}'
            if not item.get('complete', True):
                label += '（不完整）'
            self.history.addItem(label, snapshot_id)
        index = self.history.findData(current)
        if index >= 0:
            self.history.setCurrentIndex(index)

    def compare_history(self):
        snapshot_id = self.history.currentData()
        if not snapshot_id or self.services.gamedata is None:
            self.show_status('请先解析核心数据并选择完整历史快照。')
            return
        self.queue.submit('比较历史数据快照', lambda **kw: self.services.compare_snapshot(snapshot_id), lambda _: self.refresh_entities())

    def import_baseline(self):
        if self.services.gamedata is None:
            self.show_status('请先解析当前核心数据，再导入历史基线进行比较。')
            return
        path, _ = QFileDialog.getOpenFileName(self, '导入同服历史数据基线', '', '数据快照 (*.json);;所有文件 (*)')
        if path:
            self.queue.submit('导入历史数据基线', lambda **kw: self.services.import_baseline(path), lambda _: (self.refresh_entities(), self.refresh_history()))

    def export_snapshot(self):
        if self.services.gamedata is None:
            self.show_status('请先解析核心数据。')
            return
        path, _ = QFileDialog.getSaveFileName(self, '导出当前完整数据快照', str(Path(self.settings.output.text()) / 'data-snapshot.json'), '数据快照 (*.json)')
        if path:
            root = self.root_edit.text().strip()
            if root and Path(path).resolve().is_relative_to(Path(root).resolve()):
                self.show_status('数据快照输出不能位于游戏目录中。')
                return
            self.queue.submit('导出数据快照', lambda **kw: self.services.export_snapshot(path), output=str(Path(path).parent))

    def save_settings(self):
        self.services.save_config()
        self.show_status('设置已保存。')

    def manifest_stamp(self):
        installation = self.services.installation
        if installation is None:
            return None
        stamp = []
        for root in value(installation, 'source_roots', {}).values():
            for name in ('hot_update_list.json', 'persistent_res_list.json', 'resource_manifest.json'):
                path = Path(root) / name
                try:
                    info = path.stat()
                    stamp.append((str(path), info.st_mtime_ns, info.st_size))
                except OSError:
                    stamp.append((str(path), None, None))
        return tuple(stamp)

    def check_manifests(self):
        if not self.settings.monitor.isChecked() or self.queue.busy or self._scan_pending:
            return
        stamp = self.manifest_stamp()
        if self._monitor_stamp is not None and stamp != self._monitor_stamp:
            self.show_status('资源清单发生变化，已安排重新扫描。')
            self.scan()
        self._monitor_stamp = stamp

    def closeEvent(self, event: QCloseEvent):
        self._closing = True
        self.monitor_timer.stop()
        self.queue.shutdown()
        if self.queue.busy:
            self.show_status('正在取消任务并等待工作进程退出，完成后将自动关闭。')
            event.ignore()
            return
        self.remember_view_state()
        self.services.config.update(game_root=self.root_edit.text().strip(), hours=self.hours.value())
        # commit emits changed -> save_settings once, including the view state.
        self.settings.commit()
        event.accept()
