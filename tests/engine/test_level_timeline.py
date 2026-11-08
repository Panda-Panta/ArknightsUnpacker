import pytest

from arknights_unpacker.contracts import CancelToken, CancelledError
from arknights_unpacker.extraction.level_timeline import build_level_timeline


def spawn(key, at=0, **fields):
    return dict(actionType=0, key=key, preDelay=at, count=1, routeIndex=0, **fields)


def fragment(*actions, delay=0):
    return dict(actions=actions, preDelay=delay)


def wave(*fragments, before=0, after=0, limit=-1):
    return dict(fragments=fragments, preDelay=before, postDelay=after,
                maxTimeWaitingForNextWave=limit)


@pytest.mark.parametrize(('limit', 'next_spawn'), [(-1, 23), (2, 17.3), (0, 15.3)])
def test_wave_delay_and_fragment_queue_use_spawn_and_preview_events(limit, next_spawn):
    first = wave(
        fragment(spawn('a', 2, interval=4), delay=1),
        fragment(spawn('b', 3), dict(actionType=1, preDelay=5), delay=2),
        before=1, after=2, limit=limit,
    )
    second = wave(fragment(spawn('c')), before=2)
    timeline = build_level_timeline({'waves': [first, second]}, lambda *_: 10)

    assert [(event['enemyId'], event['time']) for event in timeline['events'][:2]] == [('a', 4), ('b', 9)]
    assert timeline['events'][2]['time'] == pytest.approx(next_spawn)
    assert timeline['duration'] == pytest.approx(next_spawn + 10)
    assert timeline['complete']


def test_hidden_groups_and_repeated_spawns_are_filtered_before_waiting():
    actions = [
        spawn('hidden', 100, hiddenGroup='hard'),
        dict(spawn('visible', 4, interval=2), count=3),
        spawn('variant', 0, hiddenGroup='base'),
    ]
    timeline = build_level_timeline(
        {'waves': [wave(fragment(*actions))], 'enabledHiddenGroups': ['base']},
        lambda *_: 1,
    )

    assert [(event['enemyId'], event['time']) for event in timeline['events']] == [
        ('variant', 0), ('visible', 4), ('visible', 6), ('visible', 8),
    ]
    assert timeline['duration'] == 9


def test_nonblocking_enemy_does_not_delay_next_wave_but_delays_final_completion():
    first = wave(fragment(spawn('a', 1, dontBlockWave=True, useExtraRoute=True)))
    second = wave(fragment(spawn('b', 2)))
    timeline = build_level_timeline(
        {'waves': [first, second]},
        lambda _, __, extra: 25 if extra else 1,
    )

    assert [event['time'] for event in timeline['events']] == [1, 3]
    assert timeline['events'][0]['useExtraRoute']
    assert timeline['duration'] == 26


def test_unknown_exit_preserves_fragment_events_but_does_not_assume_wave_wait():
    first = wave(fragment(spawn('unknown', 1), spawn('known', 5)), limit=6)
    second = wave(fragment(spawn('later')))
    timeline = build_level_timeline(
        {'waves': [first, second]},
        lambda enemy, *_: None if enemy == 'unknown' else 2,
    )

    assert [event['enemyId'] for event in timeline['events']] == ['unknown', 'known']
    assert not timeline['complete']
    assert timeline['blockedAt'] == 5
    assert timeline['diagnostics']


def test_unmodelled_blocking_action_stops_after_the_current_fragment():
    actions = [dict(actionType=8, preDelay=1, blockFragment=True), spawn('current', 4)]
    timeline = build_level_timeline(
        {'waves': [wave(fragment(*actions), fragment(spawn('later')))]}, lambda *_: 2,
    )

    assert [event['enemyId'] for event in timeline['events']] == ['current']
    assert not timeline['complete']
    assert timeline['blockedAt'] == 4


def test_random_group_stops_before_assuming_which_enemy_spawns():
    actions = [spawn('known', 1), spawn('random', 3, randomSpawnGroupKey='pick')]
    timeline = build_level_timeline({'waves': [wave(fragment(*actions))]}, lambda *_: 2)

    assert [event['enemyId'] for event in timeline['events']] == ['known']
    assert not timeline['complete']
    assert timeline['blockedAt'] == 3


def test_cancellation_is_checked_before_scheduling():
    cancel = CancelToken()
    cancel.cancel()

    with pytest.raises(CancelledError):
        build_level_timeline({'waves': []}, lambda *_: 1, cancel=cancel)
