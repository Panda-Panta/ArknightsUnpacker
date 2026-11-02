"""Opt-in native acceptance of the production object-preview path."""
from pathlib import Path
import hashlib
import time
import traceback

from PySide6.QtCore import QTimer

from .. import __version__
from ..paths import atomic_json


class PreviewSmoke:
    def __init__(self, app, window, source, receipt, kind, *, updates=False):
        self.app, self.window = app, window
        self.source, self.receipt = Path(source).resolve(), Path(receipt).resolve()
        self.kind = kind
        self.updates = updates
        self.started = time.monotonic()
        self.stage = 'open'
        self.dialog = None
        self.frames = 0
        self.frame_size = None
        self.result = {'version': __version__, 'source': str(self.source), 'kind': kind,
                       'entrypoint': 'updates_double_click' if updates else 'objects'}
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

    def prepare_updates(self):
        from ..contracts import FileRecord, ScanSnapshot
        from ..library.classifications import classify

        installation = self.window.services.installation
        assert installation is not None, 'The preview acceptance needs a selected installation'
        root = Path(installation.root).resolve()
        relative = self.source.relative_to(root).as_posix()
        metadata = self.source.stat()
        now = max(time.time(), metadata.st_mtime)
        layer = next((name for name, source_root in installation.source_roots.items()
                      if self.source.is_relative_to(Path(source_root).resolve())), 'other')
        record = FileRecord(relative, metadata.st_size, metadata.st_mtime_ns,
                            self.source.suffix, layer, classify(relative, layer))
        view = self.window.pages.widget('updates')
        assert view is not None, 'The updates page is unavailable'
        view.clear_filters()
        view.mode.setCurrentIndex(0)
        view.set_data(ScanSnapshot('preview-smoke', installation.profile_id, str(root), now, now, [record]),
                      None, hours=max(24, (now - metadata.st_mtime) / 3600 + 1))
        self.window.pages.select('updates')
        assert view.model.rowCount() == 1, 'The real preview source is absent from the updates page'
        self.result['update_record'] = relative

    def tick(self):
        try:
            if time.monotonic() - self.started > 85:
                raise TimeoutError('Native preview acceptance timed out at ' + self.stage)
            if self.stage == 'open':
                if self.window.queue.busy or self.window._restore_pending:
                    return
                if self.updates:
                    self.prepare_updates()
                    self.stage = 'updates_click'
                    return
                self.window.objects(str(self.source))
                self.dialog = self.window._dialogs[-1]
                self.stage = 'attach'
            if self.stage == 'updates_click':
                from PySide6.QtCore import Qt
                from PySide6.QtTest import QTest

                view = self.window.pages.widget('updates')
                index = view.model.index(0, 0)
                view.table.scrollTo(index)
                rectangle = view.table.visualRect(index)
                assert rectangle.isValid(), 'The updates row must be visible before double-clicking'
                previous = tuple(self.window._dialogs)
                QTest.mouseClick(view.table.viewport(), Qt.MouseButton.LeftButton, pos=rectangle.center())
                QTest.mouseDClick(view.table.viewport(), Qt.MouseButton.LeftButton, pos=rectangle.center())
                opened = [dialog for dialog in self.window._dialogs if dialog not in previous]
                assert len(opened) == 1, 'Double-clicking the updates row did not open one object-preview dialog'
                self.dialog = opened[0]
                assert Path(self.dialog.path).resolve() == self.source
                self.stage = 'attach'
            if self.stage == 'attach':
                from PySide6.QtWidgets import QPushButton
                assert not hasattr(self.dialog, 'preview_button')
                assert all(button.text() != '预览所选对象' for button in self.dialog.findChildren(QPushButton))
                assert self.dialog.auto_preview.isChecked()
                self.result['manual_preview_button_absent'] = True
                self.panel = self.dialog.preview_panel
                self.panel.audio_output.setMuted(True)
                self.panel.video_widget.videoSink().videoFrameChanged.connect(self.frame)
                self.stage = 'objects'
            if self.stage == 'objects':
                if not self.dialog.model.rowCount():
                    return
                from PySide6.QtCore import QPoint, Qt
                from PySide6.QtTest import QTest
                from PySide6.QtWidgets import QAbstractItemView
                from .models import selected_records

                column = next(index for index, item in enumerate(self.dialog.model.columns) if item[0] == '对象大小')
                rows = self.dialog.model.rows
                assert all(isinstance(row.get('size'), int) and row['size'] >= 0 for row in rows)
                chosen = [row['id'] for row in selected_records(self.dialog.table)]
                for order in (Qt.SortOrder.AscendingOrder, Qt.SortOrder.DescendingOrder):
                    other = Qt.SortOrder.DescendingOrder if order == Qt.SortOrder.AscendingOrder else Qt.SortOrder.AscendingOrder
                    self.dialog.table.sortByColumn(column, other)
                    self.dialog.table.scrollTo(self.dialog.model.index(0, column), QAbstractItemView.ScrollHint.PositionAtCenter)
                    self.app.processEvents()
                    header = self.dialog.table.horizontalHeader()
                    point = QPoint(header.sectionViewportPosition(column) + header.sectionSize(column) // 2, header.height() // 2)
                    assert header.viewport().rect().contains(point)
                    QTest.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=point)
                    assert header.sortIndicatorOrder() == order
                    sizes = [row['size'] for row in self.dialog.model.rows]
                    assert sizes == sorted(sizes, reverse=order == Qt.SortOrder.DescendingOrder)
                    assert [row['id'] for row in selected_records(self.dialog.table)] == chosen
                self.result.update(object_size_sort_verified=True,
                                   serialized_object_sizes={row['id']: row['size'] for row in self.dialog.model.rows},
                                   selected_object_preserved_after_sort=True)
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
