from __future__ import annotations

import time

from PySide6.QtCore import QPoint, Qt

from arknights_unpacker.contracts import (FileChangeSet, FileRecord, GameInstallation,
                                        ResolvedResource, ResourceCatalog, ScanSnapshot)
from arknights_unpacker.ui.explorer import ExplorerView
from arknights_unpacker.ui.models import time_text
from arknights_unpacker.ui.updates import UpdatesView


def column(view, label):
    return next(i for i, item in enumerate(view.model.columns) if item[0] == label)


def snapshot(root):
    now = int(time.time())
    files = [FileRecord('a.ab', 90, (now - 3) * 10**9 + 300,
                        first_seen_at=now - 1.1, created_ns=(now - 20) * 10**9 + 300),
             FileRecord('b.ab', 1024, (now - 3) * 10**9 + 100,
                        first_seen_at=now - 1.3, created_ns=(now - 20) * 10**9 + 100),
             FileRecord('c.ab', 20 * 1024**2, (now - 3) * 10**9 + 200,
                        first_seen_at=now - 1.2, created_ns=(now - 20) * 10**9 + 200),
             FileRecord('old.ab', 2 * 1024**3, 0)]
    return ScanSnapshot('current', 'profile', str(root), now, now, files)


def make_explorer(qtbot, tmp_path):
    view = ExplorerView()
    qtbot.addWidget(view)
    view.resize(1450, 700)
    view.set_root(tmp_path)
    view.set_data(snapshot(tmp_path))
    return view


def test_resource_size_header_and_filter_keep_byte_order_and_selected_path(qtbot, tmp_path):
    view = make_explorer(qtbot, tmp_path)
    view.show()
    index = column(view, '大小')
    view.table.sortByColumn(index, Qt.SortOrder.DescendingOrder)
    header = view.table.horizontalHeader()
    qtbot.mouseClick(header.viewport(), Qt.MouseButton.LeftButton,
                    pos=QPoint(
                        header.sectionViewportPosition(index) + header.sectionSize(index) // 2,
                        header.height() // 2))
    assert header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder
    assert [row['path'] for row in view.model.rows] == ['a.ab', 'b.ab', 'c.ab', 'old.ab']
    view.table.selectRow(1)
    view.table.sortByColumn(index, Qt.SortOrder.DescendingOrder)
    assert view.selected_paths() == [str(tmp_path / 'b.ab')]
    view.search.setText('.ab')
    assert [row['path'] for row in view.model.rows] == ['old.ab', 'c.ab', 'b.ab', 'a.ab']


def test_resource_time_columns_compare_original_values_and_show_unknown(qtbot, tmp_path):
    view = make_explorer(qtbot, tmp_path)
    for label in ('修改时间', '创建时间', '首次观测'):
        index = column(view, label)
        view.table.sortByColumn(index, Qt.SortOrder.AscendingOrder)
        assert [row['path'] for row in view.model.rows] == ['b.ab', 'c.ab', 'a.ab', 'old.ab']
        view.table.sortByColumn(index, Qt.SortOrder.DescendingOrder)
        assert [row['path'] for row in view.model.rows] == ['a.ab', 'c.ab', 'b.ab', 'old.ab']
    view.table.selectRow(0)
    details = view.details.toPlainText()
    assert '创建时间' in details and '首次观测' in details
    assert time_text(view.model.rows[0]['created_ns'] / 1e9) in details
    view.table.selectRow(3)
    assert '未知' in view.details.toPlainText()


def test_effective_resources_join_saved_file_times_without_reading_files(qtbot, tmp_path):
    view = make_explorer(qtbot, tmp_path)
    data = snapshot(tmp_path)
    catalog = ResourceCatalog(GameInstallation(tmp_path, 'profile'), {
        'a': ResolvedResource('logical/a.ab', str(tmp_path / 'A.ab'), 'base', 'current'),
        'b': ResolvedResource('logical/b.ab', str(tmp_path / 'b.ab'), 'hot', 'current'),
        'missing': ResolvedResource('missing.ab', None, 'hot', 'missing'),
        'other': ResolvedResource('other.ab', str(tmp_path.parent / 'outside.ab'), 'base', 'current'),
    })
    view.set_data(data, None, catalog)
    # Metadata must come from the same saved observation, even with an offline source.
    view.recursive.setChecked(True)
    view.layer.setCurrentIndex(1)
    rows = {row['logical_key']: row for row in view.model.rows}
    assert rows['logical/a.ab']['created_ns'] == data.files[0].created_ns
    assert rows['logical/a.ab']['first_seen_at'] == data.files[0].first_seen_at
    assert rows['logical/a.ab']['mtime_ns'] == data.files[0].mtime_ns
    assert rows['logical/b.ab']['created_ns'] == data.files[1].created_ns
    assert rows['missing.ab'].get('created_ns') is None
    # An absolute resource outside the selected root cannot inherit a local filename's times.
    assert rows['other.ab'].get('first_seen_at') is None
    data.files[0].created_ns += 10**9
    view.set_data(data, None, catalog)
    assert next(row for row in view.model.rows if row['logical_key'] == 'logical/a.ab')['created_ns'] == data.files[0].created_ns


def test_update_size_and_times_keep_raw_order_after_refresh(qtbot, tmp_path):
    view = UpdatesView()
    qtbot.addWidget(view)
    data = snapshot(tmp_path)
    view.set_data(data, FileChangeSet(None, data.snapshot_id))
    view.table.sortByColumn(column(view, '大小'), Qt.SortOrder.AscendingOrder)
    assert [row['path'] for row in view.model.rows] == ['a.ab', 'b.ab', 'c.ab']
    for label in ('修改时间', '首次观测'):
        view.table.sortByColumn(column(view, label), Qt.SortOrder.AscendingOrder)
        assert [row['path'] for row in view.model.rows] == ['b.ab', 'c.ab', 'a.ab']
        view.search.setText('.ab')
        assert [row['path'] for row in view.model.rows] == ['b.ab', 'c.ab', 'a.ab']
        view.search.clear()
