import json
from types import SimpleNamespace

from arknights_unpacker.extraction import level_tags


CRISIS = 'gamedata/levels/obt/crisis/v2/level_crisis_v2_02-01'


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


def test_crisis_indicators_prompt_for_archive_without_reusing_recalrune_rules():
    result = level_tags.load_level_tags('game', CRISIS, 'current')
    assert result['mode'] == 'crisis' and result['resource_version'] == 'current'
    assert result['tags'] == [] and '导入' in result['diagnostics'][0]


def test_crisis_archive_preserves_connections_mutual_exclusion_and_packs(tmp_path):
    def node(kind, adjacent, rune=None, group=None, pack=None):
        return {'nodeType': kind, 'adjacentNodeList': adjacent, 'runeId': rune,
                'mutualExclusionGroup': group, 'slotPackId': pack}

    def rune(id, score, sort, key, board, description=''):
        return {'runeId': id, 'runeName': id, 'score': score, 'sortId': sort,
                'packedRune': {'id': id, 'mutexGroupKey': 'shared-effect-group',
                               'description': description, 'runes': [{'key': key, 'blackboard': board}]}}

    archive = tmp_path / 'crisis.json'
    archive.write_text(json.dumps({
        'ts': 1712694006,
        'playerDataDelta': {'modified': {'keypoint': 'complete'}},
        'info': {
            'seasonId': 'crisis_v2_season_2_1',
            'mapStageDataMap': {'map': {'levelId': 'Obt/Crisis/V2/level_crisis_v2_02-01'}},
            'mapDetailDataMap': {'map': {
                'nodeDataMap': {
                    'start': node('START', ['a', 'b']),
                    'a': node('NORMAL', ['start', 'target'], 'rune_a', 'exclusive', 'pack'),
                    'b': node('NORMAL', ['start', 'target'], 'rune_b', 'exclusive', 'pack'),
                    'target': node('NORMAL', ['a', 'b', 'keypoint'], 'rune_c'),
                    'keypoint': node('KEYPOINT', ['target']),
                },
                'runeDataMap': {
                    'rune_a': rune('rune_a', 10, 1, 'enemy_attribute_mul', [{'key': 'atk', 'value': 0.4}],
                                   '敌人攻击力<@crisisv2.nag>+{atk:0%}</>'),
                    'rune_b': rune('rune_b', 20, 2, 'level_hidden_group_enable', [{'key': 'key', 'valueStr': 'boss2'}]),
                    'rune_c': rune('rune_c', 30, 3, 'enemy_attribute_mul', []),
                },
                'exclusionDataMap': {'exclusive': {'defaultSlotId': 'b'}},
                'bagDataMap': {'pack': {'slotPackFullName': '指标集：恶敌', 'rewardScore': 10}},
            }},
        },
    }), encoding='utf-8')
    result = level_tags.load_level_tags('game', CRISIS, 'current', crisis_info_path=archive)
    assert not result['diagnostics'] and result['mode'] == 'crisis'
    assert result['graph']['start_ids'] == ['start'] and result['graph']['keypoint_ids'] == ['keypoint']
    assert result['packs'][0]['tag_ids'] == ['a', 'b']
    tags = {tag['id']: tag for tag in result['tags']}
    assert list(tags) == ['a', 'b', 'target'] and all(not tag['selected'] for tag in tags.values())
    assert tags['target']['requires'] == ['a', 'b', 'keypoint'] and tags['target']['excludes'] == []
    assert tags['a']['excludes'] == ['b'] and tags['b']['excludes'] == ['a']
    assert tags['a']['description'] == '敌人攻击力+40%'
    assert tags['b']['effects'] == [{'key': 'level_hidden_group_enable', 'statically_applicable': True,
                                      'blackboard': [{'key': 'key', 'value': 0, 'valueStr': 'boss2'}]}]
    wrong_map = level_tags.load_level_tags('game', CRISIS.replace('02-01', '05-01'), 'current', crisis_info_path=archive)
    assert not wrong_map['tags'] and '匹配' in wrong_map['diagnostics'][0]
