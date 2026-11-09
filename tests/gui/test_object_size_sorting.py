"""Object sizes use source metadata; sorting must preserve requested IDs."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QItemSelectionModel, QPoint, Qt

from arknights_unpacker.ui.models import selected_records, size_text
from arknights_unpacker.ui.object_preview import ObjectsDialog


ASC = Qt.SortOrder.AscendingOrder
DESC = Qt.SortOrder.DescendingOrder


def size_column(dialog):
    return next(index for index, column in enumerate(dialog.model.columns) if column[0] == '对象大小')


def objects():
    sizes = [90, 1024, 2 * 1024**2, 3 * 1024**3, 1049, 1048, 0, None]
    return [{'id': str(index), 'name': f'object-{index}', 'type': 'TextAsset', 'size': size}
            for index, size in enumerate(sizes)]


@pytest.fixture
def dialog(qtbot, tmp_path):
    widget = ObjectsDialog(str(tmp_path / 'fixture.ab'), auto_preview=False)
    qtbot.addWidget(widget)
    yield widget
    widget.close()


def test_size_column_keeps_default_object_order_and_explains_its_meaning(dialog):
    dialog.set_objects(objects())
    assert [row['id'] for row in dialog.model.rows] == [row['id'] for row in objects()]
    assert dialog.table.isSortingEnabled()
    header = dialog.table.horizontalHeader()
    assert header.sortIndicatorSection() == -1
    tooltip = header.toolTip()
    assert '序列化' in tooltip and '流式' in tooltip and '导出' in tooltip and '独立文件' in tooltip
    size_column(dialog)


@pytest.mark.parametrize('order', [ASC, DESC])
def test_size_column_sorts_raw_bytes_including_equal_labels_and_unknown(dialog, order):
    dialog.set_objects(objects())
    column = size_column(dialog)
    dialog.table.sortByColumn(column, order)
    expected = sorted([row['size'] for row in objects() if row['size'] is not None], reverse=order == DESC)
    assert [row['size'] for row in dialog.model.rows] == expected + [None]
    assert dialog.model.data(dialog.model.index(len(expected), column)) == '未知'
    zero = next(index for index, row in enumerate(dialog.model.rows) if row['size'] == 0)
    assert dialog.model.data(dialog.model.index(zero, column)) == '0 B'
    assert size_text(1048) == size_text(1049)


def test_header_click_uses_numeric_order_and_keeps_selected_object(dialog, qtbot):
    dialog.set_objects(objects())
    dialog.show()
    column = size_column(dialog)
    dialog.table.sortByColumn(column, DESC)
    dialog.table.selectRow(2)
    identity = selected_records(dialog.table)[0]['id']
    dialog.table.scrollTo(dialog.model.index(0, column))
    header = dialog.table.horizontalHeader()
    qtbot.mouseClick(header.viewport(), Qt.MouseButton.LeftButton,
                    pos=QPoint(header.sectionViewportPosition(column) + header.sectionSize(column) // 2,
                               header.height() // 2))
    assert header.sortIndicatorOrder() == ASC
    assert [row['size'] for row in dialog.model.rows] == [0, 90, 1024, 1048, 1049, 2 * 1024**2, 3 * 1024**3, None]
    assert selected_records(dialog.table)[0]['id'] == identity


def test_sorted_selection_requests_exact_preview_and_extraction_ids(dialog, qtbot):
    dialog.set_objects(objects())
    dialog.table.sortByColumn(size_column(dialog), ASC)
    dialog.table.selectRow(3)
    requests = []
    dialog.extract_requested.connect(lambda source, ids, preview: requests.append((source, ids, preview)))
    dialog.auto_preview.setChecked(True)
    qtbot.waitUntil(lambda: bool(requests), timeout=1500)
    assert requests == [(dialog.path, ['5'], True)]
    dialog.table.selectionModel().select(dialog.model.index(5, 0),
                                         QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    dialog.table.sortByColumn(size_column(dialog), DESC)
    dialog.extract_button.click()
    assert requests[-1][0] == dialog.path and requests[-1][2] is False
    assert set(requests[-1][1]) == {'2', '5'}


@pytest.mark.parametrize('order, expected', [(ASC, 'small'), (DESC, 'large')])
def test_automatic_preview_uses_first_previewable_row_after_retained_sort(qtbot, tmp_path, order, expected):
    dialog = ObjectsDialog(str(tmp_path / 'fixture.ab'))
    qtbot.addWidget(dialog)
    requests = []
    dialog.extract_requested.connect(lambda source, ids, preview: requests.append((ids, preview)))
    dialog.table.sortByColumn(size_column(dialog), order)
    # In source order, supported object appears first; its numeric index is not
    # its table index after sorting. Unsupported metadata must not be selected.
    dialog.set_objects([{'id': 'large', 'type': 'Texture2D', 'size': 300},
                        {'id': 'unsupported', 'type': 'MonoBehaviour', 'size': 1},
                        {'id': 'small', 'type': 'TextAsset', 'size': 200}])
    qtbot.waitUntil(lambda: bool(requests), timeout=1500)
    assert requests == [([expected], True)]
    assert selected_records(dialog.table)[0]['id'] == expected
    # A refreshed discovery retains the same header ordering and uses its rows.
    requests.clear()
    dialog.set_objects([{'id': 'unknown-size', 'type': 'TextAsset'},
                        {'id': 'zero', 'type': 'TextAsset', 'size': 0},
                        {'id': 'unsupported', 'type': 'MonoBehaviour', 'size': 500}])
    qtbot.waitUntil(lambda: bool(requests), timeout=1500)
    assert requests == [(['zero'], True)]
    dialog.close()
