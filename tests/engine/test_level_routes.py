from arknights_unpacker.extraction.level_routes import build_level_routes


def _level(routes, block_edges=None):
    return {
        'mapData': {
            'map': {'rowSize': 2, 'columnSize': 2, 'matrixData': [0] * 4},
            'tiles': [{'passableMask': 3}],
            'blockEdges': block_edges,
        },
        'routes': routes,
    }


def _route(start, end, motion_mode=0, checkpoints=()):
    return {
        'startPosition': dict(zip(('col', 'row'), start)),
        'endPosition': dict(zip(('col', 'row'), end)),
        'motionMode': motion_mode,
        'allowDiagonalMove': True,
        'checkpoints': checkpoints,
    }


def test_block_edges_apply_in_both_directions_without_allowing_corner_cuts():
    routes, unavailable = build_level_routes(_level([
        _route((0, 0), (0, 1)),
        _route((0, 1), (0, 0)),
        _route((0, 0), (0, 1), motion_mode=1),
        _route((0, 0), (1, 1)),
    ], [{'pos': {'col': 0, 'row': 0}, 'direction': 0, 'blockMask': 1}]))

    assert not unavailable
    assert routes[False, 0]['path'] == [(0, 0), (1, 0), (1, 1), (0, 1)]
    assert routes[False, 1]['path'] == list(reversed(routes[False, 0]['path']))
    assert routes[False, 2]['path'] == [(0, 0), (0, 1)]
    assert routes[False, 3]['path'] == [(0, 0), (1, 0), (1, 1)]


def test_clock_checkpoints_keep_the_order_of_visible_and_hidden_waits():
    routes, unavailable = build_level_routes(_level([
        _route((0, 0), (1, 1), checkpoints=[
            {'type': 1, 'time': 1},
            {'type': 3, 'time': 3},
            {'type': 5},
            {'type': 2, 'time': 4},
            {'type': 1, 'time': 2},
            {'type': 6, 'position': {'col': 1, 'row': 0}},
            {'type': 4, 'time': 5},
        ]),
    ]))

    assert not unavailable
    route = routes[False, 0]
    assert route['waits'] == {0: 1}
    assert route['hidden_waits'] == {0: 2}
    assert route['jumps'] == [0]
    assert route['clock_waits'] == {
        0: [(1, 1, False), (3, 3, False), (2, 4, True), (1, 2, True)],
        1: [(4, 5, False)],
    }


def test_patrol_rewinds_into_adjacent_waits_and_closes_the_cycle():
    routes, unavailable = build_level_routes(_level([
        _route((0, 0), (0, 0), checkpoints=[
            {'type': 0, 'position': {'col': 1, 'row': 0}},
            {'type': 1, 'time': 2},
            {'type': 8, 'position': {'col': 1, 'row': 1}},
            {'type': 8, 'position': {'col': 0, 'row': 1}},
            {'type': 0, 'position': {'col': 0, 'row': 0}},
        ]),
    ]))

    assert not unavailable
    route = routes[False, 0]
    assert route['patrol_start'] == 4
    assert route['path'] == [(0, 0), (1, 0), (1, 1), (0, 1), (0, 1), (1, 1), (0, 1)]
    assert route['waits'] == {1: 2, 4: 2}
