"""Explicit unlock ordering instead of source-array ordering."""
from decimal import Decimal
import re


_POTENTIAL_ANNOTATION = re.compile(
    r'(-?\d+(?:\.\d+)?)(%?)<@ba\.talpu>[（(]([+-]\d+(?:\.\d+)?)(%?)[）)]</>')


def _potential_description(candidate):
    from .descriptions import TERM, render_description
    text = (candidate.get('description') or candidate.get('upgradeDescription') or
            candidate.get('overrideDescripton') or '')
    addition = candidate.get('additionalDescription') or ''
    if addition:
        text += ('\n' if text else '') + addition
    # Compare the game's labels, independently of where term definitions appear.
    text = TERM.sub(lambda match: match.group(2), text)
    board = candidate.get('blackboard')
    rendered, _ = render_description(text, board)
    annotations = []

    def original_value(match):
        current, unit, increment, increment_unit = match.groups()
        if unit != increment_unit:
            return match.group(0)
        annotations.append(match.group(0))
        original = Decimal(current) - Decimal(increment)
        return format(original.normalize(), 'f') + unit

    original, _ = render_description(_POTENTIAL_ANNOTATION.sub(original_value, text), board)
    return rendered, original, bool(annotations)


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
    changes = {key: {'before': old[key], 'after': value, 'delta': round(value - old[key], 12), 'kind': 'potential'} for key, value in new.items() if isinstance(value, (int, float)) and isinstance(old.get(key), (int, float)) and value != old[key]}
    if changes and baseline:
        before, _, _ = _potential_description(baseline)
        after, original, annotated = _potential_description(candidate)
        if before and after and before != after:
            evidence = {'before': before, 'after': after,
                        'annotated': annotated and original == before}
            for change in changes.values():
                change['metadata'] = {'description_evidence': evidence}
    return changes
