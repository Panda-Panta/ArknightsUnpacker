"""Show a game map image or locally rendered animation in the native workbench."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from .resource_preview import ResourcePreviewWidget


def _has_mp4_header(path):
    try:
        with path.open('rb') as stream:
            header = stream.read(12)
    except OSError:
        return False
    return len(header) == 12 and header[4:8] == b'ftyp'


class LevelPreviewDialog(QDialog):
    def __init__(self, path: Path, caption: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'{caption} · 地图预览')
        self.resize(1020, 660)

        layout = QVBoxLayout(self)
        heading = QLabel(caption)
        heading.setTextFormat(Qt.TextFormat.PlainText)
        heading.setWordWrap(True)
        heading.setProperty('role', 'pageTitle')
        layout.addWidget(heading)

        self.viewer = ResourcePreviewWidget(self)
        self.viewer.status.hide()
        layout.addWidget(self.viewer, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText('关闭')
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        suffix = path.suffix.casefold()
        if suffix not in {'.mp4', '.png'}:
            self.viewer.preview.setPlainText('地图预览需要 PNG 或 MP4 文件。')
        elif suffix == '.mp4' and path.is_file() and not _has_mp4_header(path):
            self.viewer.preview.setPlainText('动画文件不是有效的 MP4，请重新生成预览。')
        elif not self.viewer.show_file(path):
            self.viewer.preview.setPlainText('地图预览文件不存在或无法读取。请重新生成预览。')

    def done(self, result):
        self.viewer.shutdown()
        super().done(result)
