"""Potential display uses localized game descriptions, not blackboard key guesses."""
from arknights_unpacker.contracts import ModuleProfile, OperatorProfile, ReportDocument
from arknights_unpacker.gamedata.candidates import potential_delta
from arknights_unpacker.gamedata.descriptions import render_description
from arknights_unpacker.reports.model import semantic_blocks, text_report


def effect(before, after, old, new):
    baseline = {'description': before, 'blackboard': old}
    candidate = {'description': after, 'blackboard': new}
    text, _ = render_description(after, new)
    return {'name': '测试天赋', 'description': text,
            'potential_delta': potential_delta(candidate, baseline)}


def report(talent):
    return ReportDocument('资料', operators=[OperatorProfile('owner', '干员', talents=[talent])])


def test_talulah_official_annotations_cover_visible_effects_and_internal_step():
    talent = effect('造成法术伤害时附带11%的灼燃损伤；最高提升15%',
        '造成法术伤害时附带13%<@ba.talpu>（+2%）</>的灼燃损伤；最高提升18%<@ba.talpu>（+3%）</>',
        {'arcane_step': .025, 'arcane_max': .15, 'ep_damage_ratio': .11},
        {'arcane_step': .03, 'arcane_max': .18, 'ep_damage_ratio': .13})
    text = text_report(report(talent))
    assert '13%（+2%）' in text and '18%（+3%）' in text
    assert '部分潜能效果未确认' not in text
    assert not any(key == '潜能增量' for block in semantic_blocks(report(talent)) for key, _ in block.rows)


def test_clementia_official_annotations_cover_nonstandard_blackboard_keys_in_modules_too():
    talent = effect('有25%概率攻击力提升至135%', '有25%概率攻击力提升至150%<@ba.talpu>（+15%）</>',
                    {'t1_atk_scale': 1.35}, {'t1_atk_scale': 1.5})
    document = report(talent)
    document.modules = [ModuleProfile('module', 'owner', '干员', '模组', phases=[{'level': 1, 'talents': [talent]}])]
    text = text_report(document)
    assert '150%（+15%）' in text
    assert '部分潜能效果未确认' not in text
    assert not any(block.kind == 'module-potential' for block in semantic_blocks(document))


def test_unannotated_localized_changes_display_actual_before_and_after_without_inferred_units():
    talent = effect('每{period:0.0}秒获得{count:0}层充能', '每{period:0.0}秒获得{count:0}层充能',
                    {'period': 1.5, 'count': 2}, {'period': 1.2, 'count': 3})
    text = text_report(report(talent))
    assert '基础天赋：每1.5秒获得2层充能' in text
    assert '当前潜能：每1.2秒获得3层充能' in text
    assert '部分潜能效果未确认' not in text


def test_partial_annotation_does_not_conceal_another_visible_change():
    talent = effect('攻击力+8%且防御力+6%', '攻击力+10%且防御力+8%<@ba.talpu>（+2%）</>',
                    {'atk': .08, 'def': .06}, {'atk': .1, 'def': .08})
    text = text_report(report(talent))
    assert '基础天赋：攻击力+8%且防御力+6%' in text
    assert '当前潜能：攻击力+10%且防御力+8%（+2%）' in text


def test_decreasing_effect_and_percent_annotation_keep_their_actual_units():
    talent = effect('再部署时间缩短至40秒，攻击力+6%',
        '再部署时间缩短至35<@ba.talpu>（-5）</>秒，攻击力+8%<@ba.talpu>（+2%）</>',
        {'interval': 40, 'atk': .06}, {'interval': 35, 'atk': .08})
    text = text_report(report(talent))
    assert '35（-5）秒' in text and '8%（+2%）' in text
    assert '潜能增量：' not in text


def test_no_visible_description_evidence_keeps_unconfirmed_effect():
    talent = effect('攻击力提升', '攻击力提升', {'unknown_multiplier': .1}, {'unknown_multiplier': .2})
    assert '部分潜能效果未确认' in text_report(report(talent))


def test_effect_with_different_inherited_description_does_not_use_unrelated_evidence():
    talent = effect('攻击力+8%', '攻击力+10%<@ba.talpu>（+2%）</>', {'atk': .08}, {'atk': .1})
    talent['description'] = '攻击力提升'
    assert '攻击相关潜能效果有变化，幅度未确认' in text_report(report(talent))


def test_official_annotation_does_not_hide_another_known_attribute_missing_from_description():
    talent = effect('攻击力+6%', '攻击力+8%<@ba.talpu>（+2%）</>',
                    {'atk': .06, 'attack_speed': 10}, {'atk': .08, 'attack_speed': 12})
    text = text_report(report(talent))
    assert '攻击速度相关潜能效果有变化，幅度未确认' in text
    assert '攻击相关潜能效果有变化' not in text
