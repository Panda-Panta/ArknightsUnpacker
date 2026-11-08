from arknights_unpacker.extraction.level_replay_tiles import _gate_positions


def test_gate_positions_use_bottom_up_rows_and_tile_height():
    level = {'mapData': {
        'map': {'rowSize': 2, 'columnSize': 3, 'matrixData': [0, 1, 0, 2, 0, 0]},
        'tiles': [
            {'tileKey': 'tile_road', 'heightType': 0},
            {'tileKey': 'tile_start', 'heightType': 1},
            {'tileKey': 'tile_end', 'heightType': 0},
        ],
    }}
    layout = {'origin': [-1, -2, 0], 'columns': [1, 0, 0], 'rows': [0, 1, 0]}

    assert _gate_positions(level, layout) == {
        'tile_start': [[0., -1., .4]],
        'tile_end': [[-1., -2., 0.]],
    }
