"""Resource-purpose filters survive saved sessions by their category labels."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QSignalBlocker

from arknights_unpacker.application import AppServices
from arknights_unpacker.contracts import FileRecord, ScanSnapshot
from arknights_unpacker.ui.main_window import MainWindow
from arknights_unpacker.ui.pages import ExplorerPage


def page_with_files(qtbot, tmp_path):
    page = ExplorerPage(SimpleNamespace())
    qtbot.addWidget(page.view)
    page.view.set_root(str(tmp_path))
    for relative in ('avg/images', 'avg/backgrounds'):
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)
    records = [
        FileRecord('avg/images/story.ab', 10, 0, '.ab', 'base', '剧情插图'),
        FileRecord('avg/images/story.bin', 10, 0, '.bin', 'base', '剧情插图'),
        FileRecord('avg/backgrounds/story.ab', 10, 0, '.ab', 'base', '剧情背景'),
    ]
    snapshot = ScanSnapshot('scan', 'profile', str(tmp_path), 0, 0, records)
    page.view.set_data(snapshot)
    return page, snapshot


def paths(view):
    return {row['path'] for row in view.model.rows}


def test_category_state_round_trip_uses_label_and_preserves_other_filters(qtbot, tmp_path):
    page, snapshot = page_with_files(qtbot, tmp_path)
    state = {'file_type': '剧情插图', 'folder': 'avg', 'recursive': True,
             'ab_only': True, 'search': 'story'}
    page.restore_state(state)
    before = paths(page.view)
    assert before == {'avg/images/story.ab'}
    saved = json.loads(json.dumps(page.save_state(), ensure_ascii=False))
    assert saved == state
    page.restore_state({})
    assert page.view.file_type.currentData() is None
    # Simulate category choices appearing in a different order after a scan.
    with QSignalBlocker(page.view.file_type):
        page.view.file_type.clear()
        page.view.file_type.addItem('全部类型', None)
        page.view.file_type.addItem('剧情插图', '剧情插图')
        page.view.file_type.addItem('剧情背景', '剧情背景')
    page.view.set_data(snapshot)
    page.restore_state(saved)
    assert page.view.file_type.currentData() == '剧情插图'
    assert page.view.folder == 'avg'
    assert page.view.recursive.isChecked() and page.view.ab_only.isChecked()
    assert page.view.search.text() == 'story'
    assert paths(page.view) == before


def test_unobserved_custom_category_restores_before_scan_and_survives_reload(qtbot, tmp_path):
    page, snapshot = page_with_files(qtbot, tmp_path)
    page.restore_state({'file_type': '自定义用途', 'recursive': True})
    assert page.view.file_type.currentData() == '自定义用途'
    assert paths(page.view) == set()
    custom = FileRecord('custom.ab', 1, 0, '.ab', 'base', '自定义用途')
    changed = deepcopy(snapshot)
    changed.files = [custom, *reversed(changed.files)]
    page.view.set_data(changed)
    assert page.view.file_type.currentData() == '自定义用途'
    assert paths(page.view) == {'custom.ab'}
    other = tmp_path / 'another-game'
    other.mkdir()
    page.set_root(other)
    changed.root = str(other)
    page.view.set_data(changed)
    assert page.view.file_type.currentData() == '自定义用途'
    assert paths(page.view) == {'custom.ab'}
    assert page.save_state()['file_type'] == '自定义用途'


@pytest.mark.parametrize('state', [{}, {'folder': 'avg', 'recursive': True},
                                  {'file_type': None}, {'file_type': ''}, {'file_type': '  '},
                                  {'file_type': 5}, {'file_type': []}, {'file_type': {}}])
def test_missing_or_invalid_category_state_restores_all_types(qtbot, tmp_path, state):
    page, _ = page_with_files(qtbot, tmp_path)
    page.view.file_type.setCurrentIndex(page.view.file_type.findData('剧情插图'))
    page.restore_state(state)
    assert page.view.file_type.currentData() is None


def test_legacy_state_defaults_to_all_categories_and_keeps_safe_folder_scope(qtbot, tmp_path):
    page, _ = page_with_files(qtbot, tmp_path)
    page.restore_state({'file_type': '剧情背景'})
    state = page.legacy_state({'explorer_folder': 'avg', 'explorer_recursive': True,
                              'explorer_ab': True, 'explorer_search': 'story'})
    page.restore_state(state)
    assert page.view.file_type.currentData() is None
    assert paths(page.view) == {'avg/images/story.ab', 'avg/backgrounds/story.ab'}
    assert page.view.folder == 'avg'
    assert page.view.recursive.isChecked() and page.view.ab_only.isChecked()
    assert page.view.search.text() == 'story'
    page.restore_state({'folder': '../outside', 'file_type': '剧情插图', 'recursive': True})
    assert page.view.folder == 'avg'
    assert (page.view.root / page.view.folder).resolve().is_relative_to(tmp_path.resolve())


def test_real_main_window_reopens_global_type_results_and_restores_saved_narrow_scope(qtbot, tmp_path, monkeypatch):
    game = tmp_path / 'game'
    resources = game / 'Arknights_Data/StreamingAssets/AB/Windows'
    for relative in ('avg/images/story.ab', 'avg/images/story.bin', 'avg/images/deep/story-deep.ab',
                     'avg/imgs/story-secondary.ab', 'avg/images/unmatched.ab', 'avg/backgrounds/story.ab'):
        target = resources / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'UnityFS-state-fixture')
    data_root = tmp_path / 'app-data'
    first_services = AppServices(data_root, output_root=tmp_path / 'exports')
    first_services.scan(game)
    first = MainWindow(first_services)
    qtbot.addWidget(first)
    first.show()
    try:
        qtbot.waitUntil(lambda: first._view_state_ready and not first.queue.busy, timeout=10000)
        prefix = resources.relative_to(game).as_posix()
        folder = prefix + '/avg/backgrounds'
        first.explorer.folder = folder
        first.explorer.recursive.setChecked(False)
        first.explorer.ab_only.setChecked(True)
        first.explorer.search.setText('story')
        first.explorer.refresh()
        original_scope = {prefix + '/avg/backgrounds/story.ab'}
        assert paths(first.explorer) == original_scope
        first.explorer.file_type.setCurrentIndex(first.explorer.file_type.findData('剧情插图'))
        first.explorer.refresh()
        visible = paths(first.explorer)
        assert visible == {prefix + '/avg/images/story.ab', prefix + '/avg/images/deep/story-deep.ab',
                           prefix + '/avg/imgs/story-secondary.ab'}
        assert '全库筛选' in first.explorer.breadcrumb.text()
        assert first.explorer.folder == folder
        assert not first.explorer.recursive.isChecked()
        first.remember_view_state()
        first_services.save_config()
        settings = json.loads(first_services.config_file.read_text('utf-8'))
        saved = settings['view_states'][str(game.resolve())]['pages']['explorer']
        assert saved == {'file_type': '剧情插图', 'folder': folder, 'recursive': False,
                         'ab_only': True, 'search': 'story'}
    finally:
        first.close()
        first_services.shutdown()

    restored_services = AppServices(data_root, output_root=tmp_path / 'exports')

    def forbidden(*args, **kwargs):
        raise AssertionError('Restoring the file-type filter must not rescan or decode the game')

    monkeypatch.setattr(restored_services, 'scan', forbidden)
    monkeypatch.setattr(restored_services, 'load_data', forbidden)
    restored = MainWindow(restored_services)
    qtbot.addWidget(restored)
    restored.show()
    try:
        qtbot.waitUntil(lambda: restored._view_state_ready and not restored.queue.busy, timeout=10000)
        assert restored.explorer.file_type.currentData() == '剧情插图'
        assert restored.explorer.folder == folder
        assert not restored.explorer.recursive.isChecked()
        assert restored.explorer.ab_only.isChecked()
        assert restored.explorer.search.text() == 'story'
        assert paths(restored.explorer) == visible
        assert restored_services.config['view_states'] == settings['view_states']
        assert '全库筛选' in restored.explorer.breadcrumb.text()
        assert not restored.explorer.tree.isEnabled()
        assert not restored.explorer.up_button.isEnabled()
        assert not restored.explorer.recursive.isEnabled()
        # Returning to all types restores the exact saved folder and recursion;
        # the global result's unrelated directories do not become its new scope.
        restored.explorer.file_type.setCurrentIndex(0)
        assert restored.explorer.folder == folder
        assert not restored.explorer.recursive.isChecked()
        assert paths(restored.explorer) == original_scope
        assert restored.explorer.tree.isEnabled()
        assert restored.explorer.up_button.isEnabled()
        assert restored.explorer.recursive.isEnabled()
    finally:
        restored.close()
        restored_services.shutdown()
