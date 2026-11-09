"""In-dialog resource display; decoding and cache ownership belong to the host."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QEvent, QSignalBlocker, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QImageReader, QMovie, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSlider, QStackedWidget, QTextBrowser, QVBoxLayout,
    QWidget)

from ..library.preview_types import DIRECT_SOURCE_TYPES


TEXT_PREVIEW_BYTES = 256 * 1024
HEX_PREVIEW_BYTES = 16 * 1024
IMAGE_SUFFIXES = {suffix for suffix, (kind, _) in DIRECT_SOURCE_TYPES.items() if kind == 'Image'}
# USM is decoded by the extraction service first; its raw container is not a
# Qt-playable result. IVF and elementary streams remain available individually.
VIDEO_SUFFIXES = {suffix for suffix, (kind, _) in DIRECT_SOURCE_TYPES.items()
                  if kind == 'VideoClip' and suffix != '.usm'} | {'.m2v', '.h264'}
AUDIO_SUFFIXES = {suffix for suffix, (kind, _) in DIRECT_SOURCE_TYPES.items() if kind == 'AudioClip'}


def _kind(path: Path, hint: str = '') -> str:
    suffix = path.suffix.casefold()
    if suffix in IMAGE_SUFFIXES:
        return 'image'
    if suffix in VIDEO_SUFFIXES or hint in {'video', 'video_playable', 'video_stream'}:
        return 'video'
    if suffix in AUDIO_SUFFIXES or hint in {'audio', 'audio_stream'}:
        return 'audio'
    return 'text'


def _priority(output) -> int:
    path, hint = output['path'], output['kind']
    kind = _kind(path, hint)
    if kind == 'video':
        return 0 if path.suffix.casefold() not in {'.ivf', '.m2v', '.h264'} else 1
    if kind == 'audio':
        return 2 if path.suffix.casefold() not in {'.adx', '.sfa'} else 6
    if kind == 'image':
        return 3
    if path.suffix.casefold() == '.json':
        return 4
    return 5 if path.suffix.casefold() not in {'.bytes', '.bin', '.skel', '.idx', '.audio', '.usm'} else 7


def _time_label(milliseconds: int) -> str:
    seconds = max(0, milliseconds) // 1000
    return f'{seconds // 60:02d}:{seconds % 60:02d}'


class ResourcePreviewWidget(QWidget):
    save_original_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_path = None
        self.image_path = None
        self.image_pixmap = QPixmap()
        self.movie = None
        self._outputs = []
        self._active_kind = None
        self._fit_mode = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.file_tools = QWidget()
        file_row = QHBoxLayout(self.file_tools)
        file_row.setContentsMargins(0, 0, 0, 0)
        file_row.addWidget(QLabel('预览产物'))
        self.file_choice = QComboBox()
        self.file_choice.setObjectName('resourcePreviewFile')
        self.file_choice.setAccessibleName('切换预览产物')
        file_row.addWidget(self.file_choice, 1)
        self.file_tools.hide()
        layout.addWidget(self.file_tools)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setProperty('muted', True)
        layout.addWidget(self.status)
        self.stack = QStackedWidget()
        self.preview = QTextBrowser()
        self.preview.setObjectName('resourcePreviewText')
        self.preview.setOpenExternalLinks(False)
        self.preview.setOpenLinks(False)
        self.stack.addWidget(self.preview)
        self.picture = QLabel()
        self.picture.setObjectName('resourcePreviewImage')
        self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.picture.setProperty('imageCanvas', True)
        self.image_scroll = QScrollArea()
        self.image_scroll.setWidgetResizable(False)
        self.image_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_scroll.setWidget(self.picture)
        self.image_scroll.viewport().installEventFilter(self)
        self.stack.addWidget(self.image_scroll)
        self.media_page = QWidget()
        media_layout = QVBoxLayout(self.media_page)
        media_layout.setContentsMargins(0, 0, 0, 0)
        self.video_widget = QVideoWidget()
        self.video_widget.setObjectName('resourcePreviewVideo')
        media_layout.addWidget(self.video_widget, 1)
        self.audio_hint = QLabel('音频预览\n点击播放按钮试听。')
        self.audio_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.audio_hint.setWordWrap(True)
        media_layout.addWidget(self.audio_hint, 1)
        self.media_controls = QWidget(self.media_page)
        controls = QVBoxLayout(self.media_controls)
        controls.setContentsMargins(0, 0, 0, 0)
        media_layout.addWidget(self.media_controls)
        self.media_status = QLabel()
        self.media_status.setWordWrap(True)
        controls.addWidget(self.media_status)
        playback = QHBoxLayout()
        self.play_button = QPushButton('播放')
        self.play_button.setObjectName('resourceMediaPlay')
        playback.addWidget(self.play_button)
        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setObjectName('resourceMediaPosition')
        self.position_slider.setAccessibleName('播放进度')
        self.position_slider.setRange(0, 0)
        playback.addWidget(self.position_slider, 1)
        self.time_label = QLabel('00:00 / 00:00')
        playback.addWidget(self.time_label)
        controls.addLayout(playback)
        volume = QHBoxLayout()
        volume.addStretch()
        volume.addWidget(QLabel('音量'))
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setObjectName('resourceMediaVolume')
        self.volume_slider.setAccessibleName('播放音量')
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.setMaximumWidth(140)
        volume.addWidget(self.volume_slider)
        controls.addLayout(volume)
        self.stack.addWidget(self.media_page)
        layout.addWidget(self.stack, 1)
        self.image_tools = QWidget()
        tools = QHBoxLayout(self.image_tools)
        tools.setContentsMargins(0, 0, 0, 0)
        tools.addWidget(QLabel('缩放'))
        self.image_zoom = QDoubleSpinBox()
        self.image_zoom.setObjectName('objectImageZoom')
        self.image_zoom.setRange(.1, 400)
        self.image_zoom.setDecimals(1)
        self.image_zoom.setSuffix(' %')
        self.image_zoom.setValue(100)
        self.image_zoom.setToolTip('只调整预览；保存原图保留原始文件。')
        tools.addWidget(self.image_zoom)
        self.fit_button = QPushButton('适应')
        self.fit_button.setToolTip('适应预览区')
        tools.addWidget(self.fit_button)
        self.animation_button = QPushButton('播放动图')
        tools.addWidget(self.animation_button)
        tools.addStretch()
        self.save_original_button = QPushButton('保存原图…')
        self.save_original_button.setObjectName('saveOriginalImage')
        self.save_original_button.setProperty('primary', True)
        tools.addWidget(self.save_original_button)
        self.image_tools.hide()
        layout.addWidget(self.image_tools)
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(.7)
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.positionChanged.connect(self._position_changed)
        self.player.playbackStateChanged.connect(self._playback_changed)
        self.player.mediaStatusChanged.connect(self._media_status_changed)
        self.player.errorOccurred.connect(self._media_error)
        self.play_button.clicked.connect(self.toggle_playback)
        self.position_slider.sliderMoved.connect(self.player.setPosition)
        self.position_slider.sliderReleased.connect(lambda: self.player.setPosition(self.position_slider.value()))
        self.volume_slider.valueChanged.connect(lambda value: self.audio_output.setVolume(value / 100))
        self.image_zoom.valueChanged.connect(self._zoom_changed)
        self.fit_button.clicked.connect(self.fit_image)
        self.animation_button.clicked.connect(self._toggle_animation)
        self.save_original_button.clicked.connect(lambda: self.save_original_requested.emit())
        self.file_choice.currentIndexChanged.connect(self._choose_file)
        self.clear()

    def set_video_fullscreen_presentation(self, enabled):
        self.media_controls.setVisible(not enabled)
        self.video_widget.setAspectRatioMode(
            Qt.AspectRatioMode.KeepAspectRatioByExpanding if enabled else Qt.AspectRatioMode.KeepAspectRatio)

    def show_files(self, outputs) -> bool:
        self.clear()
        if isinstance(outputs, (str, Path, dict)):
            outputs = [outputs]
        seen = set()
        for item in outputs or []:
            raw = item.get('path') if isinstance(item, dict) else item
            hint = str(item.get('kind', '')) if isinstance(item, dict) else ''
            try:
                path = Path(raw).expanduser().resolve()
                if path in seen or not path.is_file():
                    continue
            except (OSError, TypeError, ValueError):
                continue
            seen.add(path)
            self._outputs.append({'path': path, 'kind': hint})
        if not self._outputs:
            self.preview.setPlainText('没有可预览的文件。资源可能尚未解码，或提取结果已不存在。')
            return False
        selected = min(range(len(self._outputs)), key=lambda index: _priority(self._outputs[index]))
        with QSignalBlocker(self.file_choice):
            for output in self._outputs:
                path = output['path']
                self.file_choice.addItem(path.name, str(path))
                self.file_choice.setItemData(self.file_choice.count() - 1, str(path), Qt.ItemDataRole.ToolTipRole)
            self.file_choice.setCurrentIndex(selected)
        self.file_tools.setVisible(len(self._outputs) > 1)
        return self._choose_file(selected)

    def show_file(self, path):
        return self.show_files([path])

    def _choose_file(self, index):
        self._clear_display()
        if not 0 <= index < len(self._outputs):
            return False
        output = self._outputs[index]
        path = output['path']
        self.current_path = path
        self.status.setText(path.name)
        self.status.setToolTip(str(path))
        kind = _kind(path, output['kind'])
        try:
            if kind == 'image':
                return self._show_image(path)
            if kind in {'video', 'audio'}:
                self._active_kind = kind
                self.stack.setCurrentWidget(self.media_page)
                self.video_widget.setVisible(kind == 'video')
                self.audio_hint.setVisible(kind == 'audio')
                self.audio_hint.setText(path.name + '\n点击播放按钮试听。')
                self.media_status.setText('正在读取音视频；默认不自动播放。')
                self.play_button.setEnabled(True)
                self.player.setSource(QUrl.fromLocalFile(str(path)))
                return True
            with path.open('rb') as stream:
                data = stream.read(TEXT_PREVIEW_BYTES + 1)
            self._show_text_or_hex(data, path)
            return True
        except (OSError, ValueError) as error:
            self.stack.setCurrentWidget(self.preview)
            self.preview.setPlainText(f'无法读取预览文件：{error}')
            return False

    def _show_image(self, path):
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            with path.open('rb') as stream:
                data = stream.read(HEX_PREVIEW_BYTES + 1)
            self._show_hex(data, '图片无法解码，以下为文件的十六进制预览。')
            return True
        self.image_path = path
        self.image_pixmap = QPixmap.fromImage(image)
        self.stack.setCurrentWidget(self.image_scroll)
        self.image_tools.show()
        self.save_original_button.setEnabled(True)
        self.status.setText(f'{path.name}　·　{image.width()} × {image.height()} 像素')
        self._fit_mode = True
        self.fit_image()
        QTimer.singleShot(0, self._fit_if_active)
        if path.suffix.casefold() == '.gif':
            self.movie = QMovie(str(path), parent=self)
            if self.movie.isValid() and self.movie.frameCount() != 1:
                self.movie.frameChanged.connect(self._animation_frame)
                self.movie.jumpToFrame(0)
                self.animation_button.show()
                self.animation_button.setText('播放动图')
            else:
                self.movie.setFileName('')
                self.movie.deleteLater()
                self.movie = None
        return True

    def _animation_frame(self, *_):
        if self.movie is not None:
            frame = self.movie.currentPixmap()
            if not frame.isNull():
                self.image_pixmap = frame
                self.update_image()

    def _toggle_animation(self):
        if self.movie is None:
            return
        if self.movie.state() == QMovie.MovieState.Running:
            self.movie.setPaused(True)
            self.animation_button.setText('播放动图')
        else:
            if self.movie.state() == QMovie.MovieState.Paused:
                self.movie.setPaused(False)
            else:
                self.movie.start()
            self.animation_button.setText('暂停动图')

    def _show_text_or_hex(self, data, path):
        truncated = len(data) > TEXT_PREVIEW_BYTES
        chunk = data[:TEXT_PREVIEW_BYTES]
        encoding = 'utf-32' if chunk.startswith((b'\xff\xfe\x00\x00', b'\x00\x00\xfe\xff')) else 'utf-16' if chunk.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
        try:
            # A bounded read can end mid-character. Ignore only that trailing
            # partial character; invalid bytes within the sample remain binary.
            text = chunk.decode(encoding)
        except UnicodeDecodeError as error:
            if truncated and error.end == len(chunk) and error.start >= len(chunk) - 4:
                try:
                    text = chunk[:error.start].decode(encoding)
                except UnicodeDecodeError:
                    self._show_hex(data)
                    return
            else:
                self._show_hex(data)
                return
        if any(ord(character) < 32 and character not in '\n\r\t\f' for character in text):
            self._show_hex(data)
            return
        if not truncated and (path.suffix.casefold() == '.json' or text.lstrip().startswith(('{', '['))):
            try:
                text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
            except (ValueError, TypeError, RecursionError):
                pass
        if truncated:
            text += '\n\n预览已限长，完整内容保留在原文件中。'
        self.stack.setCurrentWidget(self.preview)
        self.preview.setPlainText(text)

    def _show_hex(self, data, heading='二进制文件 · 有界十六进制预览'):
        chunk = data[:HEX_PREVIEW_BYTES]
        lines = [heading, '']
        for offset in range(0, len(chunk), 16):
            row = chunk[offset:offset + 16]
            hexadecimal = ' '.join(f'{byte:02x}' for byte in row)
            ascii_text = ''.join(chr(byte) if 32 <= byte < 127 else '.' for byte in row)
            lines.append(f'{offset:08x}  {hexadecimal:<47}  {ascii_text}')
        if len(data) > HEX_PREVIEW_BYTES:
            lines.append('\n预览已限长，完整二进制内容保留在原文件中。')
        self.stack.setCurrentWidget(self.preview)
        self.preview.setPlainText('\n'.join(lines))

    def _zoom_changed(self, *_):
        self._fit_mode = False
        self.update_image()

    def update_image(self, *_):
        if self.image_pixmap.isNull():
            return
        scale = self.image_zoom.value() / 100
        rendered = self.image_pixmap.scaled(max(1, round(self.image_pixmap.width() * scale)),
            max(1, round(self.image_pixmap.height() * scale)), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self.picture.setPixmap(rendered)
        self.picture.resize(rendered.size())

    def fit_image(self, *_):
        if self.image_pixmap.isNull():
            return
        self._fit_mode = True
        viewport = self.image_scroll.viewport()
        scale = min(max(1, viewport.width() - 12) / self.image_pixmap.width(),
                    max(1, viewport.height() - 12) / self.image_pixmap.height(), 1.0)
        with QSignalBlocker(self.image_zoom):
            self.image_zoom.setValue(scale * 100)
        self.update_image()

    def _fit_if_active(self):
        if self._fit_mode and not self.image_pixmap.isNull():
            self.fit_image()

    def eventFilter(self, watched, event):
        if watched is self.image_scroll.viewport() and event.type() == QEvent.Type.Resize and self._fit_mode:
            QTimer.singleShot(0, self._fit_if_active)
        return super().eventFilter(watched, event)

    def toggle_playback(self):
        if self.player.source().isEmpty():
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _duration_changed(self, duration):
        self.position_slider.setRange(0, min(max(0, duration), 2_147_483_647))
        self._position_changed(self.player.position())

    def _position_changed(self, position):
        if not self.position_slider.isSliderDown():
            with QSignalBlocker(self.position_slider):
                self.position_slider.setValue(position)
        self.time_label.setText(f'{_time_label(position)} / {_time_label(self.player.duration())}')

    def _playback_changed(self, state):
        self.play_button.setText('暂停' if state == QMediaPlayer.PlaybackState.PlayingState else '播放')

    def _media_status_changed(self, status):
        if self._active_kind not in {'video', 'audio'}:
            return
        if status in {QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia}:
            self.media_status.setText('点击播放；可拖动进度并调节音量。')
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.media_status.setText('播放结束，可再次播放。')

    def _media_error(self, error, description=''):
        if error == QMediaPlayer.Error.NoError or self._active_kind not in {'video', 'audio'}:
            return
        self.media_status.setText('无法播放该音视频：' + (description or self.player.errorString() or '当前格式不受支持') + '。可切换其他预览产物。')
        self.play_button.setEnabled(False)

    def _clear_display(self):
        self._active_kind = None
        # An empty source stops playback and all source I/O. In PySide 6.8.3
        # setSource releases the GIL; a separate stop() can deadlock FFmpeg
        # immediately after a paused seek while its worker needs the GIL.
        self.player.setSource(QUrl())
        if self.movie is not None:
            self.movie.frameChanged.disconnect(self._animation_frame)
            self.movie.stop()
            self.movie.setFileName('')
            self.movie.deleteLater()
            self.movie = None
        self.current_path = self.image_path = None
        self.image_pixmap = QPixmap()
        self._fit_mode = False
        self.picture.clear()
        self.preview.clear()
        self.image_tools.hide()
        self.animation_button.hide()
        self.save_original_button.setEnabled(False)
        self.play_button.setEnabled(False)
        self.play_button.setText('播放')
        self.position_slider.setRange(0, 0)
        self.time_label.setText('00:00 / 00:00')
        self.media_status.clear()
        self.stack.setCurrentWidget(self.preview)

    def clear(self):
        self._clear_display()
        self._outputs = []
        with QSignalBlocker(self.file_choice):
            self.file_choice.clear()
        self.file_tools.hide()
        self.status.clear()
        self.status.setToolTip('')
        self.preview.setPlainText('选择资源后在此预览。音视频点击播放后开始；预览不改动源文件。')

    def shutdown(self):
        self.clear()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
