"""Readable reports keep gameplay facts while JSON retains technical evidence."""
from copy import deepcopy
from html.parser import HTMLParser
import json
from pathlib import Path

from arknights_unpacker.contracts import (
    DecodedTable, ExportFormat, ModuleProfile, OperatorProfile, ReportDocument, ReportOptions,
    SourceRef, TableSourceSet, as_jsonable,
)
from arknights_unpacker.gamedata import build_operator, load_gamedata
from arknights_unpacker.reports import export_report
from arknights_unpacker.reports.html_render import render_html
from arknights_unpacker.reports.model import display_title, present, semantic_blocks, text_report
from arknights_unpacker.reports.render import layout_pages


class VisibleText(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.skip = 0
        self.parts = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.skip -= 1

    def handle_data(self, text):
        if not self.skip:
            self.parts.append(text)


def document():
    source = {'table': 'raw_source_table', 'sha256': 'raw_sha_123456', 'path': 'D:/raw_source_path',
              'pointer': '/raw_pointer/field'}
    module = ModuleProfile('uniequip_private_id', 'char_private_id', '测试干员', '战术模组', 'X',
        metadata={'source': source, 'version': 'raw_module_version', 'comparison_build': {
            'phase': 2, 'level': 90, 'potential': 6, 'trust': 200},
            'unlock_condition': {'phase': 'PHASE_2', 'level': 60},
            'special_equip': True, 'special_equip_description': '仅指定作战模式生效'},
        diagnostics=['unsupported raw_module_diagnostic'])
    for level in (1, 2, 3):
        module.phases.append({'level': level, 'trait': f'第{level}级特性效果', 'source': source,
            'attributes': [{'key': 'atk', 'label': '攻击', 'value': level * 10},
                           {'key': 'raw_attribute_key', 'label': 'raw_attribute_key', 'value': 912345}],
            'scope': {'validInMapTag': 'map_private_id', 'validModeIndices': [987654]},
            'token_attributes': {'token_private_a': {'max_hp': 50}, 'token_private_b': {'atk': 20}},
            'token_effects': [{'name': '召唤物强化', 'description': '仅强化指定召唤物',
                              'scope': {'tokenKey': 'token_private_b', 'isToken': True}}],
            'talents': [{'name': '模组天赋', 'description': f'第{level}级天赋效果',
                         'scope': {'validInGameTag': '可确认的中文玩法'},
                         'potential_delta': {'attack_speed': {'before': 10, 'after': 12, 'delta': 2},
                                             'raw_potential_key': {'before': 7, 'after': 9, 'delta': 2}}}],
            'diagnostics': ['missing raw_phase_diagnostic']})
    operator = OperatorProfile('char_private_id', '测试干员',
        summary={'profession': 'SNIPER', 'sub_profession': 'raw_subprofession', 'rarity': 'TIER_6',
                 'phase': 2, 'level': 90, 'potential': 6, 'trust': 200, 'form_of': 'char_private_form'},
        trait='优先攻击空中单位',
        attributes=[{'key': 'atk', 'label': '攻击', 'value': 657, 'base': 540, 'trust': 90,
                     'potential': 27, 'module': 0, 'unit': ''}],
        skills=[{'id': f'skchr_private_{index}', 'index': index, 'name': f'战术技能{index}',
                 'description': '攻击提升，倍率 {raw_placeholder}' if index == 1 else f'第{index}技能完整效果',
                 'source': source, 'blackboard': {'raw_blackboard_key': 1.5},
                 'diagnostics': ['unresolved raw_skill_diagnostic'], 'sp_type': 'INCREASE_WITH_TIME',
                 'trigger': 'MANUAL', 'level': '专精3', 'sp_cost': 30} for index in (1, 2, 3)],
        talents=[{'name': '天赋名称', 'description': '攻击速度提升', 'unlock_condition': {'phase': 2, 'level': 1}}],
        building_skills=[{'id': 'raw_building_id', 'name': '制造专长', 'description': '生产效率提升', 'room': 'MANUFACTURE'}],
        potentials=['部署费用-1'], modules=[as_jsonable(module)],
        metadata={'source': source, 'version': 'raw_game_version', 'resource_version': 'raw_resource_version',
                  'field_evidence': {'raw_field_reader': {'path': 'raw_reader_path'}}},
        diagnostics=['missing raw_operator_diagnostic'])
    return ReportDocument('玩家资料', operators=[operator], modules=[module],
        options=ReportOptions(width=700, font_size=20, max_page_height=4000),
        metadata={'generated_at': 'raw_generation_time', 'template_version': 'raw_template_version',
            'changes': {'baseline_id': 'raw_baseline', 'current_id': 'raw_current',
                'operators': [{'id': operator.char_id, 'name': operator.name, 'kind': 'modified',
                    'changes': [{'field': 'skills', 'before': [{'id': 'skchr_private_1', 'description': '旧技能效果', 'source': source}],
                                 'after': [{'id': 'skchr_private_1', 'description': '新技能效果', 'blackboard': {'raw_diff_key': 5}}]},
                                {'field': 'raw_private_field', 'before': 'raw_old_value', 'after': 'raw_new_value'}]}],
                'modules': [], 'diagnostics': ['raw_change_diagnostic']}})


def test_readable_formats_remove_technical_fields_without_losing_gameplay_or_json(tmp_path):
    report = document()
    before = deepcopy(as_jsonable(report))
    text = text_report(report)
    html = ''.join(VisibleText(render_html(report)).parts)
    lines = [line for page in layout_pages(report) for line in page]
    # Read wrapped tables down each column, without interleaving adjacent cells.
    png = ''.join(line.text for line in lines if not line.cells) + '\n'.join(
        ''.join(line.cells[column] for line in lines if len(line.cells) > column)
        for column in range(max(len(line.cells) for line in lines)))
    for output in (text, html, png):
        for phrase in ('狙击', '分支未确认', '657', '战术技能1', '战术技能2', '战术技能3',
                       '第3技能完整效果', '制造专长', '部署费用-1', '战术模组', '1级', '2级', '3级',
                       '精英2', '60级', '仅指定作战模式生效', '可确认的中文玩法', '具体范围未确认',
                       '召唤物1', '召唤物2', '生命上限', '效果未确认'):
            assert phrase in output
        assert '旧技能效果' not in output and '新技能效果' not in output
        for internal in ('raw_', 'char_private', 'skchr_private', 'uniequip_private', 'token_private',
                         'map_private', '987654', '912345', 'SHA-256', 'JSON', '诊断', '来源与诊断',
                         '资料口径与版本', '干员ID', '模组ID', '技能ID'):
            assert internal not in output
    assert as_jsonable(report) == before
    artifacts = export_report(report, tmp_path, {ExportFormat.JSON})
    saved = json.loads(Path(artifacts[0].path).read_text('utf-8'))
    expected = deepcopy(before)
    expected['metadata'].pop('changes')
    assert saved == expected
    assert saved['operators'][0]['skills'][0]['blackboard'] == {'raw_blackboard_key': 1.5}
    assert saved['modules'][0]['phases'][0]['scope']['validModeIndices'] == [987654]
    assert 'changes' not in saved['metadata']
    entries = [block.entry_id for block in semantic_blocks(report) if block.entry_id]
    assert 'skill:char_private_id:skchr_private_1' in entries
    assert 'module:char_private_id:uniequip_private_id' in entries


def test_legacy_operator_history_of_every_field_and_linked_modules_cannot_change_current_rendering():
    current = document()
    current.metadata.pop('changes')
    current.operators[0].building_skills = [
        {'slot': 1, 'name': '早期制造专长', 'description': '生产效率+10%',
         'room': 'MANUFACTURE', 'unlock': {'phase': 'PHASE_0', 'level': 1}},
        {'slot': 1, 'name': '后期制造专长', 'description': '生产效率+25%',
         'room': 'MANUFACTURE', 'unlock': {'phase': 'PHASE_2', 'level': 30}},
    ]
    legacy = deepcopy(current)
    operator = as_jsonable(current.operators[0])
    module = as_jsonable(current.modules[0])
    # Cover every profile field and both legacy history shapes. The boundary
    # must exclude the history itself, regardless of its labels or payload.
    legacy.metadata['changes'] = {
        'operators': [{'id': operator['char_id'], 'name': operator['name'], 'kind': 'modified',
            'before': {'name': '历史干员旧值', 'trait': '历史特性旧值'},
            'after': {'name': '历史干员新值', 'trait': '历史特性新值'},
            'changes': [{'field': key, 'before': f'历史字段旧值-{key}', 'after': value}
                        for key, value in operator.items()]}],
        'modules': [{'id': module['equip_id'], 'name': module['name'], 'kind': 'modified',
            'changes': [{'field': 'phases', 'before': [{'level': 1, 'trait': '历史模组旧值'}],
                         'after': module['phases']}]}],
    }
    original = deepcopy(as_jsonable(legacy))
    assert semantic_blocks(legacy) == semantic_blocks(current)
    assert text_report(legacy) == text_report(current)
    assert render_html(legacy) == render_html(current)
    assert layout_pages(legacy) == layout_pages(current)
    text = text_report(legacy)
    assert all(value in text for value in ('657', '第3技能完整效果', '早期制造专长', '后期制造专长',
                                           '生产效率+10%', '生产效率+25%', '精英0、1级', '精英2、30级',
                                           '未装备', '1级', '2级', '3级', '第3级特性效果'))
    assert not any(block.group == '更新对照' for block in semantic_blocks(legacy))
    assert as_jsonable(legacy) == original


def test_operator_only_legacy_change_document_does_not_create_an_update_report():
    current = ReportDocument('资料')
    legacy = deepcopy(current)
    legacy.metadata['changes'] = {'operators': [
        {'name': '历史干员', 'kind': 'modified', 'changes': [
            {'field': 'attributes', 'before': [{'key': 'atk', 'value': 100}],
             'after': [{'key': 'atk', 'value': 200}]},
            {'field': 'building_skills', 'before': [{'name': '旧后勤', 'description': '旧效果'}],
             'after': [{'name': '新后勤', 'description': '新效果'}]},
        ]}]}
    assert semantic_blocks(legacy) == semantic_blocks(current)
    assert text_report(legacy) == text_report(current)
    assert render_html(legacy) == render_html(current)
    assert layout_pages(legacy) == layout_pages(current)


def test_metadata_only_module_and_operator_history_cannot_create_a_report():
    current = ReportDocument('模组资料')
    report = ReportDocument('模组资料', metadata={'changes': {'modules': [
        {'name': '模组', 'kind': 'modified', 'changes': [
            {'field': 'phases', 'before': [{'level': 1, 'attributes': [{'key': 'atk', 'value': 20}]}],
             'after': [{'level': 1, 'attributes': [{'key': 'atk', 'value': 30}]}]},
        ]}]}})
    mixed = deepcopy(report)
    mixed.metadata['changes']['operators'] = [
        {'name': '历史干员', 'kind': 'modified', 'changes': [
            {'field': 'trait', 'before': '历史特性旧值', 'after': '历史特性新值'}]}]
    for legacy in (report, mixed):
        original = deepcopy(as_jsonable(legacy))
        assert semantic_blocks(legacy) == semantic_blocks(current)
        assert text_report(legacy) == text_report(current)
        assert render_html(legacy) == render_html(current)
        assert layout_pages(legacy) == layout_pages(current)
        assert as_jsonable(legacy) == original


def test_current_module_all_fields_and_effects_render_identically_with_any_legacy_history():
    current = ReportDocument('当前模组资料', modules=[deepcopy(document().modules[0])],
        options=ReportOptions(width=700, font_size=20, max_page_height=4000))
    legacy = deepcopy(current)
    module = as_jsonable(current.modules[0])
    legacy.metadata['changes'] = {
        'operators': [{'name': '历史干员', 'kind': 'modified',
                       'before': {'trait': '历史特性旧值'}, 'after': {'trait': '历史特性新值'}}],
        'modules': [{'id': module['equip_id'], 'name': module['name'], 'kind': 'modified',
            'before': {'name': '历史模组旧值', 'phases': [{'level': 1, 'trait': '历史模组特性旧值'}]},
            'after': module,
            'changes': [{'field': key, 'before': f'历史字段旧值-{key}', 'after': value}
                        for key, value in module.items()]}],
    }
    original = deepcopy(as_jsonable(legacy))
    assert semantic_blocks(legacy) == semantic_blocks(current)
    assert text_report(legacy) == text_report(current)
    assert render_html(legacy) == render_html(current)
    assert layout_pages(legacy) == layout_pages(current)
    text = text_report(legacy)
    for phrase in ('战术模组', '未装备', '1级', '2级', '3级', '第1级特性效果', '第2级特性效果',
                   '第3级特性效果', '召唤物1', '召唤物2', '生命上限', '仅指定作战模式生效',
                   '可确认的中文玩法', '具体范围未确认', '精英2', '60级', '效果未确认'):
        assert phrase in text
    assert as_jsonable(legacy) == original


def test_potential_effects_keep_confirmed_labels_without_guessing_units():
    value = {'atk': {'before': 0.06, 'after': 0.08, 'delta': 0.02},
             'raw_unknown_ratio': {'before': 0.1, 'after': 0.2, 'delta': 0.1}}
    rendered = present('potential_delta', value)
    assert '攻击相关潜能效果有变化，幅度未确认' in rendered
    assert '部分潜能效果未确认' in rendered
    assert 'raw_unknown_ratio' not in rendered and '%' not in rendered and '0.02' not in rendered


def test_described_potential_increments_are_not_duplicated_but_unique_effects_remain():
    talent = {'name': '祝福', 'description': '攻击力+8%（+2%），生命上限+13%（+3%）',
              'potential_delta': {'atk': {'before': 0.06, 'after': 0.08, 'delta': 0.02},
                                  'max_hp': {'before': 0.1, 'after': 0.13, 'delta': 0.03}}}
    module = ModuleProfile('id', 'owner', '干员', '模组', phases=[
        {'level': level, 'talents': [deepcopy(talent)]} for level in (1, 2, 3)])
    operator = OperatorProfile('owner', '干员', talents=[deepcopy(talent)], potentials=['部署费用-1'])
    report = ReportDocument('资料', operators=[operator], modules=[module])
    original = deepcopy(as_jsonable(report))
    blocks = semantic_blocks(report)
    assert not any(block.kind == 'module-potential' for block in blocks)
    assert not any(key == '潜能增量' for block in blocks if block.group == '天赋' for key, _ in block.rows)
    assert '（+2%）' in text_report(report) and '（+3%）' in text_report(report)
    assert '部署费用-1' in text_report(report)
    assert as_jsonable(report) == original
    operator.talents[0]['potential_delta']['attack_speed'] = {'before': 10, 'after': 12, 'delta': 2}
    text = text_report(report)
    assert '攻击速度相关潜能效果有变化，幅度未确认' in text
    assert '攻击相关潜能效果有变化' not in text
    operator.talents.append({'name': '独有增量', 'description': '强化天赋', 'potential_delta': '攻击速度+2'})
    assert '攻击速度+2' in text_report(report)


def test_unknown_effects_do_not_compact_to_same_stage_or_claim_no_effect():
    module = ModuleProfile('id', 'owner', '干员', '模组', phases=[
        {'level': level, 'talents': [{'name': '未确认天赋', 'blackboard': [{'key': 'unknown', 'value': 1}]}]}
        for level in (1, 2, 3)])
    effects = next(block for block in semantic_blocks(ReportDocument('资料', modules=[module]))
                   if block.kind == 'module-effects')
    row = next(row for row in effects.cells if '未确认天赋' in row[0])
    assert row[2:] == ['效果未确认'] * 3
    assert '无效果' not in text_report(ReportDocument('资料', modules=[module]))


def test_empty_and_technical_only_changes_do_not_create_visible_update_sections():
    report = ReportDocument('资料', operators=[OperatorProfile('char_private', '干员')],
        metadata={'changes': {'baseline_id': 'old', 'current_id': 'new', 'diagnostics': ['private'],
            'operators': [], 'modules': []}})
    assert not any(block.group == '更新对照' for block in semantic_blocks(report))
    report.metadata['changes']['operators'] = [{'id': 'char_private', 'kind': 'modified', 'changes': [
        {'field': 'skills', 'before': [{'id': 'old_id', 'source': {'path': 'old'}}],
         'after': [{'id': 'new_id', 'source': {'path': 'new'}}]},
        {'field': 'metadata', 'before': {'version': 'old'}, 'after': {'version': 'new'}},
    ]}]
    assert not any(block.group == '更新对照' for block in semantic_blocks(report))


def test_history_only_scope_changes_do_not_generate_scope_update_notices():
    for before, after in [({'validInMapTag': 'map-one'}, {'validInMapTag': 'map-two'}),
                          ({'validModeIndices': [1001]}, {'validModeIndices': [1002]}),
                          ({'tokenKey': 'token-a'}, {'tokenKey': 'token-b'})]:
        for field, old, new in [('scope', before, after),
                                ('phases', [{'level': 1, 'scope': before}], [{'level': 1, 'scope': after}])]:
            report = ReportDocument('资料', metadata={'changes': {'modules': [
                {'id': 'private', 'name': '模组', 'kind': 'modified',
                 'changes': [{'field': field, 'before': old, 'after': new}]}]}})
            original = deepcopy(as_jsonable(report))
            text = text_report(report)
            assert text == text_report(ReportDocument('资料'))
            assert all(marker not in text for marker in ('map-one', 'map-two', '1001', '1002', 'token-a', 'token-b'))
            assert as_jsonable(report) == original


def test_complete_flag_keeps_missing_skills_unknown_and_never_exposes_diagnostics():
    profile = OperatorProfile('internal', '残缺资料', metadata={'complete': False},
                              diagnostics=['raw diagnostic details'])
    text = text_report(ReportDocument('资料', operators=[profile]))
    assert '资料不完整' in text and '技能资料不完整' in text
    assert '无技能（' not in text and 'raw diagnostic details' not in text


def test_explicit_branch_names_are_preserved_and_raw_branch_ids_are_not_names():
    for branch_name in ('速射手', 'Marksman'):
        profile = OperatorProfile('owner', '干员', summary={
            'sub_profession': 'fastshot', 'sub_profession_name': branch_name})
        report = ReportDocument('资料', operators=[profile])
        original = deepcopy(as_jsonable(report))
        assert ('分支', branch_name) in next(block for block in semantic_blocks(report) if block.group == '概览').rows
        for text in (text_report(report), ''.join(VisibleText(render_html(report)).parts)):
            assert branch_name in text and 'fastshot' not in text and '分支未确认' not in text
        assert as_jsonable(report) == original
    assert present('sub_profession', 'fastshot') == '分支未确认'
    assert present('sub_profession_name', '') == '分支未确认'


def test_all_building_stages_keep_duplicate_names_unlocks_and_missing_effects(tmp_path):
    from arknights_unpacker.ui.report_preview import profile_html

    skills = [
        {'id': 'raw_buff_1', 'slot': 1, 'name': '后勤专长', 'description': '生产效率+10%',
         'room': 'MANUFACTURE', 'unlock': {'phase': 'PHASE_0', 'level': 1}},
        {'id': 'raw_buff_2', 'slot': 1, 'name': '后勤专长', 'description': '生产效率+25%',
         'room': 'MANUFACTURE', 'unlock': {'phase': 'PHASE_2', 'level': 30}},
        {'id': 'raw_buff_missing', 'slot': 2, 'name': '', 'description': None,
         'room': None, 'unlock': {'phase': 'PHASE_1', 'level': 40}},
    ]
    report = ReportDocument('资料', operators=[OperatorProfile('owner', '干员', building_skills=skills)])
    original = deepcopy(as_jsonable(report))
    blocks = [block for block in semantic_blocks(report) if block.group == '后勤']
    entries = [block for block in blocks if block.title.startswith('后勤 · ')]
    assert len(entries) == 3
    assert blocks == entries, 'The building section should contain actual skill stages without a generic explanation entry.'
    assert [dict(block.rows)['解锁条件'] for block in entries] == ['精英0、1级', '精英2、30级', '精英1、40级']
    assert [block.title for block in entries].count('后勤 · 后勤专长') == 2
    assert dict(entries[-1].rows)['说明'] == '效果未确认'
    png = ''.join(line.text for page in layout_pages(report) for line in page)
    qt_details = ''.join(VisibleText(profile_html(report.operators[0])).parts)
    for text in (text_report(report), ''.join(VisibleText(render_html(report)).parts), png, qt_details):
        assert all(phrase in text for phrase in ('生产效率+10%', '生产效率+25%', '精英2、30级', '精英1、40级',
                                                '制造站', '效果未确认'))
        assert '升级后的技能替换同一位置的旧技能。' not in text
        assert 'raw_buff' not in text and 'slot' not in text and '槽号' not in text
    artifacts = export_report(report, tmp_path, {ExportFormat.JSON})
    assert json.loads(Path(artifacts[0].path).read_text('utf-8')) == original
    assert as_jsonable(report) == original
    legacy = deepcopy(report)
    for skill in legacy.operators[0].building_skills:
        skill.pop('slot')
    assert semantic_blocks(legacy) == semantic_blocks(report)
    assert as_jsonable(report) == original


def test_empty_building_skills_keep_the_missing_data_status_without_generic_explanation():
    from arknights_unpacker.ui.report_preview import profile_html

    report = ReportDocument('资料', operators=[OperatorProfile('owner', '干员')])
    original = deepcopy(as_jsonable(report))
    blocks = [block for block in semantic_blocks(report) if block.group == '后勤']
    assert len(blocks) == 1 and blocks[0].title == '后勤技能'
    assert len(blocks[0].rows) == 1 and blocks[0].rows[0][0] == '状态'
    status = blocks[0].rows[0][1]
    assert status
    png = ''.join(line.text for page in layout_pages(report) for line in page)
    qt_details = ''.join(VisibleText(profile_html(report.operators[0])).parts)
    for text in (text_report(report), ''.join(VisibleText(render_html(report)).parts), png, qt_details):
        assert status in text
        assert '升级后的技能替换同一位置的旧技能。' not in text
    assert as_jsonable(report) == original


def test_real_operator_building_stages_all_reach_readable_reports():
    raw = json.loads((Path(__file__).parents[1] / 'gamedata/fixtures/fixed_reference.json').read_text('utf-8'))
    data = load_gamedata(TableSourceSet(tables={
        name: DecodedTable(name, value, SourceRef(path='fixture')) for name, value in raw['tables'].items()}))
    operator = build_operator(data, 'char_103_angel')
    report = ReportDocument('能天使', operators=[operator])
    before = deepcopy(as_jsonable(report))
    expected = sum(len(slot['buffData']) for slot in raw['tables']['building_data']['chars']['char_103_angel']['buffChar'])
    entries = [block for block in semantic_blocks(report) if block.title.startswith('后勤 · ')]
    assert len(entries) == len(operator.building_skills) == expected == 2
    for text in (text_report(report), ''.join(VisibleText(render_html(report)).parts)):
        assert '20%' in text and '35%' in text
        for skill in operator.building_skills:
            assert skill['name'] in text and present('unlock', skill['unlock']) in text
    assert as_jsonable(report) == before


def test_current_token_attributes_and_unknown_effects_remain_without_their_history():
    cases = [
        ({'token_attributes': {'token-a': {'atk': 20}}}, {'token_attributes': {'token-b': {'atk': 20}}},
         '召唤物1'),
        ({'attributes': [{'key': 'unknown_ratio', 'label': 'unknown_ratio', 'value': 0.06}]},
         {'attributes': [{'key': 'unknown_ratio', 'label': 'unknown_ratio', 'value': 0.08}]},
         '属性效果未确认'),
    ]
    for before, after, expected in cases:
        current = ReportDocument('资料', modules=[ModuleProfile('private', 'owner', '干员', '模组',
            phases=[{'level': 1, **after}])])
        report = deepcopy(current)
        report.metadata['changes'] = {'modules': [
            {'id': 'private', 'name': '模组', 'kind': 'modified', 'changes': [
                {'field': 'phases', 'before': [{'level': 1, **before}], 'after': [{'level': 1, **after}]}]}]}
        original = deepcopy(as_jsonable(report))
        assert semantic_blocks(report) == semantic_blocks(current)
        for text in (text_report(report), ''.join(VisibleText(render_html(report)).parts)):
            assert expected in text
            assert all(internal not in text for internal in ('token-a', 'token-b', 'unknown_ratio', '0.06', '0.08'))
        assert as_jsonable(report) == original


def test_potential_annotation_does_not_remove_another_attributes_unconfirmed_delta():
    talent = {'name': '双属性天赋', 'description': '攻击力+10%且防御力+8%（+2%）', 'potential_delta': {
        'atk': {'before': 0.08, 'after': 0.1, 'delta': 0.02},
        'def': {'before': 0.06, 'after': 0.08, 'delta': 0.02}}}
    report = ReportDocument('资料', operators=[OperatorProfile('owner', '干员', talents=[talent])])
    text = text_report(report)
    assert '攻击相关潜能效果有变化，幅度未确认' in text
    assert '防御相关潜能效果有变化' not in text
    assert '防御力+8%（+2%）' in text


def test_fallback_document_titles_hide_only_confirmed_identity_fallbacks():
    cases = [
        (ReportDocument('char_private', operators=[OperatorProfile('char_private', 'char_private')]), '未命名干员'),
        (ReportDocument('equip_private', modules=[ModuleProfile('equip_private', 'owner', '干员', 'equip_private')]), '未命名模组'),
        (ReportDocument('自定义 char_private 资料', operators=[OperatorProfile('char_private', 'char_private')]), '自定义 char_private 资料'),
        (ReportDocument('  '), '干员与模组资料'),
    ]
    for report, expected in cases:
        original = deepcopy(as_jsonable(report))
        assert display_title(report) == expected
        assert text_report(report).splitlines()[0] == expected
        assert as_jsonable(report) == original


def test_current_attributes_and_scope_do_not_gain_history_blocks_from_either_legacy_shape():
    for old_scope, new_scope, notice in [
        ({'scope': {'validInMapTag': 'map-a'}}, {'scope': {'validInMapTag': 'map-b'}},
         '适用范围有变化，具体范围未确认'),
        ({'token_attributes': {'token-a': {'atk': 20}}}, {'token_attributes': {'token-b': {'atk': 20}}},
         '召唤物适用对象有变化，具体对象未确认'),
    ]:
        before = [{'level': 1, **old_scope, 'attributes': [{'key': 'atk', 'label': '攻击', 'value': 20}]}]
        after = [{'level': 1, **new_scope, 'attributes': [{'key': 'atk', 'label': '攻击', 'value': 30}]}]
        for values in ({'changes': [{'field': 'phases', 'before': before, 'after': after}]},
                       {'before': {'phases': before}, 'after': {'phases': after}}):
            current = ReportDocument('资料', modules=[ModuleProfile('private', 'owner', '干员', '模组', phases=after)])
            report = deepcopy(current)
            report.metadata['changes'] = {'modules': [{'name': '模组', 'kind': 'modified', **values}]}
            original = deepcopy(as_jsonable(report))
            assert semantic_blocks(report) == semantic_blocks(current)
            assert text_report(report) == text_report(current)
            assert render_html(report) == render_html(current)
            assert layout_pages(report) == layout_pages(current)
            for text in (text_report(report), ''.join(VisibleText(render_html(report)).parts)):
                assert notice not in text
                assert '30' in text and ('具体范围未确认' in text or '召唤物1' in text)
                assert all(internal not in text for internal in ('map-a', 'map-b', 'token-a', 'token-b'))
            assert as_jsonable(report) == original
