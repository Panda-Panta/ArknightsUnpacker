"""Semantic entry boundaries used by HTML controls, without changing raw data."""
from copy import deepcopy

from arknights_unpacker.contracts import ModuleProfile, OperatorProfile, ReportDocument
from arknights_unpacker.reports.model import Block, semantic_blocks, text_report


def module_data(**overrides):
    value = {'equip_id': 'equip_main', 'char_id': 'char_owner', 'char_name': '干员甲',
             'type_name': 'X', 'name': '完整模组', 'diagnostics': ['模组来源已保留'],
             'phases': [
                 {'level': 1, 'trait': '阶段一特性',
                  'attributes': [{'label': '攻击', 'value': 12}],
                  'talents': [{'name': None, 'description': '阶段一天赋内容',
                               'potential_delta': '+2', 'scope': {'isToken': True, 'tokenKey': 'token_one'}}],
                  'token_effects': [{'name': None, 'description': '召唤物阶段一强化',
                                     'potential_delta': '+3', 'scope': {'game_tag_meta': '限定玩法'}}],
                  'token_attributes': {'token_one': {'max_hp': 50}},
                  'scope': {'validInMapTag': 'map-one'}},
                 {'level': '3', 'trait': '阶段三特性',
                  'attributes': [{'label': '生命上限', 'value': 250}],
                  'talents': [{'name': '', 'description': '阶段三天赋内容', 'potential_delta': '+4'}]},
             ]}
    value.update(overrides)
    return value


def test_block_adds_optional_entry_fields_without_breaking_legacy_construction():
    block = Block('旧标题', [('内容', '旧格式')], ['列'], [['值']], '技能')
    assert block.entry_id == ''
    assert block.entry_title == ''
    assert block.stage is None


def test_skill_entries_keep_identity_without_showing_unresolved_parameters():
    operator = OperatorProfile('char_owner', '干员甲', skills=[
        {'index': 1, 'id': 'skill_one', 'name': '主技能甲', 'description': '倍率 {ratio}',
         'blackboard': {'ratio': 2.5}, 'diagnostics': ['unresolved placeholder ratio']},
        {'index': 2, 'id': 'skill_two', 'name': '主技能乙', 'description': '技能乙内容'},
    ])
    blocks = [block for block in semantic_blocks(ReportDocument('资料', [operator])) if block.group == '技能']
    assert len(blocks) == 2
    assert blocks[0].entry_id != blocks[1].entry_id
    assert blocks[0].entry_id and 'char_owner' in blocks[0].entry_id and 'skill_one' in blocks[0].entry_id
    assert [block.entry_title for block in blocks] == ['主技能甲', '主技能乙']
    assert all(block.stage is None for block in blocks)
    assert ('说明', '倍率 （效果未确认）') in blocks[0].rows
    visible = text_report(ReportDocument('资料', [operator]))
    assert 'ratio' not in visible and 'skill_one' not in visible
    assert operator.skills[0]['blackboard'] == {'ratio': 2.5}


def test_module_categories_share_main_entry_and_compare_stages_without_losing_content():
    data = module_data()
    original = deepcopy(data)
    profile = ModuleProfile(**data)
    document = ReportDocument('资料', modules=[profile])
    blocks = [block for block in semantic_blocks(document) if block.group == '模组']
    assert len(blocks) < 9
    assert len({block.entry_id for block in blocks}) == 1
    assert blocks[0].entry_id and 'char_owner' in blocks[0].entry_id and 'equip_main' in blocks[0].entry_id
    assert {block.entry_title for block in blocks} == {blocks[0].title}
    assert all(block.stage is None for block in blocks)
    assert {'module-info', 'module-attributes', 'module-effects', 'module-summons'} <= {block.kind for block in blocks}
    assert all(block.columns == ['项目', '未装备', '1级', '2级', '3级'] for block in blocks if block.columns)
    assert '完整模组' in blocks[0].entry_title
    assert all('None' not in block.title for block in blocks)
    assert profile.phases == original['phases'], 'formatting must not rename raw talents or alter game values'
    text = text_report(document)
    for phrase in ('阶段一特性', '阶段三特性', '阶段一天赋内容', '阶段三天赋内容',
                   '召唤物阶段一强化', '限定玩法', '限定地图/模式，具体范围未确认', '召唤物1', '+2', '+3', '+4', '50', '250'):
        assert phrase in text
    for internal in ('map-one', 'token_one', '模组来源已保留', 'char_owner', 'equip_main'):
        assert internal not in text


def test_embedded_modules_fall_back_to_owner_and_keep_distinct_entries():
    operator = OperatorProfile('char_embedded', '嵌入干员', modules=[
        module_data(char_id='', equip_id='equip_first', name='第一模组'),
        module_data(char_id='', equip_id='equip_second', name='第二模组'),
    ])
    blocks = [block for block in semantic_blocks(ReportDocument('资料', [operator])) if block.group == '模组']
    entries = {block.entry_id for block in blocks}
    assert len(entries) == 2
    assert all('char_embedded' in entry for entry in entries)
    assert any('equip_first' in entry for entry in entries)
    assert any('equip_second' in entry for entry in entries)
    assert all('阶段属性' not in block.entry_title and '天赋：' not in block.entry_title for block in blocks)


def test_missing_names_have_chinese_player_fallbacks_and_do_not_mutate_input():
    operator = OperatorProfile('char_names', None, skills=[{'index': 1, 'id': 'skill_names', 'name': None}],
                               talents=[{'name': None, 'description': '天赋仍有内容'}],
                               building_skills=[{'name': '   ', 'description': '后勤仍有内容'}],
                               modules=[module_data(char_name=None, type_name=None, name=None)])
    original = deepcopy(operator)
    blocks = semantic_blocks(ReportDocument('资料', [operator]))
    assert all('None' not in block.title and block.title.strip() for block in blocks)
    assert any('未命名技能' in block.title for block in blocks)
    assert any('未命名天赋' in block.title or '天赋调整' in block.title for block in blocks)
    assert any('未命名后勤技能' in block.title for block in blocks)
    assert any('未命名模组' in block.title for block in blocks)
    assert operator == original


def test_entry_keys_are_stable_when_unrelated_entries_are_added():
    first = OperatorProfile('char_stable', '干员', skills=[{'id': 'stable_skill', 'name': '原技能'}],
                            modules=[module_data(equip_id='stable_module')])
    before = semantic_blocks(ReportDocument('资料', [first]))
    modified = deepcopy(first)
    modified.skills.insert(0, {'id': 'other_skill', 'name': '新技能'})
    modified.modules.insert(0, module_data(equip_id='other_module', name='新模组'))
    after = semantic_blocks(ReportDocument('资料', [modified]))
    for title in ('原技能', '干员甲 · X · 完整模组'):
        assert {block.entry_id for block in before if block.entry_title == title} == {
            block.entry_id for block in after if block.entry_title == title}
        assert {block.entry_id for block in before if block.entry_title == title}


def test_missing_skill_and_module_state_blocks_have_no_synthetic_selectable_entries():
    blocks = semantic_blocks(ReportDocument('资料', [OperatorProfile('empty', '无条目')]))
    states = [block for block in blocks if block.group in {'技能', '模组'}]
    assert len(states) == 2
    assert all(block.entry_id == '' and block.stage is None for block in states)


def test_missing_ids_use_distinct_repeatable_index_fallbacks():
    operator = OperatorProfile('char_fallback', '回退干员',
                               skills=[{'name': '同名技能', 'index': ''}, {'name': '同名技能', 'index': None}],
                               modules=[module_data(equip_id=None), module_data(equip_id=None)])
    document = ReportDocument('资料', [operator])
    blocks = semantic_blocks(document)
    for group in ('技能', '模组'):
        first = {block.entry_id for block in blocks if block.group == group}
        second = {block.entry_id for block in semantic_blocks(document) if block.group == group}
        assert len(first) == 2 and first == second


def test_empty_module_talent_stub_is_not_displayed_but_source_records_remain():
    empty = {'name': None, 'description': '', 'potential_delta': {}, 'talent_index': -1,
             'blackboard': [], 'scope': {'validModeIndices': None, 'tokenKey': None},
             'unlock_condition': {'level': 60, 'phase': 'PHASE_2'}}
    talents = [empty,
               {**empty, 'description': '未命名但有实际天赋效果'},
               {**empty, 'potential_delta': {'atk': {'before': 1, 'after': 2, 'delta': 1}}},
               {**empty, 'blackboard': [{'key': 'unresolved_parameter', 'value': 4}]}]
    module = ModuleProfile(**module_data(phases=[{'level': 3, 'trait': '已有特性', 'talents': talents}]))
    original = deepcopy(module)
    blocks = semantic_blocks(ReportDocument('资料', modules=[module]))
    effects, = [block for block in blocks if block.kind == 'module-effects']
    talents = [row for row in effects.cells if '未命名天赋' in row[0]]
    assert len(talents) == 1  # One category row retains these unnamed records together.
    assert '未命名但有实际天赋效果' in talents[0][4]
    assert '效果未确认' in talents[0][4]
    assert '攻击相关潜能效果有变化，幅度未确认' in text_report(ReportDocument('资料', modules=[module]))
    assert module == original
    assert module.phases[0]['talents'][0] == empty
