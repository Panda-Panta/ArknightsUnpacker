"""One row per property compares the unequipped and all module levels together."""
from copy import deepcopy

from arknights_unpacker.contracts import ModuleProfile, ReportDocument
from arknights_unpacker.reports.model import semantic_blocks, text_report


def module():
    result = ModuleProfile('equip_matrix', 'char_matrix', '对照干员', '横向模组', 'X',
        metadata={'comparison_build': {'phase': 2, 'level': 90, 'potential': 6, 'trust': 200}})
    original = '未装备天赋：赋予一名友方单位'
    for level, bonus in ((1, 27), (2, 35), (3, 41)):
        trait = '对空攻击提升至110%'
        talents = [] if level == 1 else [{'name': '共同天赋', 'talent_index': 0,
            'description': f'{level}级天赋正文', 'potential_delta': '+2',
            'comparison': {'original': original, 'previous': original if level == 2 else '2级天赋正文',
                           'current': f'{level}级天赋正文', 'previous_level': level - 1}}]
        result.phases.append({'level': level, 'trait': trait, 'talents': talents,
            'attributes': [{'key': 'atk', 'label': '攻击', 'value': bonus}],
            'comparison': {'panel_applies': True, 'reason': '', 'previous_level': level - 1,
                'attributes': [{'key': 'atk', 'label': '攻击', 'unit': '', 'before': 657,
                                'bonus': bonus, 'after': 657 + bonus, 'delta': bonus}],
                'trait': {'original': '优先攻击空中单位', 'current': trait, 'previous': trait}}})
    return result


def blocks(profile):
    return [block for block in semantic_blocks(ReportDocument('对照', modules=[profile])) if block.group == '模组']


def test_all_equipped_levels_share_one_attribute_matrix_and_keep_totals():
    profile = module()
    before = deepcopy(profile)
    parts = blocks(profile)
    attributes, = [block for block in parts if block.kind == 'module-attributes']
    assert attributes.columns == ['项目', '未装备', '1级', '2级', '3级']
    assert attributes.cells == [['攻击', '657', '684（+27）', '692（+35）', '698（+41）']]
    assert all(block.stage is None for block in parts)
    assert len({block.entry_id for block in parts}) == 1
    assert not any('横向模组 · ' in block.title for block in parts)
    assert profile == before


def test_trait_and_talent_compare_baseline_and_all_levels_without_diff_paragraphs():
    profile = module()
    effects, = [block for block in blocks(profile) if block.kind == 'module-effects']
    trait = next(row for row in effects.cells if row[0] == '特性')
    assert trait == ['特性', '优先攻击空中单位', '对空攻击提升至110%', '同1级', '同1级']
    talent = next(row for row in effects.cells if '共同天赋' in row[0])
    assert talent[1:] == ['未装备天赋：赋予一名友方单位', '同未装备', '2级天赋正文', '3级天赋正文']
    text = text_report(ReportDocument('对照', modules=[profile]))
    assert '较2级变化' not in text and '本级效果' not in text
    assert '潜能增量' in text and '+2' in text


def test_missing_level_and_conditional_panel_are_explicit_without_invented_totals():
    profile = module()
    profile.phases = profile.phases[:1] + profile.phases[2:]
    stage = profile.phases[-1]
    stage['comparison'].update(reason='conditional', panel_applies=False)
    stage['comparison']['attributes'][0]['after'] = None
    attributes, = [block for block in blocks(profile) if block.kind == 'module-attributes']
    assert attributes.cells[0][3] == '未提供'
    assert '+41' in attributes.cells[0][4] and '限定条件' in attributes.cells[0][4]
    assert '698' not in attributes.cells[0][4]


def test_different_scopes_remain_distinct_and_same_public_text_is_not_duplicated():
    profile = module()
    stage = profile.phases[1]
    effect = stage['talents'][0]
    stage['talents'].append(deepcopy(effect))  # Public and implementation aliases.
    conditional = deepcopy(effect)
    conditional['scope'] = {'validInMapTag': 'map-special'}
    conditional['comparison']['current'] = '限定地图效果'
    conditional['description'] = '限定地图效果'
    stage['talents'].append(conditional)
    effects, = [block for block in blocks(profile) if block.kind == 'module-effects']
    talents = [row for row in effects.cells if '共同天赋' in row[0]]
    assert len(talents) == 2
    assert sum(row[3].count('2级天赋正文') for row in talents) == 1
    assert any('具体范围未确认' in row[0] and '限定地图效果' in row[3] for row in talents)
    assert all('map-special' not in cell for row in talents for cell in row)


def test_legacy_bonus_only_profile_and_token_values_do_not_become_panel_totals():
    profile = ModuleProfile('legacy', 'owner', '旧干员', '旧模组', phases=[
        {'level': 1, 'trait': '旧特性', 'attributes': [{'key': 'atk', 'label': '攻击', 'value': 20}],
         'token_attributes': {'token_one': {'max_hp': 50}},
         'token_effects': [{'name': '召唤物天赋', 'description': '召唤物效果'}]}])
    parts = blocks(profile)
    attributes, = [block for block in parts if block.kind == 'module-attributes']
    assert attributes.cells[0][1] == '未提供'
    assert '加成' in attributes.cells[0][2] and '+20' in attributes.cells[0][2]
    summons, = [block for block in parts if block.kind == 'module-summons']
    assert any('召唤物1' in row[0] and '生命上限' in row[0] and '+50' in row[2] for row in summons.cells)
    assert 'token_one' not in text_report(ReportDocument('旧模组', modules=[profile]))
    assert any('召唤物效果' in row[2] for row in summons.cells)
    assert all(row[1] == '未提供' for row in summons.cells)
