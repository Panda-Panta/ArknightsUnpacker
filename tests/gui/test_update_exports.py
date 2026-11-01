import time
from pathlib import Path

from PySide6.QtCore import Qt

from arknights_unpacker.contracts import FileChange, FileChangeSet, FileRecord, ScanSnapshot
from arknights_unpacker.ui.updates import UpdatesView


def populated_updates(qtbot, tmp_path):
    now = time.time()
    files = [FileRecord(name, 30, int(now * 1e9), Path(name).suffix, 'base', '立绘')
             for name in ('z-last.ab', 'a-first.AB', 'text.json')]
    for file in files:
        (tmp_path / file.path).write_bytes(b'fixture')
    removed = FileRecord('gone.ab', 5, int(now * 1e9), '.ab', 'base', '立绘')
    changes = FileChangeSet('previous', 'current', [
        FileChange('modified', file.path, file, file) for file in files
    ] + [FileChange('removed', removed.path, removed, None)])
    view = UpdatesView()
    qtbot.addWidget(view)
    view.set_data(ScanSnapshot('current', 'profile', str(tmp_path), now, now, files), changes)
    view.mode.setCurrentIndex(2)
    return view


def test_updates_can_filter_ab_select_all_and_request_only_images(qtbot, tmp_path):
    view = populated_updates(qtbot, tmp_path)
    assert not view.images_button.isEnabled()
    view.ab_only.setChecked(True)
    assert view.model.rowCount() == 2
    view.table.selectAll()
    received = []
    view.images_requested.connect(received.append)
    view.images_button.click()
    assert set(received[0]) == {str(tmp_path / 'z-last.ab'), str(tmp_path / 'a-first.AB')}
    assert '2' in view.selection_count.text()
    view.search.setText('z-last')
    assert view.model.rowCount() == 1
    assert not view.images_button.isEnabled()


def test_sort_keeps_selected_update_source_and_deleted_rows_cannot_export(qtbot, tmp_path):
    view = populated_updates(qtbot, tmp_path)
    selected_row = next(i for i, row in enumerate(view.model.rows) if row['path'] == 'z-last.ab')
    view.table.selectRow(selected_row)
    view.table.sortByColumn(0, Qt.SortOrder.DescendingOrder)
    received = []
    view.images_requested.connect(received.append)
    view.images_button.click()
    assert received == [[str(tmp_path / 'z-last.ab')]]
    view.table.clearSelection()
    view.exclude_deleted.setChecked(False)
    gone = next(i for i, row in enumerate(view.model.rows) if row['path'] == 'gone.ab')
    view.table.selectRow(gone)
    assert not view.images_button.isEnabled()
    assert not view.extract_button.isEnabled()


def test_changed_packages_outside_recent_window_are_visible_by_default(qtbot, tmp_path):
    now = time.time()
    old = FileRecord('old.ab', 8, int((now - 48 * 3600) * 1e9), '.ab', 'base')
    current = FileRecord('old.ab', 9, old.mtime_ns, '.ab', 'base')
    view = UpdatesView()
    qtbot.addWidget(view)
    snapshot = ScanSnapshot('new', 'profile', str(tmp_path), now, now, [current])
    view.set_data(snapshot, FileChangeSet('old', 'new', [FileChange('modified', old.path, old, current)]))
    assert view.model.rowCount() == 1


def test_update_images_action_overrides_global_raw_and_resource_types(qtbot, tmp_path):
    from test_explorer import make_window, wait_idle
    from arknights_unpacker.contracts import ExtractionResult
    window, services = make_window(qtbot, tmp_path)
    game = tmp_path / 'game'
    game.mkdir()
    window.root_edit.setText(str(game))
    window.scan()
    wait_idle(qtbot, window)
    calls = []
    def extract(paths, output, **kwargs):
        calls.append((paths, kwargs['kinds'], kwargs['mode']))
        return ExtractionResult()
    services.extract = extract
    for checkbox in window.settings.kinds.values():
        checkbox.setChecked(False)
    window.settings.mode.setCurrentIndex(window.settings.mode.findData('raw'))
    window.updates.table.selectAll()
    window.updates.images_button.click()
    wait_idle(qtbot, window)
    assert len(calls[0][0]) == 2
    assert calls[0][1:] == (['image'], 'auto')

