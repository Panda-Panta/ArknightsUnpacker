from math import dist

import pytest

from arknights_unpacker.extraction import level_replay
from arknights_unpacker.extraction.level_replay import _battle_clock, _resolve_clock_waits, _route_clock, build_level_replay


def test_random_spawn_offsets_have_stable_individual_paths_and_delay_wave_clear(monkeypatch):
    route = {
        'motionMode': 0, 'startPosition': {'col': 0, 'row': 0}, 'endPosition': {'col': 2, 'row': 0},
        'spawnOffset': {'x': 0.1, 'y': 0.05}, 'spawnRandomRange': {'x': 0.3, 'y': 0.0},
    }
    spawn = {'actionType': 0, 'key': 'enemy', 'routeIndex': 0, 'count': 2}
    level = {
        'mapData': {'map': {'rowSize': 1, 'columnSize': 3, 'matrixData': [0, 0, 0]},
                    'tiles': [{'passableMask': 1}]},
        'routes': [route, {**route, 'spawnRandomRange': None}],
        'waves': [{'fragments': [{'actions': [spawn]}]},
                  {'fragments': [{'actions': [{**spawn, 'routeIndex': 1, 'count': 1}]}]}],
    }
    actors = {'enemy': {'moveSpeed': 1.0}}

    seeds = iter((1234, 5678))
    monkeypatch.setattr(level_replay, 'randbits', lambda _: next(seeds))
    replay = build_level_replay(level, actors)

    assert replay['complete']
    first, second, next_wave = replay['events']
    assert first['path'][0] != second['path'][0]
    for event in (first, second):
        x, y = event['path'][0]
        assert -0.2 <= x <= 0.4
        assert y == pytest.approx(0.05)
        seconds = sum(dist(a, b) for a, b in zip(event['path'], event['path'][1:])) / event['moveSpeed']
        assert event['exitTime'] == pytest.approx(event['time'] + seconds)
    assert next_wave['time'] == max(first['exitTime'], second['exitTime'])
    assert next_wave['path'][0] == (0.1, 0.05)
    assert replay['seed'] == 1234
    assert replay == build_level_replay(level, actors, seed=replay['seed'])
    fresh = build_level_replay(level, actors)
    assert fresh['seed'] == 5678
    assert fresh['events'][0]['path'][0] != first['path'][0]


def test_fixed_waypoint_and_hidden_wait_before_teleport_are_used_for_clear_time():
    route = {
        'motionMode': 0, 'startPosition': {'col': 0, 'row': 0}, 'endPosition': {'col': 6, 'row': 0},
        'checkpoints': [
            {'type': 0, 'position': {'col': 1, 'row': 0}, 'reachOffset': {'x': 0.25, 'y': 0.0}},
            {'type': 1, 'time': 3},
            {'type': 0, 'position': {'col': 2, 'row': 0}},
            {'type': 5},
            {'type': 1, 'time': 10},
            {'type': 6, 'position': {'col': 5, 'row': 0}},
        ],
    }
    spawn = {'actionType': 0, 'key': 'enemy', 'routeIndex': 0}
    level = {
        'mapData': {'map': {'rowSize': 1, 'columnSize': 7, 'matrixData': [0, 0, 0, 1, 1, 0, 0]},
                    'tiles': [{'passableMask': 1}, {'passableMask': 0}]},
        'routes': [route], 'waves': [{'fragments': [{'actions': [spawn]}]}],
        'options': {'moveMultiplier': 1},
    }

    replay = build_level_replay(level, {'enemy': {'moveSpeed': 1}}, seed=0)

    assert replay['complete']
    event, = replay['events']
    assert event['path'] == [(0, 0), (1.25, 0), (2, 0), (5, 0), (6, 0)]
    assert event['waits'] == {1: 3}
    assert event['hiddenWaits'] == {2: 10}
    assert event['jumps'] == [2]
    assert event['exitTime'] == replay['duration'] == 16


def test_ordered_checkpoint_waits_use_battle_fragment_and_wave_clocks():
    route = {'path': [(0, 0), (2, 0), (9, 0), (10, 0)], 'jumps': [1], 'waits': {1: 1},
             'hidden_waits': {}, 'clock_waits': {1: [(1, 1, False), (3, 8, False), (4, 20, True),
                                                    (2, 20, True)]}}

    timed = _resolve_clock_waits(route, speed=1, spawn_time=10, fragment_start=6, wave_start=5)

    assert timed['waits'] == {1: 2}
    assert timed['hidden_waits'] == {1: 11}
    assert timed['wait_seconds'] == 13
    assert route['waits'] == {1: 1}


def test_periodic_cast_pauses_route_progress_without_pausing_battle_clock():
    attack = {'firstAt': 4, 'interval': 8, 'duration': 2}

    assert [_route_clock(age, attack) for age in (3, 4, 5, 6, 7, 12, 13, 15)] == [3, 4, 4, 4, 5, 10, 10, 11]
    assert [_battle_clock(age, attack) for age in (3, 4, 5, 10, 11)] == [3, 4, 7, 12, 15]
    route = {'path': [(0, 0), (2, 0), (3, 0)], 'jumps': [], 'waits': {}, 'hidden_waits': {},
             'clock_waits': {1: [(2, 5, False)]}}

    resolved = _resolve_clock_waits(route, 1, 0, 0, 0, attack)

    assert resolved['waits'] == {1: 2}
    assert _battle_clock(3 + resolved['wait_seconds'], attack) == 7


@pytest.mark.parametrize('wait', [180, 69, None])
def test_verified_stationary_lifetime_must_end_during_the_first_wait(wait):
    route = {
        'motionMode': 0, 'startPosition': {'col': 1, 'row': 0}, 'endPosition': {'col': 0, 'row': 0},
        'spawnOffset': {'x': 0.1, 'y': 0.05}, 'spawnRandomRange': {'x': 0.3, 'y': 0.0},
    }
    stationary_route = {**route, 'checkpoints': [{'type': 1, 'time': wait}]} if wait is not None else route
    spawn = {'actionType': 0, 'key': 'stationary', 'routeIndex': 0}
    normal = {'actionType': 0, 'key': 'normal', 'routeIndex': 1}
    level = {
        'mapData': {'map': {'rowSize': 1, 'columnSize': 2, 'matrixData': [0, 0]},
                    'tiles': [{'passableMask': 1}]},
        'routes': [stationary_route, route],
        'waves': [{'fragments': [{'actions': [spawn, normal]}]},
                  {'fragments': [{'actions': [normal]}]}],
    }
    actors = {
        'stationary': {'moveSpeed': 0, 'notCountInTotal': True, 'stationaryLifetime': {
            'appearAfter': 50, 'retireAfter': 70, 'visibleClip': 'Idle',
            'visibleClipSpeed': 1, 'visibleClipLoop': True,
        }},
        'normal': {'moveSpeed': 1},
    }
    replay = build_level_replay(level, actors, seed=20261109)

    if wait != 180:
        assert not replay['complete']
        assert any('原始移动速度为 0' in reason for reason in replay['diagnostics'])
        return
    assert replay['complete']
    stationary, first, second = replay['events']
    assert len(stationary['path']) == 1
    assert stationary['path'][0][1] == pytest.approx(.05)
    assert stationary['waits'] == {0: 70}
    assert stationary['hiddenWaits'] == {}
    assert stationary['jumps'] == []
    assert stationary['patrolStart'] is None
    assert stationary['moveSpeed'] == 0
    assert stationary['exitTime'] == 70
    assert second['time'] == first['exitTime'] < stationary['exitTime']
    assert replay['duration'] == second['exitTime']
