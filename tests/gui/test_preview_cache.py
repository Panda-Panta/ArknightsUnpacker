import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys

import pytest

from arknights_unpacker.ui.preview_cache import PreviewCache


def legacy_object(history, cache, *, extra=False):
    task = cache / 'extract-20261020-120000-0123456789'
    task.mkdir(parents=True)
    output = task / 'preview.txt'
    output.write_bytes(b'original preview bytes')
    result = {'outputs': [{'path': str(output), 'size': output.stat().st_size}], 'output_root': str(task)}
    (task / 'extraction-result.json').write_text(json.dumps(result), encoding='utf-8')
    history.mkdir(parents=True, exist_ok=True)
    identifier = ('a' if not extra else 'b') * 32
    (history / (identifier + '.json')).write_text(json.dumps({
        'schema': 1, 'job_id': identifier, 'title': '预览对象 · 1 个文件', 'status': '成功',
        'request': {'operation': 'extract', 'output': str(cache), 'object_ids': {'fixture.ab': ['1']}},
        'output': str(cache), 'result': result, 'receipt_root': str(task), 'artifacts': [],
    }), encoding='utf-8')
    if extra:
        (cache / 'my-saved-copy.png').write_bytes(b'explicit user copy; keep')
    return output


@pytest.mark.parametrize('finish_first', [True, False])
def test_files_live_until_both_producer_and_viewer_release(tmp_path, finish_first):
    cache = PreviewCache(tmp_path / 'data')
    lease = cache.allocate('objects')
    original = lease.path / 'preview.txt'
    original.write_text('live', encoding='utf-8')
    callbacks = []
    lease.on_cleaned(lambda: callbacks.append('cleaned'))
    first, last = (lease.finish, lease.release) if finish_first else (lease.release, lease.finish)
    first()
    assert original.read_text(encoding='utf-8') == 'live'
    last()
    last()
    first()
    assert not lease.path.exists()
    assert callbacks == ['cleaned']


def test_browser_preview_waits_for_exit_and_running_producer_is_protected(tmp_path):
    cache = PreviewCache(tmp_path / 'data')
    browser = cache.allocate('reports')
    (browser.path / 'report.html').write_text('<html>offline</html>', encoding='utf-8')
    browser.defer_until_exit()
    browser.finish()
    browser.release()
    running = cache.allocate('objects')
    running.release()
    assert browser.path.exists()
    cache.shutdown()
    assert not browser.path.exists()
    assert running.path.exists(), 'shutdown must never remove an unfinished producer directory'
    running.finish()
    assert not running.path.exists()


def test_legacy_cleanup_requires_positive_history_and_complete_file_ownership(tmp_path):
    data, history = tmp_path / 'data', tmp_path / 'data' / 'queue'
    known = data / 'preview' / ('1' * 32)
    saved_copy = data / 'preview' / ('2' * 32)
    known_output = legacy_object(history, known)
    saved_output = legacy_object(history, saved_copy, extra=True)
    unknown = data / 'preview' / ('3' * 32)
    unknown.mkdir()
    (unknown / 'unknown.txt').write_text('keep', encoding='utf-8')
    manual = data / 'preview' / 'manual-user-folder'
    manual.mkdir()
    (manual / 'keep.txt').write_text('manual user file', encoding='utf-8')
    formal = tmp_path / 'exports'
    formal.mkdir()
    (formal / 'report.txt').write_text('formal report', encoding='utf-8')

    cache = PreviewCache(data, protected_roots=[formal])
    result = cache.cleanup_stale(history)
    assert not known_output.exists()
    assert saved_output.exists() and (saved_copy / 'my-saved-copy.png').exists()
    assert (unknown / 'unknown.txt').read_text(encoding='utf-8') == 'keep'
    assert (manual / 'keep.txt').read_text(encoding='utf-8') == 'manual user file'
    assert (formal / 'report.txt').read_text(encoding='utf-8') == 'formal report'
    assert str(known) in result['removed']
    assert str(saved_copy) in result['retained']
    assert str(manual) in result['retained']
    assert result['warnings'], 'unknown legacy files must be retained with an explanation'


def test_formal_output_inside_a_legacy_cache_is_preserved(tmp_path):
    data = tmp_path / 'data'
    directory = data / 'preview' / ('1' * 32)
    output = legacy_object(data / 'queue', directory)
    cache = PreviewCache(data, protected_roots=[directory])
    result = cache.cleanup_stale(data / 'queue')
    assert output.exists()
    assert not result['removed']


def test_active_other_process_is_skipped_then_crash_cache_is_reclaimed(tmp_path):
    data = tmp_path / 'data'
    script = '''
import sys, time
from PySide6.QtCore import QCoreApplication
from arknights_unpacker.ui.preview_cache import PreviewCache
app = QCoreApplication([])
cache = PreviewCache(sys.argv[1])
lease = cache.allocate('objects')
(lease.path / 'preview.txt').write_text('held by producer', encoding='utf-8')
print(lease.path, flush=True)
time.sleep(30)
'''
    env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[2] / 'src')}
    process = subprocess.Popen([sys.executable, '-X', 'utf8', '-c', script, str(data)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', env=env)
    try:
        active_path = Path(process.stdout.readline().strip())
        assert active_path.is_dir(), process.stderr.read() if process.poll() is not None else 'no live directory'
        cache = PreviewCache(data)
        before = cache.cleanup_stale(data / 'queue')
        assert str(active_path) in before['retained']
        assert (active_path / 'preview.txt').exists()
    finally:
        process.terminate()
        process.wait(timeout=10)
    after = cache.cleanup_stale(data / 'queue')
    assert str(active_path) in after['removed']
    assert not active_path.exists()


def test_linked_directory_is_retained_without_touching_target(tmp_path):
    data, history = tmp_path / 'data', tmp_path / 'data' / 'queue'
    directory = data / 'preview' / ('1' * 32)
    legacy_object(history, directory)
    outside = tmp_path / 'outside'
    outside.mkdir()
    source = outside / 'keep.txt'
    source.write_text('never follow a junction', encoding='utf-8')
    link = directory / 'unexpected-link'
    if os.name == 'nt':
        completed = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(link), str(outside)],
                                   capture_output=True, text=True)
        if completed.returncode:
            pytest.skip('Junction creation is unavailable on this host')
    else:
        link.symlink_to(outside, target_is_directory=True)
    result = PreviewCache(data).cleanup_stale(history)
    assert str(directory) in result['retained']
    assert source.read_text(encoding='utf-8') == 'never follow a junction'
    assert directory.exists()


def test_delete_error_keeps_preview_and_can_retry_on_shutdown(tmp_path, monkeypatch):
    from arknights_unpacker.ui import preview_cache
    cache = PreviewCache(tmp_path / 'data')
    lease = cache.allocate('objects')
    (lease.path / 'preview.txt').write_text('retry later', encoding='utf-8')
    actual = preview_cache.shutil.rmtree
    monkeypatch.setattr(preview_cache.shutil, 'rmtree', lambda _: (_ for _ in ()).throw(PermissionError('held open')))
    lease.finish()
    lease.release()
    assert lease.path.exists()
    assert cache.warnings
    monkeypatch.setattr(preview_cache.shutil, 'rmtree', actual)
    cache.shutdown()
    assert not lease.path.exists()


def test_legacy_report_manifest_proves_every_file_and_keeps_modified_reports(tmp_path):
    data = tmp_path / 'data'
    history = data / 'queue'
    history.mkdir(parents=True)
    paths = []
    for number in ('1', '2'):
        cache = data / 'previews' / (number * 32)
        task = cache / 'report-20261020-120000-0123456789'
        output = task / 'reports' / 'report.html'
        output.parent.mkdir(parents=True)
        output.write_bytes(b'<html>original</html>')
        manifest = task / 'manifest.json'
        manifest.write_text(json.dumps({'artifacts': [{'path': 'reports/report.html', 'format': 'html',
            'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}]}), encoding='utf-8')
        identifier = number * 32
        (history / (identifier + '.json')).write_text(json.dumps({
            'schema': 1, 'job_id': identifier, 'title': '预览选中资料', 'output': str(cache), 'status': '成功',
            'request': {'operation': 'report', 'preview': True, 'output': str(cache)},
            'artifacts': [{'path': str(output), 'format': 'html'}],
            'result': {'report_manifests': [str(manifest)]},
        }), encoding='utf-8')
        paths.append((cache, output))
    paths[1][1].write_bytes(b'<html>modified</html>')
    result = PreviewCache(data).cleanup_stale(history)
    assert str(paths[0][0]) in result['removed']
    assert not paths[0][0].exists()
    assert paths[1][1].read_bytes() == b'<html>modified</html>'
    assert str(paths[1][0]) in result['retained']


def test_startup_permission_failure_is_diagnostic_and_does_not_block_use(tmp_path, monkeypatch):
    data = tmp_path / 'data'
    directory = data / 'preview'
    directory.mkdir(parents=True)
    actual_iterdir = Path.iterdir

    def restricted_iterdir(path):
        if path == directory:
            raise PermissionError('preview root temporarily held')
        return actual_iterdir(path)

    monkeypatch.setattr(Path, 'iterdir', restricted_iterdir)
    cache = PreviewCache(data)
    result = cache.cleanup_stale(data / 'queue')
    assert not result['removed'] and result['warnings']
    assert 'temporarily held' in result['warnings'][0]
