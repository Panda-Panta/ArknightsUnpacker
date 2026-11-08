"""Prepare grid paths and explicit waits for the offline wave renderer."""
from heapq import heappop, heappush
from math import hypot, isfinite, sqrt


_CARDINAL = ((-1, 0), (0, 1), (1, 0), (0, -1))
_DIAGONAL = ((-1, 1), (1, 1), (1, -1), (-1, -1))
_PASSABLE = {0: 1, 1: 2}


def _grid(level):
    map_data = level.get('mapData') or {}
    if map_data.get('blockEdges'):
        raise ValueError('关卡含独立阻挡边，当前路径规划不支持。')
    grid = map_data.get('map') or {}
    rows, columns = grid.get('rowSize'), grid.get('columnSize')
    matrix = grid.get('matrixData') or []
    tiles = map_data.get('tiles') or []
    if (not rows or not columns or rows * columns > 16_384 or len(matrix) != rows * columns
            or any(not isinstance(index, int) or not 0 <= index < len(tiles) for index in matrix)):
        raise ValueError('关卡地图格子数据无效。')
    return [
        [tiles[matrix[(rows - 1 - row) * columns + col]]['passableMask'] for col in range(columns)]
        for row in range(rows)
    ]


def _point(position):
    return position['col'], position['row']


def _segment(grid, start, end, mask, diagonal, check):
    def traversable(x, y):
        return 0 <= y < len(grid) and 0 <= x < len(grid[y]) and grid[y][x] & mask

    if not traversable(*start) or not traversable(*end):
        raise ValueError('起点或终点不可通行。')
    directions = _CARDINAL + _DIAGONAL if diagonal else _CARDINAL
    parents, best = {}, {start: 0.0}
    frontier = [(0.0, start)]
    while frontier:
        check()
        distance, point = heappop(frontier)
        if point == end:
            points = [point]
            while point != start:
                point = parents[point]
                points.append(point)
            return points[::-1]
        if distance != best[point]:
            continue
        x, y = point
        for dx, dy in directions:
            neighbor = x + dx, y + dy
            if not traversable(*neighbor):
                continue
            if dx and dy and not (traversable(x + dx, y) and traversable(x, y + dy)):
                continue
            next_distance = distance + (sqrt(2) if dx and dy else 1)
            if next_distance < best.get(neighbor, float('inf')):
                parents[neighbor] = point
                best[neighbor] = next_distance
                heappush(frontier, (next_distance, neighbor))
    raise ValueError('未找到可通行的连续路线。')


def _offset(data):
    return (data or {}).get('x', 0), (data or {}).get('y', 0)


def _path_length(path):
    return sum(hypot(x2 - x1, y2 - y1) for (x1, y1), (x2, y2) in zip(path, path[1:]))


def sample_spawn_route(route, rng):
    range_x, range_y = route['spawn_range']
    if range_x == range_y == 0:
        return route
    path = route['path'].copy()
    x, y = path[0]
    # Route.GetSpawnOffset adds two independent symmetric draws to the fixed offset.
    path[0] = x + rng.uniform(-range_x, range_x), y + rng.uniform(-range_y, range_y)
    return {**route, 'path': path, 'distance': _path_length(path)}


def _route(grid, source, check):
    mask = _PASSABLE.get(source.get('motionMode'))
    if mask is None:
        raise ValueError('此移动模式需要实战触发。')
    spawn_range = _offset(source.get('spawnRandomRange'))
    if any(not isfinite(value) or value < 0 for value in spawn_range):
        raise ValueError('路线的随机出生范围无效。')
    current = _point(source['startPosition'])
    path, waits = [current], {}
    diagonal = source.get('allowDiagonalMove', False)
    for checkpoint in source.get('checkpoints') or ():
        check()
        kind = checkpoint.get('type')
        if kind == 0 and not (any(_offset(checkpoint.get('reachOffset')))
                              or checkpoint.get('randomizeReachOffset') or checkpoint.get('reachDistance')):
            end = _point(checkpoint['position'])
            path.extend(_segment(grid, current, end, mask, diagonal, check)[1:])
            current = end
        elif kind == 1 and isfinite(checkpoint['time']) and checkpoint['time'] >= 0:
            index = len(path) - 1
            waits[index] = waits.get(index, 0) + checkpoint['time']
        else:
            raise ValueError('路线含未适配的途经点指令。')
    path.extend(_segment(grid, current, _point(source['endPosition']), mask, diagonal, check)[1:])
    offset_x, offset_y = _offset(source.get('spawnOffset'))
    if offset_x or offset_y:
        x, y = path[0]
        path[0] = x + offset_x, y + offset_y
    return {'path': path, 'waits': waits, 'distance': _path_length(path),
            'wait_seconds': sum(waits.values()), 'spawn_range': spawn_range}


def build_level_routes(level, *, cancel=None):
    """Return normal and extra paths in game (column, row) coordinates."""
    check = cancel.check if cancel is not None else lambda: None
    check()
    grid = _grid(level)
    routes, unavailable = {}, {}
    for field, extra in (('routes', False), ('extraRoutes', True)):
        for index, source in enumerate(level.get(field) or ()):
            check()
            try:
                routes[(extra, index)] = _route(grid, source, check)
            except (KeyError, TypeError, ValueError) as error:
                unavailable[(extra, index)] = str(error)
    return routes, unavailable
