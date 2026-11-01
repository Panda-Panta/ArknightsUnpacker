"""Interactive process reuse must preserve isolated task and cancellation state."""
import json
from pathlib import Path
import threading

import pytest

from arknights_unpacker.contracts import CancelToken, CancelledError, ExtractionRequest, as_jsonable
from arknights_unpacker.jobs import WorkerRunner


def test_interactive_requests_reuse_process_but_read_current_source_and_isolate_results(tmp_path):
    source = tmp_path / 'preview.json'
    source.write_text('{"version": 1}', encoding='utf-8')
    runner = WorkerRunner(tmp_path / 'workers')
    try:
        first = runner.run('objects', {'path': str(source)}, reusable=True)
        proc = runner._preview_server[0]
        source.write_text('{"version": 2}', encoding='utf-8')
        request = ExtractionRequest([str(source)], str(tmp_path / 'output'),
                                    kinds=['text'], object_ids={str(source): ['source']})
        result = runner.run('extract', as_jsonable(request), reusable=True)
        last = runner.run('objects', {'path': str(source)}, reusable=True)
        assert first == last
        assert runner._preview_server[0] is proc and proc.poll() is None
        assert Path(result['outputs'][0]['path']).read_text('utf-8') == '{"version": 2}'
        receipts = [json.loads(p.read_text('utf-8')) for p in runner.work_root.glob('*/result.json')]
        assert len(receipts) == 3
        assert all(item['status'] == 'succeeded' for item in receipts)
        runner.run('objects', {'path': str(source)})
        assert runner._preview_server[0] is proc
        assert len(list(runner.work_root.glob('*/result.json'))) == 4
    finally:
        processes = list(runner._active)
        runner.shutdown()
        assert all(p.poll() is not None for p in processes)


def test_interactive_failure_and_process_exit_do_not_poison_later_requests(tmp_path):
    source = tmp_path / 'text.json'
    source.write_text('fixture', encoding='utf-8')
    runner = WorkerRunner(tmp_path / 'workers')
    try:
        runner.run('objects', {'path': str(source)}, reusable=True)
        first = runner._preview_server[0]
        with pytest.raises(RuntimeError, match='missing'):
            runner.run('objects', {'path': str(tmp_path / 'missing.json')}, reusable=True)
        assert runner.run('objects', {'path': str(source)}, reusable=True)[0]['id'] == 'source'
        assert runner._preview_server[0] is first
        first.terminate()
        first.wait(timeout=3)
        assert runner.run('objects', {'path': str(source)}, reusable=True)[0]['name'] == source.name
        assert runner._preview_server[0] is not first
    finally:
        runner.shutdown()


def test_interactive_idle_exit_is_restarted_on_demand(tmp_path):
    source = tmp_path / 'text.json'
    source.write_text('fixture', encoding='utf-8')
    runner = WorkerRunner(tmp_path / 'workers')
    runner._preview_idle_timeout = 0.1
    try:
        runner.run('objects', {'path': str(source)}, reusable=True)
        first = runner._preview_server[0]
        first.wait(timeout=5)
        assert first.returncode == 0
        assert runner.run('objects', {'path': str(source)}, reusable=True)[0]['id'] == 'source'
        assert runner._preview_server[0] is not first
    finally:
        runner.shutdown()


def test_waiting_for_interactive_slot_can_be_cancelled_without_creating_a_task(tmp_path):
    runner = WorkerRunner(tmp_path / 'workers')
    token = CancelToken()
    failures = []
    runner._reusable_lock.acquire()

    def wait_for_slot():
        try:
            runner.run('objects', {'path': 'unused'}, cancel=token, reusable=True)
        except BaseException as error:
            failures.append(error)

    thread = threading.Thread(target=wait_for_slot)
    try:
        thread.start()
        token.cancel()
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert len(failures) == 1 and isinstance(failures[0], CancelledError)
        assert not runner.work_root.exists()
    finally:
        runner._reusable_lock.release()
        runner.shutdown()
        thread.join(timeout=2)


def test_cancelling_interactive_decode_allows_next_request_and_releases_process_on_shutdown(tmp_path):
    source = tmp_path / 'invalid.ab'
    source.write_bytes(b'UnityFS\0invalid-bundle-data')
    token = CancelToken()
    events = []
    runner = WorkerRunner(tmp_path / 'workers')
    request = ExtractionRequest([str(source)], str(tmp_path / 'output'), kinds=['image'])

    def progress(event):
        events.append(event)
        if event.get('stage') == 'extract':
            token.cancel()

    try:
        with pytest.raises(CancelledError):
            runner.run('extract', as_jsonable(request), emit=progress, cancel=token, reusable=True)
        assert any(event.get('stage') == 'extract' for event in events)
        replacement = tmp_path / 'text.json'
        replacement.write_text('next selection', encoding='utf-8')
        assert runner.run('objects', {'path': str(replacement)}, reusable=True)[0]['name'] == replacement.name
        processes = list(runner._active)
    finally:
        runner.shutdown()
    assert all(p.poll() is not None for p in processes)
    assert source.read_bytes() == b'UnityFS\0invalid-bundle-data'


def test_background_table_decode_cannot_accidentally_use_interactive_server(tmp_path):
    runner = WorkerRunner(tmp_path / 'workers')
    with pytest.raises(ValueError, match='交互资源'):
        runner.run('tables', {}, reusable=True)
    assert not runner.work_root.exists()
