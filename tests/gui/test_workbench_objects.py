"""Vue object bridge with the actual Qt queue, using a small decoder fixture."""
import threading
from pathlib import Path

import pytest

from arknights_unpacker.contracts import ExtractionResult
from arknights_unpacker.ui.workbench.objects import WorkbenchObjects
from test_explorer import make_window, wait_idle


def test_bundle_preview_keeps_latest_selection_and_only_publishes_its_own_files(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    package = tmp_path / 'sample.ab'
    package.write_bytes(b'input')
    outside = tmp_path / 'outside.txt'
    outside.write_text('untouched', encoding='utf-8')
    services.objects = lambda *_args, **_kwargs: [
        {'id': '10', 'type': 'TextAsset', 'name': 'first', 'size': 5},
        {'id': '20', 'type': 'TextAsset', 'name': 'latest', 'size': None},
    ]
    entered, resume = threading.Event(), threading.Event()
    calls = []

    def extract(paths, output, **kwargs):
        object_ids = kwargs['object_ids'][paths[0]]
        calls.append((object_ids, Path(output), kwargs['remember_output']))
        if kwargs['remember_output']:
            return ExtractionResult()
        if object_ids == ['10']:
            entered.set()
            assert resume.wait(6)
        owned = Path(output) / 'result.txt'
        owned.write_text('<b>' + object_ids[0] + '</b>', encoding='utf-8')
        return ExtractionResult(outputs=[{'path': str(outside)}, {'path': str(owned)}])

    services.extract = extract
    changes = []
    bridge = WorkbenchObjects(window, lambda: changes.append(True))
    token = bridge.open(str(package))['token']
    try:
        wait_idle(qtbot, window)
        assert [row['id'] for row in bridge.state(token)['rows']] == ['10', '20']
        bridge.select(token, '10')
        qtbot.waitUntil(entered.is_set)
        bridge.select(token, '20')
        assert bridge.preview(token) == {'id': '20', 'loading': True, 'error': '', 'artifacts': []}
        resume.set()
        qtbot.waitUntil(lambda: bool(bridge.preview(token)['artifacts']), timeout=5000)
        wait_idle(qtbot, window)
        assert bridge.preview(token)['artifacts'] == [
            {'name': 'result.txt', 'kind': 'text', 'url': '', 'text': '<b>20</b>'},
        ]
        assert [call[0] for call in calls] == [['10'], ['20']]
        assert not calls[0][1].exists()
        assert calls[1][1].is_dir()
        with pytest.raises(ValueError, match='对象'):
            bridge.extract(token, ['unknown'])
        bridge.extract(token, ['20'])
        wait_idle(qtbot, window)
        assert calls[-1] == (['20'], tmp_path / 'exports', True)
    finally:
        resume.set()
        bridge.close(token)
        wait_idle(qtbot, window)
    assert not calls[1][1].exists()
    assert changes and outside.read_text(encoding='utf-8') == 'untouched'
    assert package.read_bytes() == b'input'
