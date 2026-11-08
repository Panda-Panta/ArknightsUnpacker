import json
import time
import pytest
from pathlib import Path
from PySide6.QtGui import QImage
from PySide6.QtCore import Qt
from arknights_unpacker.contracts import ReportArtifact, ExtractionResult, CancelToken
from arknights_unpacker.ui.jobs import JobQueue
from arknights_unpacker.ui.job_history import extraction_completion
from test_explorer import make_window, wait_idle


def test_successful_report_history_can_preview_after_new_window(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    png = tmp_path / 'retained-report.png'
    image = QImage(120, 240, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.white)
    assert image.save(str(png))
    services.load_data(str(tmp_path))
    services.export = lambda *args, **kw: [ReportArtifact(str(png), 'png')]
    window.export('operators', ['char_fixture'])
    wait_idle(qtbot, window)
    window.close()
    reopened, fresh_services = make_window(qtbot, tmp_path)
    assert not reopened.queue.busy
    assert not fresh_services.calls
    assert reopened.queue.jobs[0].status == '成功'
    reopened.show_task_history().table.selectRow(0)
    reopened.jobs.preview_artifacts()
    assert reopened._dialogs[-1].image.pixmap().width() == 90
    record = json.loads(next((services.data_root / 'queue').glob('*.json')).read_text(encoding='utf-8'))
    assert record['request']['operation'] == 'report'
    assert 'call' not in record and 'done' not in record


def test_active_and_queued_tasks_restore_interrupted_without_running(qtbot, tmp_path):
    queue = JobQueue(history_root=tmp_path / 'queue')
    queue.paused = True
    calls = []
    queued = queue.submit('等待任务', lambda **kw: calls.append(1), request={'operation': 'scan', 'root': str(tmp_path)})
    running = queue.submit('运行任务', lambda **kw: calls.append(2), request={'operation': 'scan', 'root': str(tmp_path)})
    running.status = '运行中'
    running.started_at = time.time()
    queue.history.save(running)
    restored = JobQueue(history_root=tmp_path / 'queue')
    qtbot.wait(20)
    assert len(restored.jobs) == 2
    assert all('已中断' in job.status for job in restored.jobs)
    assert not restored.busy and not calls


def test_recovered_extraction_reads_own_receipt_and_only_unfinished_objects(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    window.queue.paused = True
    source = str(tmp_path / 'fixture.ab')
    output = tmp_path / 'exports'
    receipt = output / 'extract-own-task'
    receipt.mkdir(parents=True)
    retained = receipt / 'successful.png'
    retained.write_bytes(b'kept-output')
    request = {'operation': 'extract', 'root': '', 'paths': [source], 'output': str(output),
               'kinds': ['image'], 'object_ids': {}, 'mode': 'raw'}
    job = window.queue.submit('中断解包', lambda **kw: None, output=str(output), request=request)
    job.status, job.started_at, job.receipt_root = '运行中', time.time() - 2, str(receipt)
    window.queue.history.save(job)
    result = {'status': 'partial', 'outputs': [{'source': source, 'object_id': '1', 'path': str(retained)}],
              'errors': [{'source': source, 'object_id': '2', 'error': '模拟失败'}], 'skipped': []}
    (receipt / 'extraction-result.json').write_text(json.dumps(result), encoding='utf-8')
    # An unrelated shared-root receipt must never mark the whole source complete.
    (output / 'extraction-result.json').write_text(json.dumps({**result, 'status': 'succeeded', 'errors': []}), encoding='utf-8')
    window.close()
    reopened, fresh = make_window(qtbot, tmp_path)
    assert not fresh.calls and '已中断' in reopened.queue.jobs[0].status
    fresh.objects = lambda path, **kw: [{'id': '1'}, {'id': '2'}, {'id': '3'}]
    calls = []
    def extract(paths, target, **kw):
        calls.append((paths, target, kw['kinds'], kw['object_ids'], kw['mode']))
        return ExtractionResult()
    fresh.extract = extract
    reopened.queue.retry(0)
    wait_idle(qtbot, reopened)
    assert calls == [([source], str(output), ['image'], {source: ['2', '3']}, 'raw')]
    assert retained.read_bytes() == b'kept-output'


def test_only_completion_events_prove_crash_checkpoint_and_groups_require_files(tmp_path):
    first = tmp_path / 'first.png'
    second = tmp_path / 'second.json'
    first.write_bytes(b'ok')
    second.write_bytes(b'ok')
    events = [{'kind': 'image', 'source': 'bundle', 'object_id': '1', 'path': str(first)},
              {'kind': 'object_complete', 'source': 'bundle', 'object_id': '1'},
              {'kind': 'text_raw', 'source': 'bundle', 'object_id': '2', 'path': str(second)}]
    sources, objects = extraction_completion([{'events': events}])
    assert objects == {'bundle': {'1'}} and not sources
    group = [{'kind': 'spine', 'source': 'group', 'object_id': '10', 'path': str(first)},
             {'kind': 'spine', 'source': 'group', 'object_id': '10', 'path': str(second)},
             {'kind': 'object_complete', 'source': 'group', 'group_id': '10', 'object_ids': ['10', '11', '12']}]
    assert extraction_completion([{'events': group}])[1] == {'group': {'10', '11', '12'}}
    second.unlink()
    assert extraction_completion([{'events': group}])[1] == {}


def test_receipt_and_completed_artifacts_survive_worker_failure(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    source = str(tmp_path / 'bundle.ab')
    receipt = tmp_path / 'exports/extract-own'
    receipt.mkdir(parents=True)
    output = receipt / 'kept.png'
    image = QImage(100, 100, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.white)
    image.save(str(output))
    def interrupted(paths, base, **kw):
        kw['emit']({'message': '开始任务'})
        kw['emit']({'type': 'progress', 'stage': 'extraction_task', 'output_root': str(receipt), 'request_id': 'fixture'})
        kw['emit']({'kind': 'image', 'source': source, 'object_id': '1', 'path': str(output)})
        kw['emit']({'kind': 'object_complete', 'source': source, 'object_id': '1'})
        raise RuntimeError('模拟工作进程崩溃')
    services.extract = interrupted
    window.extract([source])
    wait_idle(qtbot, window)
    assert window.queue.jobs[0].receipt_root == str(receipt)
    window.close()
    reopened, fresh = make_window(qtbot, tmp_path)
    assert not fresh.calls and reopened.queue.jobs[0].status == '失败'
    reopened.show_task_history().table.selectRow(0)
    reopened.jobs.preview_artifacts()
    assert reopened._dialogs[-1].image.pixmap().width() == 75
    records = reopened.queue.history.evidence(reopened.queue.jobs[0])
    assert extraction_completion(records)[1] == {source: {'1'}}


def test_partial_object_output_missing_one_file_is_never_skipped(tmp_path):
    present = tmp_path / 'raw.bytes'
    missing = tmp_path / 'decoded.json'
    present.write_bytes(b'raw')
    result = {'status': 'partial', 'outputs': [
        {'source': 'bundle', 'object_id': '1', 'path': str(present)},
        {'source': 'bundle', 'object_id': '1', 'path': str(missing)}],
        'errors': [{'source': 'bundle', 'object_id': '2'}]}
    assert extraction_completion([{'result': result}]) == (set(), {})


def test_truncated_retained_files_are_not_completion_evidence(tmp_path):
    artifact = tmp_path / 'truncated.png'
    artifact.write_bytes(b'bad')
    output = {'source': 'bundle', 'object_id': '1', 'path': str(artifact), 'size': 1024}
    events = [output, {'kind': 'object_complete', 'source': 'bundle', 'object_id': '1'}]
    assert extraction_completion([{'events': events}]) == (set(), {})
    result = {'status': 'succeeded', 'outputs': [output]}
    assert extraction_completion([{'result': result}]) == (set(), {})
    del output['size']
    assert extraction_completion([{'result': result}])[0] == {'bundle'}  # Legacy presence-only receipt.


def test_recover_load_data_syncs_old_installation_root(qtbot, tmp_path):
    from arknights_unpacker.contracts import GameInstallation
    old, current = tmp_path / 'old-game', tmp_path / 'current-game'
    old.mkdir()
    current.mkdir()
    window, _ = make_window(qtbot, tmp_path)
    window.queue.paused = True
    window.queue.submit('旧安装解析', lambda **kw: None,
                        request={'operation': 'load_data', 'root': str(old), 'locale': 'unknown'})
    window.close()
    reopened, services = make_window(qtbot, tmp_path)
    reopened.root_edit.setText(str(current))
    reopened.explorer.set_root(str(current))
    original = services.load_data
    def load(root, **kw):
        services.installation = GameInstallation(Path(root), 'old-profile')
        return original(root, **kw)
    services.load_data = load
    reopened.queue.retry(0)
    wait_idle(qtbot, reopened)
    assert Path(reopened.root_edit.text()) == old
    assert reopened.explorer.root == old


def test_history_report_retry_requires_matching_loaded_snapshot(qtbot, tmp_path):
    window, _ = make_window(qtbot, tmp_path)
    window.queue.paused = True
    job = window.queue.submit('历史报告', lambda **kw: None, request={'operation': 'report', 'snapshot_id': 'old'})
    job.status = '失败'
    window.queue.history.save(job)
    window.close()
    reopened, services = make_window(qtbot, tmp_path)
    reopened.queue.retry(0)
    assert len(reopened.queue.jobs) == 1
    assert '请先解析' in reopened.statusBar().currentMessage()
    services.load_data(str(tmp_path))
    reopened.queue.retry(0)
    assert len(reopened.queue.jobs) == 1
    assert '快照与历史报告任务不同' in reopened.statusBar().currentMessage()


def test_pause_finishes_current_task_and_requires_continue_for_next(qtbot):
    queue = JobQueue()
    calls = []
    def first(**kw):
        time.sleep(.04)
        calls.append('first')
    queue.submit('当前', first)
    queue.submit('之后', lambda **kw: calls.append('second'))
    queue.toggle_pause()
    qtbot.waitUntil(lambda: not queue.busy, timeout=3000)
    assert calls == ['first'] and queue.jobs[1].status == '排队中'
    queue.toggle_pause()
    qtbot.waitUntil(lambda: not queue.busy and len(calls) == 2, timeout=3000)
    assert calls == ['first', 'second']


def test_cancelled_report_keeps_every_successful_page_and_bound_manifest(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    services.load_data(str(tmp_path))
    task = tmp_path / 'exports/report-fixture'
    directory = task / 'reports'
    directory.mkdir(parents=True)
    pages = []
    for index in range(2):
        path = directory / f'page-{index + 1}.png'
        image = QImage(120, 240, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.white)
        assert image.save(str(path))
        pages.append(path)
    manifest = task / 'manifest.json'
    def cancelled_report(*args, **kw):
        kw['emit']({'kind': 'progress', 'message': '开始渲染'})
        try:
            # All events arrive in one throttle interval, then no success list returns.
            for path in pages:
                kw['emit']({'kind': 'progress', 'stage': 'report_export', 'format': 'png',
                            'status': 'succeeded', 'path': str(path), 'message': '已保存页'})
            kw['cancel'].cancel()
            kw['cancel'].check()
        finally:
            manifest.write_text(json.dumps({'status': 'cancelled', 'complete': False, 'artifacts':
                [{'path': str(path.relative_to(task)), 'format': 'png'} for path in pages]}), encoding='utf-8')
    services.export = cancelled_report
    window.export('operators', ['char_fixture'])
    wait_idle(qtbot, window)
    job = window.queue.jobs[0]
    assert job.status == '已取消' and len(job.artifacts) == 2
    assert job.result['report_manifests'] == [str(manifest)]
    events = [json.loads(line) for line in (services.data_root / 'queue' / (job.job_id + '.events.jsonl')).read_text(encoding='utf-8').splitlines()]
    assert len([event for event in events if event.get('stage') == 'report_export']) == 2
    window.close()
    reopened, fresh = make_window(qtbot, tmp_path)
    assert not fresh.calls and reopened.queue.jobs[0].status == '已取消'
    reopened.show_task_history().table.selectRow(0)
    reopened.jobs.preview_artifacts()
    assert reopened._dialogs[-1].pages.count() == 2
    assert not json.loads(manifest.read_text(encoding='utf-8'))['complete']


@pytest.mark.parametrize('changed', ['snapshot', 'installation'])
def test_report_recovery_rechecks_binding_after_prior_queued_task(qtbot, tmp_path, changed):
    from types import SimpleNamespace
    from arknights_unpacker.contracts import GameInstallation
    window, services = make_window(qtbot, tmp_path)
    original_root, other_root = tmp_path / 'original-game', tmp_path / 'other-game'
    original_root.mkdir()
    other_root.mkdir()
    services.load_data(str(original_root))
    services.installation = GameInstallation(original_root, 'original')
    request = {'operation': 'report', 'root': str(original_root), 'snapshot_id': services.gamedata.snapshot_id,
               'operators': ['char_fixture'], 'modules': [], 'output': str(tmp_path / 'exports'), 'formats': ['png']}
    call, done = window.prepare_recovery(SimpleNamespace(request=request))
    window.queue.paused = True
    def earlier_task(**kw):
        if changed == 'snapshot':
            services.gamedata.snapshot_id = 'new-snapshot'
        else:
            # Content IDs can be equal while the installation provenance differs.
            services.installation = GameInstallation(other_root, 'other')
    window.queue.submit('先前解析', earlier_task)
    window.queue.submit('恢复报告', call, done, request=request)
    window.queue.toggle_pause()
    wait_idle(qtbot, window)
    assert not any(item[0] == 'export' for item in services.calls)
    assert window.queue.jobs[-1].status == '失败'
    assert ('快照与历史报告任务不同' if changed == 'snapshot' else '安装与历史报告来源不同') in window.queue.jobs[-1].last_error
