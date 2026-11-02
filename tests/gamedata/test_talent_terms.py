"""Talent glossary definitions stay separate from gameplay descriptions."""
from copy import deepcopy
import json
from pathlib import Path

from arknights_unpacker.contracts import DecodedTable, SourceRef, TableSourceSet
from arknights_unpacker.gamedata import build_module, build_operator, compare_entities, load_gamedata
from arknights_unpacker.gamedata.descriptions import render_description


BURNING = '累计满时爆发（普通、精英敌人1000点、领袖2000点累计值），敌人立即受到7000点元素伤害且期间法术抗性-20。10秒冷却'
TERMS = {'ba.dt.burning2': {'description': BURNING}}
TALULAH = '攻击造成法术伤害；造成法术伤害时附带13%<@ba.talpu>（+2%）</>的<$ba.dt.burning2>灼燃损伤</>；停止攻击3秒后法术和元素伤害逐渐提升（最高提升18%<@ba.talpu>（+3%）</>，每次攻击时衰减）'


def data_with_terms():
    raw = json.loads((Path(__file__).parent / 'fixtures/fixed_reference.json').read_text('utf-8'))
    data = load_gamedata(TableSourceSet(tables={
        name: DecodedTable(name, value, SourceRef(path='talent-term-fixture'))
        for name, value in raw['tables'].items()}, version=raw['version'],
        resource_version=raw['resource_version']))
    data.tables['gamedata_const']['termDescriptionDict'].update(TERMS)
    return data


def test_talulah_terms_move_out_without_removing_potential_or_condition_parentheses():
    definitions = []
    text, diagnostics = render_description(TALULAH, terms=TERMS, term_definitions=definitions)
    assert text == '攻击造成法术伤害；造成法术伤害时附带13%（+2%）的灼燃损伤；停止攻击3秒后法术和元素伤害逐渐提升（最高提升18%（+3%），每次攻击时衰减）'
    assert definitions == [{'term': '灼燃损伤', 'description': BURNING}]
    assert not diagnostics


def test_multiple_and_repeated_terms_keep_order_and_decode_text():
    definitions = []
    terms = {'burn': {'description': '满时爆发&amp;伤害'}, 'stun': {'description': '无法行动<br>持续1秒'}}
    text, diagnostics = render_description('<$burn>灼燃</>与<$stun>晕眩</>，再施加<$burn>灼燃</>',
                                           terms=terms, term_definitions=definitions)
    assert text == '灼燃与晕眩，再施加灼燃'
    assert definitions == [{'term': '灼燃', 'description': '满时爆发&伤害'},
                           {'term': '晕眩', 'description': '无法行动\n持续1秒'}]
    assert not diagnostics


def test_default_rendering_keeps_inline_terms_for_other_description_types():
    text, diagnostics = render_description('<$ba.dt.burning2>灼燃损伤</>', terms=TERMS)
    assert text == f'灼燃损伤（{BURNING}）'
    assert not diagnostics


def test_collector_can_be_reused_without_duplicate_definitions():
    definitions = []
    for _ in range(2):
        render_description('<$ba.dt.burning2>灼燃损伤</>', terms=TERMS, term_definitions=definitions)
    assert definitions == [{'term': '灼燃损伤', 'description': BURNING}]


def test_nested_definitions_are_clean_and_retained():
    definitions = []
    terms = {'resist': {'description': '<$stun>晕眩</>的持续时间减半'},
             'stun': {'description': '无法移动和攻击'}}
    text, diagnostics = render_description('获得<$resist>抵抗</>', terms=terms, term_definitions=definitions)
    assert text == '获得抵抗'
    assert definitions == [{'term': '抵抗', 'description': '晕眩的持续时间减半'},
                           {'term': '晕眩', 'description': '无法移动和攻击'}]
    assert not diagnostics


def test_unknown_terms_remain_diagnostic_and_recursive_terms_terminate():
    definitions = []
    text, diagnostics = render_description('<$missing>未知</>', term_definitions=definitions)
    assert text == '未知 [术语:missing]'
    assert diagnostics == ['unresolved term: missing'] and definitions == []
    text, diagnostics = render_description('<$loop>循环</>', terms={'loop': {'description': '<$loop>循环</>'}},
                                           term_definitions=definitions)
    assert text == '循环'
    assert definitions == [{'term': '循环', 'description': '循环'}]
    assert not diagnostics


def test_cold_and_frozen_mutual_references_are_valid_glossary_links():
    definitions = []
    terms = {'ba.cold': {'description': '攻击速度下降30，再次受到寒冷则变为<$ba.frozen>冻结</>'},
             'ba.frozen': {'description': '无法移动和攻击（通过<$ba.cold>寒冷</>触发）'}}
    text, diagnostics = render_description('施加<$ba.cold>寒冷</>', terms=terms, term_definitions=definitions)
    assert text == '施加寒冷'
    assert definitions == [
        {'term': '寒冷', 'description': '攻击速度下降30，再次受到寒冷则变为冻结'},
        {'term': '冻结', 'description': '无法移动和攻击（通过寒冷触发）'}]
    assert not diagnostics


def test_operator_talents_collect_terms_without_changing_skills_or_source_tables():
    data = data_with_terms()
    character = data.tables['character_table']['char_4231_clemnt']
    for candidate in character['talents'][0]['candidates']:
        candidate['description'] = TALULAH
    skill = data.tables['skill_table'][character['skills'][0]['skillId']]['levels'][-1]
    skill['description'] = '<$ba.dt.burning2>灼燃损伤</>'
    original = deepcopy(data.tables)
    profile = build_operator(data, 'char_4231_clemnt')
    assert BURNING not in profile.talents[0]['description']
    assert profile.talents[0]['term_definitions'] == [{'term': '灼燃损伤', 'description': BURNING}]
    assert BURNING in profile.skills[0]['description']
    assert data.tables == original


def test_module_talents_and_original_comparison_collect_their_definitions():
    data = data_with_terms()
    character = data.tables['character_table']['char_103_angel']
    for candidate in character['talents'][1]['candidates']:
        candidate['description'] += '，造成<$ba.dt.burning2>灼燃损伤</>'
    for phase in data.tables['battle_equip_table']['uniequip_002_angel']['phases']:
        for part in phase['parts']:
            if part['target'] == 'TALENT':
                for candidate in part['addOrOverrideTalentDataBundle']['candidates']:
                    candidate['description'] = '强化后的<$ba.dt.burning2>灼燃损伤</>（原条件不变）'
    original = deepcopy(data.tables)
    module = build_module(data, 'uniequip_002_angel')
    effect = module.phases[-1]['talents'][0]
    assert effect['description'] == '强化后的灼燃损伤（原条件不变）'
    assert BURNING not in effect['comparison']['original']
    assert effect['term_definitions'] == [{'term': '灼燃损伤', 'description': BURNING}]
    assert data.tables == original


def test_module_retains_original_only_terms_for_the_unmodified_table_column():
    data = data_with_terms()
    for candidate in data.tables['character_table']['char_103_angel']['talents'][1]['candidates']:
        candidate['description'] += '，造成<$ba.dt.burning2>灼燃损伤</>'
    effect = build_module(data, 'uniequip_002_angel').phases[-1]['talents'][0]
    assert '灼燃损伤' in effect['comparison']['original']
    assert BURNING not in effect['comparison']['original']
    assert not effect.get('term_definitions')
    assert effect['comparison']['original_term_definitions'] == [{'term': '灼燃损伤', 'description': BURNING}]


def test_original_talent_glossary_does_not_create_a_module_gameplay_change():
    before = data_with_terms()
    after = deepcopy(before)
    before.locale = after.locale = 'zh_CN'
    for candidate in after.tables['character_table']['char_103_angel']['talents'][1]['candidates']:
        candidate['description'] += '，造成<$ba.dt.burning2>灼燃损伤</>'
    changes = compare_entities(before, after)
    operator = next(row for row in changes.operators if row['char_id'] == 'char_103_angel')
    assert 'modules' not in operator['fields']
    assert not changes.modules
