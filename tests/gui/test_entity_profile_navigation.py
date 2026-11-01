"""Navigation belongs only to the operator page's current single-detail browser."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from arknights_unpacker.contracts import EntityChangeSet, ReportArtifact
from arknights_unpacker.gamedata import build_operator
from arknights_unpacker.ui.entity_view import EntityView
from arknights_unpacker.ui.report_preview import ReportArtifactsDialog
from test_operator_current_detail import reference_data


def targets(navigation):
    return [navigation.sections.itemData(index) for index in range(navigation.sections.count())
            if navigation.sections.itemData(index) is not None]


def select_id(view, identity):
    row = next(index for index, record in enumerate(view.model.rows) if record['id'] == identity)
    view.table.selectRow(row)


def test_navigation_is_embedded_above_operator_details_and_absent_from_modules(qtbot):
    from arknights_unpacker.ui.profile_navigation import ProfileNavigation

    operator, module = EntityView('operators'), EntityView('modules')
    qtbot.addWidget(operator)
    qtbot.addWidget(module)
    navigation = operator.findChildren(ProfileNavigation)
    assert len(navigation) == 1
    assert operator.profile_navigation is operator.navigation is navigation[0]
    assert operator.profile_navigation.parentWidget() is operator.details.parentWidget()
    layout = operator.details.parentWidget().layout()
    assert layout.indexOf(operator.profile_navigation) < layout.indexOf(operator.details)
    assert not module.findChildren(ProfileNavigation)
    assert module.profile_navigation is None


def test_changing_single_operator_clears_old_navigation_while_loading_and_refills_it(qtbot):
    data = reference_data()
    first = build_operator(data, 'char_4231_clemnt')
    second = build_operator(data, 'char_103_angel')
    view = EntityView('operators')
    qtbot.addWidget(view)
    view.set_rows([{'id': first.char_id, 'name': first.name}, {'id': second.char_id, 'name': second.name}])
    select_id(view, first.char_id)
    view.set_profile(first)
    navigation = view.profile_navigation
    assert len(targets(navigation)) > 3 and navigation.sections.isEnabled()
    assert first.name in view.details.toPlainText()
    select_id(view, second.char_id)
    assert targets(navigation) == [] and not navigation.sections.isEnabled()
    assert '正在读取当前资料' in view.details.toPlainText()
    assert first.name not in view.details.toPlainText()
    view.set_profile(second)
    assert targets(navigation) and navigation.sections.isEnabled()
    assert second.name in view.details.toPlainText()


def test_multi_empty_removed_and_clear_data_reset_navigation_without_erasing_placeholders(qtbot):
    profile = build_operator(reference_data(), 'char_4231_clemnt')
    view = EntityView('operators')
    qtbot.addWidget(view)
    view.set_rows([{'id': profile.char_id, 'name': profile.name}, {'id': 'other', 'name': '另一干员'}],
                  EntityChangeSet('old', 'current', operators=[{'id': 'removed', 'name': '已删除干员', 'kind': 'removed'}]))
    select_id(view, profile.char_id)
    view.set_profile(profile)
    navigation = view.profile_navigation
    assert targets(navigation)
    view.table.selectAll()
    assert targets(navigation) == [] and not navigation.sections.isEnabled()
    assert '已选择 3 项' in view.details.toPlainText()
    view.table.clearSelection()
    assert targets(navigation) == [] and '从列表中选择一项' in view.details.toPlainText()
    select_id(view, profile.char_id)
    view.set_profile(profile)
    select_id(view, 'removed')
    assert targets(navigation) == [] and '已删除' in view.details.toPlainText()
    assert not view.export_selected.isEnabled()
    select_id(view, profile.char_id)
    view.set_profile(profile)
    view.clear_data()
    assert targets(navigation) == [] and not navigation.sections.isEnabled()
    assert '从列表中选择一项' in view.details.toPlainText()


def test_png_preview_window_does_not_gain_operator_navigation(qtbot, tmp_path):
    from arknights_unpacker.ui.profile_navigation import ProfileNavigation

    source = tmp_path / 'page.png'
    image = QImage(200, 400, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.white)
    assert image.save(str(source))
    dialog = ReportArtifactsDialog([ReportArtifact(str(source), 'png')])
    qtbot.addWidget(dialog)
    assert not dialog.findChildren(ProfileNavigation)
