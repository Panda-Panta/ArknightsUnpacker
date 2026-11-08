"""Join the original stage schedule and routes with verified enemy data."""
from math import isfinite

from .level_routes import build_level_routes
from .level_timeline import build_level_timeline


def build_level_replay(level, actors, *, cancel=None):
    """Plan an unopposed wave preview using actual enemy movement speeds."""
    speed_factor = (level.get('options') or {}).get('moveMultiplier', 0.5)
    if not isfinite(speed_factor) or speed_factor <= 0:
        raise ValueError('移动速度倍率必须大于零。')
    routes, unavailable = build_level_routes(level, cancel=cancel)
    errors = []

    def travel(enemy_id, route_index, extra):
        route_key = extra, route_index
        if route_key not in routes:
            errors.append(f'{enemy_id} · 路线 {route_index}：{unavailable.get(route_key, "关卡未定义这条路线。")}')
            return None
        speed = actors.get(enemy_id, {}).get('moveSpeed')
        if speed is None or not isfinite(speed) or speed <= 0:
            errors.append(f'{enemy_id} · 缺少有效的敌人移动速度。')
            return None
        route = routes[route_key]
        seconds = route['wait_seconds'] + route['distance'] / (speed * speed_factor)
        if seconds == 0:
            errors.append(f'{enemy_id} · 路线 {route_index} 需要实战触发。')
            return None
        return seconds

    timeline = build_level_timeline(level, travel, cancel=cancel)
    events = []
    for event in timeline['events']:
        if event['exitTime'] is None:
            continue
        route = routes[(event['useExtraRoute'], event['routeIndex'])]
        events.append({
            **event, 'path': route['path'], 'waits': route['waits'],
            'moveSpeed': actors[event['enemyId']]['moveSpeed'] * speed_factor,
        })
    return {
        **timeline, 'events': events, 'actors': actors,
        'complete': timeline['complete'] and not errors,
        'diagnostics': list(dict.fromkeys([*timeline['diagnostics'], *errors])),
    }
