from math import dist

import pytest

from arknights_unpacker.extraction import level_replay
from arknights_unpacker.extraction.level_replay import build_level_replay


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
