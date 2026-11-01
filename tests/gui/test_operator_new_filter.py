"""Both entity pages expose additions as their only status filter."""
from arknights_unpacker.contracts import EntityChangeSet
from arknights_unpacker.ui.entity_view import EntityView
from test_explorer import make_window


def test_operator_and_module_pages_offer_only_the_new_filter(qtbot):
    for kind in ('operators', 'modules'):
        view = EntityView(kind)
        qtbot.addWidget(view)
        view.show()
        assert view.only_new.isVisible()
        assert not view.only_changes.isVisible()


def test_only_new_excludes_existing_changes_and_initial_inventory(qtbot):
    view = EntityView('operators')
    qtbot.addWidget(view)
    rows = [{'id': identity, 'name': identity} for identity in ('new', 'modified', 'unchanged')]
    view.only_new.setChecked(True)
    view.set_rows(rows)
    assert view.model.rows == []
    view.set_rows(rows, EntityChangeSet('before', 'after', operators=[
        {'id': 'new', 'kind': 'added'}, {'id': 'modified', 'kind': 'modified'}]))
    assert [row['id'] for row in view.model.rows] == ['new']


def test_old_operator_changes_filter_is_ignored_on_restore(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    services.load_data(str(tmp_path))
    window.refresh_entities()
    page = window.pages._pages['operators']
    page.restore_state({'only_changes': True, 'only_new': False})
    assert not window.operators.only_changes.isChecked()
    assert window.operators.model.rowCount() == 1
    assert 'only_changes' not in page.save_state()
