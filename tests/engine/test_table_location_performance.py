"""Core table matching retains exact names without repeated per-asset regex work."""
import re
from pathlib import Path

import pytest

from arknights_unpacker.extraction import tables


def original_table_name(value, names):
    value = Path(str(value).replace('\\', '/')).name
    return next((name for name in sorted(names, key=len, reverse=True)
                 if re.fullmatch(re.escape(name) + r'(?:[0-9a-f]+)?(?:\.bytes|\.json|\.txt)?', value)), None)


@pytest.mark.parametrize('value', [
    'character_table', 'gamedata/excel/character_tableabcdef',
    r'gamedata\excel\character_table0123.bytes', 'skill_table.json',
    'battle_equip_table9.txt', 'building_data/', 'character_tableABC',
    'character_table.jsonx', 'prefixcharacter_table', 'not_a_table', '',
    'character_tableabcdef.json', 'skill_table1' + chr(92),
])
def test_table_matcher_preserves_original_name_boundaries(value):
    names = tables.CORE_TABLES | tables.SUPPORT_TABLES
    assert tables._table_name(value, names) == original_table_name(value, names)


def test_bulk_table_lookup_compiles_once_and_reuses_exact_matcher(monkeypatch):
    calls = []
    original = tables.re.escape

    def escape(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(tables.re, 'escape', escape)
    names = {'character_table', 'skill_table'}
    assert [tables._table_name(value, names) for value in ['chararts/char_002_amiya', 'gamedata/skill_tableabcdef.bytes'] * 100] == [None, 'skill_table'] * 100
    assert tables._table_name('character_table', names) == 'character_table'
    assert len(calls) <= len(names), 'Repeated assets must reuse prepared table-name expressions'


def test_table_names_with_overlapping_prefixes_and_regex_characters_keep_original_semantics():
    names = {'table', 'tablea', 'skill.table', 'skill'}
    for name in ['tableabc', 'tablea.json', 'skill.table1.bytes', 'skillXtable']:
        assert tables._table_name(name, names) == original_table_name(name, names)
    assert tables._table_name('table', set()) is None
