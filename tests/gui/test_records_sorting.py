"""The table compares domain values while retaining formatted cell labels."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPersistentModelIndex, Qt
from PySide6.QtWidgets import QAbstractItemView, QTableView

from arknights_unpacker.ui.entity_view import _ModuleRecordsModel
from arknights_unpacker.ui.models import RecordsModel, selected_records, size_text


ASC = Qt.SortOrder.AscendingOrder
DESC = Qt.SortOrder.DescendingOrder


@pytest.mark.parametrize('order', [ASC, DESC])
@pytest.mark.parametrize('raw_getter', ['size', lambda row: row['size']])
def test_formatted_sizes_sort_by_exact_bytes(qtbot, order, raw_getter):
    sizes = [90, 1024, 20 * 1024**2, 3 * 1024**3, 1049, 1048, 0]
    # 1048 and 1049 both display as 1.0 KiB; sorting labels loses precision.
    model = RecordsModel([('大小', lambda row: size_text(row['size']), raw_getter)])
    model.replace([{'size': size} for size in sizes])
    model.sort(0, order)
    assert [row['size'] for row in model.rows] == sorted(sizes, reverse=order == DESC)
    assert model.data(model.index(0, 0)) == size_text(model.rows[0]['size'])


@pytest.mark.parametrize('order', [ASC, DESC])
def test_unformatted_numeric_column_keeps_native_order(qtbot, order):
    model = RecordsModel([('数值', 'number')])
    model.replace([{'number': n} for n in [10, 2, 0, -4, 100, 2.5]])
    model.sort(0, order)
    assert [row['number'] for row in model.rows] == sorted([-4, 0, 2, 2.5, 10, 100], reverse=order == DESC)


@pytest.mark.parametrize('order', [ASC, DESC])
def test_unknown_values_stay_last_and_equal_values_are_stable(qtbot, order):
    model = RecordsModel([('时间', lambda row: '未知' if row['timestamp'] is None else '显示时间', 'timestamp')])
    model.replace([{'id': 'missing', 'timestamp': None}, {'id': 'same-a', 'timestamp': 5},
                   {'id': 'early', 'timestamp': 2}, {'id': 'same-b', 'timestamp': 5},
                   {'id': 'also-missing', 'timestamp': None}])
    model.sort(0, order)
    expected = ['early', 'same-a', 'same-b'] if order == ASC else ['same-a', 'same-b', 'early']
    assert [row['id'] for row in model.rows] == expected + ['missing', 'also-missing']
    model.sort(0, DESC if order == ASC else ASC)
    assert [row['id'] for row in model.rows if row['timestamp'] == 5] == ['same-a', 'same-b']
    assert [row['id'] for row in model.rows[-2:]] == ['missing', 'also-missing']


@pytest.mark.parametrize('order', [ASC, DESC])
def test_replacement_reapplies_current_sort(qtbot, order):
    model = RecordsModel([('大小', lambda row: size_text(row['size']), 'size')])
    # A table may ask to sort while the model is still empty.
    model.sort(0, order)
    model.replace([{'size': n} for n in [90, 2, 1500]])
    assert [row['size'] for row in model.rows] == sorted([90, 2, 1500], reverse=order == DESC)
    model.replace([{'size': n} for n in [3, 100, 20]])
    assert [row['size'] for row in model.rows] == sorted([3, 100, 20], reverse=order == DESC)


def test_two_element_text_columns_remain_case_insensitive(qtbot):
    model = RecordsModel([('名称', 'name')])
    model.replace([{'name': name} for name in ['zeta', 'Beta', 'alpha']])
    model.sort(0, ASC)
    assert [row['name'] for row in model.rows] == ['alpha', 'Beta', 'zeta']
    model.sort(-1, DESC)
    model.replace([{'name': name} for name in ['Gamma', 'beta']])
    assert [row['name'] for row in model.rows] == ['beta', 'Gamma']


def test_no_requested_sort_retains_input_order(qtbot):
    model = RecordsModel([('名称', 'name')])
    model.replace([{'name': name} for name in ['Zulu', 'Alpha', 'Beta']])
    assert [row['name'] for row in model.rows] == ['Zulu', 'Alpha', 'Beta']
    model.sort(-1, ASC)
    model.replace([{'name': name} for name in ['Gamma', 'Alpha']])
    assert [row['name'] for row in model.rows] == ['Gamma', 'Alpha']


def test_sort_preserves_selected_record_and_persistent_index_with_duplicate_values(qtbot):
    model = RecordsModel([('大小', lambda row: size_text(row['size']), 'size')])
    model.replace([{'id': 'same-a', 'size': 100}, {'id': 'smaller', 'size': 2}, {'id': 'same-b', 'size': 100}])
    table = QTableView()
    qtbot.addWidget(table)
    table.setModel(model)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.selectRow(2)
    index = QPersistentModelIndex(model.index(0, 0))
    model.sort(0, ASC)
    assert selected_records(table)[0]['id'] == 'same-b'
    assert model.rows[index.row()]['id'] == 'same-a'
    model.sort(0, DESC)
    assert selected_records(table)[0]['id'] == 'same-b'
    assert model.rows[index.row()]['id'] == 'same-a'


def test_module_checks_keep_id_through_sort_and_replacement(qtbot):
    model = _ModuleRecordsModel([('模组', 'name')])
    model.replace([{'id': 'one', 'name': 'Zulu'}, {'id': 'two', 'name': 'Alpha'}])
    model.set_checked_ids({'one'})
    model.sort(0, ASC)
    assert model.data(model.index(1, 0), Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
    model.replace([{'id': 'one', 'name': 'Beta'}, {'id': 'two', 'name': 'Alpha'}])
    assert [row['id'] for row in model.rows] == ['two', 'one']
    assert model.data(model.index(1, 0), Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
