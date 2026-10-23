"""Entity pages explain empty results and keep export scope usable."""
import pytest

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QToolButton

from arknights_unpacker.contracts import EntityChangeSet, OperatorProfile
from arknights_unpacker.ui.entity_view import EntityView
from arknights_unpacker.ui.styles import apply_theme


def make_view(qtbot, kind='operators'):
    apply_theme()
    view = EntityView(kind)
    qtbot.addWidget(view)
    view.resize(1050, 700)
    view.show()
    qtbot.waitExposed(view)
    return view


@pytest.mark.parametrize('kind', ['operators', 'modules'])
def test_initial_and_parsed_empty_states_offer_the_correct_recovery(qtbot, kind):
    view = make_view(qtbot, kind)
    loads = []
    view.load_requested.connect(lambda: loads.append(True))
    assert view.empty_state.isVisible() and not view.table.isVisible()
    assert '尚未' in view.empty_title.text()
    assert not view.preview_selected.isEnabled()
    assert not view.export_selected.isEnabled()
    qtbot.mouseClick(view.empty_action, Qt.MouseButton.LeftButton)
    assert loads == [True]

    view.set_rows([])
    assert '未找到' in view.empty_title.text()
    assert '解析' in view.empty_action.text()
    qtbot.mouseClick(view.empty_action, Qt.MouseButton.LeftButton)
    assert loads == [True, True]

    view.clear_data()
    assert '尚未' in view.empty_title.text()
    assert view.empty_state.isVisible()


def test_empty_filter_recovery_keeps_hidden_module_checks_and_export_scope(qtbot):
    view = make_view(qtbot, 'modules')
    view.set_rows([{'id': 'module_a', 'name': '模组甲'}, {'id': 'module_b', 'name': '模组乙'}],
        EntityChangeSet('before', 'after', modules=[{'id': 'module_b', 'kind': 'added'}]))
    view.model.setData(view.model.index(0, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    view.only_new.setChecked(True)
    view.only_changes.setChecked(True)
    view.search.setText('无匹配')
    assert view.empty_state.isVisible()
    assert '筛选' in view.empty_title.text()
    assert '隐藏 1' in view.count.text()
    assert view.export_selected.isEnabled() and view.preview_selected.isEnabled()
    assert not view.select_all_button.isEnabled()
    exports = []
    view.export_requested.connect(lambda ids, new: exports.append((ids, new)))
    qtbot.mouseClick(view.export_selected, Qt.MouseButton.LeftButton)
    assert exports == [(['module_a'], False)]

    qtbot.mouseClick(view.empty_action, Qt.MouseButton.LeftButton)
    assert not view.search.text()
    assert not view.only_changes.isChecked() and not view.only_new.isChecked()
    assert view.table.isVisible() and view.model.rowCount() == 2
    assert view.checked_ids == {'module_a'}
    assert not view.clear_filters_button.isEnabled()


def test_search_clear_button_only_clears_search_and_filter_clear_resets_all(qtbot):
    view = make_view(qtbot)
    view.set_rows([{'id': 'a', 'name': '干员甲'}, {'id': 'b', 'name': '干员乙'}],
        EntityChangeSet('before', 'after', operators=[{'id': 'b', 'kind': 'added'}]))
    view.only_new.setChecked(True)
    view.search.setText('没有这位干员')
    qtbot.waitUntil(lambda: any(button.isVisible() for button in view.search.findChildren(QToolButton)))
    clear = next(button for button in view.search.findChildren(QToolButton) if button.isVisible())
    qtbot.mouseClick(clear, Qt.MouseButton.LeftButton)
    assert not view.search.text() and view.only_new.isChecked()
    assert [row['id'] for row in view.model.rows] == ['b']
    qtbot.mouseClick(view.clear_filters_button, Qt.MouseButton.LeftButton)
    assert not view.only_new.isChecked()
    assert view.model.rowCount() == 2


def test_export_actions_follow_available_selection(qtbot):
    view = make_view(qtbot)
    view.set_rows([{'id': 'a', 'name': '干员甲'}],
        EntityChangeSet('before', 'after', operators=[{'id': 'removed', 'kind': 'removed'}]))
    assert not view.export_selected.isEnabled()
    view.table.selectRow(0)
    assert view.export_selected.isEnabled() and view.preview_selected.isEnabled()
    view.table.selectRow(1)
    assert not view.export_selected.isEnabled() and not view.preview_selected.isEnabled()


def test_filter_recovery_requests_the_same_profile_again_and_multi_select_has_a_hint(qtbot):
    view = make_view(qtbot)
    view.set_rows([{'id': 'a', 'name': '干员甲'}, {'id': 'b', 'name': '干员乙'}])
    requests = []
    view.profile_requested.connect(lambda entity_id, spec: requests.append(entity_id))
    view.table.selectRow(0)
    view.set_profile(OperatorProfile('a', '单项正文标记'))
    assert '单项正文标记' in view.details.toPlainText()
    view.search.setText('无匹配')
    assert '单项正文标记' not in view.details.toPlainText()
    view.clear_filters()
    view.table.selectRow(0)
    assert requests == ['a', 'a']
    view.set_profile(OperatorProfile('a', '重新加载的正文'))
    assert '重新加载的正文' in view.details.toPlainText()
    view.table.selectAll()
    assert '重新加载的正文' not in view.details.toPlainText()
    assert '已选择 2 项' in view.details.toPlainText()
    assert view.preview_selected.isEnabled()


@pytest.mark.parametrize('kind', ['operators', 'modules'])
@pytest.mark.parametrize('size', [(1050, 700), (1450, 930)])
def test_footer_actions_fit_without_overlap_at_supported_sizes(qtbot, kind, size):
    view = make_view(qtbot, kind)
    view.resize(*size)
    view.set_rows([{'id': f'id_{index}', 'name': f'资料 {index}'} for index in range(30)])
    if kind == 'modules':
        view.check_all_visible()
        view.search.setText('资料 1')
    else:
        view.table.selectAll()
    qtbot.wait(1)
    controls = [view.count, view.select_all_button, view.preview_selected,
                view.export_new, view.export_selected]
    if kind == 'modules':
        controls.append(view.clear_checked_button)
    bounds = []
    for control in controls:
        rect = QRect(control.mapTo(view, QPoint(0, 0)), control.size())
        assert view.rect().contains(rect), (control, rect, view.rect())
        assert all(not rect.intersects(other) for other in bounds)
        bounds.append(rect)
        if control is not view.count:
            assert control.width() >= control.sizeHint().width()
