from types import SimpleNamespace

from arknights_unpacker.extraction import level_tags


def test_default_selection_keeps_independent_tags_and_only_first_highest_in_each_group():
    def tag(id, score, sort, group=None, required=False):
        return dict(id=id, score=score, sort=sort, group=group, required=required)

    tags = level_tags._default_tags([
        tag('required-second', 0, 2, 'required', True),
        tag('optional-low', 2, 3, 'optional'),
        tag('optional-second', 3, 5, 'optional'),
        tag('optional-first', 3, 4, 'optional'),
        tag('required-first', 0, 1, 'required', True),
        tag('base', 0, 0, required=True),
        tag('independent', 2, 6),
    ])
    assert [tag['id'] for tag in tags if tag['selected']] == [
        'base', 'required-first', 'optional-first', 'independent',
    ]


def test_load_tags_reads_only_recalrune_table_and_binds_to_catalog_resource_version(monkeypatch):
    calls = []

    def load(root, cache, **kwargs):
        calls.append((cache, kwargs['names'], kwargs['expected_resource_version']))
        decode = kwargs['decoders']['crisis_v2_table']
        decoded, _ = decode(b'current data', 'crisis_v2_table')
        return SimpleNamespace(tables={'crisis_v2_table': SimpleNamespace(data=decoded)},
                               resource_version='current', diagnostics=[])

    def decode(raw, table, level_id, cancel):
        assert raw == b'current data' and table == 'crisis_v2_table'
        assert level_id == 'obt/recalrune/level_recalrune_02-04'
        return {'found': True, 'tags': [{'id': 'base'}]}, {}

    monkeypatch.setattr(level_tags, 'load_local_tables', load)
    monkeypatch.setattr(level_tags, '_decode_level_tags', decode)
    normal = level_tags.load_level_tags('game', 'gamedata/levels/obt/main/level_main_00-01', 'current')
    assert not calls and normal == {'tags': [], 'diagnostics': [], 'resource_version': 'current'}
    result = level_tags.load_level_tags('game', 'gamedata/levels/obt/recalrune/level_recalrune_02-04', 'current')
    assert calls == [(None, {'crisis_v2_table'}, 'current')]
    assert result == {'tags': [{'id': 'base'}], 'diagnostics': [], 'resource_version': 'current'}
