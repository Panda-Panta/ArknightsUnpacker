"""Operator branch names come from the same game snapshot, including forms."""
import json
from pathlib import Path

import pytest

from arknights_unpacker.contracts import DecodedTable, SourceRef, TableSourceSet, as_jsonable
from arknights_unpacker.gamedata import build_operator, load_gamedata
from arknights_unpacker.library.serialization import dumps_snapshot, loads_snapshot


@pytest.fixture
def sources():
    fixtures = Path(__file__).parent / 'fixtures'
    raw = json.loads((fixtures / 'fixed_reference.json').read_text(encoding='utf8'))
    branches = json.loads((fixtures / 'local_operator_branches.json').read_text(encoding='utf8'))
    raw['tables']['uniequip_table']['subProfDict'] = branches['subProfDict']
    return TableSourceSet(tables={name: DecodedTable(name, value, SourceRef())
        for name, value in raw['tables'].items()}, version=raw['version'], locale='zh_CN')


@pytest.mark.parametrize('char_id,branch_id,name', [
    ('char_103_angel', 'fastshot', '速射手'),
    ('char_4231_clemnt', 'primguard', '本源近卫'),
    ('char_285_medic2', 'physician', '医师'),
    ('char_009_12fce', 'splashcaster', '扩散术师'),
    ('char_002_amiya', 'corecaster', '中坚术师'),
    ('char_1001_amiya2', 'artsfghter', '术战者'),
    ('char_1037_amiya3', 'incantationmedic', '咒愈师'),
])
def test_game_branch_name_preserves_raw_id_and_form_identity(sources, char_id, branch_id, name):
    data = load_gamedata(sources)
    # Restoring an existing table snapshot does not need a schema migration or rescan.
    profile = build_operator(loads_snapshot(dumps_snapshot(data)), char_id)
    assert profile.summary['sub_profession'] == branch_id
    assert profile.summary['sub_profession_name'] == name
    saved = as_jsonable(profile)
    assert saved['summary']['sub_profession'] == branch_id
    assert saved['summary']['sub_profession_name'] == name
    if char_id in {'char_1001_amiya2', 'char_1037_amiya3'}:
        assert profile.summary['form_of'] == 'char_002_amiya'
        assert profile.metadata['source']['pointer'] == '/patchChars/' + char_id


def test_branch_name_is_read_from_snapshot_and_does_not_require_chinese(sources):
    sources.tables['uniequip_table'].data['subProfDict']['fastshot']['subProfessionName'] = 'Marksman'
    profile = build_operator(load_gamedata(sources), 'char_103_angel')
    assert profile.summary['sub_profession'] == 'fastshot'
    assert profile.summary['sub_profession_name'] == 'Marksman'


@pytest.mark.parametrize('mapping', [{}, {'fastshot': None}, {'fastshot': {}},
    {'fastshot': {'subProfessionName': ''}}, {'fastshot': {'subProfessionName': 25}}])
def test_missing_branch_name_stays_unknown_and_keeps_original_id(sources, mapping):
    sources.tables['uniequip_table'].data['subProfDict'] = mapping
    profile = build_operator(load_gamedata(sources), 'char_103_angel')
    assert profile.summary['sub_profession'] == 'fastshot'
    assert profile.summary.get('sub_profession_name') is None


@pytest.mark.parametrize('missing', ['subProfDict', 'uniequip_table'])
def test_old_snapshot_without_branch_table_remains_usable(sources, missing):
    if missing == 'subProfDict':
        del sources.tables['uniequip_table'].data['subProfDict']
    else:
        del sources.tables['uniequip_table']
    data = loads_snapshot(dumps_snapshot(load_gamedata(sources)))
    profile = build_operator(data, 'char_103_angel')
    assert profile.summary['sub_profession'] == 'fastshot'
    assert profile.summary.get('sub_profession_name') is None
    assert profile.name == '能天使'
    assert profile.skills and profile.attributes
