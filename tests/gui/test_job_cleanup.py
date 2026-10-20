import json

import pytest
from PySide6.QtWidgets import QPushButton

from arknights_unpacker.contracts import GameDataSnapshot
from arknights_unpacker.ui.job_history import JobHistory
from arknights_unpacker.ui.jobs import Job, JobQueue, JobsView


def saved_job(history, number, status='成功', **kwargs):
    job = Job(f'任务 {number}', None, status=status, created_at=float(number), **kwargs)
    history.save(job)
    history.append_event(job, {'kind': 'object_complete', 'object_id': str(number)})
    return job


def test_startup_retains_twenty_recent_successes_without_touching_outputs(qtbot, tmp_path):
    history = JobHistory(tmp_path / 'queue')
    formal = tmp_path / 'exports' / 'kept.png'
    formal.parent.mkdir()
    formal.write_bytes(b'formal-report-output')
    receipt = formal.parent / 'extraction-result.json'
    receipt.write_text('{"outputs": ["kept.png"]}', encoding='utf-8')
    other = history.root / 'notes.json'
    other.write_text('user notes', encoding='utf-8')
    jobs = [saved_job(history, index, output=str(formal.parent), receipt_root=str(formal.parent),
                      artifacts=[{'path': str(formal), 'format': 'png'}]) for index in range(25)]

    queue = JobQueue(history_root=history.root)

    assert [job.job_id for job in queue.jobs] == [job.job_id for job in jobs[-20:]]
    assert len(list(history.root.glob('*.events.jsonl'))) == 20
    assert all(not (history.root / (job.job_id + '.json')).exists() for job in jobs[:5])
    assert formal.read_bytes() == b'formal-report-output'
    assert json.loads(receipt.read_text(encoding='utf-8')) == {'outputs': ['kept.png']}
    assert other.read_text(encoding='utf-8') == 'user notes'
    # The retained recent task still supports the established restart preview path.
    reopened = JobQueue(history_root=history.root)
    assert len(reopened.jobs) == 20 and reopened.jobs[-1].artifacts[0]['path'] == str(formal)


def test_automatic_cleanup_preserves_non_successes_and_recursive_recovery_ancestors(qtbot, tmp_path):
    history = JobHistory(tmp_path / 'queue')
    oldest = saved_job(history, 0)
    ancestor = saved_job(history, 1, ancestors=[oldest.job_id])
    jobs = [oldest, ancestor, *[saved_job(history, i) for i in range(2, 25)]]
    protected = [saved_job(history, 100 + i, status, last_error='保留诊断',
                           ancestors=[ancestor.job_id] if i == 0 else [])
                 for i, status in enumerate(['失败', '已取消', '部分完成（查看诊断）',
                                             '结果处理失败', '已中断（等待手动重试）', '运行中', '排队中'])]
    queue = JobQueue(history_root=history.root)

    assert {job.job_id for job in queue.jobs} == {job.job_id for job in [*jobs[-20:], oldest, ancestor, *protected]}
    assert all((history.root / (job.job_id + '.events.jsonl')).exists() for job in [oldest, ancestor, *protected])
    assert all(job.last_error == '保留诊断' for job in queue.jobs if job.job_id in {item.job_id for item in protected})
    assert not queue.busy


def test_completion_enforces_twenty_and_emits_settled_after_worker_release(qtbot, tmp_path):
    queue = JobQueue(history_root=tmp_path / 'queue')
    calls, settled = [], []

    def on_settled(job):
        settled.append((job.job_id, job.status, queue.worker, queue.active))

    queue.settled.connect(on_settled)
    submitted = [queue.submit(str(index), lambda number=index, **kw: calls.append(number)) for index in range(25)]
    qtbot.waitUntil(lambda: len(calls) == 25 and not queue.busy, timeout=5000)

    assert calls == list(range(25))
    assert [job.job_id for job in queue.jobs] == [job.job_id for job in submitted[-20:]]
    assert [item[0] for item in settled] == [job.job_id for job in submitted]
    assert all(status == '成功' and worker is None and active is None for _, status, worker, active in settled)
    assert len(list(queue.history.root.glob('*.json'))) == 20


def test_manual_clear_button_preserves_active_pending_and_failed_jobs(qtbot, tmp_path):
    queue = JobQueue(history_root=tmp_path / 'queue')
    queue.paused = True
    jobs = [queue.submit(title, lambda **kw: None) for title in ['可清成功', '正在处理结果', '失败任务', '待运行']]
    for job, status in zip(jobs, ['成功', '成功', '失败', '排队中']):
        job.status = status
        queue.history.save(job)
    queue.active = jobs[1]  # A succeeded signal can precede QThread.finished.
    view = JobsView(queue)
    qtbot.addWidget(view)

    button = next(item for item in view.findChildren(QPushButton) if item.text() == '清理成功任务')
    button.click()

    assert queue.jobs == jobs[1:]
    assert view.table.rowCount() == 3
    assert not (queue.history.root / (jobs[0].job_id + '.json')).exists()
    assert all((queue.history.root / (job.job_id + '.json')).exists() for job in jobs[1:])
    queue.active = None


def test_forget_finished_is_exact_and_preserves_retained_recovery_dependencies(qtbot, tmp_path):
    queue = JobQueue(history_root=tmp_path / 'queue')
    queue.paused = True
    parent = queue.submit('需保留依据', lambda **kw: None)
    failed = queue.submit('预览失败', lambda **kw: None)
    cancelled = queue.submit('预览取消', lambda **kw: None)
    pending = queue.submit('待运行', lambda **kw: None, ancestors=[parent.job_id])
    active = queue.submit('活动', lambda **kw: None)
    for job, status in [(parent, '成功'), (failed, '失败'), (cancelled, '已取消'), (active, '运行中')]:
        job.status = status
        queue.history.save(job)
    queue.active = active

    removed = queue.forget_finished([parent.job_id, failed.job_id, cancelled.job_id, pending.job_id, active.job_id, '../outside'])

    assert set(removed) == {failed.job_id, cancelled.job_id}
    assert queue.jobs == [parent, pending, active]
    assert all((queue.history.root / (job.job_id + '.json')).exists() for job in queue.jobs)
    assert all(not (queue.history.root / (job.job_id + '.json')).exists() for job in [failed, cancelled])
    queue.active = None


def test_shutdown_settles_each_cancelled_pending_job_even_when_callbacks_remove_it(qtbot, tmp_path):
    queue = JobQueue(history_root=tmp_path / 'queue')
    queue.paused = True
    submitted = [queue.submit(str(index), lambda **kw: None) for index in range(3)]
    settled = []

    def forget(job):
        settled.append(job)
        queue.forget_finished([job.job_id])

    queue.settled.connect(forget)
    queue.shutdown()

    assert settled == submitted
    assert all(job.status == '已取消' for job in settled)
    assert queue.jobs == []
    assert list(queue.history.root.iterdir()) == []


def test_failed_record_delete_preserves_its_recovery_ancestors(qtbot, tmp_path, monkeypatch):
    queue = JobQueue(history_root=tmp_path / 'queue')
    queue.paused = True
    parent = queue.submit('恢复依据', lambda **kw: None)
    child = queue.submit('恢复任务', lambda **kw: None, ancestors=[parent.job_id])
    parent.status, child.status = '成功', '失败'
    queue.history.save(parent)
    queue.history.save(child)
    original = queue.history.remove

    def blocked_delete(job_id):
        if job_id == child.job_id:
            raise PermissionError('测试：诊断文件被占用')
        original(job_id)

    monkeypatch.setattr(queue.history, 'remove', blocked_delete)
    assert queue.forget_finished([parent.job_id, child.job_id]) == []
    assert queue.jobs == [parent, child]
    assert all((queue.history.root / (job.job_id + '.json')).exists() for job in queue.jobs)
    assert '诊断文件被占用' in queue.history.warnings[-1]


def test_history_delete_rejects_non_id_paths_and_reparse_leaf(tmp_path):
    history = JobHistory(tmp_path / 'queue')
    outside = tmp_path / 'outside.json'
    outside.write_text('protected', encoding='utf-8')
    with pytest.raises(ValueError):
        history.remove('../outside')
    assert outside.read_text(encoding='utf-8') == 'protected'
    job_id = 'a' * 32
    link = history.root / (job_id + '.json')
    try:
        link.symlink_to(outside)
    except OSError as error:
        pytest.skip(f'This environment cannot create a symbolic link: {error}')
    with pytest.raises((ValueError, OSError)):
        history.remove(job_id)
    assert link.is_symlink() and outside.read_text(encoding='utf-8') == 'protected'


@pytest.mark.parametrize('complete', [False, True])
def test_gamedata_completion_classification_keeps_partial_diagnostics_after_pruning(qtbot, tmp_path, complete):
    queue = JobQueue(history_root=tmp_path / 'queue')
    settled = []
    queue.settled.connect(lambda job: settled.append((job.job_id, job.status)))
    diagnostic = '缺少 building_data，资料未完整解析'
    snapshot = GameDataSnapshot('data-fixture', '1', '1', {}, diagnostics=[diagnostic] if not complete else [], complete=complete)
    parsed = queue.submit('解析核心资料', lambda **kw: snapshot,
                          request={'operation': 'load_data', 'root': str(tmp_path)})
    qtbot.waitUntil(lambda: len(settled) == 1 and not queue.busy, timeout=3000)
    expected_status = '成功' if complete else '部分解析（查看诊断）'
    assert settled == [(parsed.job_id, expected_status)]

    for index in range(21):
        queue.submit(f'后续成功 {index}', lambda **kw: None)
    qtbot.waitUntil(lambda: len(settled) == 22 and not queue.busy, timeout=5000)
    assert sum(job.status == '成功' for job in queue.jobs) == 20
    metadata = queue.history.root / (parsed.job_id + '.json')
    if complete:
        assert parsed not in queue.jobs and not metadata.exists()
    else:
        assert parsed in queue.jobs
        record = json.loads(metadata.read_text(encoding='utf-8'))
        assert record['status'] == expected_status
        assert diagnostic in record['last_error']
        reopened = JobQueue(history_root=queue.history.root)
        retained = next(job for job in reopened.jobs if job.job_id == parsed.job_id)
        assert retained.status == expected_status and diagnostic in retained.last_error
