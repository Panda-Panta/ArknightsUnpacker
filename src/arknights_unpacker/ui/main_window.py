from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import os
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QCloseEvent, QFontDatabase, QFont
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QLineEdit, QPushButton, QFileDialog, QDoubleSpinBox, QCheckBox, QTabWidget,
    QComboBox, QSizePolicy)
from arknights_unpacker.contracts import BuildSpec, ExportFormat, ReportOptions, ExtractionResult, as_jsonable
from .models import value
from .jobs import JobQueue
from .pages import PageComposition
from .report_preview import ObjectsDialog, ReportArtifactsDialog
from .styles import apply_theme
from .job_history import remaining_extraction
from .preview_cache import PreviewCache, legacy_preview_paths


class _PathLabel(QLabel):
    """Keep the full output path available without forcing the window wider."""
    def setText(self, text):
        self._full_text = text
        self.setToolTip(text)
        super().setText(self.fontMetrics().elidedText(text, Qt.TextElideMode.ElideMiddle, self.width()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_full_text'):
            self.setText(self._full_text)


class MainWindow(QMainWindow):
    """Native workbench; all expensive services run in a serial cancellable queue."""
    def __init__(self, services, initial_root: str = '', *, page_definitions=None):
        super().__init__()
        apply_theme(QApplication.instance())
        self.services = services
        self._scan_pending = False
        self._load_pending = False
        self._scan_job = None
        self._load_job = None
        self._monitor_stamp = None
        self._dialogs = []
        self._dialog_jobs = {}
        self._preview_jobs = {}
        self._object_preview_jobs = {}
        self._object_preview_pending = {}
        self._report_preview_jobs = {}
        self._report_preview_pending = {}
        self._displayed_preview_jobs = set()
        self._discard_when_settled = set()
        self._preview_warning_count = 0
        self._closing = False
        self._restore_pending = False
        self._view_state_ready = False
        history_root = Path(services.data_root) / 'queue'
        old_previews = legacy_preview_paths(services.data_root, history_root)
        saved_output = services.config.get('output_root')
        if saved_output and Path(saved_output).expanduser().resolve() in old_previews:
            from arknights_unpacker.paths import default_output_root, validate_output
            output = validate_output(default_output_root(), services.config.get('game_root'))
            output.mkdir(parents=True, exist_ok=True)
            services.config['output_root'] = str(output)
            services.save_config()
        self.preview_cache = PreviewCache(services.data_root,
            protected_roots=[services.config['output_root']] if services.config.get('output_root') else [])
        self.preview_cache.cleanup_stale(history_root)
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
        removed_previews = {Path(path) for path in self.preview_cache.last_cleanup['removed']}
        self.queue.forget_finished([job.job_id for job in self.queue.jobs
            if job.status == '成功' and (job.request or {}).get('output') and
            (Path(job.request['output']).expanduser().resolve() in removed_previews or
             Path(job.request['output']).expanduser().resolve() in old_previews and not Path(job.request['output']).exists())])
        self.queue.settled.connect(self._job_settled)
        self.queue.message.connect(self.show_status)
        self.queue.changed.connect(self._queue_changed)
        self.queue.changed.connect(self._scan_state)
        self.queue.changed.connect(self._load_state)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(14, 12, 14, 10)
        layout.setSpacing(10)
        header = QFrame()
        header.setObjectName('header')
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(16, 10, 16, 10)
        header_layout.setSpacing(8)
        title_row = QHBoxLayout()
        brand = QLabel('ARK / ARCHIVE')
        brand.setObjectName('brandTag')
        title_row.addWidget(brand)
        title = QLabel('资源与资料工作台')
        title.setObjectName('appTitle')
        title_row.addWidget(title)
        title_row.addStretch()
        subtitle = QLabel('本地资源 · 离线资料')
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
        self.scan_priority = QComboBox()
        self.scan_priority.setObjectName('scanPriority')
        self.scan_priority.setAccessibleName('检查方式')
        self.scan_priority.addItem('干员 / 模组优先', 'data_first')
        self.scan_priority.addItem('仅检查干员 / 模组', 'data_only')
        self.scan_priority.addItem('仅扫描资源文件', 'files_only')
        self.scan_priority.setCurrentIndex(max(0, self.scan_priority.findData(services.config.get('scan_priority', 'data_first'))))
        self.scan_priority.setToolTip('资料优先：先显示干员、模组检查结果，再扫描全部资源。仅检查资料可跳过全库扫描。')
        self.scan_priority.currentIndexChanged.connect(self._save_scan_priority)
        root_row.addWidget(self.scan_priority)
        self.scan_button = QPushButton('扫描 / 检查更新')
        self.scan_button.setToolTip('按所选方式检查；干员和模组以完整资料基线判断新增，资源文件与保存的扫描比较。')
        self.scan_button.setProperty('primary', True)
        self.scan_button.setObjectName('scanButton')
        self.scan_button.clicked.connect(self.scan)
        root_row.addWidget(self.scan_button)
        header_layout.addLayout(root_row)
        status_row = QHBoxLayout()
        self.session_label = QLabel('选择游戏目录并扫描，开始浏览资源；已有记录会在启动时恢复。')
        self.session_label.setObjectName('sessionStatus')
        self.session_label.setWordWrap(True)
        status_row.addWidget(self.session_label, 1)
        self.scan_options_button = QPushButton('扫描选项')
        self.scan_options_button.setObjectName('scanOptionsButton')
        self.scan_options_button.setCheckable(True)
        self.scan_options_button.setToolTip('调整最近更新时间范围，或启用完整摘要校验。')
        status_row.addWidget(self.scan_options_button)
        self.history_button = QPushButton('历史对照')
        self.history_button.setObjectName('historyToggle')
        self.history_button.setCheckable(True)
        self.history_button.setToolTip('比较、导入或导出干员与模组资料快照。')
        status_row.addWidget(self.history_button)
        header_layout.addLayout(status_row)
        self.scan_options = QWidget()
        scan_options_layout = QHBoxLayout(self.scan_options)
        scan_options_layout.setContentsMargins(0, 0, 0, 0)
        scan_options_layout.addWidget(QLabel('最近更新时间'))
        self.hours = QDoubleSpinBox()
        self.hours.setObjectName('recentHours')
        self.hours.setRange(0.01, 876000)
        self.hours.setDecimals(2)
        self.hours.setValue(float(services.config.get('hours', 24)))
        self.hours.setSuffix(' 小时')
        self.hours.setFixedWidth(130)
        self.hours.valueChanged.connect(self._hours_changed)
        scan_options_layout.addWidget(self.hours)
        self.strict = QCheckBox('严格校验')
        self.strict.setToolTip('重新计算所选资源范围的完整摘要；耗时更长，可取消。')
        scan_options_layout.addWidget(self.strict)
        scan_hint = QLabel('按本机写入时间筛选；严格校验会增加扫描耗时。')
        scan_hint.setProperty('muted', True)
        scan_options_layout.addWidget(scan_hint, 1)
        self.scan_options.hide()
        self.scan_options_button.toggled.connect(self.scan_options.setVisible)
        header_layout.addWidget(self.scan_options)
        layout.addWidget(header)
        self.baseline_panel = QFrame()
        self.baseline_panel.setProperty('role', 'surface')
        baseline_row = QHBoxLayout(self.baseline_panel)
        baseline_row.setContentsMargins(12, 8, 12, 8)
        baseline_row.addWidget(QLabel('资料对照'))
        self.history = QComboBox()
        self.history.setMinimumWidth(180)
        self.history.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.history.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.history.addItem('解析核心数据后可选择历史快照', None)
        baseline_row.addWidget(self.history, 1)
        self.compare_button = QPushButton('比较所选快照')
        self.compare_button.clicked.connect(self.compare_history)
        baseline_row.addWidget(self.compare_button)
        import_button = QPushButton('导入历史基线…')
        import_button.clicked.connect(self.import_baseline)
        baseline_row.addWidget(import_button)
        self.export_snapshot_button = QPushButton('导出当前快照…')
        self.export_snapshot_button.clicked.connect(self.export_snapshot)
        baseline_row.addWidget(self.export_snapshot_button)
        self.baseline_panel.hide()
        self.history_button.toggled.connect(self.baseline_panel.setVisible)
        self.history.currentIndexChanged.connect(self._refresh_history_actions)
        layout.addWidget(self.baseline_panel)
        self.page_heading = QWidget()
        page_heading = QHBoxLayout(self.page_heading)
        page_heading.setContentsMargins(4, 2, 4, 2)
        self.page_title = QLabel()
        self.page_title.setProperty('role', 'pageTitle')
        self.page_description = QLabel()
        self.page_description.setProperty('muted', True)
        self.page_description.setWordWrap(True)
        page_heading.addWidget(self.page_title)
        page_heading.addSpacing(12)
        page_heading.addWidget(self.page_description, 1)
        layout.addWidget(self.page_heading)
        self.tabs = QTabWidget()
        self.tabs.setObjectName('mainTabs')
        self.pages = PageComposition(self, page_definitions)
        self.tabs.currentChanged.connect(self._update_page_heading)
        self._update_page_heading()
        layout.addWidget(self.tabs, 1)
        footer = QHBoxLayout()
        self.output_label = _PathLabel()
        self.output_label.setObjectName('subtitle')
        self.output_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.output_label.setText('输出：' + self.settings.output.text())
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
        self.pages.connect()
        self.monitor_timer = QTimer(self)
        self.monitor_timer.setInterval(15000)
        self.monitor_timer.timeout.connect(self.check_manifests)
        self.monitor_timer.start()
        self._queue_changed()
        self._refresh_history_actions()
        self._report_preview_warnings()
        if self.root_edit.text().strip():
            QTimer.singleShot(0, self.restore_previous)

    def _update_page_heading(self, *_):
        descriptions = {
            'explorer': ('资源浏览', '浏览目录，选择资源包，查看对象或加入解包队列。'),
            'updates': ('更新记录', '按时间和历史扫描定位变化，批量导出资源图片。'),
            'operators': ('干员资料', '检索干员，查看培养面板与技能，生成完整资料。'),
            'modules': ('模组更新', '对照模组各级效果，勾选资料并合并导出。'),
            'jobs': ('导出任务', '查看处理进度与结果，重试失败任务或打开产物。'),
            'settings': ('工作台设置', '调整输出位置、资料排版与历史记录选项。'),
        }
        current = self.pages.current_id()
        title, description = descriptions.get(current, (self.tabs.tabText(self.tabs.currentIndex()), ''))
        self.page_title.setText(title)
        self.page_description.setText(description)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'page_heading'):
            # The tabs still name every page; short windows need the space for rows.
            self.page_heading.setVisible(event.size().height() >= 800)

    def _refresh_history_actions(self, *_):
        available = self.services.gamedata is not None and not self.queue.busy
        self.compare_button.setEnabled(available and bool(self.history.currentData()))
        self.export_snapshot_button.setEnabled(available)

    def restore_previous(self):
        if self._closing or self._restore_pending or self.queue.busy:
            return
        root = self.root_edit.text().strip()
        if not root:
            return
        self._restore_pending = True
        job = self.queue.submit('读取上次扫描与解析结果',
                                lambda **kw: self.services.restore(root, **kw), self.restored,
                                show_in_tasks=False)
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
        states = self.services.config.setdefault('view_states', {})
        root = str(Path(root).resolve())
        state = self.pages.save_state(states.get(root, {}))
        state['root'] = root
        states[root] = state

    def restore_view_state(self):
        root = value(self.services.installation, 'root') or self.root_edit.text().strip()
        if not root:
            return
        state = self.services.config.get('view_states', {}).get(str(Path(root).resolve()), {})
        if not state:
            return
        self.pages.restore_state(state)

    def show_status(self, message):
        self.statusBar().showMessage(str(message)[-450:])

    def _queue_changed(self):
        self.cancel_button.setEnabled(self.queue.busy)
        self.root_edit.setEnabled(not self.queue.busy)
        self.choose_root_button.setEnabled(not self.queue.busy)
        self.scan_priority.setEnabled(not self.queue.busy)
        self.pages.queue_changed()
        self._refresh_history_actions()
        if self._closing and not self.queue.busy:
            QTimer.singleShot(0, self.close)

    def choose_root(self):
        root = QFileDialog.getExistingDirectory(self, '选择游戏目录', self.root_edit.text())
        if root:
            self.root_edit.setText(root)
            self.scan()

    def scan(self):
        if self._scan_pending or self._load_pending:
            self.show_status('扫描或资料检查已在队列中。')
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
        self.pages.set_root(root)
        self._scan_job = None
        self._scan_pending = True
        self.scan_button.setEnabled(False)
        mode = self.scan_priority.currentData()
        if mode == 'files_only':
            self._submit_file_scan(root, hours, strict)
        else:
            self.load_data()
            self._scan_job = self._load_job
            if mode == 'data_first':
                priority_job = self._load_job
                def continue_inventory(job):
                    if job is not priority_job:
                        return
                    self.queue.settled.disconnect(continue_inventory)
                    # A resource-only folder may have no core tables. Keep its
                    # file scan usable, while retaining the failed data job.
                    if not job.token.cancelled and not self._closing:
                        self._scan_pending = True
                        self.scan_button.setEnabled(False)
                        self._submit_file_scan(root, hours, strict)
                self.queue.settled.connect(continue_inventory)

    def _save_scan_priority(self, *_):
        self.services.config['scan_priority'] = self.scan_priority.currentData()
        self.services.save_config()

    def _submit_file_scan(self, root, hours, strict):
        # submit emits changed before returning; an old completed job must not
        # release the pending flag for the new request during that signal.
        self._scan_job = None
        self._scan_job = self.queue.submit('扫描游戏目录' + ('（严格校验）' if strict else ''),
                               lambda **kw: self.services.scan(root, hours=hours, strict=strict, **kw),
                               self.scanned, request={'operation': 'scan', 'root': root, 'hours': hours, 'strict': strict})

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
        self.pages.scanned(snapshot, changes, catalog)
        self._monitor_stamp = self.manifest_stamp()
        self.refresh_history()
        self.refresh_entities()
        self.refresh_session_label()
        self.restore_view_state()
        self._view_state_ready = True
        self.show_status(f'扫描{"完成" if value(snapshot, "complete") else "存在未完成项"}：{len(value(snapshot, "files", [])):,} 个文件。')

    def _hours_changed(self):
        self.pages.hours_changed()

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
        self._load_job = None
        self._load_pending = True
        self._load_job = self.queue.submit('解析核心数据', lambda **kw: self.services.load_data(root, **kw), self.data_loaded,
                                          request={'operation': 'load_data', 'root': root, 'locale': self.services.config.get('data_locale', 'unknown')})

    def _load_state(self):
        job = getattr(self, '_load_job', None)
        if job and job.status not in ('排队中', '运行中', '正在取消'):
            self._load_pending = False

    def data_loaded(self, snapshot):
        installation_root = value(self.services.installation, 'root')
        if installation_root:
            self.root_edit.setText(str(installation_root))
        self.pages.data_loaded()
        self.refresh_entities()
        self.refresh_history()
        self.refresh_session_label()
        self.restore_view_state()
        self._view_state_ready = True
        self.show_status('核心资料已解析。首次快照的历史状态未知；可导入完整历史基线比较。')

    def refresh_entities(self):
        self.pages.refresh_entities()

    def profile(self, kind, entity_id, spec):
        self.pages.profile(kind, entity_id, spec)

    def output_root(self):
        text = self.settings.output.text().strip()
        if not text:
            self.show_status('请在设置中选择独立输出目录。')
            return None
        output = Path(text).resolve()
        if any(output.is_relative_to(root) for root in self.preview_cache.roots):
            self.show_status('临时预览目录会自动回收，请选择独立的正式输出目录。')
            return None
        root = self.root_edit.text().strip()
        if root and output.is_relative_to(Path(root).resolve()):
            self.show_status('输出目录不能位于游戏目录中。请在设置中选择独立目录。')
            return None
        return str(output)

    @staticmethod
    def _object_preview_kinds(dialog, object_ids):
        identifiers = {str(identifier) for ids in (object_ids or {}).values() for identifier in ids}
        rows = [row for row in dialog.model.rows if str(value(row, 'id')) in identifiers]
        if len(rows) == 1:
            row = rows[0]
            kind = {'Texture2D': 'image', 'Sprite': 'image', 'Image': 'image',
                    'AudioClip': 'audio', 'VideoClip': 'video', 'TextAsset': 'text'}.get(value(row, 'type'))
            if kind:
                if kind == 'text' and any(part in str(value(row, 'name', '')).lower()
                                          for part in ('.atlas', '.skel', '.spine')):
                    return ['text', 'spine']
                return [kind]
        return ['image', 'text', 'audio', 'spine', 'video']

    def extract(self, paths, object_ids=None, preview_dialog=None, *, kinds=None, mode=None, character_options=None):
        if preview_dialog and (self._closing or getattr(preview_dialog, '_workbench_closed', False)):
            return
        generation = getattr(preview_dialog, 'preview_generation', None)
        character_options = dict(character_options) if character_options is not None else None
        if preview_dialog and preview_dialog in self._object_preview_jobs:
            self._object_preview_pending[preview_dialog] = (generation, lambda: self.extract(
                list(paths), object_ids, preview_dialog, kinds=kinds, mode=mode, character_options=character_options))
            return
        output = self.output_root() if preview_dialog is None else None
        lease = None
        if preview_dialog:
            try:
                lease = self.preview_cache.allocate('objects')
            except (OSError, ValueError) as error:
                self.show_status('无法创建对象预览：' + str(error))
                preview_dialog.preview_failed(str(error), generation=generation)
                return
            preview_dialog.track_preview(lease)
            output = str(lease.path)
        if output is None:
            return
        if preview_dialog:
            kinds = list(kinds) if kinds is not None else self._object_preview_kinds(preview_dialog, object_ids)
            mode = 'auto'
        else:
            kinds = list(kinds) if kinds is not None else [key for key, check in self.settings.kinds.items() if check.isChecked()]
            mode = mode if mode is not None else self.settings.mode.currentData()
        if not kinds:
            if lease:
                lease.release()
                lease.finish()
            self.show_status('请在设置中至少选择一种资源类型。')
            return
        character_arguments = {'character_options': character_options} if character_options is not None else {}
        self.show_status(f'加入解包队列：{len(paths)} 个文件 · {mode} · {output}')
        def done(result):
            errors = value(result, 'errors', [])
            if errors and self.queue.active and not preview_dialog:
                failed_paths = list(dict.fromkeys(str(e.get('source')) for e in errors if e.get('source')))
                failed_ids = {}
                for path in failed_paths:
                    failures = [e for e in errors if str(e.get('source')) == path]
                    if all(e.get('object_id') is not None for e in failures):
                        failed_ids[path] = [str(e['object_id']) for e in failures]
                if failed_paths:
                    self.queue.active.retry_call = lambda **kw: self.services.extract(failed_paths, output, kinds=kinds,
                                                                                     object_ids=failed_ids, mode=mode, **character_arguments, **kw)
            if preview_dialog:
                if self._closing or getattr(preview_dialog, '_workbench_closed', False):
                    lease.release()
                    return
                outputs = value(result, 'outputs', [])
                if preview_dialog.show_files(outputs, preview_lease=lease, generation=generation):
                    if self.queue.active:
                        self._displayed_preview_jobs.add(self.queue.active.job_id)
                else:
                    lease.release()
                    details = [str(value(item, 'error', value(item, 'reason', ''))) for item in
                               [*value(result, 'errors', []), *value(result, 'skipped', [])]]
                    preview_dialog.preview_failed('未生成可预览文件。' + ('\n'.join(details) or '请在任务页查看失败或跳过原因。'),
                                                  generation=generation)
        title = ('预览表情合成' if preview_dialog else '导出表情差分') if kinds == ['expression'] else (
            '预览对象' if preview_dialog else '导出包内原图' if kinds == ['image'] and mode == 'auto' else '解包所选')
        job = self.queue.submit(title + f' · {len(paths)} 个文件',
                          lambda **kw: self.services.extract(paths, output, kinds=kinds, object_ids=object_ids, mode=mode,
                                                            remember_output=not bool(preview_dialog), **character_arguments, **kw), done, output,
                          request={'operation': 'extract', 'root': str(value(self.services.installation, 'root') or self.root_edit.text().strip()), 'paths': list(paths),
                                   'output': output, 'kinds': kinds, 'object_ids': object_ids or {}, 'mode': mode, 'preview': bool(preview_dialog),
                                   'character_options': character_options})
        if lease:
            self._object_preview_jobs[preview_dialog] = (job.job_id, generation)
            self._bind_preview_job(job, lease, preview_dialog)

    def objects(self, path, *, auto_preview=True):
        dialog = ObjectsDialog(path, self, auto_preview=auto_preview)
        self._track_dialog(dialog)
        dialog.extract_requested.connect(lambda source, ids, preview: self.extract([source], {source: ids}, dialog if preview else None))
        dialog.show()
        job = self.queue.submit('读取内部对象 · ' + Path(path).name,
                          lambda **kw: self.services.objects(path, **kw),
                          lambda objects: dialog.set_objects(objects) if not getattr(dialog, '_workbench_closed', False) else None,
                          show_in_tasks=False)
        self._dialog_jobs[job.job_id] = dialog

    def character_workbench(self, paths):
        if not paths or self._closing:
            return
        if len(paths) > 1:
            self.extract(paths, kinds=['expression'], mode='auto')
            return
        from .character_workbench import CharacterWorkbench
        path = str(paths[0])
        dialog = CharacterWorkbench(path, self)
        dialog._cancel_owned_jobs_on_close = True
        self._track_dialog(dialog)
        dialog.preview_requested.connect(lambda options: self.extract(
            [path], preview_dialog=dialog, kinds=['expression'], mode='auto', character_options=options))
        dialog.export_requested.connect(lambda options: self.extract(
            [path], kinds=['expression'], mode='auto', character_options=options))
        dialog.batch_requested.connect(lambda: self.extract([path], kinds=['expression'], mode='auto'))
        dialog.show()
        job = self.queue.submit('读取角色表情配置 · ' + Path(path).name,
                                lambda **kw: self.services.character_catalog(path, **kw),
                                lambda catalog: dialog.set_catalog(catalog) if not dialog._workbench_closed else None,
                                show_in_tasks=False)
        self._dialog_jobs[job.job_id] = dialog
        def loaded(finished):
            if finished is not job:
                return
            self.queue.settled.disconnect(loaded)
            if finished.status != '成功' and not dialog._workbench_closed:
                dialog.load_failed(finished.last_error or finished.status)
        self.queue.settled.connect(loaded)

    def export(self, kind, ids, only_new=False, *, preview=False, report_spec=None, report_options=None,
               preview_dialog=None, preview_generation=0, report_binding=None, report_formats=None):
        if self._closing:
            return
        if preview_dialog is not None and (getattr(preview_dialog, '_workbench_closed', False)
                or preview_dialog.preview_generation != preview_generation):
            return
        if report_binding is not None:
            try:
                self.check_report_binding(report_binding)
            except ValueError as error:
                if preview_dialog is not None:
                    preview_dialog.font_preview_failed(str(error), generation=preview_generation)
                self.show_status(str(error))
                return
        ids = list(ids)
        output = None if preview else self.output_root()
        formats = set(report_formats) if report_formats is not None else self.settings.selected_formats()
        if preview:
            formats = formats | {ExportFormat.PNG}
        if not preview and output is None:
            return
        if not formats:
            self.show_status('请在设置中至少选择一种导出格式。')
            return
        if only_new and not value(self.services.entity_changes, 'baseline_id'):
            self.show_status('没有可比较的历史数据基线，不能认定本次新增。')
            return
        operators, modules = (ids, []) if kind == 'operators' else ([], ids)
        # A single chosen module may enter the static panel; never combine modules.
        spec = replace(report_spec or self.pages.report_spec(kind, ids))
        options = replace(report_options or self.settings.report_options())
        binding = report_binding or {'root': self.root_edit.text().strip(),
                                     'snapshot_id': value(self.services.gamedata, 'snapshot_id')}
        if kind == 'modules' and only_new and not options.title:
            options = replace(options, title='本次新增模组')
        try:
            lease = self.preview_cache.allocate('reports') if preview else None
        except (OSError, ValueError) as error:
            self.show_status('无法创建资料预览：' + str(error))
            return
        if lease:
            output = str(lease.path)
        def done(artifacts):
            if self._closing or preview_dialog is not None and getattr(preview_dialog, '_workbench_closed', False):
                if lease:
                    lease.release()
                return
            if preview_dialog is not None:
                dialog = preview_dialog
                if not dialog.replace_artifacts(artifacts, preview_lease=lease, report_options=options,
                                                generation=preview_generation):
                    return
            else:
                dialog = self.show_report_artifacts(artifacts, preview_only=preview, preview_lease=lease,
                                                    report_options=options)
                if preview:
                    dialog.export_requested.connect(lambda: self.export(kind, ids, report_spec=spec,
                        report_options=dialog.successful_options, report_binding=binding))
                    dialog.font_preview_requested.connect(lambda chosen, generation: self._refresh_report_preview(
                        dialog, kind, ids, spec, formats, binding, chosen, generation))
            self.show_status(f'资料{"预览" if preview else "导出"}完成：{len(artifacts)} 个产物。')
            if lease and self.queue.active:
                self._dialog_jobs[self.queue.active.job_id] = dialog
                self._displayed_preview_jobs.add(self.queue.active.job_id)
        def call(**kw):
            if report_binding is not None:
                self.check_report_binding(binding)
            return self.services.export(operators, modules, output, formats, spec=spec, options=options,
                                        remember_output=not preview, **kw)
        job = self.queue.submit(f'{"预览" if preview else "导出"}{"新增" if only_new else "选中"}资料 · {len(ids)} 项',
                          call, done, output, request={'operation': 'report', **binding, 'operators': operators, 'modules': modules,
                          'output': output, 'formats': [fmt.value for fmt in formats], 'spec': as_jsonable(spec),
                          'options': as_jsonable(options), 'preview': preview})
        if lease:
            self._bind_preview_job(job, lease, preview_dialog)
        if preview_dialog is not None:
            self._report_preview_jobs[preview_dialog] = (job.job_id, preview_generation)

    def _refresh_report_preview(self, dialog, kind, ids, spec, formats, binding, options, generation):
        if self._closing or getattr(dialog, '_workbench_closed', False) or dialog.preview_generation != generation:
            return
        def submit():
            self.export(kind, ids, preview=True, report_spec=spec, report_options=options,
                        preview_dialog=dialog, preview_generation=generation, report_binding=binding,
                        report_formats=formats)
        if dialog in self._report_preview_jobs:
            self._report_preview_pending[dialog] = (generation, submit)
        else:
            submit()

    def preview_reports(self, kind, ids):
        self.export(kind, ids, preview=True)

    def prepare_recovery(self, job):
        """Resolve declarative history only after the user explicitly presses retry."""
        request = job.request or {}
        if request.get('preview'):
            raise ValueError('预览是临时任务，请从原页面重新预览；正式导出文件不受影响。')
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
                                             mode=request.get('mode', 'auto'),
                                             **({'character_options': request['character_options']} if request.get('character_options') is not None else {}), **kw)
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

    def _track_dialog(self, dialog):
        dialog._workbench_closed = False
        self._dialogs.append(dialog)
        def closed(*_):
            dialog._workbench_closed = True
            self._object_preview_pending.pop(dialog, None)
            self._object_preview_jobs.pop(dialog, None)
            self._report_preview_pending.pop(dialog, None)
            self._report_preview_jobs.pop(dialog, None)
            if dialog in self._dialogs:
                self._dialogs.remove(dialog)
            ids = {job_id for job_id, owner in self._dialog_jobs.items() if owner is dialog}
            pending = {job.job_id for job in self.queue.jobs if job.job_id in ids and
                       job.status in ('排队中', '运行中', '正在取消')}
            self._discard_when_settled.update(pending)
            # Closing a report or character viewer cancels only its own producers. A
            # queued producer has no worker to finish its lease later.
            for job in list(self.queue.jobs):
                report_preview = ((job.request or {}).get('operation') == 'report'
                                  and (job.request or {}).get('preview'))
                if job.job_id not in pending or not (report_preview or getattr(dialog, '_cancel_owned_jobs_on_close', False)):
                    continue
                job.token.cancel()
                queued = job.status == '排队中'
                job.status = '已取消' if queued else '正在取消'
                self.queue._persist(job)
                if queued:
                    self.queue.settled.emit(job)
            self.queue.changed.emit()
            self.queue.forget_finished([job.job_id for job in self.queue.jobs if job.job_id in ids and job.status == '成功'])
            for job_id in ids - pending:
                self._dialog_jobs.pop(job_id, None)
                self._discard_when_settled.discard(job_id)
            self._report_preview_warnings()
            dialog.deleteLater()
        dialog.finished.connect(closed)

    def _bind_preview_job(self, job, lease, dialog=None):
        self._preview_jobs[job.job_id] = lease
        if dialog is not None:
            self._dialog_jobs[job.job_id] = dialog
        def cleaned():
            if job.status == '成功':
                self.queue.forget_finished([job.job_id])
            self._dialog_jobs.pop(job.job_id, None)
            self._discard_when_settled.discard(job.job_id)
        lease.on_cleaned(cleaned)

    def _job_settled(self, job):
        owner = self._dialog_jobs.get(job.job_id)
        report_current = self._report_preview_jobs.get(owner)
        report_pending = None
        if report_current and report_current[0] == job.job_id:
            self._report_preview_jobs.pop(owner, None)
            report_pending = self._report_preview_pending.pop(owner, None)
            if (not self._closing and not getattr(owner, '_workbench_closed', False)
                    and job.status != '成功'):
                owner.font_preview_failed(job.last_error or job.status, generation=report_current[1])
        current = self._object_preview_jobs.get(owner)
        pending = None
        if current and current[0] == job.job_id:
            self._object_preview_jobs.pop(owner, None)
            pending = self._object_preview_pending.pop(owner, None)
            if not self._closing and not getattr(owner, '_workbench_closed', False) and job.last_error:
                owner.preview_failed(job.last_error, generation=current[1])
        lease = self._preview_jobs.pop(job.job_id, None)
        if lease:
            if job.job_id not in self._displayed_preview_jobs or self._closing:
                lease.release()
            lease.finish()
        self._displayed_preview_jobs.discard(job.job_id)
        if job.job_id in self._discard_when_settled:
            if job.status == '成功':
                self.queue.forget_finished([job.job_id])
            self._dialog_jobs.pop(job.job_id, None)
            self._discard_when_settled.discard(job.job_id)
        self._report_preview_warnings()
        if report_pending is not None:
            generation, submit = report_pending
            def latest_report():
                if (not self._closing and not getattr(owner, '_workbench_closed', False)
                        and owner.preview_generation == generation):
                    submit()
            QTimer.singleShot(0, latest_report)
        if pending is not None:
            generation, submit = pending
            def latest():
                if (not self._closing and not getattr(owner, '_workbench_closed', False)
                        and getattr(owner, 'preview_generation', None) == generation):
                    submit()
            QTimer.singleShot(0, latest)

    def _report_preview_warnings(self):
        for warning in self.preview_cache.warnings[self._preview_warning_count:]:
            self.queue.message.emit(warning)
        self._preview_warning_count = len(self.preview_cache.warnings)

    def show_report_artifacts(self, artifacts, *, preview_only=False, export_action=None, preview_lease=None,
                              report_options=None):
        if self._closing:
            if preview_lease:
                preview_lease.release()
            return None
        artifacts = list(artifacts)
        requested = {str(value(artifact, 'path', '')) for artifact in artifacts}
        for job in self.queue.jobs:
            owner = self._dialog_jobs.get(job.job_id)
            if owner is not None and not getattr(owner, '_workbench_closed', False) and requested.intersection(
                    str(value(artifact, 'path', '')) for artifact in job.artifacts):
                owner.show()
                owner.raise_()
                owner.activateWindow()
                return owner
        dialog = ReportArtifactsDialog(artifacts, self, preview_only=preview_only, preview_lease=preview_lease,
                                       report_options=report_options)
        dialog.html_open_requested.connect(lambda path: QDesktopServices.openUrl(QUrl.fromLocalFile(path)))
        if export_action:
            dialog.export_requested.connect(export_action)
        self._track_dialog(dialog)
        dialog.show()
        return dialog

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
        self.settings.save_status.setText('设置已保存。后续导出将使用当前设置。')
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
        for dialog in list(self._dialogs):
            dialog.close()
        self.monitor_timer.stop()
        self.queue.shutdown()
        if self.queue.busy:
            self.show_status('正在取消任务并等待工作进程退出，完成后将自动关闭。')
            event.ignore()
            return
        self.preview_cache.shutdown()
        self._report_preview_warnings()
        self.remember_view_state()
        self.services.config.update(game_root=self.root_edit.text().strip(), hours=self.hours.value())
        # commit emits changed -> save_settings once, including the view state.
        self.settings.commit()
        event.accept()
