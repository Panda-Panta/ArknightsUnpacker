import copy
import json
from pathlib import Path
import unittest

from arknights_unpacker.contracts import BuildSpec, DecodedTable, SourceRef, TableSourceSet
from arknights_unpacker.gamedata import build_module, build_operator, compare_entities, load_gamedata
from arknights_unpacker.gamedata.descriptions import render_description


def reference():
    fixture = json.loads((Path(__file__).parent / 'fixtures/fixed_reference.json').read_text(encoding='utf8'))
    return TableSourceSet(tables={name: DecodedTable(name, value, SourceRef(path=fixture['sources'][name]['url'], sha256=fixture['sources'][name]['sha256'])) for name, value in fixture['tables'].items()}, version=fixture['version'], resource_version=fixture['resource_version'],locale='zh_CN')


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.sources = reference()
        self.data = load_gamedata(self.sources)

    def test_clementia_exact_panel_and_provenance(self):
        p = build_operator(self.data, 'char_4231_clemnt', BuildSpec())
        attrs = {item['key']: item for item in p.attributes}
        self.assertEqual([attrs[k]['value'] for k in ['maxHp', 'atk', 'def', 'magicResistance', 'cost', 'respawnTime', 'blockCnt', 'baseAttackTime']], [2720, 1065, 371, 10, 21, 70, 2, 1.2])
        self.assertEqual([attrs['atk'][k] for k in ['base', 'trust', 'potential', 'module']], [920, 110, 35, 0])
        self.assertEqual((p.summary['phase'], p.summary['level'], p.summary['potential']), (2, 90, 6))
        self.assertEqual([b['name'] for b in p.building_skills], ['谈判技巧', '合作原则'])
        self.assertTrue(all(s['level'] == '专精3' for s in p.skills))
        self.assertEqual(p.talents[0]['description'].count('（+15%）'), 1)
        self.assertTrue(p.metadata['source'])

    def test_low_star_and_interpolation(self):
        p = build_operator(self.data, 'char_009_12fce', BuildSpec())
        self.assertEqual((p.summary['phase'], p.summary['level']), (0, 30))
        self.assertEqual(p.skills, [])
        p = build_operator(self.data, 'char_4231_clemnt', BuildSpec(phase=0, level=1, potential=1, trust=0))
        self.assertEqual(next(a['value'] for a in p.attributes if a['key'] == 'atk'), 410)
        self.assertEqual(len(p.skills), 1)

    def test_module_phase_totals_and_upgrade_description(self):
        p = build_module(self.data, 'uniequip_002_angel', BuildSpec())
        self.assertEqual([x['level'] for x in p.phases], [1, 2, 3])
        self.assertEqual(next(a['value'] for a in p.phases[-1]['attributes'] if a['key'] == 'atk'), 41)
        self.assertIn('攻击力+10%', p.phases[-1]['talents'][0]['description'])
        plain = build_operator(self.data, 'char_103_angel', BuildSpec())
        equipped = build_operator(self.data, 'char_103_angel', BuildSpec(module_id=p.equip_id))
        before = next(a['value'] for a in plain.attributes if a['key'] == 'atk')
        after = next(a['value'] for a in equipped.attributes if a['key'] == 'atk')
        self.assertEqual(after-before, 41)
        self.assertFalse(any(m['type_name'] == 'INITIAL' for m in plain.modules))

    def test_description_formats_and_missing(self):
        text, ds = render_description('<@ba.kw>{a.b:0%}</> / {attack@count:0.0} / {label} / {missing}', [{'key':'a.b','value':2.9}, {'key':'attack@count','value':1.25}, {'key':'label','valueStr':'原文'}])
        self.assertEqual(text, '290% / 1.2 / 原文 / {missing}')
        self.assertTrue(ds)

    def test_snapshot_missing_null_and_broken_reference(self):
        del self.sources.tables['skill_table']
        self.sources.tables['character_table'].data['char_4231_clemnt']['talents'] = None
        d = load_gamedata(self.sources)
        self.assertFalse(d.complete)
        p = build_operator(d, 'char_4231_clemnt', BuildSpec())
        self.assertTrue(any('skill_table' in x for x in p.diagnostics))
        self.assertTrue(any('talents' in x for x in p.diagnostics))

    def test_diff_first_baseline_shared_skill_and_json_order(self):
        first = compare_entities(None, self.data)
        self.assertEqual(first.operators, [])
        self.assertTrue(first.diagnostics)
        self.sources.tables['skill_table'].data['skchr_clemnt_1']['levels'][-1]['description'] += '新增说明'
        changed = load_gamedata(self.sources)
        diff = compare_entities(self.data, changed)
        self.assertIn('char_4231_clemnt', [x['char_id'] for x in diff.operators])
        same = copy.deepcopy(changed)
        same.tables['character_table'] = dict(reversed(list(same.tables['character_table'].items())))
        self.assertEqual(compare_entities(changed, same).operators, [])

    def test_diff_incompatible_and_nonplayable(self):
        other = copy.deepcopy(self.data)
        other.locale = 'en_US'
        self.assertEqual(compare_entities(self.data, other).operators, [])
        self.assertTrue(compare_entities(self.data, other).diagnostics)
        ch = copy.deepcopy(self.sources.tables['character_table'].data['char_009_12fce'])
        ch['name'] = '召唤物'; ch['isNotObtainable'] = True
        self.sources.tables['character_table'].data['token_new'] = ch
        d = load_gamedata(self.sources)
        self.assertFalse(compare_entities(self.data, d).operators)

    def test_form_profile_and_non_mastery(self):
        sources = reference()
        form = copy.deepcopy(sources.tables['character_table'].data['char_009_12fce'])
        form['name'] = '测试形态'
        sources.tables['char_patch_table'].data['infos']['char_009_12fce'] = {'tmplIds':['char_009_12fce','char_form_test']}
        sources.tables['char_patch_table'].data['patchChars']['char_form_test'] = form
        data = load_gamedata(sources)
        self.assertEqual(build_operator(data, 'char_form_test').summary['form_of'], 'char_009_12fce')
        diff = compare_entities(self.data, data)
        self.assertEqual(next(x['kind'] for x in diff.operators if x['char_id'] == 'char_form_test'), 'form_added')
        sources = reference()
        sk = sources.tables['skill_table'].data['skchr_clemnt_1']
        sk['levels'] = sk['levels'][:7]
        p = build_operator(load_gamedata(sources), 'char_4231_clemnt')
        self.assertEqual(p.skills[0]['level'], '等级7')

    def test_unknown_potential_formula_and_missing_trust_are_not_zero(self):
        ch = self.sources.tables['character_table'].data['char_4231_clemnt']
        ch['potentialRanks'][2]['buff']['attributes']['attributeModifiers'][0]['formulaItem'] = 'MULTIPLICATION'
        p = build_operator(load_gamedata(self.sources), 'char_4231_clemnt')
        self.assertIsNone(next(a['value'] for a in p.attributes if a['key'] == 'atk'))
        del self.sources.tables['favor_table']
        p = build_operator(load_gamedata(self.sources), 'char_4231_clemnt')
        self.assertIsNone(next(a['trust'] for a in p.attributes if a['key'] == 'atk'))

    def test_module_hidden_token_and_unknown_scope(self):
        battle = self.sources.tables['battle_equip_table'].data['uniequip_002_angel']
        part = copy.deepcopy(battle['phases'][-1]['parts'][-1])
        part['target'] = 'TALENT_DATA_ONLY'; part['isToken'] = True
        part['validInGameTag'] = 'roguelike'
        for candidate in part['addOrOverrideTalentDataBundle']['candidates']:
            candidate['isHideTalent'] = True
        battle['phases'][-1]['parts'].append(part)
        p = build_module(load_gamedata(self.sources), 'uniequip_002_angel')
        self.assertEqual(len(p.phases[-1]['hidden_effects']), 1)
        self.assertEqual(p.phases[-1]['token_effects'][0]['scope']['validInGameTag'], 'roguelike')
        self.assertFalse(p.phases[-1]['scope'])

    def test_snapshot_mixed_versions_and_roundtrip(self):
        self.sources.tables['character_table'].field_evidence['version'] = 'a'
        self.sources.tables['skill_table'].field_evidence['version'] = 'b'
        d = load_gamedata(self.sources)
        self.assertFalse(d.complete)
        from arknights_unpacker.contracts import as_jsonable
        self.assertTrue(json.dumps(as_jsonable(d)))

    def test_pc_numeric_enum_and_def_alias(self):
        sources = reference()
        ch = sources.tables['character_table'].data['char_4231_clemnt']
        ch['profession'] = 1; ch['rarity'] = 5
        for ph in ch['phases']:
            for frame in ph['attributesKeyFrames']:
                frame['data']['def_'] = frame['data'].pop('def')
        for frame in ch['favorKeyFrames']:
            frame['data']['def_'] = frame['data'].pop('def')
        for potential in ch['potentialRanks']:
            potential['type'] = 0 if potential['buff'] else 1
            if potential['buff']:
                for mod in potential['buff']['attributes']['attributeModifiers']:
                    mod['attributeType'] = {'COST':4,'ATK':1}[mod['attributeType']]
                    mod['formulaItem'] = 0
        p = build_operator(load_gamedata(sources),'char_4231_clemnt')
        self.assertEqual(p.summary['profession'],'WARRIOR')
        self.assertEqual(p.summary['rarity'],'TIER_6')
        self.assertEqual(next(a['value'] for a in p.attributes if a['key']=='def'),371)
        self.assertEqual(next(a['value'] for a in p.attributes if a['key']=='atk'),1065)
        self.assertEqual(next(a['value'] for a in p.attributes if a['key']=='cost'),21)

    def test_module_trait_full_text_override_and_token_separation(self):
        p = build_module(self.data,'uniequip_002_angel')
        self.assertIn('优先攻击',p.phases[0]['trait'])
        self.assertIn('110%',p.phases[0]['trait'])
        battle = self.sources.tables['battle_equip_table'].data['uniequip_002_angel']
        part = battle['phases'][0]['parts'][0]
        part['overrideTraitDataBundle']['candidates'][0]['overrideDescripton'] = '新特性'
        part['overrideTraitDataBundle']['candidates'][0]['additionalDescription'] = '附加'
        p = build_module(load_gamedata(self.sources),'uniequip_002_angel')
        self.assertEqual(p.phases[0]['trait'],'新特性\n附加')
        part['isToken'] = True
        p = build_module(load_gamedata(self.sources),'uniequip_002_angel')
        self.assertIn('优先攻击',p.phases[0]['trait'])
        self.assertEqual(len(p.phases[0]['token_effects']),1)

    def test_diff_text_only_and_cosmetic_assets(self):
        self.sources.tables['skill_table'].data['skchr_clemnt_1']['levels'][-1]['description'] += '文案'
        changes = compare_entities(self.data,load_gamedata(self.sources))
        self.assertIn('text_only',changes.operators[0]['categories'])
        sources = reference()
        sources.tables['skin_table'] = DecodedTable('skin_table',{'changed':True})
        changes = compare_entities(self.data,load_gamedata(sources))
        self.assertEqual(changes.operators,[])

    def test_mode_only_module_does_not_enter_unconditional_panel(self):
        self.sources.tables['uniequip_table'].data['equipDict']['uniequip_002_angel']['isSpecialEquip'] = True
        p = build_operator(load_gamedata(self.sources),'char_103_angel',BuildSpec(module_id='uniequip_002_angel'))
        self.assertEqual(next(x['module'] for x in p.attributes if x['key']=='atk'),0)
        self.assertTrue(any('conditional module' in x for x in p.diagnostics))

    def test_unknown_locale_is_preserved_and_part_of_content_identity(self):
        self.assertEqual(self.data.locale,'zh_CN')
        self.sources.locale='unknown'
        data=load_gamedata(self.sources)
        self.assertEqual(data.locale,'unknown')
        self.assertNotEqual(data.snapshot_id,self.data.snapshot_id)

    def test_unknown_locale_same_installation_allows_content_diff_with_warning(self):
        self.sources.locale='unknown'
        old=load_gamedata(self.sources)
        self.sources.tables['character_table'].data['char_4231_clemnt']['name']='文案改名'
        new=load_gamedata(self.sources)
        for data in (old,new):
            data.sources['_installation']={'profile_id':'same-local-installation'}
        diff=compare_entities(old,new)
        self.assertEqual([x['char_id'] for x in diff.operators],['char_4231_clemnt'])
        self.assertIn('区服未知，仅比较同一安装位置内容，不能确认服务器发布',diff.diagnostics)
        self.assertEqual(old.locale,'unknown')
        self.assertEqual(new.locale,'unknown')

    def test_unknown_locale_different_or_missing_installation_blocks_diff(self):
        self.sources.locale='unknown'
        old=load_gamedata(self.sources)
        self.sources.tables['character_table'].data['char_4231_clemnt']['name']='文案改名'
        new=load_gamedata(self.sources)
        for old_profile,new_profile in [('first','second'),('first',None),(None,None)]:
            with self.subTest(old_profile=old_profile,new_profile=new_profile):
                old.sources['_installation']={'profile_id':old_profile}
                new.sources['_installation']={'profile_id':new_profile}
                diff=compare_entities(old,new)
                self.assertEqual(diff.operators,[])
                self.assertTrue(any('声明区服' in x for x in diff.diagnostics))

    def test_unknown_locale_warning_does_not_bypass_incomplete_guard(self):
        old=copy.deepcopy(self.data)
        new=copy.deepcopy(self.data)
        old.locale=new.locale='unknown'
        for data in (old,new):
            data.sources['_installation']={'profile_id':'same'}
        new.complete=False
        new.tables['character_table']['char_4231_clemnt']['name']='变化'
        diff=compare_entities(old,new)
        self.assertEqual(diff.operators,[])
        self.assertTrue(any('incomplete' in x for x in diff.diagnostics))


if __name__ == '__main__':
    unittest.main()
