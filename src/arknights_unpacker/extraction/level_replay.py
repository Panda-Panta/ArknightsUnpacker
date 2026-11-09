"""Join the original stage schedule and routes with verified enemy data."""
from collections import defaultdict
from math import ceil, dist, inf, isfinite
from random import Random
from secrets import randbits

from .level_routes import build_level_routes, sample_spawn_route
from .level_timeline import build_level_timeline


def _route_clock(battle_age, attack):
    if attack is None or battle_age <= attack['firstAt']:
        return battle_age
    cycles, within = divmod(battle_age - attack['firstAt'], attack['interval'])
    return battle_age - cycles * attack['duration'] - min(within, attack['duration'])


def _battle_clock(route_age, attack):
    if attack is None or route_age <= attack['firstAt']:
        return route_age
    running_period = attack['interval'] - attack['duration']
    casts = ceil((route_age - attack['firstAt']) / running_period)
    return route_age + casts * attack['duration']


def _resolve_clock_waits(route, speed, spawn_time, fragment_start, wave_start, attack=None):
    steps = route.get('clock_waits')
    if not steps:
        return route
    anchors = {2: 0.0, 3: fragment_start, 4: wave_start}
    waits, hidden_waits = route['waits'].copy(), route['hidden_waits'].copy()
    path, jumps = route['path'], route['jumps']
    elapsed = 0.0
    for index, point in enumerate(path):
        if index in steps:
            waits.pop(index, None)
            hidden_waits.pop(index, None)
            for kind, authored_time, hidden in steps[index]:
                if kind == 1:
                    pause = authored_time
                else:
                    target_age = anchors[kind] + authored_time - spawn_time
                    pause = max(0.0, _route_clock(target_age, attack) - elapsed)
                if pause:
                    target = hidden_waits if hidden else waits
                    target[index] = target.get(index, 0.0) + pause
                    elapsed += pause
        else:
            elapsed += waits.get(index, 0.0) + hidden_waits.get(index, 0.0)
        if index + 1 < len(path) and index not in jumps:
            elapsed += dist(point, path[index + 1]) / speed
    return {**route, 'waits': waits, 'hidden_waits': hidden_waits,
            'wait_seconds': sum(waits.values()) + sum(hidden_waits.values())}


def _stationary_duration(route, lifetime):
    if lifetime is None:
        return None
    appear, retire = lifetime['appearAfter'], lifetime['retireAfter']
    # Only truncate before the first authored wait finishes. Clock-dependent
    # waits or an immediately hidden path require a separate runtime model.
    if (isfinite(appear) and isfinite(retire) and 0 <= appear < retire < route['waits'].get(0, 0)
            and 0 not in route['hidden_waits'] and 0 not in route['clock_waits']):
        return retire
    return None


def build_level_replay(level, actors, *, seed=None, inactive_branches=(), battle_deadline=None, cancel=None):
    """Plan an unopposed wave preview using actual enemy movement speeds."""
    speed_factor = (level.get('options') or {}).get('moveMultiplier', 0.5)
    if not isfinite(speed_factor) or speed_factor <= 0:
        raise ValueError('移动速度倍率必须大于零。')
    routes, unavailable = build_level_routes(level, cancel=cancel)
    errors = []
    route_errors = defaultdict(set)
    seed = randbits(53) if seed is None else seed
    rng = Random(seed)
    spawn_routes = []

    def travel(enemy_id, route_index, extra, spawn_time, fragment_start, wave_start):
        # The scheduler calls travel once for each emitted spawn, in event order.
        spawn_routes.append(None)
        route_key = extra, route_index
        if route_key not in routes:
            reason = unavailable.get(route_key, '关卡未定义这条路线。')
            route_errors[reason].add(route_key)
            return None
        actor = actors.get(enemy_id, {})
        speed = actor.get('moveSpeed')
        if speed is None or not isfinite(speed) or speed < 0:
            errors.append(f'{enemy_id} · 缺少有效的敌人移动速度。')
            return None
        if speed == 0:
            duration = _stationary_duration(routes[route_key], actor.get('stationaryLifetime'))
            if duration is None:
                errors.append(f'{enemy_id} · 路线 {route_index} 的敌人原始移动速度为 0，退场时刻未确定。')
                return None
            route = sample_spawn_route(routes[route_key], rng)
            spawn_routes[-1] = {**route, 'path': route['path'][:1], 'waits': {0: duration},
                                'hidden_waits': {}, 'jumps': [], 'patrol_start': None}
            return duration
        route = sample_spawn_route(routes[route_key], rng)
        move_speed = speed * speed_factor
        attack = actor.get('periodicAttack')
        route = _resolve_clock_waits(route, move_speed, spawn_time, fragment_start, wave_start, attack)
        seconds = route['wait_seconds'] + route['distance'] / move_speed
        if seconds == 0:
            errors.append(f'{enemy_id} · 路线 {route_index} 需要实战触发。')
            return None
        spawn_routes[-1] = route
        return inf if route.get('patrol_start') is not None else _battle_clock(seconds, attack)

    not_count_in_total = {enemy_id for enemy_id, actor in actors.items()
                          if actor.get('notCountInTotal') is True}
    timeline = build_level_timeline(level, travel, spawn_clock=True, inactive_branches=inactive_branches,
                                    battle_deadline=battle_deadline, not_count_in_total=not_count_in_total,
                                    cancel=cancel)
    events = []
    for event, route in zip(timeline['events'], spawn_routes, strict=True):
        if route is None:
            continue
        events.append({
            **event, 'path': route['path'], 'waits': route['waits'],
            'hiddenWaits': route['hidden_waits'], 'jumps': route['jumps'],
            'patrolStart': route.get('patrol_start'),
            'moveSpeed': actors[event['enemyId']]['moveSpeed'] * speed_factor,
        })
    for reason, affected in route_errors.items():
        examples = '、'.join(f'{"额外 " if extra else ""}{index}' for extra, index in sorted(affected)[:3])
        errors.append(f'{len(affected)} 条路线受影响（例如 {examples}）。{reason}')
    diagnostics = [*errors, *timeline['diagnostics']]
    if any(event['patrolStart'] is not None for event in events):
        diagnostics.append('循环巡逻按关卡路线播放，实战技能触发的停留变化未模拟。')
    if any(route is not None and any(route['spawn_range']) for route in spawn_routes):
        diagnostics.append('当前回放使用同一个随机种子计算出生偏移。')
    return {
        **timeline, 'events': events, 'actors': actors, 'seed': seed,
        'complete': timeline['complete'] and not errors,
        'diagnostics': list(dict.fromkeys(diagnostics)),
    }
