"""Show a game map image or locally rendered animation in the native workbench."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPushButton, QStackedWidget, QVBoxLayout

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
        self._replay_fullscreen = False
        self.setWindowTitle(f'{caption} · 地图预览')
        self.resize(1020, 660)

        layout = QVBoxLayout(self)
        self._windowed_margins = layout.contentsMargins()
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

        self.content = QStackedWidget(self)
        self.viewer = ResourcePreviewWidget(self.content)
        self.viewer.status.hide()
        self.content.addWidget(self.viewer)
        layout.addWidget(self.content, 1)
        self.replay_view = None
        self._has_video = False
        self._windowed_state = None

        self.replay_status = QLabel()
        self.replay_status.setTextFormat(Qt.TextFormat.PlainText)
        self.replay_status.setWordWrap(True)
        self.replay_status.hide()
        layout.addWidget(self.replay_status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.replay_button = QPushButton('播放出怪…')
        self.replay_button.setToolTip('读取原始场景和出怪脚本，在预览窗口内播放。')
        self.buttons.addButton(self.replay_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.replay_button.hide()
        self.fullscreen_button = QPushButton('全屏播放')
        self.fullscreen_button.clicked.connect(self._toggle_fullscreen)
        self.buttons.addButton(self.fullscreen_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.fullscreen_button.hide()
        self._fullscreen_exit = QPushButton('退出全屏', self)
        self._fullscreen_exit.setToolTip('按 Esc 退出全屏')
        self._fullscreen_exit.clicked.connect(self._leave_fullscreen)
        self._fullscreen_exit.hide()
        self._escape_fullscreen = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._escape_fullscreen.setEnabled(False)
        self._escape_fullscreen.activated.connect(self._leave_fullscreen)
        self.buttons.button(QDialogButtonBox.StandardButton.Close).setText('关闭')
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        if path is not None:
            self.show_media(path)

    def show_detail(self, text):
        self.detail.setText(text)
        self.detail.setVisible(bool(text) and not self._replay_fullscreen)

    def show_replay_status(self, text):
        self.replay_status.setText(text)
        self.replay_status.setVisible(bool(text) and not self._replay_fullscreen)

    def show_replay(self, url):
        from .level_replay_view import LevelReplayView

        view = LevelReplayView(url, self.content)
        self.replay_view = view
        view.loadFinished.connect(self._replay_loaded)
        view.renderProcessTerminated.connect(self._replay_process_stopped)
        self.content.addWidget(view)
        self.toggle_replay()
        view.load_replay()

    def toggle_replay(self):
        view = self.replay_view
        if view is None:
            return
        show_player = self.content.currentWidget() is self.viewer
        if show_player:
            self.viewer.player.pause()
        else:
            self._leave_fullscreen()
        self.content.setCurrentWidget(view if show_player else self.viewer)
        view.page().setVisible(show_player)
        self.replay_button.setText('返回地图预览' if show_player else '显示出怪回放')
        self.fullscreen_button.setVisible(show_player or self._has_video)

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self._leave_fullscreen()
            return
        self._windowed_state = self.windowState()
        if self.replay_view is not None and self.content.currentWidget() is self.replay_view:
            self._set_replay_fullscreen(True)
        self.showFullScreen()
        self.fullscreen_button.setText('退出全屏')
        self._escape_fullscreen.setEnabled(True)

    def _leave_fullscreen(self):
        if self._windowed_state is None:
            return
        if self._replay_fullscreen:
            self._set_replay_fullscreen(False)
        self.setWindowState(self._windowed_state)
        self._windowed_state = None
        self.fullscreen_button.setText('全屏播放')
        self._escape_fullscreen.setEnabled(False)

    def _set_replay_fullscreen(self, enabled):
        self._replay_fullscreen = enabled
        if enabled:
            self.layout().setContentsMargins(0, 0, 0, 0)
        else:
            self.layout().setContentsMargins(self._windowed_margins)
        self.heading.setVisible(not enabled)
        self.detail.setVisible(bool(self.detail.text()) and not enabled)
        self.replay_status.setVisible(bool(self.replay_status.text()) and not enabled)
        self.buttons.setVisible(not enabled)
        self.replay_view.set_fullscreen_presentation(enabled)
        self._fullscreen_exit.setVisible(enabled)
        if enabled:
            self._place_fullscreen_exit()

    def _place_fullscreen_exit(self):
        self._fullscreen_exit.adjustSize()
        self._fullscreen_exit.move(self.width() - self._fullscreen_exit.width() - 12, 12)
        self._fullscreen_exit.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._replay_fullscreen:
            self._place_fullscreen_exit()

    def _replay_loaded(self, loaded):
        if not loaded and self.replay_view is not None:
            self.show_replay_status('窗口内回放未能载入。关闭预览后可以重试。')

    def _replay_process_stopped(self, *_):
        if self.replay_view is not None:
            self.show_replay_status('窗口内播放器已停止。关闭预览后可以重试。')

    def show_message(self, text):
        self.viewer.clear()
        self.viewer.preview.setPlainText(text)

    def show_media(self, path):
        suffix = path.suffix.casefold()
        self._has_video = False
        if suffix not in {'.mp4', '.png'}:
            self.viewer.preview.setPlainText('地图预览需要 PNG 或 MP4 文件。')
        elif suffix == '.mp4' and path.is_file() and not _has_mp4_header(path):
            self.viewer.preview.setPlainText('动画文件不是有效的 MP4，请重新生成预览。')
        elif not self.viewer.show_file(path):
            self.viewer.preview.setPlainText('地图预览文件不存在或无法读取。请重新生成预览。')
        elif suffix == '.mp4':
            self.viewer.player.setPlaybackRate(2.0)
            self._has_video = True
        self.fullscreen_button.setVisible(self._has_video or self.content.currentWidget() is self.replay_view)

    def done(self, result):
        if self.replay_view is not None:
            view, self.replay_view = self.replay_view, None
            view.shutdown()
        self.viewer.shutdown()
        super().done(result)
