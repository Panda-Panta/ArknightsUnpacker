"""Queue/window integration for owned previews, including late results."""
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from arknights_unpacker.contracts import ExtractionResult, ReportArtifact
from arknights_unpacker.ui.main_window import MainWindow
from test_explorer import MockServices, make_window, wait_idle


def object_dialog(qtbot, window, package):
    package.write_bytes(b'original package')
    window.objects(str(package), auto_preview=False)
    wait_idle(qtbot, window)
    dialog = window._dialogs[-1]
    dialog.table.selectRow(0)
    return dialog


def test_object_closed_during_writing_waits_for_task_without_reopening(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    started, release = threading.Event(), threading.Event()
    outputs = []
    def extract(paths, output, **kw):
        path = Path(output) / 'object.txt'
        path.write_text('preview bytes', encoding='utf-8')
        outputs.append(path)
        started.set()
        assert release.wait(5)
        return ExtractionResult(outputs=[{'path': str(path)}])
    services.extract = extract
    dialog = object_dialog(qtbot, window, tmp_path / 'fixture.ab')
    dialog.request(True)
    try:
        qtbot.waitUntil(started.is_set)
        dialog.close()
        assert outputs[0].exists(), 'A closed viewer must not remove files while their producer is active.'
        assert not window._dialogs
    finally:
        release.set()
        wait_idle(qtbot, window)
    assert not outputs[0].parent.exists()
    assert not window._dialogs and not window._preview_jobs
    assert (tmp_path / 'fixture.ab').read_bytes() == b'original package'


def test_cancelled_queued_previews_are_cleaned_without_starting(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    services.load_data(str(tmp_path))
    window.queue.paused = True
    for _ in range(2):
        window.preview_reports('operators', ['char_fixture'])
    caches = list((services.data_root / 'previews').iterdir())
    assert len(caches) == 2 and not window.queue.busy
    window.close()
    assert all(not path.exists() for path in caches)
    assert all(job.status == '已取消' for job in window.queue.jobs)
    assert not any(call[0] == 'export' for call in services.calls)
    assert not window._preview_jobs


def test_failed_report_releases_cache_and_keeps_failure_diagnostic(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    services.load_data(str(tmp_path))
    roots = []
    def fail(*args, **kw):
        root = Path(args[2])
        (root / 'partial.txt').write_text('incomplete preview', encoding='utf-8')
        roots.append(root)
        raise RuntimeError('preview failure fixture')
    services.export = fail
    window.preview_reports('operators', ['char_fixture'])
    wait_idle(qtbot, window)
    assert roots and not roots[0].exists()
    assert not window._dialogs
    assert window.queue.jobs[-1].status == '失败'
    assert 'preview failure fixture' in window.queue.jobs[-1].last_error
    assert services.config['output_root'] == str(tmp_path / 'exports')


def test_partial_object_preview_remains_readable_until_closed(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    outputs = []
    def partial(paths, output, **kw):
        path = Path(output) / 'partial.txt'
        path.write_text('completed object from partial batch', encoding='utf-8')
        outputs.append(path)
        return ExtractionResult(status='partial', outputs=[{'path': str(path)}], errors=[{'error': 'another object failed'}])
    services.extract = partial
    dialog = object_dialog(qtbot, window, tmp_path / 'fixture.ab')
    dialog.request(True)
    wait_idle(qtbot, window)
    assert outputs[0].exists()
    assert 'completed object' in dialog.preview.toPlainText()
    dialog.close()
    assert not outputs[0].parent.exists()
    assert any(job.status == '部分完成（查看诊断）' for job in window.queue.jobs)


def test_report_reuses_live_window_then_closing_removes_files_and_success_record(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    services.load_data(str(tmp_path))
    roots = []
    def export(*args, **kw):
        root = Path(args[2])
        path = root / 'report.png'
        image = QImage(30, 60, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.white)
        assert image.save(str(path))
        roots.append(root)
        return [ReportArtifact(str(path), 'png')]
    services.export = export
    window.preview_reports('operators', ['char_fixture'])
    wait_idle(qtbot, window)
    dialog = window._dialogs[-1]
    window.jobs.table.selectRow(len(window.queue.jobs) - 1)
    window.jobs.preview_artifacts()
    assert window._dialogs == [dialog] and roots[0].exists()
    dialog.close()
    assert not roots[0].exists() and not window._dialogs
    assert not window.queue.jobs
    assert not list((services.data_root / 'queue').glob('*.json'))


@pytest.mark.parametrize('owned', [False, True])
def test_only_proven_old_preview_output_setting_is_repaired(qtbot, tmp_path, monkeypatch, owned):
    services = MockServices(tmp_path)
    queue_root = services.data_root / 'queue'
    queue_root.mkdir(parents=True)
    cached = services.data_root / 'preview' / ('a' * 32)
    services.config.update(output_root=str(cached), hours=31)
    job_id = 'b' * 32
    record = {'schema': 1, 'job_id': job_id, 'title': '预览对象 · 1 个文件' if owned else '解包所选 · 1 个文件',
              'output': str(cached), 'status': '成功', 'request': {'operation': 'extract', 'output': str(cached)}}
    (queue_root / (job_id + '.json')).write_text(json.dumps(record), encoding='utf-8')
    official = tmp_path / 'portable' / 'exports'
    monkeypatch.setattr('arknights_unpacker.paths.default_output_root', lambda: official)
    window = MainWindow(services)
    qtbot.addWidget(window)
    assert services.config['output_root'] == str(official if owned else cached)
    assert services.config['hours'] == 31
    assert official.is_dir() == owned
    assert window.settings.output.text() == services.config['output_root']


@pytest.mark.parametrize('recovered', [False, True])
def test_report_success_already_queued_during_close_does_not_reopen(qtbot, tmp_path, recovered):
    window, services = make_window(qtbot, tmp_path)
    services.load_data(str(tmp_path))
    started, release, succeeded = threading.Event(), threading.Event(), threading.Event()
    def export(*args, **kw):
        root = Path(args[2])
        root.mkdir(parents=True, exist_ok=True)
        target = root / 'formal.png'
        image = QImage(30, 60, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.white)
        assert image.save(str(target))
        started.set()
        assert release.wait(5)
        return [ReportArtifact(str(target), 'png')]
    services.export = export
    late_dialogs = []
    track = window._track_dialog
    def tracking(dialog):
        if window._closing:
            late_dialogs.append(dialog)
        track(dialog)
    window._track_dialog = tracking
    if recovered:
        request = {'operation': 'report', 'root': '', 'snapshot_id': services.gamedata.snapshot_id,
                   'operators': ['char_fixture'], 'modules': [], 'output': str(tmp_path / 'exports'), 'formats': ['png']}
        call, done = window.prepare_recovery(SimpleNamespace(request=request))
        window.queue.submit('recovered report', call, done, request=request)
    else:
        window.export('operators', ['char_fixture'])
    qtbot.waitUntil(started.is_set)
    window.queue.worker.succeeded.connect(lambda _: succeeded.set(), Qt.ConnectionType.DirectConnection)
    release.set()
    assert succeeded.wait(5), 'The worker must emit success while the GUI callback is still queued.'
    window.close()
    qtbot.waitUntil(lambda: not window.queue.busy and not window.isVisible())
    assert not late_dialogs


def test_formal_report_original_save_also_rejects_preview_cache(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    window, _ = make_window(qtbot, tmp_path)
    lease = window.preview_cache.allocate('objects')
    lease.finish()
    source = tmp_path / 'formal.png'
    image = QImage(30, 60, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.white)
    assert image.save(str(source))
    original = source.read_bytes()
    dialog = window.show_report_artifacts([ReportArtifact(str(source), 'png')])
    target = lease.path / 'saved-original.png'
    warnings = []
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **kw: (str(target), ''))
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a: warnings.append(str(a[-1])))
    dialog.save_original()
    assert not target.exists(), 'Formal report saves must not put user copies into another active temporary cache.'
    assert warnings and '正式输出目录' in warnings[-1]
    lease.release()
    assert source.read_bytes() == original
