"""Entity details keep current operator parameters without historical sections."""
from copy import deepcopy
import json
from pathlib import Path

from PySide6.QtWidgets import QTextBrowser

from arknights_unpacker.contracts import DecodedTable, EntityChangeSet, TableSourceSet, as_jsonable
from arknights_unpacker.gamedata import build_module, build_operator, load_gamedata
from arknights_unpacker.reports.model import present
from arknights_unpacker.ui.entity_view import EntityView
from arknights_unpacker.ui.report_preview import profile_html


def reference_data():
    fixture = json.loads((Path(__file__).parents[1] / 'gamedata/fixtures/fixed_reference.json').read_text('utf-8'))
    return load_gamedata(TableSourceSet(
        tables={name: DecodedTable(name, value) for name, value in fixture['tables'].items()},
        version=fixture['version'], resource_version=fixture['resource_version'], locale='zh_CN'))


def operator_changes(profile, kind='modified'):
    current = as_jsonable(profile)
    previous = {
        'attributes': [{'key': 'atk', 'label': '攻击', 'value': -1234567}],
        'skills': [{'name': '历史技能标记', 'description': '历史技能说明'}],
        'building_skills': [{'name': '历史后勤标记', 'description': '历史后勤说明', 'unlock': {'phase': 0, 'level': 1}}],
        'talents': [{'name': '历史天赋标记', 'description': '历史天赋说明'}],
        'trait': '历史特性标记',
    }
    return EntityChangeSet('old', 'current', operators=[{
        'id': profile.char_id, 'name': profile.name, 'kind': kind,
        'changes': [{'field': name, 'before': before, 'after': current[name]}
                    for name, before in previous.items()]}])


def assert_no_operator_history(text):
    for marker in ('属性更新', '技能更新', '后勤技能更新', '天赋更新', '特性更新', '更新前', '更新后',
                   '历史技能标记', '历史后勤标记', '历史天赋标记', '历史特性标记', '-1234567'):
        assert marker not in text


def test_operator_selection_shows_complete_current_profile_without_calling_history_renderer(qtbot, monkeypatch):
    profile = build_operator(reference_data(), 'char_4231_clemnt')
    changes = operator_changes(profile)
    original_profile, original_changes = deepcopy(as_jsonable(profile)), deepcopy(as_jsonable(changes))
    view = EntityView('operators')
    qtbot.addWidget(view)
    history_calls = []
    original_diff = view.diff_html
    monkeypatch.setattr(view, 'diff_html', lambda identity: history_calls.append(identity) or original_diff(identity))
    view.set_rows([{'id': profile.char_id, 'name': profile.name}], changes)
    requests = []
    view.profile_requested.connect(lambda identity, spec: requests.append(identity))
    view.table.selectRow(0)
    assert requests == [profile.char_id]
    view.set_profile(profile)
    text = view.details.toPlainText()
    assert history_calls == []
    assert_no_operator_history(text)
    current_only = QTextBrowser()
    qtbot.addWidget(current_only)
    current_only.setHtml(profile_html(profile))
    assert text == current_only.toPlainText()
    assert profile.name in text and '1065' in text
    assert all(skill['name'] in text for skill in profile.skills)
    assert all(skill['name'] in text for skill in profile.building_skills)
    assert all(present('unlock', skill['unlock']) in text for skill in profile.building_skills)
    assert as_jsonable(profile) == original_profile
    assert as_jsonable(changes) == original_changes


def test_removed_operator_is_identified_without_historical_values_or_export(qtbot, monkeypatch):
    profile = build_operator(reference_data(), 'char_4231_clemnt')
    view = EntityView('operators')
    qtbot.addWidget(view)
    history_calls = []
    original_diff = view.diff_html
    monkeypatch.setattr(view, 'diff_html', lambda identity: history_calls.append(identity) or original_diff(identity))
    view.set_rows([], operator_changes(profile, 'removed'))
    view.table.selectRow(0)
    assert history_calls == []
    assert '已删除' in view.details.toPlainText()
    assert_no_operator_history(view.details.toPlainText())
    assert not view.export_selected.isEnabled()
    assert not view.preview_selected.isEnabled()


def test_module_detail_still_includes_its_independent_history(qtbot):
    module = build_module(reference_data(), 'uniequip_002_angel')
    changes = EntityChangeSet('old', 'current', modules=[{
        'id': module.equip_id, 'name': module.name, 'kind': 'modified',
        'changes': [{'field': 'phases', 'before': [{'level': 1, 'trait': '历史模组参数标记'}],
                     'after': as_jsonable(module.phases)}]}])
    view = EntityView('modules')
    qtbot.addWidget(view)
    view.set_rows([{'id': module.equip_id, 'name': module.name}], changes)
    view.table.selectRow(0)
    view.set_profile(module)
    text = view.details.toPlainText()
    assert module.name in text
    assert '历史模组参数标记' in text
    assert '更新前' in text and '更新后' in text


def test_operator_empty_details_describe_current_parameters(qtbot):
    view = EntityView('operators')
    qtbot.addWidget(view)
    assert '更新变化' not in view.details.toPlainText()
    view.clear_data()
    assert '更新变化' not in view.details.toPlainText()
    assert '当前' in view.details.toPlainText()
