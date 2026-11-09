from arknights_unpacker.extraction.level_spawn_choices import inactive_replay_branches, resolve_replay_waves
from arknights_unpacker.extraction.level_timeline import build_level_timeline


def action(key, *, kind=0, group='draw', pack=None, weight=1, **fields):
    return dict(actionType=kind, key=key, count=1, randomSpawnGroupKey=group,
                randomSpawnGroupPackKey=pack, weight=weight, **fields)


def stage(*fragments, **fields):
    return dict(waves=[{'fragments': [{'actions': actions} for actions in fragments]}], **fields)


def test_weighted_groups_choose_pack_rows_together_per_fragment():
    level = stage([action('soldier', pack='reinforcements'),
                   action('token', kind=6, pack='reinforcements', preDelay=2),
                   action('other', weight=0)],
                  [action('later'), action('other', weight=0)])

    resolved = resolve_replay_waves(level, 7)
    timeline = build_level_timeline(resolved, lambda *_: 3)

    assert [event['enemyId'] for event in timeline['events']] == ['soldier', 'later']
    assert timeline['predefinedActivations'] == [dict(key='token', time=2, waveIndex=0, fragmentIndex=0)]
    assert timeline['complete']
    assert resolve_replay_waves(level, 7) == resolved
    assert level['waves'][0]['fragments'][0]['actions'][0]['randomSpawnGroupKey'] == 'draw'


def test_weighted_empty_option_is_removed_and_does_not_delay_the_next_fragment():
    level = stage([action('', kind=6, preDelay=100), action('trap', kind=6, weight=0)],
                  [action('later', group=None)])

    timeline = build_level_timeline(resolve_replay_waves(level, 7), lambda *_: 3)

    assert timeline['events'][0]['time'] == 0
    assert not timeline['predefinedActivations']
    assert timeline['complete']


def test_run_dependent_weighted_choice_remains_unresolved():
    level = stage([action('trap', kind=6, preDelay=4, randomType=1)])

    timeline = build_level_timeline(resolve_replay_waves(level, 7), lambda *_: 1)

    assert timeline['blockedAt'] == 4
    assert not timeline['complete']
    assert not timeline['predefinedActivations']


def test_branch_without_activated_owner_is_dormant_but_unknown_triggers_are_preserved():
    owner = dict(hidden=True, alias='mimic', overrideSkillBlackboard=[dict(key='branch_id', valueStr='mimic-spawn')])
    other = dict(owner, alias='other')
    level = stage([action('mimic', kind=6, group=None, hiddenGroup='alternate')],
                  predefines={'tokenInsts': [owner, other]}, branches={'mimic-spawn': {}, 'unknown': {}})

    assert inactive_replay_branches(level) == {'mimic-spawn'}
    assert not inactive_replay_branches(dict(level, enabledHiddenGroups=['alternate']))
    assert not inactive_replay_branches(dict(level, options={'branch': 'mimic-spawn'}))
    timeline = build_level_timeline(level, lambda *_: 1, inactive_branches=inactive_replay_branches(level))
    assert not timeline['complete']


def test_unopposed_larva_destruction_and_unused_directional_spawn_branches_are_dormant():
    pos = {'row': 2, 'col': 2}
    owner = dict(hidden=True, alias='larva', inst={'characterKey': 'trap_086_larva'}, position=pos, skillIndex=0,
                 overrideSkillBlackboard=[dict(key='branch_id', valueStr='larva-spawn')])

    def branch(route):
        return {'phases': [{'actions': [action('scout', group=None, routeIndex=route)]}]}

    level = stage([action('larva', kind=6, group=None)], predefines={'tokenInsts': [owner]},
                  mapData={'tiles': [{'tileKey': 'tile_floor'}]},
                  extraRoutes=[{'startPosition': pos}, {'startPosition': {'row': 0, 'col': 0}}],
                  branches={'larva-spawn': branch(0), 'north_s1': branch(1), 'unknown': branch(1)})

    assert inactive_replay_branches(level) == {'larva-spawn', 'north_s1'}
    assert inactive_replay_branches(dict(level, runes=[{'key': 'north_s1'}])) == set()
    assert inactive_replay_branches(dict(level, options={'branch': 'north_s1'})) == {'larva-spawn'}


def test_timed_sandbox_wood_branch_requires_a_verified_passive_scenario():
    owner = dict(hidden=False, alias=None, inst={'characterKey': 'trap_515_xb2wdo'}, skillIndex=0,
                 overrideSkillBlackboard=[dict(key='branch_id', valueStr='wood-spawn'),
                                          dict(key='action_index', value=0)])
    fields = dict(predefines={'tokenInsts': [owner]}, mapData={'tiles': [{'tileKey': 'tile_road'}]},
                  branches={'wood-spawn': {}})
    passive = stage([action('enemy_7067_xbcrag', group=None)], **fields)
    attacker = stage([action('different_enemy', group=None)], **fields)

    assert inactive_replay_branches(passive) == set()
    assert inactive_replay_branches(attacker, sandbox_timed=True) == set()
    assert inactive_replay_branches(passive, sandbox_timed=True) == {'wood-spawn'}
