"""Routine reads share the worker queue while staying out of the task page."""
import json
from pathlib import Path
import threading

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QPushButton

from arknights_unpacker.ui.job_history import JobHistory
from arknights_unpacker.ui.jobs import Job, JobQueue, JobsView
from test_explorer import make_window, wait_idle


def named_button(view, text):
    return next(button for button in view.findChildren(QPushButton) if button.text() == text)


def test_hidden_running_read_has_no_table_log_progress_or_cancel_target(qtbot, tmp_path):
    queue = JobQueue(history_root=tmp_path / 'queue')
    view = JobsView(queue)
    qtbot.addWidget(view)
    started, release = threading.Event(), threading.Event()
    all_messages, worker_threads = [], []
    queue.message.connect(all_messages.append)

    def read(**kw):
        worker_threads.append(threading.get_ident())
        kw['emit']({'message': 'internal-read-progress', 'current': 1, 'total': 3})
        started.set()
        assert release.wait(5)

    internal = queue.submit('内部读取', read, show_in_tasks=False)
    try:
        qtbot.waitUntil(started.is_set)
        qtbot.wait(20)
        assert queue.active is internal and queue.busy
        assert queue.visible_jobs == [] and view.table.rowCount() == 0
        assert view.progress.maximum() == 100 and view.progress.value() == 0
        assert not named_button(view, '取消当前任务').isEnabled()
        named_button(view, '取消当前任务').click()
        assert not internal.token.cancelled
        assert not view.log.toPlainText()
        assert any('internal-read-progress' in message for message in all_messages)
        visible = queue.submit('正式导出', lambda **kw: kw['emit']({'message': 'formal-export-progress'}))
        assert queue.visible_jobs == [visible] and view.table.rowCount() == 1
        assert view.table.item(0, 0).text() == '正式导出'
    finally:
        release.set()
        qtbot.waitUntil(lambda: not queue.busy and all(job.status != '排队中' for job in queue.jobs), timeout=5000)
    assert worker_threads != [threading.get_ident()]
    assert 'internal-read-progress' not in view.log.toPlainText()
    assert 'formal-export-progress' in view.log.toPlainText()
    assert internal.status == '成功' and internal in queue.jobs


def test_hidden_failure_keeps_global_error_and_history_without_task_page_noise(qtbot, tmp_path):
    queue = JobQueue(history_root=tmp_path / 'queue')
    view = JobsView(queue)
    qtbot.addWidget(view)
    messages = []
    queue.message.connect(messages.append)

    def fail(**kw):
        raise RuntimeError('internal-reader-error')

    job = queue.submit('查看资料 · missing', fail, show_in_tasks=False)
    qtbot.waitUntil(lambda: not queue.busy, timeout=3000)
    assert job.status == '失败' and 'internal-reader-error' in job.last_error
    assert any('internal-reader-error' in message for message in messages)
    assert view.table.rowCount() == 0 and not view.log.toPlainText()
    restored = JobQueue(history_root=queue.history.root)
    assert restored.jobs[0].job_id == job.job_id and not restored.visible_jobs


def test_history_restores_explicit_visibility_and_only_precise_legacy_internal_titles(qtbot, tmp_path):
    history = JobHistory(tmp_path / 'queue')
    explicit_hidden = Job('未知类型读取', None, status='成功', show_in_tasks=False)
    explicit_visible = Job('查看资料 · 用户明确创建的任务', None, status='成功', show_in_tasks=True)
    for job in (explicit_hidden, explicit_visible):
        history.save(job)
    hidden_titles = ['查看资料 · char_fixture', '读取内部对象 · sample.ab', '读取上次扫描与解析结果']
    visible_titles = ['查看资料总结', '读取内部对象', '读取上次扫描与解析结果副本', '正式导出']
    legacy = []
    for index, title in enumerate([*hidden_titles, *visible_titles]):
        job = Job(title, None, status='成功', created_at=index)
        history.save(job)
        path = history.root / (job.job_id + '.json')
        payload = json.loads(path.read_text('utf-8'))
        payload.pop('show_in_tasks')
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        legacy.append(job)
    output = tmp_path / 'unchanged-report.png'
    output.write_bytes(b'formal-output')
    restored = JobQueue(history_root=history.root)
    assert {job.job_id for job in restored.visible_jobs} == {explicit_visible.job_id, *[job.job_id for job in legacy[3:]]}
    assert len(restored.jobs) == 9 and len(list(history.root.glob('*.json'))) == 9
    assert all(isinstance(json.loads(path.read_text('utf-8'))['show_in_tasks'], bool)
               for path in history.root.glob('*.json'))
    assert output.read_bytes() == b'formal-output'


def test_filtered_second_row_actions_use_job_identity_and_preserve_selection(qtbot, monkeypatch, tmp_path):
    queue = JobQueue(history_root=tmp_path / 'queue')
    queue.paused = True
    hidden = queue.submit('hidden first', lambda **kw: None, show_in_tasks=False)
    first = queue.submit('first visible', lambda **kw: None, output=str(tmp_path / 'first'))
    second_hidden = queue.submit('hidden middle', lambda **kw: None, show_in_tasks=False)
    second = queue.submit('second visible', lambda **kw: None, output=str(tmp_path / 'second'))
    for job in queue.jobs:
        job.status = '失败'
        queue.history.save(job)
    second.artifacts = [{'path': str(tmp_path / 'second.png'), 'format': 'png'}]
    queue.history.save(second)
    view = JobsView(queue)
    qtbot.addWidget(view)
    view.table.selectRow(1)
    previews, opened = [], []
    view.artifacts_requested.connect(previews.append)
    monkeypatch.setattr(QDesktopServices, 'openUrl', lambda url: opened.append(url.toLocalFile()) or True)
    view.preview_artifacts()
    view.open_output()
    assert previews == [second.artifacts] and [Path(path) for path in opened] == [Path(second.output)]
    assert queue.forget_finished([hidden.job_id]) == [hidden.job_id]
    assert view.table.item(view.table.currentRow(), 0).text() == second.title
    view.retry()
    retried = queue.jobs[-1]
    assert retried.title == second.title + '（重试）' and retried.ancestors == [second.job_id]
    assert retried.show_in_tasks and first in queue.jobs and second_hidden in queue.jobs
    assert (queue.history.root / (second_hidden.job_id + '.json')).exists()


def test_success_retention_has_separate_visible_and_internal_budgets_and_protects_recovery(qtbot, tmp_path):
    history = JobHistory(tmp_path / 'queue')
    visible, hidden = [], []
    for index in range(25):
        for show, jobs in ((True, visible), (False, hidden)):
            job = Job(f'{show}-{index}', None, status='成功', created_at=index, show_in_tasks=show)
            history.save(job)
            history.append_event(job, {'kind': 'object_complete', 'object_id': str(index)})
            jobs.append(job)
    failed = Job('failed recovery', None, status='失败', created_at=100,
                 ancestors=[visible[0].job_id, hidden[0].job_id])
    history.save(failed)
    formal = tmp_path / 'kept-output.txt'
    formal.write_bytes(b'kept formal output')
    queue = JobQueue(history_root=history.root)
    expected_visible = {job.job_id for job in [visible[0], *visible[-20:]]}
    expected_hidden = {job.job_id for job in [hidden[0], *hidden[-20:]]}
    assert {job.job_id for job in queue.visible_jobs if job.status == '成功'} == expected_visible
    assert {job.job_id for job in queue.jobs if not job.show_in_tasks} == expected_hidden
    assert any(job.job_id == failed.job_id for job in queue.jobs)
    assert queue.clear_successful() == 20
    assert {job.job_id for job in queue.jobs if not job.show_in_tasks} == expected_hidden
    assert any(job.job_id == visible[0].job_id for job in queue.jobs)
    assert formal.read_bytes() == b'kept formal output'


@pytest.mark.parametrize('kind', ['operators', 'modules'])
def test_entity_profile_remains_a_background_read_without_task_row_or_badge(qtbot, tmp_path, kind):
    window, services = make_window(qtbot, tmp_path)
    services.load_data(str(tmp_path))
    window.data_loaded(services.gamedata)
    threads = []
    method_name = 'operator_profile' if kind == 'operators' else 'module_profile'
    original = getattr(services, method_name)

    def profile(*args):
        threads.append(threading.get_ident())
        return original(*args)

    setattr(services, method_name, profile)
    view = getattr(window, kind)
    view.table.selectRow(0)
    wait_idle(qtbot, window)
    job = window.queue.jobs[-1]
    assert job.title.startswith('查看资料 · ') and not job.show_in_tasks
    assert not window.queue.visible_jobs and window.show_task_history().table.rowCount() == 0
    assert '交互测试' in view.details.toPlainText()
    assert threads and all(identity != threading.get_ident() for identity in threads)
    assert window.tabs.indexOf(window.jobs) == -1


def test_visible_pending_and_active_tasks_keep_records_and_cancel_action(qtbot, tmp_path):
    window, _ = make_window(qtbot, tmp_path)
    started, release = threading.Event(), threading.Event()

    def run(**kw):
        started.set()
        assert release.wait(5)

    active = window.queue.submit('可见主动预览', run, request={'operation': 'report', 'preview': True})
    try:
        qtbot.waitUntil(started.is_set)
        pending = window.queue.submit('可见正式导出', lambda **kw: None)
        window.show_task_history()
        assert window.tabs.indexOf(window.jobs) == -1
        assert window.jobs.table.rowCount() == 2 and window.queue.visible_jobs == [active, pending]
        cancel = named_button(window.jobs, '取消当前任务')
        assert cancel.isEnabled()
        qtbot.mouseClick(cancel, Qt.MouseButton.LeftButton)
        assert active.token.cancelled and not pending.token.cancelled
    finally:
        release.set()
        wait_idle(qtbot, window)
    assert active.status == '已取消' and pending.status == '成功'
