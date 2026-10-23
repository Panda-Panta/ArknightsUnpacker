"""Player dossiers must retain every building-skill unlock stage."""
import copy
import json
from pathlib import Path

import pytest

from arknights_unpacker.contracts import BuildSpec, DecodedTable, TableSourceSet, as_jsonable
from arknights_unpacker.gamedata import build_operator, compare_entities, load_gamedata


def snapshot():
    fixture = json.loads((Path(__file__).parent / 'fixtures/fixed_reference.json').read_text(encoding='utf-8'))
    return load_gamedata(TableSourceSet(
        tables={name: DecodedTable(name, value) for name, value in fixture['tables'].items()},
        version=fixture['version'], resource_version=fixture['resource_version'], locale='zh_CN'))


@pytest.mark.parametrize('spec', [BuildSpec(), BuildSpec(phase=0, level=1, potential=1, trust=0)])
def test_all_building_versions_are_retained_at_any_selected_build(spec):
    profile = build_operator(snapshot(), 'char_103_angel', spec)
    assert [(item['name'], item['unlock'], item['slot']) for item in profile.building_skills] == [
        ('企鹅物流·α', {'phase': 'PHASE_0', 'level': 1}, 1),
        ('物流专家', {'phase': 'PHASE_2', 'level': 1}, 1)]
    assert all(item['description'] and item['room'] == 'TRADING' for item in profile.building_skills)
    assert [item['id'] for item in as_jsonable(profile)['building_skills']] == [
        'trade_ord_spd[010]', 'trade_ord_spd[020]']


def test_low_star_level_unlocks_and_separate_slots_are_kept():
    profile = build_operator(snapshot(), 'char_009_12fce', BuildSpec(phase=0, level=1))
    assert [(item['name'], item['unlock']['level'], item['slot']) for item in profile.building_skills] == [
        ('线索搜集·β', 1, 1), ('特训记录', 30, 2)]


def test_stage_order_uses_unlock_conditions_and_keeps_same_name_versions():
    data = snapshot()
    building = data.tables['building_data']
    entries = building['chars']['char_103_angel']['buffChar'][0]['buffData']
    entries.reverse()
    building['buffs']['trade_ord_spd[020]']['buffName'] = '企鹅物流·α'
    profile = build_operator(data, 'char_103_angel')
    assert [item['unlock']['phase'] for item in profile.building_skills] == ['PHASE_0', 'PHASE_2']
    assert [item['name'] for item in profile.building_skills] == ['企鹅物流·α', '企鹅物流·α']
    assert profile.building_skills[0]['description'] != profile.building_skills[1]['description']


def test_form_inherits_all_stages_from_original_character():
    data = snapshot()
    data.tables['character_table']['char_form_test'] = copy.deepcopy(data.tables['character_table']['char_103_angel'])
    data.tables['_indexes'].setdefault('forms', {})['char_form_test'] = 'char_103_angel'
    original = build_operator(data, 'char_103_angel')
    form = build_operator(data, 'char_form_test')
    assert len(original.building_skills) == 2
    assert form.building_skills == original.building_skills


def test_missing_stage_reference_retains_unlock_and_reports_incomplete_effect():
    data = snapshot()
    del data.tables['building_data']['buffs']['trade_ord_spd[010]']
    profile = build_operator(data, 'char_103_angel')
    assert len(profile.building_skills) == 2
    missing = profile.building_skills[0]
    assert missing['id'] == 'trade_ord_spd[010]'
    assert missing['unlock'] == {'phase': 'PHASE_0', 'level': 1}
    assert missing['description'] is None
    assert any('unresolved buff trade_ord_spd[010]' in message for message in profile.diagnostics)


def test_change_to_earlier_stage_is_a_building_skill_change():
    before = snapshot()
    after = copy.deepcopy(before)
    after.tables['building_data']['buffs']['trade_ord_spd[010]']['description'] += '更新后的说明'
    change = next(item for item in compare_entities(before, after).operators if item['char_id'] == 'char_103_angel')
    assert 'building_skills' in change['categories']
    assert 'raw_fields_only' not in change['categories']
