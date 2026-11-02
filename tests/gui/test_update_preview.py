from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt

from arknights_unpacker.contracts import FileChange, FileChangeSet, FileRecord, ScanSnapshot
from arknights_unpacker.ui.pages import UpdatesPage


@pytest.fixture
def update_page(qtbot, tmp_path):
    now = time.time()
    records = [
        FileRecord(name, 10, int(now * 1e9), Path(name).suffix, layer, category)
        for name, layer, category in (
            ('avg/images/z-last.ab', 'base', '剧情插图'),
            ('avg/images/a-first.bin', 'hot', '剧情插图'),
            ('avg/backgrounds/place.ab', 'base', '剧情背景'),
            ('preview.png', 'other', '未知用途'),
            ('config.json', 'other', '未知用途'),
            ('config.exe', 'other', '未知用途'),
            ('../outside.ab', 'base', '剧情插图'),
        )
    ]
    for record in records:
        if record.path.startswith('../'):
            continue
        path = tmp_path / record.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'fixture')
    removed = FileRecord('avg/images/deleted.ab', 10, int(now * 1e9), '.ab', 'base', '剧情插图')
    changes = [FileChange('modified', record.path, record, record) for record in records]
    changes.append(FileChange('removed', removed.path, removed, None))
    received = []
    page = UpdatesPage(SimpleNamespace(extract=lambda *_args, **_kwargs: None, objects=received.append))
    page.connect()
    qtbot.addWidget(page.view)
    page.view.set_data(ScanSnapshot('current', 'profile', str(tmp_path), now, now, records),
                       FileChangeSet('previous', 'current', changes))
    page.view.resize(1080, 650)
    page.view.show()
    qtbot.waitUntil(page.view.isVisible)
    return page, received


def double_click_path(qtbot, view, path, *, select_all=False):
    row = next(index for index, record in enumerate(view.model.rows) if record['path'] == path)
    index = view.model.index(row, 0)
    view.table.scrollTo(index)
    point = view.table.visualRect(index).center()
    # Include the preceding press/release, as an actual user double click does.
    qtbot.mouseClick(view.table.viewport(), Qt.MouseButton.LeftButton, pos=point)
    if select_all:
        view.table.selectAll()
        assert len(view.table.selectionModel().selectedRows()) > 1
    qtbot.mouseDClick(view.table.viewport(), Qt.MouseButton.LeftButton, pos=point)


@pytest.mark.parametrize('path', ['avg/images/z-last.ab', 'avg/images/a-first.bin', 'preview.png', 'config.json'])
def test_double_click_update_opens_resource_preview_through_page(qtbot, tmp_path, update_page, path):
    page, received = update_page
    double_click_path(qtbot, page.view, path)
    assert received == [str(tmp_path / path)]


def test_double_click_after_filtering_and_sorting_opens_clicked_file(qtbot, tmp_path, update_page):
    page, received = update_page
    view = page.view
    view.file_type.setCurrentIndex(view.file_type.findData('剧情插图'))
    view.search.setText('avg/images/')
    view.table.sortByColumn(0, Qt.SortOrder.DescendingOrder)
    double_click_path(qtbot, view, 'avg/images/a-first.bin', select_all=True)
    assert len(view.table.selectionModel().selectedRows()) == 2
    assert received == [str(tmp_path / 'avg/images/a-first.bin')]


@pytest.mark.parametrize('path', ['avg/images/deleted.ab', 'config.exe', '../outside.ab'])
def test_double_click_unavailable_or_nonresource_update_does_not_open_preview(qtbot, update_page, path):
    page, received = update_page
    page.view.exclude_deleted.setChecked(False)
    double_click_path(qtbot, page.view, path)
    assert received == []
