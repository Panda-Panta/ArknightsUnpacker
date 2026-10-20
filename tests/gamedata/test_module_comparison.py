"""Module comparisons use the same build and panel rules as operator profiles."""
from copy import deepcopy
import importlib
import json
from pathlib import Path

import pytest

from arknights_unpacker.contracts import BuildSpec, DecodedTable, SourceRef, TableSourceSet
from arknights_unpacker.gamedata import build_module, build_operator, compare_entities, load_gamedata


def snapshot(filename='fixed_reference.json'):
    raw = json.loads((Path(__file__).parent / 'fixtures' / filename).read_text('utf-8'))
    return load_gamedata(TableSourceSet(
        tables={name: DecodedTable(name, value, SourceRef(path=raw['sources'][name].get('url', 'fixture')))
                for name, value in raw['tables'].items()},
        version=raw['version'], resource_version=raw['resource_version']))


def test_each_stage_compares_same_build_without_accumulating_stage_totals():
    data = snapshot()
    original = deepcopy(data.tables)
    module = build_module(data, 'uniequip_002_angel')
    base = build_operator(data, module.char_id)
    base_atk = next(row['value'] for row in base.attributes if row['key'] == 'atk')
    expected = [(27, 27), (35, 8), (41, 6)]
    for stage, (bonus, increase) in zip(module.phases, expected):
        comparison = stage['comparison']
        row = next(row for row in comparison['attributes'] if row['key'] == 'atk')
        equipped = build_operator(data, module.char_id, BuildSpec(module_id=module.equip_id, module_level=stage['level']))
        assert row['before'] == base_atk
        assert row['bonus'] == bonus and row['delta'] == increase
        assert row['after'] == next(row['value'] for row in equipped.attributes if row['key'] == 'atk')
        assert row['after'] - row['before'] == bonus
    assert module.phases[2]['comparison']['previous_level'] == 2
    assert data.tables == original


def test_talent_comparison_separates_original_previous_stage_and_potential():
    data = snapshot()
    module = build_module(data, 'uniequip_002_angel')
    second = module.phases[1]['talents'][0]
    third = module.phases[2]['talents'][0]
    assert '一名随机友方单位' in second['comparison']['original']
    assert second['comparison']['previous'] == second['comparison']['original']
    assert '两名随机友方单位' in second['comparison']['current']
    assert third['comparison']['previous'] == second['description']
    assert '攻击力+10%' in third['comparison']['current']
    assert third['potential_delta']['atk']['delta'] == 0.02
    assert module.phases[1]['comparison']['trait']['changed_from_previous'] is False
    low = build_module(data, module.equip_id, BuildSpec(potential=1))
    assert '攻击力+8%' in low.phases[2]['talents'][0]['comparison']['current']
    assert not low.phases[2]['talents'][0]['potential_delta']


def test_token_effects_do_not_block_personal_stats_and_cost_reduction_keeps_sign():
    data = snapshot('local_module_regressions.json')
    ling = build_module(data, 'uniequip_002_ling')
    assert ling.phases[-1]['comparison']['panel_applies'] is True
    rows = {row['key']: row for row in ling.phases[-1]['comparison']['attributes']}
    assert rows['atk']['after'] - rows['atk']['before'] == 50
    assert rows['maxHp']['bonus'] == 150
    assert all(effect['comparison']['original'] is None for effect in ling.phases[-1]['token_effects'])
    dusk = build_module(data, 'uniequip_003_dusk')
    row = next(row for row in dusk.phases[-1]['comparison']['attributes'] if row['key'] == 'cost')
    assert row['bonus'] == -8 and row['delta'] == 0
    assert row['after'] == row['before'] - 8
    talent = next(t for t in dusk.phases[-1]['talents'] if t['name'] == '点睛')
    assert '每2.5秒' in talent['comparison']['previous']
    assert '每1.5秒' in talent['comparison']['current']


def test_unavailable_or_conditional_module_never_claims_unconditional_equipped_panel():
    data = snapshot()
    locked = build_module(data, 'uniequip_002_angel', BuildSpec(phase=0, level=1))
    assert locked.phases[0]['comparison']['panel_applies'] is False
    assert locked.phases[0]['comparison']['reason'] == 'locked'
    assert all(row['after'] is None for row in locked.phases[0]['comparison']['attributes'])
    data.tables['uniequip_table']['equipDict']['uniequip_002_angel']['isSpecialEquip'] = True
    conditional = build_module(data, 'uniequip_002_angel')
    assert conditional.phases[2]['comparison']['reason'] == 'conditional'
    assert all(row['after'] is None for row in conditional.phases[2]['comparison']['attributes'])


def test_missing_trust_is_preserved_as_unknown_in_comparison():
    data = snapshot()
    del data.tables['favor_table']
    stage = build_module(data, 'uniequip_002_angel').phases[-1]
    atk = next(row for row in stage['comparison']['attributes'] if row['key'] == 'atk')
    assert atk['bonus'] == 41 and atk['before'] is None and atk['after'] is None


def test_module_build_no_longer_calls_operator_implementation(monkeypatch):
    # Public build_module must remain usable if the operator implementation is replaced.
    operators = importlib.import_module('arknights_unpacker.gamedata.operators')
    monkeypatch.setattr(operators, 'build_state', lambda *_: pytest.fail('module depends on operators.build_state'))
    monkeypatch.setattr(operators, 'metadata', lambda *_: pytest.fail('module depends on operators.metadata'))
    assert build_module(snapshot(), 'uniequip_002_angel').phases


def test_derived_comparisons_do_not_turn_text_only_changes_into_mechanics_changes():
    before = snapshot()
    after = deepcopy(before)
    before.locale = after.locale = 'zh_CN'
    for candidate in after.tables['character_table']['char_103_angel']['talents'][1]['candidates']:
        candidate['description'] += '文字勘误'
    changes = compare_entities(before, after)
    operator = next(row for row in changes.operators if row['char_id'] == 'char_103_angel')
    assert 'text_only' in operator['categories']
    assert 'modules' not in operator['fields']
    assert not changes.modules


@pytest.mark.parametrize(('target', 'name'), [('TALENT', None), ('TALENT_DATA_ONLY', '天使的祝福')])
def test_implementation_record_cannot_replace_previous_public_effect(target, name):
    # Real module shapes include another target or an unnamed implementation
    # record with the same talent index and scope as the public upgrade.
    data = snapshot()
    battle = data.tables['battle_equip_table']['uniequip_002_angel']
    original = build_module(data, 'uniequip_002_angel').phases[1]['talents'][0]['description']
    part = deepcopy(battle['phases'][1]['parts'][-1])
    part['target'] = target
    for candidate in part['addOrOverrideTalentDataBundle']['candidates']:
        candidate.update(name=name, description='另一个实现条目的内容', upgradeDescription='')
    battle['phases'][1]['parts'].append(part)
    module = build_module(data, 'uniequip_002_angel')
    assert module.phases[2]['talents'][0]['comparison']['previous'] == original


def test_unique_named_effect_keeps_its_predecessor_when_implementation_target_changes():
    data = snapshot()
    battle = data.tables['battle_equip_table']['uniequip_002_angel']
    battle['phases'][1]['parts'][-1]['target'] = 'TALENT_DATA_ONLY'
    module = build_module(data, 'uniequip_002_angel')
    assert module.phases[2]['talents'][0]['comparison']['previous'] == module.phases[1]['talents'][0]['description']
