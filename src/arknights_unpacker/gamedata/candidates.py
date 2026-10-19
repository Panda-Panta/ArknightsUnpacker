"""Explicit unlock ordering instead of source-array ordering."""


def phase_number(value):
    if isinstance(value, int):
        return value
    try:
        return int(str(value).rsplit('_', 1)[-1])
    except ValueError:
        return -1


def condition(candidate):
    return candidate.get('unlockCondition') or candidate.get('unlockCond') or candidate.get('cond') or {}


def unlocked(cond, phase, level):
    needed = phase_number(cond.get('phase', 0))
    return phase > needed or (phase == needed and level >= cond.get('level', 1))


def choose(candidates, phase, level, rank):
    eligible = [c for c in candidates or [] if isinstance(c, dict) and unlocked(condition(c), phase, level) and c.get('requiredPotentialRank', 0) <= rank]
    return max(eligible, key=lambda c: (phase_number(condition(c).get('phase', 0)), condition(c).get('level', 1), c.get('requiredPotentialRank', 0)), default=None)


def potential_delta(candidate, baseline):
    from .descriptions import blackboard_map
    new = blackboard_map(candidate.get('blackboard'))
    old = blackboard_map((baseline or {}).get('blackboard'))
    return {key: {'before': old[key], 'after': value, 'delta': round(value - old[key], 12), 'kind': 'potential'} for key, value in new.items() if isinstance(value, (int, float)) and isinstance(old.get(key), (int, float)) and value != old[key]}
