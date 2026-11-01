"""Entity changes ignore presentation bookkeeping, retaining unrendered gameplay."""
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path

import pytest

from arknights_unpacker.contracts import DecodedTable, OperatorProfile, SourceRef, TableSourceSet, as_jsonable
from arknights_unpacker.gamedata import compare_entities, load_gamedata
from arknights_unpacker.gamedata.diff import _business


def sources():
    raw = json.loads((Path(__file__).parent / 'fixtures/fixed_reference.json').read_text('utf-8'))
    return TableSourceSet(
        tables={name: DecodedTable(name, value, SourceRef(path=raw['sources'][name]['url']))
                for name, value in raw['tables'].items()},
        version=raw['version'], resource_version=raw['resource_version'], locale='zh_CN')


def test_early_business_projection_matches_old_json_projection_with_nested_types_and_large_sources():
    class Unit(Enum):
        SECONDS = '秒'

    @dataclass
    class Effect:
        values: dict
        source: dict

    source = {'field_evidence': {'fields': {str(index): 'source-only text' for index in range(10000)}}}
    path = Path('nested/example')
    profile = OperatorProfile('char_test', '测试干员',
        summary={1: (Unit.SECONDS, path, {2, 3}), 'nested': [Effect({4: Unit.SECONDS}, source)]},
        attributes=[{'key': 'atk', 'value': 123, 'sources': {'base': source}}],
        skills=[{'name': '技能', 'source': source, 'diagnostics': ['excluded'],
                 'comparison': {'before': 1, 'after': 2}}],
        metadata=source)
    # The reference takes the old full JSON conversion route. The direct route
    # must retain its public value types and string dictionary keys exactly.
    expected = _business(as_jsonable(profile))
    assert _business(profile) == expected
    assert expected['summary'] == {
        '1': ['秒', str(path), [2, 3]],
        'nested': [{'values': {'4': '秒'}}]}
    assert expected['attributes'] == [{'key': 'atk', 'value': 123}]
    assert expected['skills'] == [{'name': '技能'}]
    assert 'metadata' not in expected


def test_business_projection_never_walks_excluded_source_payloads():
    class SourcePayload(dict):
        def items(self):
            raise AssertionError('business comparison traversed discarded source evidence')

    source = SourcePayload({'large': 'source-only data'})
    profile = OperatorProfile('char_test', '测试干员', metadata=source,
        attributes=[{'key': 'atk', 'value': 123, 'sources': source}])
    result = _business(profile)
    assert result['attributes'] == [{'key': 'atk', 'value': 123}]
    assert 'metadata' not in result


def test_presentation_sort_changes_do_not_mark_every_operator_modified():
    original = sources()
    before = load_gamedata(original)
    for index, record in enumerate(original.tables['character_table'].data.values()):
        record['sortIndex'] = index + 100
    after = load_gamedata(original)
    assert after.snapshot_id != before.snapshot_id
    changes = compare_entities(before, after)
    assert changes.operators == []
    assert changes.modules == []


def test_module_promotion_window_is_not_a_module_or_operator_parameter_change():
    original = sources()
    before = load_gamedata(original)
    original.tables['uniequip_table'].data['equipDict']['uniequip_002_angel']['uniEquipShowEnd'] = 1793487600
    after = load_gamedata(original)
    changes = compare_entities(before, after)
    assert changes.modules == []
    assert changes.operators == []


def test_changed_source_hashes_paths_versions_and_key_order_are_not_entity_changes():
    original = sources()
    before = load_gamedata(original)
    original.version = 'new-game-version'
    original.resource_version = 'new-resource-version'
    for name, table in original.tables.items():
        table.source = SourceRef(path=f'other/path/{name}.ab', sha256='changed-table-hash')
        table.data = dict(reversed(list(table.data.items())))
    changes = compare_entities(before, load_gamedata(original))
    assert changes.operators == []
    assert changes.modules == []


def test_unrendered_gameplay_fields_remain_real_raw_changes():
    original = sources()
    before = load_gamedata(original)
    original.tables['character_table'].data['char_009_12fce']['phases'][0]['attributesKeyFrames'][0]['data']['stunImmune'] = True
    changes = compare_entities(before, load_gamedata(original))
    assert [row['id'] for row in changes.operators] == ['char_009_12fce']
    assert changes.operators[0]['categories'] == ['raw_fields_only']
    assert changes.operators[0]['raw_changed'] is True


def test_earlier_cultivation_attribute_is_not_lost_when_maximum_profile_is_unchanged():
    original = sources()
    before = load_gamedata(original)
    original.tables['character_table'].data['char_4231_clemnt']['phases'][0]['attributesKeyFrames'][0]['data']['atk'] += 1
    changes = compare_entities(before, load_gamedata(original))
    assert [row['id'] for row in changes.operators] == ['char_4231_clemnt']
    assert changes.operators[0]['categories'] == ['raw_fields_only']


def test_shared_skill_earlier_level_change_reaches_every_owner():
    original = sources()
    character = original.tables['character_table'].data
    character['char_009_12fce']['skills'] = [deepcopy(character['char_4231_clemnt']['skills'][0])]
    before = load_gamedata(original)
    original.tables['skill_table'].data['skchr_clemnt_1']['levels'][0]['description'] += '低等级调整'
    changes = compare_entities(before, load_gamedata(original))
    assert {row['id'] for row in changes.operators} == {'char_009_12fce', 'char_4231_clemnt'}
    assert all(row['raw_changed'] for row in changes.operators)
    assert changes.modules == []


def test_module_low_stage_attributes_change_the_module_and_its_owner_only():
    original = sources()
    before = load_gamedata(original)
    original.tables['battle_equip_table'].data['uniequip_002_angel']['phases'][0]['attributeBlackboard'][0]['value'] += 1
    changes = compare_entities(before, load_gamedata(original))
    assert [row['id'] for row in changes.modules] == ['uniequip_002_angel']
    assert changes.modules[0]['fields'] == ['phases']
    assert [row['id'] for row in changes.operators] == ['char_103_angel']
    assert 'modules' in changes.operators[0]['fields']


@pytest.mark.parametrize('field', ['unlockLevel', 'uniEquipGetTime'])
def test_module_unlock_and_availability_parameters_remain_sensitive_outside_the_rendered_profile(field):
    original = sources()
    before = load_gamedata(original)
    original.tables['uniequip_table'].data['equipDict']['uniequip_002_angel'][field] += 1
    changes = compare_entities(before, load_gamedata(original))
    assert [row['id'] for row in changes.modules] == ['uniequip_002_angel']
    assert changes.modules[0]['raw_changed'] is True
    assert [row['id'] for row in changes.operators] == ['char_103_angel']


def test_added_and_removed_entities_are_still_identified_by_stable_ids():
    original = sources()
    before = load_gamedata(original)
    characters = original.tables['character_table'].data
    characters['char_test_new'] = characters.pop('char_009_12fce')
    equipment = original.tables['uniequip_table'].data['equipDict']
    equipment['uniequip_test_new'] = equipment.pop('uniequip_002_angel')
    battle = original.tables['battle_equip_table'].data
    battle['uniequip_test_new'] = battle.pop('uniequip_002_angel')
    changes = compare_entities(before, load_gamedata(original))
    operators = {row['id']: row['kind'] for row in changes.operators}
    modules = {row['id']: row['kind'] for row in changes.modules}
    assert operators['char_test_new'] == 'added'
    assert operators['char_009_12fce'] == 'removed'
    assert modules == {'uniequip_test_new': 'added', 'uniequip_002_angel': 'removed'}


@pytest.mark.parametrize('mismatch', ['locale', 'normalization', 'incomplete'])
def test_incompatible_or_partial_snapshots_cannot_confirm_changes(mismatch):
    before = load_gamedata(sources())
    after = deepcopy(before)
    after.tables['character_table']['char_009_12fce']['name'] += '更新'
    if mismatch == 'locale':
        after.locale = 'en_US'
    elif mismatch == 'normalization':
        after.tables['_normalization_version'] += 1
    else:
        after.complete = False
    changes = compare_entities(before, after)
    assert changes.operators == []
    assert changes.modules == []
    assert changes.diagnostics


def test_first_snapshot_is_an_inventory_not_all_added():
    changes = compare_entities(None, load_gamedata(sources()))
    assert changes.operators == []
    assert changes.modules == []
    assert changes.baseline_id is None
