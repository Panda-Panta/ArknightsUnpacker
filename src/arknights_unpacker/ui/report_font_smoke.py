"""Explicit native acceptance of font selection, refreshed preview, and export."""
from base64 import b64decode
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import sys
import time
import traceback

from PIL import Image, ImageFont
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest

from .. import __version__
from ..paths import atomic_json
from .report_preview import ReportArtifactsDialog


class ReportFontSmoke:
    def __init__(self, app, window, receipt):
        self.app, self.window, self.receipt = app, window, Path(receipt)
        self.started, self.stage = time.monotonic(), 'open'
        self.dialog = None
        self.font = Path('C:/Windows/Fonts/msyh.ttc')
        self.original_hash = self.digest(self.font)
        self.result = {'version': __version__, 'frozen': bool(getattr(sys, 'frozen', False)),
                       'qt_platform': app.platformName(), 'changes': []}
        self.timer = QTimer(window)
        self.timer.setInterval(70)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    @staticmethod
    def digest(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    @staticmethod
    def pixels(path):
        with Image.open(path) as image:
            return hashlib.sha256(image.convert('RGBA').tobytes()).hexdigest()

    def choose(self, index):
        combo = self.dialog.font_picker.system_combo
        target = next(i for i in range(combo.count()) if combo.itemData(i) and
                      Path(combo.itemData(i)[0]) == self.font and combo.itemData(i)[1] == index)
        # Confirm the selected system entry by keyboard, including the editable
        # combo's Return handling inside this real QDialog.
        combo.setCurrentIndex(target)
        combo.setFocus()
        QTest.keyClick(combo, Qt.Key.Key_Return)

    def ready(self, index):
        options = self.dialog.successful_options
        return (Path(options.font_path) == self.font and options.font_index == index and
                self.dialog.export_button.isEnabled())

    def tick(self):
        try:
            if time.monotonic() - self.started > 90:
                raise TimeoutError('Font preview acceptance timed out: ' + self.stage)
            if self.window.queue.busy or self.window._restore_pending:
                return
            if self.stage == 'open':
                assert self.window.operators.current_profile is not None
                self.result['operator_id'] = self.window.operators.current_profile.char_id
                self.original_options = self.window.settings.report_options()
                self.window.pages.select('operators')
                QTest.mouseClick(self.window.operators.preview_selected, Qt.MouseButton.LeftButton)
                self.stage = 'initial'
                return
            if self.stage == 'initial':
                previews = [dialog for dialog in self.window._dialogs if isinstance(dialog, ReportArtifactsDialog)
                            and dialog.font_picker is not None]
                if not previews:
                    return
                self.dialog, = previews
                self.initial_pixels = self.pixels(self.dialog.pages.currentData())
                self.previous_cache = self.dialog._preview_lease.path
                self.dialog.zoom.setValue(60)
                self.stage = 'face0'
                self.choose(0)
                return
            if self.stage in {'face0', 'face1'}:
                index = int(self.stage[-1])
                if not self.ready(index):
                    return
                assert self.dialog in self.window._dialogs and not self.dialog.preview_closed
                assert self.dialog.zoom.value() == 60
                assert not self.previous_cache.exists(), 'Replaced preview cache remains'
                path = self.dialog.pages.currentData()
                self.result['changes'].append({'font_path': str(self.font), 'font_index': index,
                    'pixels_sha256': self.pixels(path), 'font_name': ImageFont.truetype(str(self.font), 20, index=index).getname()})
                self.previous_cache = self.dialog._preview_lease.path
                if index == 0:
                    assert self.result['changes'][0]['pixels_sha256'] != self.initial_pixels
                    self.stage = 'face1'
                    self.choose(1)
                    return
                assert self.window.settings.report_options() == self.original_options, 'Preview changed global settings'
                self.receipt.parent.mkdir(parents=True, exist_ok=True)
                image = self.receipt.with_name(self.receipt.stem + '-preview.png')
                assert self.dialog.grab().save(str(image))
                self.result['screenshot'] = str(image)
                previous = {job.job_id for job in self.window.queue.jobs}
                QTest.mouseClick(self.dialog.export_button, Qt.MouseButton.LeftButton)
                self.job, = [job for job in self.window.queue.jobs if job.job_id not in previous]
                self.stage = 'export'
                return
            if self.stage == 'export':
                assert self.job.status == '成功', self.job.last_error or self.job.status
                expected = ImageFont.truetype(str(self.font), 20, index=1).getname()
                artifacts = self.job.artifacts
                assert {item.format for item in artifacts} >= {'png', 'html', 'json', 'txt'}
                for artifact in artifacts:
                    path = Path(artifact.path)
                    if artifact.format == 'json':
                        options = json.loads(path.read_text('utf-8'))['options']
                        assert Path(options['font_path']) == self.font and options['font_index'] == 1
                    elif artifact.format == 'html':
                        encoded, = re.findall(r'data:font/(?:ttf|otf);base64,([A-Za-z0-9+/=]+)', path.read_text('utf-8'))
                        font = b64decode(encoded)
                        assert not font.startswith(b'ttcf')
                        assert ImageFont.truetype(BytesIO(font), 20).getname() == expected
                    elif artifact.format == 'png':
                        with Image.open(path) as image:
                            image.verify()
                self.result['formal_artifacts'] = [{'path': item.path, 'format': item.format} for item in artifacts]
                self.dialog.close()
                self.stage = 'closed'
                return
            if self.stage == 'closed':
                assert not self.previous_cache.exists(), 'Closing preview did not release its cache'
                assert self.digest(self.font) == self.original_hash
                self.result.update(success=True, same_window=True, original_font_unchanged=True,
                    original_settings_unchanged=True, preview_cache_released=True,
                    elapsed_seconds=round(time.monotonic() - self.started, 2))
                self.finish(0)
        except Exception:
            self.result.update(success=False, stage=self.stage, traceback=traceback.format_exc())
            if self.dialog is not None:
                self.result.update(font_status=self.dialog.font_status.text(),
                    successful_font=self.dialog.successful_options.font_path,
                    successful_index=self.dialog.successful_options.font_index,
                    selected_font=self.dialog.font_picker.font_path,
                    selected_index=self.dialog.font_picker.font_index)
                self.receipt.parent.mkdir(parents=True, exist_ok=True)
                self.dialog.grab().save(str(self.receipt.with_suffix('.png')))
            self.finish(1)

    def finish(self, code):
        self.timer.stop()
        atomic_json(self.receipt, self.result)
        for dialog in tuple(self.window._dialogs):
            dialog.close()
        self.window.close()
        self.app.exit(code)
