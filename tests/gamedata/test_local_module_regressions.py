import json
from pathlib import Path
import unittest

from arknights_unpacker.contracts import BuildSpec,DecodedTable,SourceRef,TableSourceSet
from arknights_unpacker.gamedata import build_module,build_operator,load_gamedata


class LocalModuleRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw=json.loads((Path(__file__).parent/'fixtures/local_module_regressions.json').read_text(encoding='utf8'))
        cls.data=load_gamedata(TableSourceSet(tables={key:DecodedTable(key,value,SourceRef(**raw['sources'][key])) for key,value in raw['tables'].items()},version=raw['version'],resource_version=raw['resource_version']))

    def test_ling_personal_stats_are_independent_of_token_parts(self):
        plain=build_operator(self.data,'char_2023_ling')
        selected=build_operator(self.data,'char_2023_ling',BuildSpec(module_id='uniequip_002_ling'))
        before={x['key']:x for x in plain.attributes}
        after={x['key']:x for x in selected.attributes}
        self.assertEqual(after['maxHp']['value']-before['maxHp']['value'],150)
        self.assertEqual(after['atk']['value']-before['atk']['value'],50)
        self.assertEqual(after['maxHp']['module'],150)
        self.assertEqual(after['atk']['module'],50)
        module=build_module(self.data,'uniequip_002_ling')
        self.assertTrue(module.phases[-1]['token_effects'])
        self.assertNotIn('isToken',module.phases[-1]['scope'])

    def test_dusk_personal_cost_and_visible_summon_talent(self):
        p=build_operator(self.data,'char_2015_dusk',BuildSpec(module_id='uniequip_003_dusk'))
        self.assertEqual(next(a['module'] for a in p.attributes if a['key']=='cost'),-8)
        module=build_module(self.data,'uniequip_003_dusk')
        talent=next(t for t in module.phases[-1]['talents'] if t['name']=='点睛')
        self.assertIn('每1.5秒为夕回复1点技力',talent['description'])
        self.assertEqual(talent['scope']['tokenKey'],'token_10015_dusk_drgn')
        self.assertTrue(module.phases[-1]['token_attributes'])

    def test_data_only_visible_upgrade_is_not_hidden(self):
        cases=[('uniequip_002_ling','挑灯问梦','最多同时部署4个'),('uniequip_002_mgllan','光学折射配件',''),('uniequip_003_mgllan','支援无人机·龙腾','最多同时部署4个')]
        for equip_id,name,fragment in cases:
            with self.subTest(equip_id=equip_id):
                p=build_module(self.data,equip_id)
                item=next(t for t in p.phases[-1]['talents'] if t['name']==name)
                self.assertTrue(item['description'])
                self.assertIn(fragment,item['description'])
                self.assertNotIn(item,p.phases[-1]['hidden_effects'])


if __name__=='__main__':
    unittest.main()
