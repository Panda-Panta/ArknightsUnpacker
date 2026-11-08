"""Show a game map image or locally rendered animation in the native workbench."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPushButton, QVBoxLayout

from .resource_preview import ResourcePreviewWidget


def _has_mp4_header(path):
    try:
        with path.open('rb') as stream:
            header = stream.read(12)
    except OSError:
        return False
    return len(header) == 12 and header[4:8] == b'ftyp'


class LevelPreviewDialog(QDialog):
    def __init__(self, path: Path | None, caption: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'{caption} · 地图预览')
        self.resize(1020, 660)

        layout = QVBoxLayout(self)
        self.heading = QLabel(caption)
        self.heading.setTextFormat(Qt.TextFormat.PlainText)
        self.heading.setWordWrap(True)
        self.heading.setProperty('role', 'pageTitle')
        layout.addWidget(self.heading)

        self.detail = QLabel()
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        self.detail.setWordWrap(True)
        self.detail.setVisible(False)
        layout.addWidget(self.detail)

        self.viewer = ResourcePreviewWidget(self)
        self.viewer.status.hide()
        layout.addWidget(self.viewer, 1)

        self.replay_status = QLabel()
        self.replay_status.setTextFormat(Qt.TextFormat.PlainText)
        self.replay_status.setWordWrap(True)
        self.replay_status.hide()
        layout.addWidget(self.replay_status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.replay_button = QPushButton('播放出怪…')
        self.replay_button.setToolTip('读取原始场景和出怪脚本，在浏览器内播放。')
        buttons.addButton(self.replay_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.replay_button.hide()
        buttons.button(QDialogButtonBox.StandardButton.Close).setText('关闭')
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if path is not None:
            self.show_media(path)

    def show_detail(self, text):
        self.detail.setText(text)
        self.detail.setVisible(bool(text))

    def show_replay_status(self, text):
        self.replay_status.setText(text)
        self.replay_status.setVisible(bool(text))

    def show_message(self, text):
        self.viewer.clear()
        self.viewer.preview.setPlainText(text)

    def show_media(self, path):
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
