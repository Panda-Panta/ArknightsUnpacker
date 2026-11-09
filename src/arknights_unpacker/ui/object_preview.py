"""Browse package objects and coordinate the selection's live preview."""
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QSplitter,
    QTableView, QVBoxLayout,
)

from .models import RecordsModel, selected_records, size_text, value
from .original_image import choose_original_save, input_roots


class ObjectsDialog(QDialog):
    extract_requested = Signal(str, list, bool)

    def __init__(self, path, parent=None, *, auto_preview=True):
        super().__init__(parent)
        from .resource_preview import ResourcePreviewWidget

        self.path = path
        self.preview_closed = False
        self.preview_generation = 0
        self._preview_leases = []
        self._current_preview_lease = None
        self._preview_cache_roots = ()
        self._input_roots = input_roots(parent, path)
        self.finished.connect(self._release_previews)
        self.setWindowTitle('内部对象 · ' + Path(path).name)
        self.resize(1180, 780)
        layout = QVBoxLayout(self)
        self.status = QLabel('正在读取内部对象…')
        self.status.setWordWrap(True)
        self.status.setToolTip(str(path))
        layout.addWidget(self.status)
        self.splitter = QSplitter()
        self.splitter.setChildrenCollapsible(False)
        self.model = RecordsModel([('对象 ID', 'id'), ('类型', 'type'), ('名称', 'name'),
                                   ('对象大小', lambda row: size_text(value(row, 'size')) if value(row, 'size') is not None else '未知', 'size'),
                                   ('逻辑路径', 'logical_path')], self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setMinimumWidth(300)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setToolTip('对象大小：Unity 对象的序列化数据字节数，不含独立流式载荷，也不是导出后文件大小；独立文件显示原文件大小。未知表示未提供大小。')
        for column, width in enumerate((90, 110, 120, 95)):
            self.table.setColumnWidth(column, width)
        self.splitter.addWidget(self.table)
        self.preview_panel = ResourcePreviewWidget()
        self.preview_panel.setMinimumWidth(320)
        self.splitter.addWidget(self.preview_panel)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([500, 640])
        layout.addWidget(self.splitter, 1)
        # Existing original-image actions and callers share the embedded panel.
        for name in ('preview', 'picture', 'image_scroll', 'image_tools', 'image_zoom', 'save_original_button'):
            setattr(self, name, getattr(self.preview_panel, name))
        self.preview.setPlainText('开启“自动预览”后，选择单个可预览对象即可显示。关闭时可浏览或解包；需要预览请重新开启。预览只写入应用缓存，不改动游戏文件。')
        self.preview_panel.save_original_requested.connect(self.save_original)
        row = QHBoxLayout()
        self.auto_preview = QCheckBox('自动预览')
        self.auto_preview.setObjectName('automaticObjectPreview')
        self.auto_preview.setChecked(bool(auto_preview))
        self.auto_preview.setToolTip('选择单个图片、音视频或文本对象后自动预览。关闭后仅浏览与解包；需要预览时重新开启。音视频需点击播放。')
        row.addWidget(self.auto_preview)
        self.extract_button = QPushButton('解包所选对象')
        self.extract_button.clicked.connect(lambda: self.request(False))
        self.extract_button.setEnabled(False)
        row.addWidget(self.extract_button)
        row.addStretch()
        close = QPushButton('关闭')
        close.clicked.connect(self.close)
        row.addWidget(close)
        layout.addLayout(row)
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.setInterval(250)
        self._auto_timer.timeout.connect(self._auto_request)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)
        self.auto_preview.toggled.connect(self._auto_toggled)

    @property
    def _image_path(self):
        return self.preview_panel.image_path

    @property
    def _image_pixmap(self):
        return self.preview_panel.image_pixmap or QPixmap()

    @staticmethod
    def _previewable(row):
        return value(row, 'previewable', True) is not False and str(value(row, 'type', '')).casefold() in {
            'texture2d', 'sprite', 'audioclip', 'textasset', 'videoclip', 'image'}

    def set_objects(self, objects):
        if self.preview_closed:
            return
        self.preview_generation += 1
        self._auto_timer.stop()
        self._clear_current_preview()
        objects = list(objects)
        self.model.replace(objects)
        self.status.setText(f'{len(objects):,} 个对象　·　{Path(self.path).name}')
        if self.auto_preview.isChecked():
            first = next((index for index, row in enumerate(self.model.rows) if self._previewable(row)), None)
            if first is not None:
                self.table.selectRow(first)

    def _selection_changed(self, *_):
        self.preview_generation += 1
        self._auto_timer.stop()
        self._clear_current_preview()
        selected = selected_records(self.table)
        self.extract_button.setEnabled(bool(selected))
        self.status.setText(f'已选 {len(selected):,} 个对象　·　{Path(self.path).name}')
        if self.auto_preview.isChecked() and len(selected) == 1 and self._previewable(selected[0]):
            self._auto_timer.start()

    def _auto_toggled(self, checked):
        self.preview_generation += 1
        self._auto_timer.stop()
        selected = selected_records(self.table)
        if checked and len(selected) == 1 and self._previewable(selected[0]) and not self.preview_closed:
            self._auto_timer.start()

    def _auto_request(self):
        selected = selected_records(self.table)
        if not self.preview_closed and self.auto_preview.isChecked() and len(selected) == 1 and self._previewable(selected[0]):
            self.request(True)

    def track_preview(self, lease):
        if self.preview_closed:
            lease.release()
            return
        if lease not in self._preview_leases:
            self._preview_leases.append(lease)
        self._preview_cache_roots = tuple(dict.fromkeys((*self._preview_cache_roots, *lease.cache.roots)))

    def _release_lease(self, lease):
        if lease is not None:
            lease.release()
            if lease in self._preview_leases:
                self._preview_leases.remove(lease)

    def _clear_current_preview(self, keep_lease=None):
        # Media must release file handles before its cache can be removed.
        self.preview_panel.clear()
        previous, self._current_preview_lease = self._current_preview_lease, None
        if previous is not keep_lease:
            self._release_lease(previous)

    def _release_previews(self, *_):
        if self.preview_closed:
            return
        self.preview_closed = True
        self.preview_generation += 1
        self._auto_timer.stop()
        self.preview_panel.shutdown()
        for lease in list(self._preview_leases):
            self._release_lease(lease)
        self._current_preview_lease = None

    def closeEvent(self, event):
        super().closeEvent(event)
        if event.isAccepted():
            self._release_previews()

    def request(self, preview):
        if self.preview_closed:
            return
        selected = selected_records(self.table)
        ids = [str(row['id']) for row in selected]
        if preview:
            self._auto_timer.stop()
            if len(ids) != 1:
                self.status.setText('请选择一个对象进行预览。')
                return
            if value(selected[0], 'previewable', True) is False:
                self.status.setText('此对象暂不支持预览，可选择解包查看诊断。')
                return
            self.preview_generation += 1
            self._clear_current_preview()
            self.status.setText('正在准备预览…')
        if ids:
            self.extract_requested.emit(self.path, ids, preview)

    def show_files(self, outputs, preview_lease=None, generation=None):
        if self.preview_closed or (generation is not None and generation != self.preview_generation):
            self._release_lease(preview_lease)
            return False
        self._clear_current_preview(keep_lease=preview_lease)
        if preview_lease is not None:
            self.track_preview(preview_lease)
        outputs = list(outputs)
        try:
            shown = self.preview_panel.show_files(outputs)
        except (OSError, ValueError) as error:
            self._release_lease(preview_lease)
            self.preview_failed(str(error), generation=generation)
            return False
        if shown:
            self._current_preview_lease = preview_lease
            self.status.setText(f'已显示预览　·　{len(outputs):,} 个产物　·　{Path(self.path).name}')
        else:
            self._release_lease(preview_lease)
            self.status.setText('未生成可预览文件。请在任务页查看失败或跳过原因。')
        return shown

    def show_file(self, path, preview_lease=None, generation=None):
        return self.show_files([path], preview_lease=preview_lease, generation=generation)

    def preview_failed(self, message, generation=None):
        if self.preview_closed or (generation is not None and generation != self.preview_generation):
            return False
        self._clear_current_preview()
        self.status.setText(str(message))
        self.preview.setPlainText(str(message))
        return True

    def update_image(self, *_):
        self.preview_panel.update_image()

    def fit_image(self):
        self.preview_panel.fit_image()

    def save_original(self):
        if self._image_path and not self._image_pixmap.isNull():
            saved = choose_original_save(self, self._image_path, self._input_roots, self._preview_cache_roots)
            if saved:
                self.status.setText(f'已保存原图　·　{self._image_pixmap.width()} × {self._image_pixmap.height()} 像素　·　{saved}')
