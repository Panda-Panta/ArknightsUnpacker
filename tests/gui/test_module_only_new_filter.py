"""Module additions remain filterable without restoring the retired changes filter."""
from copy import deepcopy
from types import SimpleNamespace

from arknights_unpacker.contracts import as_jsonable
from arknights_unpacker.ui.pages import ModulesPage
from test_module_export_layout import check_id, modules


def ids(view):
    return {row['id'] for row in view.model.rows}


def test_module_new_filter_selects_added_alias_and_excludes_changed_removed_or_unknown(qtbot):
    view = modules(qtbot)
    original = deepcopy(as_jsonable(view.changes))
    view.only_new.setChecked(True)
    assert ids(view) == {'equip_new', 'equip_new_alias'}
    view.search.setText('另一新增')
    assert ids(view) == {'equip_new_alias'}
    view.clear_filters()
    assert ids(view) == {'equip_new', 'equip_new_alias', 'equip_changed', 'equip_same', 'equip_gone'}
    assert as_jsonable(view.changes) == original
    initial = modules(qtbot, baseline=None)
    initial.only_new.setChecked(True)
    assert ids(initial) == set()
    assert not initial.export_new.isEnabled()


def test_hidden_legacy_module_filter_never_changes_current_results(qtbot):
    view = modules(qtbot)
    before = ids(view)
    view.only_changes.setChecked(True)
    assert ids(view) == before
    assert not view.clear_filters_button.isEnabled()
    view.only_new.setChecked(True)
    assert ids(view) == {'equip_new', 'equip_new_alias'}


def test_checked_modules_and_export_scope_survive_only_new_and_search(qtbot):
    view = modules(qtbot)
    check_id(view, 'equip_changed')
    check_id(view, 'equip_new')
    view.only_new.setChecked(True)
    view.search.setText('另一新增')
    assert ids(view) == {'equip_new_alias'}
    assert view.checked_ids == {'equip_changed', 'equip_new'}
    exports = []
    view.export_requested.connect(lambda selected, only_new: exports.append((set(selected), only_new)))
    view.request_export(False)
    view.request_export(True)
    assert exports == [({'equip_changed', 'equip_new'}, False), ({'equip_new', 'equip_new_alias'}, True)]
    view.clear_filters()
    assert view.checked_ids == {'equip_changed', 'equip_new'}
    assert not view.only_new.isChecked()


def test_legacy_module_change_state_is_ignored_and_not_saved(qtbot):
    page = ModulesPage(SimpleNamespace())
    qtbot.addWidget(page.view)
    fixture = modules(qtbot)
    page.view.set_rows([dict(row) for row in fixture.all_rows if row['status'] != 'removed'], fixture.changes)
    before = ids(page.view)
    page.restore_state({'only_changes': True, 'only_new': False})
    assert not page.view.only_changes.isChecked()
    assert ids(page.view) == before
    assert 'only_changes' not in page.save_state()
    page.restore_state(page.legacy_state({'modules': {'only_changes': True, 'only_new': True, 'search': '新增'}}))
    assert not page.view.only_changes.isChecked()
    assert ids(page.view) == {'equip_new', 'equip_new_alias'}
    saved = page.save_state()
    assert saved['only_new'] is True and saved['search'] == '新增'
    assert 'only_changes' not in saved
