"""Prepare grid paths and explicit waits for the offline wave renderer."""
from heapq import heappop, heappush
from math import hypot, isfinite, sqrt


_CARDINAL = ((-1, 0), (0, 1), (1, 0), (0, -1))
_DIAGONAL = ((-1, 1), (1, 1), (1, -1), (-1, -1))
_EDGE_DIRECTIONS = ((0, 1), (1, 0), (0, -1), (-1, 0))
_PASSABLE = {0: 1, 1: 2}
_MOVE = 0
_WAIT = 1
_CLOCK_WAITS = (2, 3, 4)
_WAITS = (_WAIT, *_CLOCK_WAITS)
_DISAPPEAR = 5
_APPEAR = 6
_PATROL_MOVE = 8
_PATROL_CHECKPOINTS = range(1, 11)


def _grid(map_data):
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


def _blocked_edges(map_data):
    blocked = {}
    for edge in map_data.get('blockEdges') or ():
        direction, mask = edge['direction'], edge['blockMask']
        if direction not in range(len(_EDGE_DIRECTIONS)) or mask not in range(4):
            raise ValueError('关卡阻挡边数据无效。')
        x, y = start = _point(edge['pos'])
        dx, dy = _EDGE_DIRECTIONS[direction]
        end = x + dx, y + dy
        # The client removes both outgoing directions on the shared edge.
        combined = blocked.get((start, end), 0) | mask
        blocked[start, end] = blocked[end, start] = combined
    return blocked


def _segment(grid, edges, start, end, mask, diagonal, check):
    def traversable(x, y):
        return 0 <= y < len(grid) and 0 <= x < len(grid[y]) and grid[y][x] & mask

    def blocked(first, second):
        return edges.get((first, second), 0) & mask

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
            if dx and dy:
                horizontal, vertical = (x + dx, y), (x, y + dy)
                if not (traversable(*horizontal) and traversable(*vertical)):
                    continue
                # A diagonal must clear all sides of the corner it crosses.
                if edges and (blocked(point, horizontal) or blocked(point, vertical)
                              or blocked(horizontal, neighbor) or blocked(vertical, neighbor)):
                    continue
            elif edges and blocked(point, neighbor):
                continue
            next_distance = distance + (sqrt(2) if dx and dy else 1)
            if next_distance < best.get(neighbor, float('inf')):
                parents[neighbor] = point
                best[neighbor] = next_distance
                heappush(frontier, (next_distance, neighbor))
    raise ValueError('未找到可通行的连续路线。')


def _offset(data):
    return (data or {}).get('x', 0), (data or {}).get('y', 0)


def _path_length(path, jumps):
    return sum(hypot(x2 - x1, y2 - y1)
               for i, ((x1, y1), (x2, y2)) in enumerate(zip(path, path[1:])) if i not in jumps)


def sample_spawn_route(route, rng):
    range_x, range_y = route['spawn_range']
    if range_x == range_y == 0:
        return route
    path = route['path'].copy()
    x, y = path[0]
    # Route.GetSpawnOffset adds two independent symmetric draws to the fixed offset.
    path[0] = x + rng.uniform(-range_x, range_x), y + rng.uniform(-range_y, range_y)
    return {**route, 'path': path, 'distance': _path_length(path, route['jumps'])}


def _append_move(path, segment, target):
    path.extend(segment[1:-1])
    if path[-1] != target:
        path.append(target)


def _waypoint(checkpoint, tile):
    offset_x, offset_y = _offset(checkpoint.get('reachOffset'))
    if not all(isfinite(value) and abs(value) <= 0.5 for value in (offset_x, offset_y)):
        raise ValueError('途经点偏移超出原地图格。')
    return tile[0] + offset_x, tile[1] + offset_y


def _patrol_checkpoints(checkpoints):
    """Return the authored prefix and one repeat when a patrol rewinds."""
    kinds = [checkpoint.get('type') for checkpoint in checkpoints]
    for index, kind in enumerate(kinds):
        next_index = index + 1
        if kind != _PATROL_MOVE or (next_index < len(kinds) and kinds[next_index] in _PATROL_CHECKPOINTS):
            continue
        start = index
        while start > 0 and kinds[start - 1] in _PATROL_CHECKPOINTS:
            start -= 1
        if start == index:
            continue
        if any(kind in _CLOCK_WAITS for kind in kinds[start:next_index]):
            raise ValueError('循环巡逻包含依赖战斗时钟的等待。')
        return checkpoints[:next_index] + checkpoints[start:next_index], next_index
    return checkpoints, None


def _route(grid, edges, source, check):
    mask = _PASSABLE.get(source.get('motionMode'))
    if mask is None:
        raise ValueError('此移动模式需要实战触发。')
    spawn_range = _offset(source.get('spawnRandomRange'))
    if any(not isfinite(value) or value < 0 for value in spawn_range):
        raise ValueError('路线的随机出生范围无效。')
    current = _point(source['startPosition'])
    path, waits, hidden_waits, jumps = [current], {}, {}, []
    ordered_waits = {}
    hidden = False
    diagonal = source.get('allowDiagonalMove', False)
    checkpoints, patrol_restart = _patrol_checkpoints(source.get('checkpoints') or ())
    patrol_start = None
    for checkpoint_index, checkpoint in enumerate(checkpoints):
        check()
        if checkpoint_index == patrol_restart:
            # A wait after the rewind belongs to the repeat, even at the same position.
            patrol_start = len(path)
            path.append(path[-1])
        kind = checkpoint.get('type')
        if kind in (_MOVE, _PATROL_MOVE) and not hidden:
            if checkpoint.get('randomizeReachOffset') or checkpoint.get('reachDistance'):
                raise ValueError('途经点使用随机偏移或特殊到达距离。')
            end = _point(checkpoint['position'])
            _append_move(path, _segment(grid, edges, current, end, mask, diagonal, check), _waypoint(checkpoint, end))
            current = end
        elif kind in _WAITS and isfinite(checkpoint['time']) and checkpoint['time'] >= 0:
            index = len(path) - 1
            seconds = checkpoint['time']
            ordered_waits.setdefault(index, []).append((kind, seconds, hidden))
            if kind == _WAIT:
                pauses = hidden_waits if hidden else waits
                pauses[index] = pauses.get(index, 0) + seconds
        elif kind == _DISAPPEAR and not hidden:
            hidden = True
        elif kind == _APPEAR and hidden:
            current = _point(checkpoint['position'])
            jumps.append(len(path) - 1)
            path.append(_waypoint(checkpoint, current))
            hidden = False
        else:
            raise ValueError(f'路线含尚未支持的途经点指令 {kind}。')
    if hidden:
        raise ValueError('敌人消失后需要运行时指令才能返回。')
    if patrol_start is None:
        end = _point(source['endPosition'])
        _append_move(path, _segment(grid, edges, current, end, mask, diagonal, check), end)
    else:
        loop_jumps = {index - patrol_start for index in jumps if index >= patrol_start}
        loop_waits = sum(seconds for pauses in (waits, hidden_waits)
                         for index, seconds in pauses.items() if index >= patrol_start)
        if not loop_waits and not _path_length(path[patrol_start:], loop_jumps):
            raise ValueError('循环巡逻没有移动距离或等待时间。')
        if len(path) == patrol_start + 1:
            path.append(path[-1])
    offset_x, offset_y = _offset(source.get('spawnOffset'))
    if offset_x or offset_y:
        x, y = path[0]
        path[0] = x + offset_x, y + offset_y
    clock_waits = {index: waits_at_point for index, waits_at_point in ordered_waits.items()
                   if any(kind in _CLOCK_WAITS for kind, _, _ in waits_at_point)}
    return {'path': path, 'waits': waits, 'hidden_waits': hidden_waits, 'clock_waits': clock_waits, 'jumps': jumps,
            'distance': _path_length(path, jumps), 'patrol_start': patrol_start,
            'wait_seconds': sum(waits.values()) + sum(hidden_waits.values()), 'spawn_range': spawn_range}


def build_level_routes(level, *, cancel=None):
    """Return normal and extra paths in game (column, row) coordinates."""
    check = cancel.check if cancel is not None else lambda: None
    check()
    map_data = level.get('mapData') or {}
    grid, edges = _grid(map_data), _blocked_edges(map_data)
    routes, unavailable = {}, {}
    for field, extra in (('routes', False), ('extraRoutes', True)):
        for index, source in enumerate(level.get(field) or ()):
            check()
            try:
                routes[(extra, index)] = _route(grid, edges, source, check)
            except (KeyError, TypeError, ValueError) as error:
                unavailable[(extra, index)] = str(error)
    return routes, unavailable
