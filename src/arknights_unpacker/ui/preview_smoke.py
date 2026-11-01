"""Opt-in native acceptance of the production object-preview path."""
from pathlib import Path
import hashlib
import time
import traceback

from PySide6.QtCore import QTimer

from .. import __version__
from ..paths import atomic_json


class PreviewSmoke:
    def __init__(self, app, window, source, receipt, kind):
        self.app, self.window = app, window
        self.source, self.receipt = Path(source).resolve(), Path(receipt).resolve()
        self.kind = kind
        self.started = time.monotonic()
        self.stage = 'open'
        self.dialog = None
        self.frames = 0
        self.frame_size = None
        self.result = {'version': __version__, 'source': str(self.source), 'kind': kind}
        self.original_hash = self.digest()
        self.timer = QTimer(window)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def digest(self):
        with self.source.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()

    def frame(self, frame):
        if frame.isValid():
            self.frames += 1
            self.frame_size = [frame.width(), frame.height()]

    def tick(self):
        try:
            if time.monotonic() - self.started > 85:
                raise TimeoutError('Native preview acceptance timed out at ' + self.stage)
            if self.stage == 'open':
                if self.window.queue.busy or self.window._restore_pending:
                    return
                self.window.objects(str(self.source))
                self.dialog = self.window._dialogs[-1]
                self.panel = self.dialog.preview_panel
                self.panel.audio_output.setMuted(True)
                self.panel.video_widget.videoSink().videoFrameChanged.connect(self.frame)
                self.stage = 'objects'
            if self.stage == 'objects':
                if not self.dialog.model.rowCount():
                    return
                wanted = {'image': {'Texture2D', 'Sprite', 'Image'}, 'audio': {'AudioClip'},
                          'video': {'VideoClip'}, 'text': {'TextAsset'}}[self.kind]
                index = next((index for index, row in enumerate(self.dialog.model.rows)
                              if row.get('type') in wanted and row.get('previewable', True)), None)
                if index is None:
                    raise AssertionError('No matching preview object: ' + self.kind)
                self.dialog.table.selectRow(index)
                self.stage = 'ready'
            if self.stage == 'ready':
                if self.window.queue.busy or self.panel.current_path is None:
                    return
                self.result.update(preview_file=str(self.panel.current_path),
                    right_panel=self.panel.x() > self.dialog.table.x(),
                    panel_size=[self.panel.width(), self.panel.height()],
                    automatic=self.dialog.auto_preview.isChecked())
                if self.kind == 'image':
                    assert not self.panel.image_pixmap.isNull()
                    self.panel.fit_image()
                    self.result.update(image_size=[self.panel.image_pixmap.width(), self.panel.image_pixmap.height()],
                                       displayed_size=[self.panel.picture.width(), self.panel.picture.height()],
                                       zoom=self.panel.image_zoom.value())
                    self.stage = 'close'
                elif self.kind == 'text':
                    assert self.panel.preview.toPlainText()
                    self.result['text_length'] = len(self.panel.preview.toPlainText())
                    self.stage = 'close'
                else:
                    if self.panel.player.error().value:
                        raise AssertionError(self.panel.player.errorString())
                    if self.panel.player.duration() <= 0:
                        return
                    self.result['autoplay'] = self.panel.player.playbackState().name
                    assert self.panel.player.playbackState().name == 'StoppedState'
                    self.result['duration_ms'] = self.panel.player.duration()
                    self.panel.play_button.click()
                    self.stage = 'playing'
            if self.stage == 'playing':
                if self.panel.player.error().value:
                    raise AssertionError(self.panel.player.errorString())
                if self.panel.player.position() < min(350, self.panel.player.duration() // 2):
                    return
                if self.kind == 'video' and self.frames == 0:
                    return
                self.result.update(played_to_ms=self.panel.player.position(), video_frames=self.frames,
                                   video_frame_size=self.frame_size, muted=self.panel.audio_output.isMuted())
                self.panel.play_button.click()
                assert self.panel.player.playbackState().name == 'PausedState'
                self.panel.player.setPosition(min(500, self.panel.player.duration() // 2))
                self.result['pause_seek'] = True
                self.stage = 'close'
            if self.stage == 'close':
                self.receipt.parent.mkdir(parents=True, exist_ok=True)
                screenshot = self.receipt.with_suffix('.png')
                self.dialog.grab().save(str(screenshot))
                self.result['screenshot'] = str(screenshot)
                self.cache_paths = [lease.path for lease in self.dialog._preview_leases]
                assert self.cache_paths
                self.dialog.close()
                assert self.panel.player.source().isEmpty()
                self.stage = 'verify'
                return
            if self.stage == 'verify':
                assert all(not path.exists() for path in self.cache_paths), self.cache_paths
                assert self.digest() == self.original_hash
                self.result.update(success=True, source_unchanged=True, media_source_released=True,
                    owned_cache_removed=True, qt_platform=self.app.platformName(),
                    elapsed_seconds=round(time.monotonic() - self.started, 2))
                atomic_json(self.receipt, self.result)
                self.timer.stop()
                self.window.close()
        except Exception as error:
            self.timer.stop()
            atomic_json(self.receipt, {**self.result, 'success': False, 'stage': self.stage,
                                      'error': str(error), 'traceback': traceback.format_exc()})
            self.window.close()
            self.app.exit(1)
