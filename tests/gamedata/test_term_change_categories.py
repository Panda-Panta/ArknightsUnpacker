"""Moving glossary text out of descriptions must preserve change categories."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from arknights_unpacker.contracts import DecodedTable, SourceRef, TableSourceSet
from arknights_unpacker.gamedata import compare_entities, load_gamedata


@pytest.mark.parametrize('change', ['label', 'add', 'definition', 'numeric'])
def test_glossary_text_changes_stay_text_only_but_numeric_changes_do_not(change):
    fixture = json.loads((Path(__file__).parent / 'fixtures/fixed_reference.json').read_text('utf-8'))
    sources = TableSourceSet(tables={name: DecodedTable(name, value, SourceRef(path=name))
                                    for name, value in fixture['tables'].items()}, locale='zh_CN')
    sources.tables['gamedata_const'].data.setdefault('termDescriptionDict', {})['test.burn'] = {
        'description': '累计满时爆发（领袖2000点）'}
    for slot in sources.tables['character_table'].data['char_103_angel']['talents']:
        for candidate in slot['candidates']:
            if change != 'add':
                candidate['description'] += '；<$test.burn>灼燃损伤</>'
    before = load_gamedata(sources)
    updated = deepcopy(sources)
    for slot in updated.tables['character_table'].data['char_103_angel']['talents']:
        for candidate in slot['candidates']:
            if change == 'label':
                candidate['description'] = candidate['description'].replace('灼燃损伤', '灼烧损伤')
            elif change == 'add':
                candidate['description'] += '；<$test.burn>灼燃损伤</>'
            elif change == 'numeric':
                candidate['blackboard'][0]['value'] += 1
    if change == 'definition':
        updated.tables['gamedata_const'].data['termDescriptionDict']['test.burn']['description'] += '，立即结算'
    changes = compare_entities(before, load_gamedata(updated))
    operator = next(item for item in changes.operators if item['id'] == 'char_103_angel')
    assert ('text_only' in operator['categories']) == (change != 'numeric')
    if change in {'label', 'add', 'definition'}:
        assert not changes.modules
