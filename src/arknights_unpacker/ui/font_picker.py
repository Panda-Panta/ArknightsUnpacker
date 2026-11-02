"""Shared export-font chooser; search text never becomes a font selection."""
from pathlib import Path

from PySide6.QtCore import QEvent, QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ..reports.font_catalog import system_font_faces


class ExportFontPicker(QWidget):
    font_changed = Signal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._font_path, self._font_index = '', 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        row = QHBoxLayout()
        self.system_combo = QComboBox()
        self.system_combo.setObjectName('systemReportFont')
        self.system_combo.setEditable(True)
        self.system_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.system_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.system_combo.setMinimumContentsLength(18)
        self.system_combo.addItem('默认字体（自动选择）', ('', 0))
        for face in system_font_faces():
            self.system_combo.addItem(f'{face.family} · {face.style}', (face.path, face.index))
            self.system_combo.setItemData(self.system_combo.count() - 1,
                                          f'{face.path}\n字体序号：{face.index}', Qt.ItemDataRole.ToolTipRole)
        self.system_combo.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        self.system_combo.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.system_combo.setToolTip('输入名称搜索系统字体，再从列表中选择字体及字形。')
        self.system_combo.activated.connect(self._activate_font)
        row.addWidget(self.system_combo, 1)
        self.choose_button = QPushButton('选择字体文件…')
        self.choose_button.setObjectName('chooseReportFont')
        self.choose_button.clicked.connect(self.choose_file)
        row.addWidget(self.choose_button)
        self.reset_button = QPushButton('恢复默认')
        self.reset_button.setObjectName('resetReportFont')
        self.reset_button.clicked.connect(lambda: self._change_font('', 0))
        row.addWidget(self.reset_button)
        layout.addLayout(row)
        self.path_edit = QLineEdit()
        self.path_edit.setObjectName('reportFontPath')
        self.path_edit.setPlaceholderText('默认字体（自动选择）；也可粘贴字体文件路径')
        self.path_edit.setToolTip('支持 TTF、OTF 和 TTC 字体；仅用于资料导出。')
        self.path_edit.textChanged.connect(self._path_changed)
        layout.addWidget(self.path_edit)
        for control in (self.system_combo, self.system_combo.lineEdit(), self.path_edit):
            control.installEventFilter(self)

    def eventFilter(self, control, event):
        if (event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and control in (self.system_combo, self.system_combo.lineEdit(), self.path_edit)):
            if control is not self.path_edit:
                text = self.system_combo.currentText().strip().casefold()
                current = self.system_combo.currentIndex()
                if current >= 0 and self.system_combo.itemText(current).strip().casefold() == text:
                    self._activate_font(current)
                else:
                    for index in range(self.system_combo.count()):
                        if self.system_combo.itemText(index).strip().casefold() == text:
                            self._activate_font(index)
                            break
            # QDialog must not treat text confirmation as a click on one of
            # its default buttons (including the font-file chooser).
            event.accept()
            return True
        return super().eventFilter(control, event)

    @property
    def font_path(self):
        return self._font_path

    @property
    def font_index(self):
        return self._font_index

    def _sync_combo(self):
        blocker = QSignalBlocker(self.system_combo)
        try:
            target = -1
            for index in range(self.system_combo.count()):
                path, face = self.system_combo.itemData(index)
                if face == self._font_index and ((not path and not self._font_path) or
                                                (path and self._font_path and Path(path) == Path(self._font_path))):
                    target = index
                    break
            self.system_combo.setCurrentIndex(target)
            if target < 0:
                self.system_combo.setEditText(f'本地字体 · {Path(self._font_path).name} · 字体 {self._font_index + 1}')
        finally:
            blocker.unblock()

    def set_font(self, path, index=0):
        """Restore a selection without signalling a user change."""
        self._font_path = str(path or '').strip()
        self._font_index = index if self._font_path and isinstance(index, int) and index >= 0 else 0
        blocker = QSignalBlocker(self.path_edit)
        try:
            self.path_edit.setText(self._font_path)
        finally:
            blocker.unblock()
        self._sync_combo()

    def _change_font(self, path, index):
        before = self._font_path, self._font_index
        self.set_font(path, index)
        if before != (self._font_path, self._font_index):
            self.font_changed.emit(self._font_path, self._font_index)

    def _activate_font(self, index):
        data = self.system_combo.itemData(index)
        if data is not None:
            self._change_font(*data)

    def _path_changed(self, text):
        before = self._font_path, self._font_index
        path = text.strip()
        if path != self._font_path:
            self._font_path, self._font_index = path, 0
        self._sync_combo()
        if before != (self._font_path, self._font_index):
            self.font_changed.emit(self._font_path, self._font_index)

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择资料导出字体', self._font_path,
                                             '字体文件 (*.ttf *.otf *.ttc)')
        if path:
            self._change_font(path, 0)
