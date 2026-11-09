"""Schedule ordinary LevelData waves against caller-supplied enemy exit times."""
from __future__ import annotations

from math import inf, isfinite


_SPAWN = 0
_PREVIEW_CURSOR = 1
_ACTIVATE_PREDEFINED = 6
_STORY = {2, 3}
_PRESENTATION = {_PREVIEW_CURSOR, 4, 5, 13}  # Red line, BGM, enemy info, empty action.
_CURSOR_INTERVAL = 0.3


def _seconds(value, default=0.0):
    if isinstance(value, (int, float)) and isfinite(value):
        return float(value)
    return default


def _fragment_queue(fragment, groups, check):
    queue = []
    delay = _seconds(fragment.get('preDelay'))
    for action in fragment.get('actions') or ():
        check()
        group = action.get('hiddenGroup')
        if group is not None and group not in groups:
            continue
        kind = action.get('actionType', _SPAWN)
        at = delay + _seconds(action.get('preDelay'))
        if kind == _PREVIEW_CURSOR:
            queue.extend((max(0.0, at + repeat * _CURSOR_INTERVAL), kind, action)
                         for repeat in range(2))
        elif kind == _SPAWN:
            interval = _seconds(action.get('interval'))
            for repeat in range(action.get('count', 1)):
                check()
                queue.append((max(0.0, at + repeat * interval), kind, action))
        else:
            queue.append((max(0.0, at), kind, action))
    return sorted(queue, key=lambda item: item[0])


def build_level_timeline(level, finish_time, *, cancel=None, spawn_clock=False, inactive_branches=(),
                         battle_deadline=None, not_count_in_total=()):
    """Return spawn events in battle seconds under the preview's movement assumptions.

    ``finish_time(enemy_id, route_index, use_extra_route)`` gives seconds from
    spawn until that enemy exits the simulation. Return infinity for an indefinite
    patrol and None for an unknown exit.
    With ``spawn_clock``, the callback also receives the spawn, fragment start,
    and wave start times in that order. The starts precede their authored delays.
    ``inactive_branches`` identifies branches proved unreachable in this preview.
    ``not_count_in_total`` contains enemies excluded from the scheduler's clear
    sets by the enemy database. Their visual spawn and exit are still recorded.
    Story and tutorial dialogs are treated as skipped. Simulation ticks, player
    actions and mode-specific scheduler plugins are outside this timeline.
    """
    def check():
        if cancel is not None:
            cancel.check()

    check()
    groups = set(level.get('enabledHiddenGroups') or ())
    waves = level.get('waves') or ()
    events = []
    predefined_activations = []
    diagnostics = []
    branches = set(level.get('branches') or ())
    inactive = branches.intersection(inactive_branches)
    unresolved = branches - inactive
    if inactive:
        diagnostics.append(f'{len(inactive)} 条条件分支在当前无部署预览场景中不会触发。')
    if unresolved:
        examples = '、'.join(sorted(unresolved)[:3])
        diagnostics.append(f'{len(unresolved)} 条运行时分支的触发条件未确定（例如 {examples}）。')
    now = last_exit = 0.0
    unknown_final_exit = False
    persistent_final = False

    def result(blocked_at=None):
        duration = max(now, last_exit)
        if battle_deadline is not None:
            duration = min(duration, battle_deadline)
        return {'events': events, 'duration': duration,
                'predefinedActivations': predefined_activations,
                'inactiveBranchIds': sorted(inactive),
                'battleDeadline': battle_deadline,
                'diagnostics': diagnostics, 'complete': not unresolved and blocked_at is None,
                'blockedAt': blocked_at}

    for wave_index, wave in enumerate(waves):
        check()
        wave_start = now
        now += max(0.0, _seconds(wave.get('preDelay')))
        if battle_deadline is not None and now >= battle_deadline:
            return result()
        label = f'第 {wave_index + 1} 波'
        if wave.get('advancedWaveTag'):
            diagnostics.append(f'{label}依赖模式条件，出怪时间未确定。')
            return result(now)
        wave_exit = 0.0
        unknown_wave_exit = False
        for fragment_index, fragment in enumerate(wave.get('fragments') or ()):
            check()
            label_fragment = f'{label}第 {fragment_index + 1} 段'
            fragment_start = now
            unknown_blocking_action = False
            for offset, kind, action in _fragment_queue(fragment, groups, check):
                check()
                now = fragment_start + offset
                if battle_deadline is not None and now >= battle_deadline:
                    return result()
                if action.get('randomSpawnGroupKey') or action.get('randomSpawnGroupPackKey'):
                    diagnostics.append(f'{label_fragment}包含未确定的随机动作，后续出怪未确定。')
                    return result(now)
                if kind in _STORY:
                    message = '剧情和教学对话按跳过处理，时间轴采用战斗计时。'
                    if message not in diagnostics:
                        diagnostics.append(message)
                    continue
                if kind == _ACTIVATE_PREDEFINED:
                    if action.get('key'):
                        predefined_activations.append({'key': action['key'], 'time': now,
                                                       'waveIndex': wave_index,
                                                       'fragmentIndex': fragment_index})
                    continue
                if kind != _SPAWN:
                    if action.get('blockFragment'):
                        unknown_blocking_action = True
                    elif kind not in _PRESENTATION:
                        diagnostics.append(f'{label_fragment}依赖运行时动作 {kind}，后续时间未确定。')
                        return result(now)
                    continue
                enemy = action.get('key')
                route = action.get('routeIndex', 0)
                extra = bool(action.get('useExtraRoute'))
                if not enemy or not isinstance(route, int) or route < 0:
                    diagnostics.append(f'{label_fragment}缺少有效的敌人或路线引用。')
                    return result(now)
                clocks = (now, fragment_start, wave_start) if spawn_clock else ()
                travel = finish_time(enemy, route, extra, *clocks)
                persistent = travel == inf
                duration = _seconds(travel, None)
                exit_at = now + duration if duration is not None and duration >= 0 else None
                events.append({'enemyId': enemy, 'time': now, 'exitTime': exit_at,
                               'routeIndex': route, 'useExtraRoute': extra,
                               'waveIndex': wave_index, 'fragmentIndex': fragment_index})
                if (action.get('isUnharmfulAndAlwaysCountAsKilled') or action.get('notCountInTotal')
                        or enemy in not_count_in_total):
                    continue
                if exit_at is not None:
                    last_exit = max(last_exit, exit_at)
                if action.get('managedByScheduler', True):
                    unknown_final_exit |= exit_at is None and not persistent
                    persistent_final |= persistent
                    if not action.get('dontBlockWave'):
                        unknown_wave_exit |= exit_at is None and not persistent
                        if persistent:
                            wave_exit = inf
                        elif exit_at is not None:
                            wave_exit = max(wave_exit, exit_at)
            if unknown_blocking_action:
                diagnostics.append(f'{label_fragment}仍需等待动作完成，下一段时间未确定。')
                return result(now)
        limit = _seconds(wave.get('maxTimeWaitingForNextWave'), -1.0)
        has_next_wave = wave_index + 1 < len(waves)
        deadline = now + max(0.0, limit) if has_next_wave and limit >= -0.00001 else None
        if battle_deadline is not None:
            deadline = battle_deadline if deadline is None else min(deadline, battle_deadline)
        wait_until = max(now, wave_exit)
        if (unknown_wave_exit and (deadline is None or wait_until < deadline)) or (wait_until == inf and deadline is None):
            diagnostics.append(f'{label}仍有敌人退出时间未确定，不能确定清场时刻。')
            return result(now)
        if deadline is not None:
            wait_until = min(wait_until, deadline)
        now = wait_until + max(0.0, _seconds(wave.get('postDelay')))

    if persistent_final and battle_deadline is not None:
        now = battle_deadline
    elif unknown_final_exit or persistent_final:
        diagnostics.append('仍有敌人退出时间未确定，不能确定关卡结束时刻。')
        return result(now)
    return result()
