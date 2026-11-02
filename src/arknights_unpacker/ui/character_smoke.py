"""Explicit native acceptance of automatic AVG previews and configured export."""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import time
import traceback

from PIL import Image
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton

from .. import __version__
from ..paths import atomic_json
from .character_workbench import CharacterWorkbench


class CharacterSmoke:
    def __init__(self, app, window, source, receipt):
        self.app, self.window = app, window
        self.source, self.receipt = Path(source).resolve(), Path(receipt).resolve()
        self.app.setQuitOnLastWindowClosed(False)
        self.started, self.stage = time.monotonic(), 'open'
        self.dialog = None
        self.preview_paths = []
        self.original_hash = self.digest(self.source)
        self.result = {'version': __version__, 'frozen': bool(getattr(sys, 'frozen', False)),
                       'qt_platform': app.platformName(), 'source': str(self.source),
                       'source_sha256': self.original_hash}
        self.timer = QTimer(window)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    @staticmethod
    def digest(path):
        with Path(path).open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()

    @staticmethod
    def pixels(path):
        with Image.open(path) as source:
            image = source.convert('RGBA')
            alpha = image.getchannel('A')
            return {'pixels_sha256': hashlib.sha256(image.tobytes()).hexdigest(),
                    'size': list(image.size), 'alpha_range': list(alpha.getextrema()),
                    'transparent_pixels': alpha.histogram()[0]}

    def output_unchanged(self):
        assert Path(self.window.services.config['output_root']).resolve() == self.output_root
        assert Path(self.window.settings.output.text()).resolve() == self.output_root

    def click_job(self, button):
        before = {job.job_id for job in self.window.queue.jobs}
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        job, = [job for job in self.window.queue.jobs if job.job_id not in before]
        return job

    def automatic_preview_job(self, options):
        jobs = [job for job in self.window.queue.jobs if (job.request or {}).get('preview') is True
                and (job.request or {}).get('kinds') == ['expression']
                and (job.request or {}).get('paths') == [str(self.source)]
                and (job.request or {}).get('character_options') == options]
        if not jobs:
            return None
        job, = jobs
        if job.status in ('排队中', '运行中', '正在取消'):
            return None
        return job

    @staticmethod
    def successful(job):
        assert job.status == '成功', job.last_error or f'{job.title}: {job.status}'

    def preview_ready(self, job):
        self.successful(job)
        assert self.dialog.export_button.isEnabled(), self.dialog.status.text()
        assert self.dialog.successful_options == self.dialog.current_options()
        assert job.request['kinds'] == ['expression'] and job.request['preview']
        assert job.request['character_options'] == self.dialog.successful_options
        path = self.dialog.preview_panel.image_path
        assert path is not None and path.is_file()
        assert path.is_relative_to(Path(job.output).resolve())
        self.output_unchanged()
        evidence = self.pixels(path)
        assert evidence['size'] == self.canvas, evidence
        assert evidence['alpha_range'] == [0, 255] and evidence['transparent_pixels'] > 0, evidence
        return path, evidence

    def tick(self):
        try:
            if time.monotonic() - self.started > 90:
                raise TimeoutError('Character composition acceptance timed out: ' + self.stage)
            if self.window.queue.busy or self.window._restore_pending:
                return
            if self.stage != 'open':
                assert self.window.tabs.currentWidget() is self.origin_page, 'Character work changed the current page'
            if self.stage == 'open':
                self.output_root = Path(self.window.services.config['output_root']).resolve()
                self.window.pages.select('explorer')
                self.origin_page = self.window.tabs.currentWidget()
                previous = tuple(self.window._dialogs)
                before = {job.job_id for job in self.window.queue.jobs}
                self.window.character_workbench([str(self.source)])
                self.dialog, = [dialog for dialog in self.window._dialogs if dialog not in previous]
                assert isinstance(self.dialog, CharacterWorkbench)
                self.catalog_job, = [job for job in self.window.queue.jobs if job.job_id not in before]
                assert not self.catalog_job.show_in_tasks
                self.stage = 'catalog'
                return
            if self.stage == 'catalog':
                self.successful(self.catalog_job)
                assert self.dialog._groups, self.dialog.status.text()
                assert not hasattr(self.dialog, 'preview_button'), 'Manual preview button attribute remains'
                assert all(button.text() != '预览合成' and button.objectName() != 'previewCharacterComposition'
                           for button in self.dialog.findChildren(QPushButton)), 'Manual preview button remains in the window'
                assert self.catalog_job not in self.window.queue.visible_jobs
                self.expected_batch_count = sum(len(group['entries']) for group in self.dialog._groups)
                group = next(group for group in self.dialog._groups if group['id'] == self.dialog.group_choice.currentData())
                base = next(entry for entry in group['entries'] if entry['id'] == group['base_id'])
                face = next(entry for entry in group['entries'] if entry['id'] == self.dialog.face_choice.currentData())
                assert face['role'] == 'face', 'The acceptance sample needs a movable face patch'
                self.canvas = [base['width'], base['height']]
                self.initial_options = dict(self.dialog.current_options())
                self.result.update(group_count=len(self.dialog._groups), expected_batch_count=self.expected_batch_count,
                                   catalog_read_hidden=True, logical_canvas=self.canvas,
                                   manual_preview_button_absent=True)
                self.stage = 'first_preview'
                return
            if self.stage == 'first_preview':
                self.first_job = self.automatic_preview_job(self.initial_options)
                if self.first_job is None:
                    return
                self.preview_paths.append(Path(self.first_job.output))
                _, self.first_pixels = self.preview_ready(self.first_job)
                self.result['initial_preview'] = {**self.first_pixels, 'options': self.initial_options}
                spin = self.dialog.x_spin
                spin.setFocus()
                spin.selectAll()
                QTest.keyClicks(spin, str(self.initial_options['x'] + 3))
                QTest.keyClick(spin, Qt.Key.Key_Tab)
                assert spin.value() == self.initial_options['x'] + 3
                assert not self.dialog.export_button.isEnabled(), 'Changed parameters retained old export confirmation'
                assert not self.preview_paths[0].exists(), 'Changed parameters retained the old preview cache'
                self.modified_options = dict(self.dialog.current_options())
                self.stage = 'modified_preview'
                return
            if self.stage == 'modified_preview':
                self.second_job = self.automatic_preview_job(self.modified_options)
                if self.second_job is None:
                    return
                self.preview_paths.append(Path(self.second_job.output))
                _, self.second_pixels = self.preview_ready(self.second_job)
                assert self.second_pixels['pixels_sha256'] != self.first_pixels['pixels_sha256']
                self.successful_options = dict(self.dialog.successful_options)
                self.result['modified_preview'] = {**self.second_pixels, 'options': self.successful_options}
                self.export_job = self.click_job(self.dialog.export_button)
                self.stage = 'formal_export'
                return
            if self.stage == 'formal_export':
                self.successful(self.export_job)
                assert self.export_job.request['character_options'] == self.successful_options
                assert not self.export_job.request['preview'] and self.export_job.show_in_tasks
                outputs = self.export_job.result.get('outputs', [])
                assert len(outputs) == 1 and outputs[0]['kind'] == 'character_expression', outputs
                path = Path(outputs[0]['path']).resolve()
                assert path.is_relative_to(self.output_root)
                assert self.pixels(path) == self.second_pixels, 'Formal PNG differs from the confirmed automatic preview'
                self.output_unchanged()
                self.result.update(formal_preview_pixels_equal=True, formal_options_preserved=True,
                                   formal_png=str(path), formal_output_root=str(self.output_root))
                self.batch_job = self.click_job(self.dialog.batch_button)
                self.stage = 'batch_export'
                return
            if self.stage == 'batch_export':
                self.successful(self.batch_job)
                assert self.batch_job.request.get('character_options') is None
                outputs = self.batch_job.result.get('outputs', [])
                assert len(outputs) == self.expected_batch_count, (len(outputs), self.expected_batch_count)
                assert all(output['kind'] == 'character_expression' and Path(output['path']).is_file() for output in outputs)
                corresponding, = [output for output in outputs if output.get('character', {}).get('entry_id') == self.initial_options['face_id']]
                assert self.pixels(corresponding['path']) == self.first_pixels, 'Batch export reused manual placement'
                self.output_unchanged()
                self.receipt.parent.mkdir(parents=True, exist_ok=True)
                image = self.receipt.with_name(self.receipt.stem + '-preview.png')
                assert self.dialog.grab().save(str(image))
                self.result.update(batch_export_count=len(outputs), batch_uses_config=True,
                                   batch_pngs=[output['path'] for output in outputs], screenshot=str(image))
                self.preview_paths.extend(lease.path for lease in self.dialog._preview_leases)
                panel = self.dialog.preview_panel
                self.dialog.close()
                assert panel.player.source().isEmpty()
                self.stage = 'closed'
                return
            if self.stage == 'closed':
                assert all(not path.exists() for path in self.preview_paths), self.preview_paths
                assert self.digest(self.source) == self.original_hash
                self.output_unchanged()
                self.result.update(success=True, source_unchanged=True, current_page_preserved=True,
                                   preview_settings_unchanged=True, parameter_edit_invalidates_export=True,
                                   preview_pixels_changed=True, preview_cache_released=True,
                                   automatic_preview=True, manual_preview_button_absent=True,
                                   media_source_released=True,
                                   elapsed_seconds=round(time.monotonic() - self.started, 2))
                self.finish(0)
        except Exception:
            self.result.update(success=False, stage=self.stage, traceback=traceback.format_exc())
            if self.dialog is not None and not getattr(self.dialog, '_workbench_closed', False):
                self.result['dialog_status'] = self.dialog.status.text()
                self.receipt.parent.mkdir(parents=True, exist_ok=True)
                self.dialog.grab().save(str(self.receipt.with_suffix('.png')))
            self.finish(1)

    def finish(self, code):
        self.timer.stop()
        atomic_json(self.receipt, self.result)
        for dialog in tuple(self.window._dialogs):
            dialog.close()
        self.window.close()
        QTimer.singleShot(200, lambda: self.app.exit(code))
