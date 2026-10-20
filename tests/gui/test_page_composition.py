from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest
from PySide6.QtWidgets import QWidget

from arknights_unpacker.contracts import BuildSpec
from arknights_unpacker.ui.main_window import MainWindow
from test_explorer import MockServices, wait_idle


def make_window(qtbot, tmp_path, **kwargs):
    services = MockServices(tmp_path)
    window = MainWindow(services, **kwargs)
    qtbot.addWidget(window)
    return window, services


def test_inserting_page_does_not_rename_another_page_when_queue_changes(qtbot, tmp_path):
    window, _ = make_window(qtbot, tmp_path)
    inserted = QWidget()
    window.tabs.insertTab(0, inserted, '附加页面')
    window.queue.paused = True
    window.queue.submit('等待处理', lambda **kw: None)

    assert window.tabs.tabText(window.tabs.indexOf(window.modules)) == '模组更新'
    assert window.tabs.tabText(window.tabs.indexOf(window.jobs)) == '导出任务 (1)'
    assert window.tabs.tabText(window.tabs.indexOf(inserted)) == '附加页面'


@pytest.mark.parametrize('removed', ['explorer', 'updates', 'operators', 'modules'])
def test_omitting_optional_page_keeps_scan_load_queue_and_state_working(qtbot, tmp_path, removed):
    from arknights_unpacker.ui.pages import PAGE_DEFINITIONS

    definitions = [page for page in PAGE_DEFINITIONS if page.page_id != removed]
    window, services = make_window(qtbot, tmp_path, page_definitions=definitions)
    assert getattr(window, removed) is None
    assert window.jobs is not None and window.settings is not None
    game = tmp_path / 'game'
    game.mkdir()
    window.root_edit.setText(str(game))
    window.scan()
    wait_idle(qtbot, window)
    window.load_data()
    wait_idle(qtbot, window)
    window.hours.setValue(48)
    window.remember_view_state()
    window.restore_view_state()
    # The compatibility entry point remains safe even without its feature page.
    window.profile(removed, 'missing', BuildSpec())
    assert window.tabs.tabText(window.tabs.indexOf(window.jobs)) == '导出任务'
    assert services.loaded == 1
    assert services.config['view_states'][str(game.resolve())]['tab'] in {
        page.page_id for page in definitions
    }


@pytest.mark.parametrize('module_name,page_id', [
    ('explorer', 'explorer'), ('updates', 'updates'),
    ('operator_view', 'operators'), ('module_view', 'modules'),
])
def test_missing_optional_module_does_not_prevent_main_window_import_or_use(tmp_path, module_name, page_id):
    source_root = Path(__file__).resolve().parents[2] / 'src'
    script = '''
import importlib.abc
from pathlib import Path
import sys
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication

missing, page_id, data_root = sys.argv[1:]
class MissingPage(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'arknights_unpacker.ui.' + missing:
            raise ModuleNotFoundError('optional page removed', name=fullname)
sys.meta_path.insert(0, MissingPage())
from arknights_unpacker.ui.main_window import MainWindow
app = QApplication([])
services = SimpleNamespace(data_root=Path(data_root), config={}, installation=None,
    scan_snapshot=None, gamedata=None, entity_changes=None, operators=lambda: [],
    modules=lambda: [], save_config=lambda: None)
window = MainWindow(services)
assert getattr(window, page_id) is None
assert window.jobs is not None and window.settings is not None
window.refresh_entities()
window._hours_changed()
window.queue.paused = True
window.queue.submit('waiting', lambda **kw: None)
assert window.tabs.tabText(window.tabs.indexOf(window.jobs)) == '导出任务 (1)'
window.close()
'''
    env = {**os.environ, 'PYTHONPATH': str(source_root), 'QT_QPA_PLATFORM': 'offscreen'}
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', script, module_name, page_id,
                             str(tmp_path / 'data')], env=env, capture_output=True, text=True,
                            encoding='utf-8', timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_page_id_and_individual_state_survive_reordered_registry_and_removed_page(qtbot, tmp_path):
    from arknights_unpacker.ui.pages import PAGE_DEFINITIONS, PageController, PageDefinition

    class ExtraPage(PageController):
        def create_view(self):
            return QWidget()

    definitions = (PageDefinition('extra', '附加页面', ExtraPage), *reversed(PAGE_DEFINITIONS))
    window, services = make_window(qtbot, tmp_path, page_definitions=definitions)
    window.root_edit.setText(str(tmp_path))
    services.load_data(str(tmp_path))
    window.refresh_entities()
    window.operators.search.setText('交互')
    window.modules.search.setText('模组')
    window.updates.search.setText('sample')
    window.explorer.recursive.setChecked(True)
    window.tabs.setCurrentWidget(window.modules)
    window._view_state_ready = True
    window.remember_view_state()
    saved = services.config['view_states'][str(tmp_path.resolve())]
    assert saved['tab'] == 'modules'
    assert saved['pages']['operators']['search'] == '交互'
    window._view_state_ready = False
    window.close()

    # Saving with one page absent keeps that page's saved filters for its return.
    reduced = [page for page in definitions if page.page_id != 'operators']
    reopened = MainWindow(services, page_definitions=reduced)
    qtbot.addWidget(reopened)
    reopened.root_edit.setText(str(tmp_path))
    reopened.refresh_entities()
    reopened.restore_view_state()
    assert reopened.tabs.currentWidget() is reopened.modules
    assert reopened.modules.search.text() == '模组'
    assert reopened.updates.search.text() == 'sample'
    assert reopened.explorer.recursive.isChecked()
    reopened._view_state_ready = True
    reopened.remember_view_state()
    assert services.config['view_states'][str(tmp_path.resolve())]['pages']['operators']['search'] == '交互'
    reopened._view_state_ready = False
    reopened.close()

    returned = MainWindow(services)
    qtbot.addWidget(returned)
    returned.root_edit.setText(str(tmp_path))
    returned.refresh_entities()
    returned.restore_view_state()
    assert returned.operators.search.text() == '交互'
    assert returned.tabs.currentWidget() is returned.modules


@pytest.mark.parametrize('legacy_index,page_id', enumerate(
    ('explorer', 'updates', 'operators', 'modules', 'jobs', 'settings')))
def test_legacy_numeric_tab_and_page_fields_restore_by_original_page_identity(qtbot, tmp_path, legacy_index, page_id):
    from arknights_unpacker.ui.pages import PAGE_DEFINITIONS

    window, services = make_window(qtbot, tmp_path, page_definitions=tuple(reversed(PAGE_DEFINITIONS)))
    window.root_edit.setText(str(tmp_path))
    services.load_data(str(tmp_path))
    window.refresh_entities()
    window.explorer.set_root(str(tmp_path))
    services.config['view_states'] = {str(tmp_path.resolve()): {
        'tab': legacy_index, 'explorer_recursive': True, 'explorer_ab': True,
        'explorer_search': 'archive', 'update_mode': 1, 'update_ab': True,
        'update_search': 'sample', 'operators': {'search': '交互', 'selected_id': 'char_fixture'},
        'modules': {'search': '模组'},
    }}
    window.restore_view_state()
    assert window.tabs.currentWidget() is window.pages.widget(page_id)
    assert window.explorer.recursive.isChecked() and window.explorer.ab_only.isChecked()
    assert window.explorer.search.text() == 'archive'
    assert window.updates.mode.currentIndex() == 1 and window.updates.ab_only.isChecked()
    assert window.updates.search.text() == 'sample'
    assert window.operators.search.text() == '交互'
    assert window.modules.search.text() == '模组'
    wait_idle(qtbot, window)

