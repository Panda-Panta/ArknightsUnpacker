from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem

from arknights_unpacker.application import AppServices
from arknights_unpacker.contracts import EntityChangeSet
from arknights_unpacker.ui.module_view import ModuleView
from arknights_unpacker.ui.operator_view import OperatorView
from arknights_unpacker.ui.settings import SettingsView


def select_ids(view, ids):
    selection = view.table.selectionModel()
    selection.clearSelection()
    for row, record in enumerate(view.model.rows):
        if record['id'] in ids:
            selection.select(view.model.index(row, 0),
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)


def modules(qtbot, baseline='before'):
    from arknights_unpacker.ui.styles import apply_theme
    apply_theme()
    view = ModuleView()
    qtbot.addWidget(view)
    changes = EntityChangeSet(baseline, 'after', modules=[
        {'id': 'equip_new', 'name': '新增模组', 'kind': 'added'},
        {'id': 'equip_new_alias', 'name': '另一新增模组', 'kind': 'new'},
        {'id': 'equip_changed', 'name': '变化模组', 'kind': 'modified'},
        {'id': 'equip_gone', 'name': '已删除模组', 'kind': 'removed'},
    ])
    view.set_rows([{'id': module_id, 'name': name, 'char_name': '测试干员', 'type': 'X'}
        for module_id, name in [('equip_new', '新增模组'), ('equip_new_alias', '另一新增模组'),
                                ('equip_changed', '变化模组'), ('equip_same', '未变化模组')]], changes)
    return view


def check_id(view, module_id):
    row = next(i for i, item in enumerate(view.model.rows) if item['id'] == module_id)
    assert view.model.setData(view.model.index(row, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)


def test_old_settings_default_to_single_module_png(qtbot, tmp_path):
    view = SettingsView({'report_width': 1440, 'report_font_size': 30, 'report_theme': 'light'}, tmp_path)
    qtbot.addWidget(view)
    assert view.module_image_layout.currentData() == 'single'
    options = view.report_options()
    assert options.module_image_layout == 'single'
    assert (options.width, options.font_size, options.theme) == (1440, 30, 'light')


def test_paged_module_option_commits_to_disk_and_restores(qtbot, tmp_path):
    data_dir = tmp_path / 'data'
    services = AppServices(data_dir, output_root=tmp_path / 'exports')
    try:
        view = SettingsView(services.config, services.data_root)
        qtbot.addWidget(view)
        assert {view.module_image_layout.itemData(i) for i in range(view.module_image_layout.count())} == {'single', 'paged'}
        view.changed.connect(services.save_config)
        view.module_image_layout.setCurrentIndex(view.module_image_layout.findData('paged'))
        view.commit()
        assert services.config['report_module_image_layout'] == 'paged'
        assert view.report_options().module_image_layout == 'paged'
    finally:
        services.shutdown()
    reopened = AppServices(data_dir, output_root=tmp_path / 'exports')
    try:
        restored = SettingsView(reopened.config, reopened.data_root)
        qtbot.addWidget(restored)
        assert restored.module_image_layout.currentData() == 'paged'
        assert restored.report_options().module_image_layout == 'paged'
        restored.module_image_layout.setCurrentIndex(restored.module_image_layout.findData('single'))
        restored.commit()
        assert reopened.config['report_module_image_layout'] == 'single'
    finally:
        reopened.shutdown()


def test_module_merge_selection_emits_only_selected_available_ids(qtbot):
    view = modules(qtbot)
    assert view.export_selected.text() == '合并导出选中模组'
    assert view.export_new.text() == '合并导出本次新增'
    select_ids(view, {'equip_new', 'equip_changed', 'equip_gone'})
    exports = []
    view.export_requested.connect(lambda ids, only_new: exports.append((ids, only_new)))
    qtbot.mouseClick(view.export_selected, Qt.MouseButton.LeftButton)
    assert len(exports) == 1
    assert set(exports[0][0]) == {'equip_new', 'equip_changed'}
    assert exports[0][1] is False


def test_module_merge_new_emits_all_added_ids_independent_of_filter(qtbot):
    view = modules(qtbot)
    check_id(view, 'equip_changed')
    view.search.setText('变化模组')
    assert all(row['id'] not in {'equip_new', 'equip_new_alias'} for row in view.model.rows)
    exports = []
    view.export_requested.connect(lambda ids, only_new: exports.append((ids, only_new)))
    assert view.export_new.isEnabled()
    qtbot.mouseClick(view.export_new, Qt.MouseButton.LeftButton)
    assert len(exports) == 1
    assert set(exports[0][0]) == {'equip_new', 'equip_new_alias'}
    assert exports[0][1] is True


def test_module_merge_does_not_invent_new_items_without_a_baseline(qtbot):
    view = modules(qtbot, baseline=None)
    exports = []
    view.export_requested.connect(lambda *args: exports.append(args))
    assert not view.export_new.isEnabled()
    qtbot.mouseClick(view.export_new, Qt.MouseButton.LeftButton)
    view.request_export(True)
    assert exports == []
    assert all(row['status'] == 'unknown' for row in view.all_rows)


def test_operator_buttons_and_export_signal_are_unchanged(qtbot):
    view = OperatorView()
    qtbot.addWidget(view)
    assert view.export_selected.text() == '导出选中资料'
    assert view.export_new.text() == '一键导出本次新增'
    view.set_rows([{'id': 'char_a', 'name': '干员甲'}, {'id': 'char_b', 'name': '干员乙'}],
        EntityChangeSet('before', 'after', operators=[{'id': 'char_b', 'kind': 'added'}]))
    index = view.model.index(0, 0)
    assert view.model.data(index, Qt.ItemDataRole.CheckStateRole) is None
    assert not view.model.flags(index) & Qt.ItemFlag.ItemIsUserCheckable
    select_ids(view, {'char_a', 'char_b'})
    exports = []
    view.export_requested.connect(lambda ids, only_new: exports.append((ids, only_new)))
    qtbot.mouseClick(view.export_selected, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(view.export_new, Qt.MouseButton.LeftButton)
    assert set(exports[0][0]) == {'char_a', 'char_b'} and exports[0][1] is False
    assert exports[1] == (['char_b'], True)


def test_module_checkbox_supports_mouse_and_space(qtbot):
    view = modules(qtbot)
    view.resize(1050, 700)
    view.show()
    qtbot.waitExposed(view)
    row = next(i for i, item in enumerate(view.model.rows) if item['id'] == 'equip_new')
    index = view.model.index(row, 0)
    assert view.model.flags(index) & Qt.ItemFlag.ItemIsUserCheckable
    option = QStyleOptionViewItem()
    option.initFrom(view.table)
    option.features |= QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
    option.checkState = Qt.CheckState.Unchecked
    option.rect = view.table.visualRect(index)
    indicator = view.table.style().subElementRect(QStyle.SubElement.SE_ItemViewItemCheckIndicator, option, view.table)
    assert indicator.isValid()
    qtbot.mouseClick(view.table.viewport(), Qt.MouseButton.LeftButton, pos=indicator.center())
    assert view.checked_ids == {'equip_new'}
    assert view.model.data(index, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
    view.table.setCurrentIndex(index)
    view.table.setFocus()
    qtbot.keyClick(view.table, Qt.Key.Key_Space)
    assert not view.checked_ids
    assert view.model.data(index, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Unchecked


def test_checked_ids_survive_sort_filter_and_override_selected_rows(qtbot):
    view = modules(qtbot)
    check_id(view, 'equip_new')
    check_id(view, 'equip_changed')
    view.table.sortByColumn(0, Qt.SortOrder.DescendingOrder)
    checked_row = next(i for i, item in enumerate(view.model.rows) if item['id'] == 'equip_new')
    assert view.model.data(view.model.index(checked_row, 0), Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
    view.search.setText('另一新增')
    select_ids(view, {'equip_new_alias'})
    assert view.checked_ids == {'equip_new', 'equip_changed'}
    assert '已勾选 2' in view.count.text()
    assert '隐藏' in view.count.text()
    exports, previews = [], []
    view.export_requested.connect(lambda ids, only_new: exports.append((ids, only_new)))
    view.preview_requested.connect(previews.append)
    qtbot.mouseClick(view.export_selected, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(view.preview_selected, Qt.MouseButton.LeftButton)
    assert len(exports) == len(previews) == 1
    assert set(exports[0][0]) == set(previews[0]) == {'equip_new', 'equip_changed'}
    assert exports[0][1] is False


def test_select_all_visible_adds_checks_and_clear_removes_hidden_checks(qtbot):
    view = modules(qtbot)
    check_id(view, 'equip_new')
    view.search.setText('变化模组')
    qtbot.mouseClick(view.select_all_button, Qt.MouseButton.LeftButton)
    assert view.checked_ids == {'equip_new', 'equip_changed', 'equip_same'}
    view.search.clear()
    qtbot.mouseClick(view.select_all_button, Qt.MouseButton.LeftButton)
    assert view.checked_ids == {'equip_new', 'equip_new_alias', 'equip_changed', 'equip_same'}
    gone = next(i for i, item in enumerate(view.model.rows) if item['id'] == 'equip_gone')
    assert not view.model.flags(view.model.index(gone, 0)) & Qt.ItemFlag.ItemIsUserCheckable
    view.search.setText('另一新增')
    qtbot.mouseClick(view.clear_checked_button, Qt.MouseButton.LeftButton)
    assert not view.checked_ids
    assert '已勾选 0' in view.count.text()
    select_ids(view, {'equip_new_alias'})
    exports = []
    view.export_requested.connect(lambda ids, only_new: exports.append((ids, only_new)))
    qtbot.mouseClick(view.export_selected, Qt.MouseButton.LeftButton)
    assert exports == [(['equip_new_alias'], False)]


def test_checked_ids_clear_on_dataset_refresh_and_clear_data(qtbot):
    view = modules(qtbot)
    check_id(view, 'equip_new')
    view.refresh()
    assert view.checked_ids == {'equip_new'}
    rows = [dict(row) for row in view.all_rows if row['status'] != 'removed']
    view.set_rows(rows, view.changes)
    assert not view.checked_ids
    check_id(view, 'equip_changed')
    view.clear_data()
    assert not view.checked_ids
    assert view.model.rowCount() == 0
