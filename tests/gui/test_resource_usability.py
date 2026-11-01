from __future__ import annotations

import time

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QToolButton

from arknights_unpacker.contracts import FileChangeSet, FileRecord, ScanSnapshot
from arknights_unpacker.ui.explorer import ExplorerView
from arknights_unpacker.ui.styles import apply_theme
from arknights_unpacker.ui.updates import UpdatesView


@pytest.fixture
def explorer(qtbot, qapp):
    apply_theme(qapp)
    view = ExplorerView()
    qtbot.addWidget(view)
    view.resize(1000, 480)
    view.show()
    return view


def snapshot_for(root, names, **kwargs):
    now = time.time()
    files = []
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'UI fixture')
        resource = path.suffix.casefold() == '.ab'
        files.append(FileRecord(name, 10, int(now * 1e9), path.suffix,
                                'base' if resource else 'other', '立绘' if resource else '其他文件'))
    return ScanSnapshot('current', 'fixture', str(root), now, now, files, **kwargs)


def test_explorer_has_truthful_initial_state_before_root_selection(explorer, tmp_path):
    assert explorer.results.currentWidget() is explorer.empty_panel
    assert '尚未扫描' in explorer.empty_title.text()
    assert not explorer.tree.isVisible()
    assert explorer.breadcrumb.text() == ''
    assert explorer.directory_empty.isVisible()
    assert not explorer.extract_button.isEnabled()
    assert not explorer.objects_button.isEnabled()
    assert not explorer.select_all_button.isEnabled()

    explorer.set_root(tmp_path)
    assert explorer.tree.isVisible()
    assert explorer.tree.rootIndex().isValid()
    assert explorer.results.currentWidget() is explorer.empty_panel
    assert not explorer.up_button.isEnabled()


def test_directory_empty_state_exposes_subfolders_only_when_they_have_files(explorer, qtbot, tmp_path):
    snapshot = snapshot_for(tmp_path, ['units/fixture.ab'])
    (tmp_path / 'empty').mkdir()
    explorer.set_root(tmp_path)
    explorer.set_data(snapshot)
    assert '子目录' in explorer.empty.text()
    assert explorer.include_subfolders_button.isVisible()

    qtbot.mouseClick(explorer.include_subfolders_button, Qt.MouseButton.LeftButton)
    assert explorer.recursive.isChecked()
    assert explorer.model.rowCount() == 1
    assert explorer.results.currentWidget() is explorer.table

    explorer.recursive.setChecked(False)
    explorer.select_directory(explorer.fs.index(str(tmp_path / 'empty')))
    assert explorer.model.rowCount() == 0
    assert '没有已索引文件' in explorer.empty_title.text()
    assert not explorer.include_subfolders_button.isVisible()
    assert explorer.up_button.isEnabled()
    qtbot.mouseClick(explorer.up_button, Qt.MouseButton.LeftButton)
    assert explorer.folder == ''
    assert explorer.include_subfolders_button.isVisible()


def test_resource_filter_recovery_clears_stale_details_and_preserves_scope(explorer, qtbot, tmp_path):
    explorer.set_root(tmp_path)
    explorer.set_data(snapshot_for(tmp_path, ['fixture.ab', 'notes.json']))
    explorer.recursive.setChecked(True)
    explorer.ab_only.setChecked(True)
    explorer.table.selectRow(0)
    assert explorer.objects_button.isEnabled()
    assert 'fixture.ab' in explorer.details.toPlainText()

    explorer.search.setText('no-such-resource')
    assert '没有匹配' in explorer.empty_title.text()
    assert 'fixture.ab' not in explorer.details.toPlainText()
    assert not explorer.objects_button.isEnabled()
    assert not explorer.extract_button.isEnabled()
    qtbot.mouseClick(explorer.clear_filters_button, Qt.MouseButton.LeftButton)
    assert explorer.search.text() == ''
    assert not explorer.ab_only.isChecked()
    assert explorer.recursive.isChecked()
    assert explorer.model.rowCount() == 2

    explorer.search.setText('fixture')
    clear = explorer.search.findChild(QToolButton)
    qtbot.waitUntil(clear.isVisible)
    qtbot.mouseClick(clear, Qt.MouseButton.LeftButton)
    assert explorer.search.text() == ''
    assert explorer.model.rowCount() == 2
    explorer.table.selectAll()
    assert '已选 2 项' in explorer.count.text()
    # Standalone JSON is now a supported preview/extraction source too.
    assert '可解包 2 项' in explorer.count.text()
    assert set(explorer.selected_paths()) == {str(tmp_path / 'fixture.ab'), str(tmp_path / 'notes.json')}
    explorer.table.clearSelection()
    assert '选择一个文件' in explorer.details.toPlainText()


def test_resource_panes_remain_usable_after_dragging_splitters(explorer, qtbot):
    qtbot.waitUntil(lambda: explorer.splitter.width() > 900)
    explorer.splitter.moveSplitter(0, 1)
    explorer.splitter.moveSplitter(explorer.width(), 2)
    assert all(size > 0 for size in explorer.splitter.sizes())
    assert explorer.splitter.widget(1).width() >= 280
    for button in (explorer.up_button, explorer.objects_button, explorer.extract_button):
        assert button.isVisible()
        assert explorer.rect().contains(button.mapTo(explorer, QPoint(0, 0)))
        assert explorer.rect().contains(button.mapTo(explorer, button.rect().bottomRight()))


def test_updates_distinguish_missing_baseline_and_search_results(qtbot, qapp, tmp_path):
    apply_theme(qapp)
    view = UpdatesView()
    qtbot.addWidget(view)
    view.resize(1000, 480)
    view.show()
    assert '还没有更新记录' in view.empty_title.text()
    assert not view.images_button.isEnabled()
    view.set_data(snapshot_for(tmp_path, ['fixture.ab']), FileChangeSet(None, 'current'))
    view.mode.setCurrentIndex(1)
    assert '尚无可比较' in view.empty_title.text()
    assert '没有记录' in view.empty.text()
    view.mode.setCurrentIndex(0)
    assert view.model.rowCount() == 1

    view.search.setText('no-such-update')
    assert '没有匹配' in view.empty_title.text()
    qtbot.mouseClick(view.clear_filters_button, Qt.MouseButton.LeftButton)
    assert view.model.rowCount() == 1
    assert view.mode.currentIndex() == 0
    qtbot.mouseClick(view.select_all_button, Qt.MouseButton.LeftButton)
    assert view.images_button.isEnabled()
    assert view.clear_selection_button.isEnabled()
    assert '已选 1 项' in view.selection_count.text()
    qtbot.mouseClick(view.clear_selection_button, Qt.MouseButton.LeftButton)
    assert not view.images_button.isEnabled()
    assert not view.extract_button.isEnabled()
    assert '已选 0 项' in view.selection_count.text()


def test_update_scan_diagnostics_stay_visible_when_filter_hides_all_rows(qtbot, tmp_path):
    view = UpdatesView()
    qtbot.addWidget(view)
    view.show()
    snapshot = snapshot_for(tmp_path, ['fixture.ab'], complete=False, errors=['无法读取某个文件'])
    view.set_data(snapshot, FileChangeSet(None, 'current'))
    assert view.model.rowCount() == 1
    assert '部分扫描' in view.summary.text()
    assert view.diagnostics.isVisible()
    view.search.setText('no-such-update')
    assert view.model.rowCount() == 0
    assert view.diagnostics.isVisible()
    assert '无法读取某个文件' in view.diagnostics.text()
