from __future__ import annotations

import time
from types import SimpleNamespace

from PySide6.QtCore import QPoint

from arknights_unpacker.contracts import FileChange, FileChangeSet, FileRecord, ScanSnapshot
from arknights_unpacker.library.classifications import category_labels, classify
from arknights_unpacker.ui.pages import UpdatesPage
from arknights_unpacker.ui.updates import UpdatesView


def updates(qtbot, tmp_path):
    now = time.time()
    records = [
        FileRecord('avg/images/story.ab', 10, int(now * 1e9), '.ab', 'base', classify('avg/images/story.ab', 'base')),
        FileRecord('avg/imgs/alternate.bin', 11, int(now * 1e9), '.bin', 'hot', classify('avg/imgs/alternate.bin', 'hot')),
        FileRecord('avg/backgrounds/place.ab', 12, int(now * 1e9), '.ab', 'base', classify('avg/backgrounds/place.ab', 'base')),
        FileRecord('avg/images/older.ab', 13, int((now - 48 * 3600) * 1e9), '.ab', 'base', '剧情插图'),
    ]
    removed = FileRecord('avg/images/deleted.ab', 9, int(now * 1e9), '.ab', 'base', '剧情插图')
    changes = [FileChange('modified', record.path, record, record) for record in records]
    changes.append(FileChange('removed', removed.path, removed, None))
    view = UpdatesView()
    qtbot.addWidget(view)
    view.set_data(ScanSnapshot('current', 'profile', str(tmp_path), now, now, records),
                  FileChangeSet('previous', 'current', changes))
    return view


def visible_paths(view):
    return {row['path'] for row in view.model.rows}


def test_common_category_choices_are_deduplicated_classification_labels():
    labels = category_labels()
    assert labels.count('剧情插图') == 1
    assert labels.count('剧情背景') == 1
    assert len(labels) == len(set(labels))
    assert {'干员头像', '干员肖像', '技能图标', '剧情插图', '剧情背景'} <= set(labels)


def test_deleted_files_are_excluded_by_default_and_can_be_shown(qtbot, tmp_path):
    view = updates(qtbot, tmp_path)
    assert view.exclude_deleted.isChecked()
    assert len(visible_paths(view)) == 4
    view.exclude_deleted.setChecked(False)
    assert 'avg/images/deleted.ab' in visible_paths(view)
    gone = next(index for index, row in enumerate(view.model.rows) if not row['exists'])
    view.table.selectRow(gone)
    assert not view.images_button.isEnabled()
    assert not view.extract_button.isEnabled()
    view.exclude_deleted.setChecked(True)
    assert 'avg/images/deleted.ab' not in visible_paths(view)


def test_category_filter_uses_resource_purpose_and_combines_with_scope_search_and_extension(qtbot, tmp_path):
    view = updates(qtbot, tmp_path)
    assert view.file_type.findData('剧情插图') >= 0
    view.file_type.setCurrentIndex(view.file_type.findData('剧情插图'))
    assert visible_paths(view) == {'avg/images/story.ab', 'avg/imgs/alternate.bin', 'avg/images/older.ab'}
    view.ab_only.setChecked(True)
    assert visible_paths(view) == {'avg/images/story.ab', 'avg/images/older.ab'}
    view.mode.setCurrentIndex(0)
    assert visible_paths(view) == {'avg/images/story.ab'}
    view.search.setText('older')
    assert not visible_paths(view)
    view.mode.setCurrentIndex(1)
    assert visible_paths(view) == {'avg/images/older.ab'}
    view.search.clear()
    view.exclude_deleted.setChecked(False)
    assert visible_paths(view) == {'avg/images/story.ab', 'avg/images/older.ab', 'avg/images/deleted.ab'}
    view.mode.setCurrentIndex(3)
    assert visible_paths(view) == {'avg/images/story.ab'}


def test_clear_filters_restores_category_and_deleted_defaults_without_changing_scope(qtbot, tmp_path):
    view = updates(qtbot, tmp_path)
    view.mode.setCurrentIndex(1)
    view.file_type.setCurrentIndex(view.file_type.findData('剧情背景'))
    view.search.setText('no matching file')
    view.ab_only.setChecked(True)
    view.exclude_deleted.setChecked(False)
    view.clear_filters()
    assert view.file_type.currentData() is None
    assert view.exclude_deleted.isChecked()
    assert not view.ab_only.isChecked()
    assert view.search.text() == ''
    assert view.mode.currentIndex() == 1
    assert len(visible_paths(view)) == 4


def test_category_choices_include_common_purposes_before_scan_and_observed_custom_categories(qtbot, tmp_path):
    view = UpdatesView()
    qtbot.addWidget(view)
    assert view.file_type.findData('剧情插图') >= 0
    now = time.time()
    record = FileRecord('custom.ab', 1, int(now * 1e9), '.ab', 'base', '自定义用途')
    view.set_data(ScanSnapshot('current', 'profile', str(tmp_path), now, now, [record]), FileChangeSet(None, 'current'))
    assert view.file_type.findData('自定义用途') >= 0
    view.file_type.setCurrentIndex(view.file_type.findData('自定义用途'))
    assert visible_paths(view) == {'custom.ab'}
    # Refreshing the same observation must not reset the chosen purpose.
    view.set_data(view.snapshot, view.changes)
    assert view.file_type.currentData() == '自定义用途'


def test_new_update_filters_round_trip_and_old_saved_state_uses_deleted_default(qtbot):
    page = UpdatesPage(SimpleNamespace())
    qtbot.addWidget(page.view)
    page.view.mode.setCurrentIndex(1)
    page.view.file_type.setCurrentIndex(page.view.file_type.findData('剧情插图'))
    page.view.exclude_deleted.setChecked(False)
    page.view.search.setText('sample')
    saved = page.save_state()
    page.restore_state({})
    assert page.view.file_type.currentData() is None
    assert page.view.exclude_deleted.isChecked()
    page.restore_state(saved)
    assert page.view.file_type.currentData() == '剧情插图'
    assert not page.view.exclude_deleted.isChecked()
    assert page.view.mode.currentIndex() == 1
    assert page.view.search.text() == 'sample'
    page.restore_state(page.legacy_state({'update_mode': 3, 'update_ab': True, 'update_search': 'old'}))
    assert page.view.file_type.currentData() is None
    assert page.view.exclude_deleted.isChecked()
    assert page.view.mode.currentIndex() == 3
    assert page.view.ab_only.isChecked()


def test_filter_controls_fit_inside_a_1050_pixel_window(qtbot):
    view = UpdatesView()
    qtbot.addWidget(view)
    view.resize(1050, 480)
    view.show()
    qtbot.waitUntil(view.isVisible)
    assert view.width() <= 1050
    for control in (view.mode, view.search, view.file_type, view.exclude_deleted, view.ab_only):
        assert view.rect().contains(control.mapTo(view, QPoint(0, 0)))
        assert view.rect().contains(control.mapTo(view, control.rect().bottomRight()))
