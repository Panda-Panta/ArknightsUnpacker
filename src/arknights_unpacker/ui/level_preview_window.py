"""Standalone shell for the shared level catalog and replay dialogs."""

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
                               QProgressBar, QPushButton, QTabWidget, QVBoxLayout, QWidget)

from .jobs import JobQueue
from .models import value
from .pages import LevelCatalogPage
from .preview_cache import PreviewCache
from .styles import apply_theme


class LevelPreviewWindow(QMainWindow):
    def __init__(self, services, *, initial_root=''):
        super().__init__()
        apply_theme()
        self.services = services
        self._closing = False
        self._catalog_job = None
        self._progress_job = None
        self._dialogs = []

        output = services.config.get('output_root')
        self.preview_cache = PreviewCache(services.data_root, protected_roots=[output] if output else [])
        self.preview_cache.cleanup_stale(Path(services.data_root) / 'queue')
        self.queue = JobQueue(self)
        self.native_replay_queue = JobQueue(self)

        self.setWindowTitle('明日方舟 · 地图预览')
        self.resize(1200, 790)
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(14, 12, 14, 10)
        root_row = QHBoxLayout()
        root_label = QLabel('游戏目录')
        self.root_edit = QLineEdit(str(initial_root or services.config.get('game_root') or ''))
        self.root_edit.setObjectName('gameRoot')
        self.root_edit.setPlaceholderText('选择游戏根目录、Arknights_Data 或单层资源目录')
        self.root_edit.returnPressed.connect(self.scan)
        root_label.setBuddy(self.root_edit)
        self.choose_root_button = QPushButton('选择目录…')
        self.choose_root_button.clicked.connect(self.choose_root)
        self.scan_button = QPushButton('扫描 / 检查更新')
        self.scan_button.setObjectName('scanButton')
        self.scan_button.setProperty('primary', True)
        self.scan_button.clicked.connect(self.scan)
        root_row.addWidget(root_label)
        root_row.addWidget(self.root_edit, 1)
        root_row.addWidget(self.choose_root_button)
        root_row.addWidget(self.scan_button)
        layout.addLayout(root_row)

        # The shared page uses the current tab to start metadata and preloads.
        self.tabs = QTabWidget()
        self.tabs.tabBar().hide()
        self.page = LevelCatalogPage(self)
        self.tabs.addTab(self.page.view, '关卡预览')
        layout.addWidget(self.tabs, 1)
        self.page.connect()

        self.progress = QProgressBar()
        self.progress.setObjectName('levelPreviewProgress')
        self.progress.setAccessibleName('任务进度')
        self.cancel_button = QPushButton('取消任务')
        self.cancel_button.clicked.connect(self._cancel_current)
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().addPermanentWidget(self.cancel_button)
        for queue in (self.queue, self.native_replay_queue):
            queue.changed.connect(self._queue_changed)
            queue.message.connect(lambda message, source=queue: self._queue_message(source, message))
            queue.progress.connect(lambda event, source=queue: self._queue_progress(source, event))
        self.queue.settled.connect(self._catalog_settled)
        self._queue_changed()
        self.show_status('选择游戏目录后扫描关卡。')
        QTimer.singleShot(0, self.restore_previous)

    def show_status(self, message):
        lines = str(message).strip().splitlines()
        if lines:
            self.statusBar().setToolTip(str(message))
            self.statusBar().showMessage(lines[-1])

    def choose_root(self):
        root = QFileDialog.getExistingDirectory(self, '选择游戏目录', self.root_edit.text())
        if root:
            self.root_edit.setText(root)
            self.scan()

    def restore_previous(self):
        root = self.root_edit.text().strip()
        if root and not self._closing and not self.queue.busy:
            self._load_catalog('恢复已保存的关卡扫描', root, self.services.restore_level_catalog)

    def scan(self):
        if self._closing or self.queue.busy:
            return
        root = self.root_edit.text().strip()
        if not root or not Path(root).is_dir():
            self.show_status(f'游戏目录不存在或无法访问：{root}' if root else '请先选择游戏目录。')
            return
        self._load_catalog('扫描关卡资源', root, self.services.scan_level_catalog)

    def _load_catalog(self, title, root, load):
        self.page.set_root(root)
        self.page.view.setEnabled(False)
        self._catalog_job = self.queue.submit(title, lambda **kw: load(root, **kw), self._catalog_loaded)

    def _catalog_loaded(self, result):
        if self._closing:
            return
        normalized_root = value(self.services.installation, 'root')
        if normalized_root:
            self.root_edit.setText(str(normalized_root))
        self.page.scanned(result.get('snapshot'), result.get('changes'), result.get('catalog'))

    def _catalog_settled(self, job):
        if job is self._catalog_job:
            self._catalog_job = None
            self.page.view.setEnabled(not self._closing)

    def _active_queue(self):
        if self.queue.busy:
            return self.queue
        if self.native_replay_queue.busy:
            return self.native_replay_queue
        return None

    def _queue_changed(self):
        controls_enabled = not (self._closing or self.queue.busy)
        self.root_edit.setEnabled(controls_enabled)
        self.choose_root_button.setEnabled(controls_enabled)
        self.scan_button.setEnabled(controls_enabled)
        active_queue = self._active_queue()
        active = active_queue.active if active_queue is not None else None
        self.progress.setVisible(active is not None)
        if active is not self._progress_job:
            self._progress_job = active
            self.progress.setRange(0, 0)
        self.cancel_button.setEnabled(not self._closing and active is not None and active.status == '运行中')
        if self._closing and active_queue is None:
            QTimer.singleShot(0, self.close)

    def _queue_message(self, source, message):
        if not self._closing and source is self._active_queue() and not message.startswith('{'):
            self.show_status(message)

    def _queue_progress(self, source, event):
        if self._closing or source is not self._active_queue() or not isinstance(event, dict):
            return
        if event.get('phase') == 'scan' and isinstance(event.get('files'), int):
            self.show_status(f"正在扫描游戏资源 · 已读取 {event['files']:,} 个文件")
        total = event.get('total', event.get('total_files', 0))
        done = event.get('current', event.get('completed', event.get('done', 0)))
        if isinstance(total, (int, float)) and total > 0 and isinstance(done, (int, float)):
            self.progress.setRange(0, 100)
            self.progress.setValue(round(100 * max(0, min(1, done / total))))

    def _cancel_current(self):
        if (queue := self._active_queue()) is not None:
            queue.cancel()

    def _track_dialog(self, dialog):
        self._dialogs.append(dialog)
        def closed(*_):
            if dialog in self._dialogs:
                self._dialogs.remove(dialog)
        dialog.finished.connect(closed)

    def closeEvent(self, event):
        if not self._closing:
            self._closing = True
            # Close the native child before its owning preview. Include the
            # indicator dialog, which the shared page opens directly.
            for dialog in reversed(self.findChildren(QDialog)):
                dialog.close()
            self.native_replay_queue.shutdown()
            self.queue.shutdown()
        if self._active_queue() is not None:
            self.show_status('正在取消任务，工作进程退出后将自动关闭。')
            event.ignore()
            return
        self.preview_cache.shutdown()
        super().closeEvent(event)
