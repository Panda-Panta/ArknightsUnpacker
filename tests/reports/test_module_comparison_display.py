"""All readable outputs consume the same domain comparisons, including old profiles."""
from copy import deepcopy
import json
from pathlib import Path

from arknights_unpacker.contracts import DecodedTable, ModuleProfile, ReportDocument, SourceRef, TableSourceSet
from arknights_unpacker.gamedata import build_module, build_operator, load_gamedata
from arknights_unpacker.reports.html_render import render_html
from arknights_unpacker.reports.model import semantic_blocks, text_report
from arknights_unpacker.reports.render import layout_pages


def data():
    raw = json.loads((Path(__file__).parents[1] / 'gamedata/fixtures/fixed_reference.json').read_text('utf-8'))
    return load_gamedata(TableSourceSet(tables={name: DecodedTable(name, value, SourceRef(path='fixture'))
                                               for name, value in raw['tables'].items()},
                                        version=raw['version'], resource_version=raw['resource_version']))


def test_stage_effects_are_readable_in_operator_and_module_outputs_without_mutation():
    snapshot = data()
    documents = [ReportDocument('能天使', operators=[build_operator(snapshot, 'char_103_angel')]),
                 ReportDocument('模组', modules=[build_module(snapshot, 'uniequip_002_angel')])]
    for doc in documents:
        before = deepcopy(doc)
        blocks = semantic_blocks(doc)
        comparison, = [block for block in blocks if block.kind == 'module-attributes' and
                        block.entry_id.endswith(':uniequip_002_angel')]
        assert comparison.columns == ['项目', '未装备', '1级', '2级', '3级']
        atk = next(row for row in comparison.cells if row[0] == '攻击')
        assert '+27' in atk[2] and '+35' in atk[3] and '+41' in atk[4]
        text = text_report(doc)
        assert all(value in text for value in ('未装备', '1级', '2级', '3级'))
        assert '本级效果' not in text and '较2级变化' not in text
        assert '一名随机友方单位' in text and '两名随机友方单位' in text
        assert '属性口径' in text and '（+2%）' in text and '（+3%）' in text
        assert '潜能增量' not in text  # The same increments already appear in the effects.
        html = render_html(doc)
        png_text = ''.join(line.text for page in layout_pages(doc) for line in page)
        for phrase in ('属性对照', '未装备', '3级', '+41'):
            assert phrase in html and phrase in png_text
        assert doc == before


def test_old_profile_without_comparison_fields_keeps_original_content():
    old = ModuleProfile('old', 'owner', '干员', '旧模组', phases=[
        {'level': 1, 'trait': '旧特性', 'attributes': [{'key': 'atk', 'label': '攻击', 'value': 20}],
         'talents': [{'name': '旧天赋', 'description': '旧效果'}]}])
    text = text_report(ReportDocument('旧报告', modules=[old]))
    assert all(word in text for word in ('旧特性', '攻击', '20', '旧天赋', '旧效果'))
