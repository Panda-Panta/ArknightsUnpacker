"""Compare absolute module stages under one build without stacking their bonuses."""
import json

from .attributes import panel
from .build import build_state
from .candidates import choose, unlocked
from .descriptions import render_description


def _identity(effect):
    scope = {key: value for key, value in effect.get('scope', {}).items() if value}
    index = effect.get('talent_index')
    talent = index if isinstance(index, int) and index >= 0 else effect.get('name', '')
    return talent, effect.get('name') or '', json.dumps(scope, sort_keys=True, ensure_ascii=False)


def _previous_description(effect, previous_effects, original):
    candidates = previous_effects.get(_identity(effect), [])
    if not candidates:
        return original
    visible = [item for item in candidates if item.get('description', '').strip()]
    exact = [item for item in visible if item.get('target') == effect.get('target')]
    descriptions = {item['description'] for item in exact or visible}
    # Targets can change between levels while the same named effect continues.
    # Prefer the same target, then accept only a unique nonempty description.
    return next(iter(descriptions)) if len(descriptions) == 1 else None


def add_comparisons(data, ch, spec, module, base_trait):
    """Enrich a newly built profile; original stage/effect fields remain intact.

    Attribute totals use panel() exactly as build_operator does. Battle talent
    percentages, token effects and conditional implementation parameters never
    enter these totals. Each attributeBlackboard is an absolute stage total.
    """
    phase, level, rank = build_state(ch, spec)
    module.metadata['comparison_build'] = {'phase': phase, 'level': level,
                                          'potential': rank + 1, 'trust': spec.trust}
    diagnostics = []
    before = {row['key']: row for row in panel(data.tables, ch, phase, level, rank, spec.trust, [], diagnostics)}
    terms = data.tables.get('gamedata_const', {}).get('termDescriptionDict', {})
    originals = {}
    for index, slot in enumerate(ch.get('talents') or []):
        talent = choose(slot.get('candidates'), phase, level, rank)
        if talent and not talent.get('isHideTalent'):
            originals[index], _ = render_description(talent.get('description'), talent.get('blackboard'), terms)
    previous = None
    for stage in module.phases:
        previous_level = previous['level'] if previous else 0
        # Match the unconditional panel acceptance rules in build_operator.
        reason = ('conditional' if module.metadata.get('special_equip') or any(stage.get('scope', {}).values())
                  else 'locked' if not unlocked(module.metadata.get('unlock_condition') or {}, phase, level) else '')
        after = {row['key']: row for row in panel(data.tables, ch, phase, level, rank, spec.trust,
                                                 stage.get('attributes', []), [])} if not reason else {}
        old_bonuses = {row['key']: row.get('value') for row in previous.get('attributes', [])} if previous else {}
        attributes = []
        for row in stage.get('attributes', []):
            key, bonus = row['key'], row.get('value')
            old = old_bonuses.get(key, 0)
            delta = round(bonus - old, 12) if isinstance(bonus, (int, float)) and isinstance(old, (int, float)) else None
            attributes.append({'key': key, 'label': row.get('label', key),
                               'unit': before.get(key, {}).get('unit', ''),
                               'before': before.get(key, {}).get('value'),
                               'after': after.get(key, {}).get('value'),
                               'bonus': bonus, 'delta': delta})
        previous_trait = previous.get('trait', base_trait) if previous else base_trait
        stage['comparison'] = {'previous_level': previous_level, 'panel_applies': not reason,
                               'reason': reason, 'attributes': attributes,
                               'trait': {'original': base_trait, 'previous': previous_trait,
                                         'current': stage.get('trait', ''),
                                         'changed_from_previous': stage.get('trait', '') != previous_trait}}
        old_effects = {}
        for effect in previous.get('effects', []) if previous else []:
            old_effects.setdefault(_identity(effect), []).append(effect)
        for effect in stage.get('effects', []):
            # A token's talent index refers to the token, never to the operator.
            original = None if effect.get('scope', {}).get('isToken') else originals.get(effect.get('talent_index'))
            effect['comparison'] = {'original': original,
                                    'previous': _previous_description(effect, old_effects, original),
                                    'current': effect.get('description', ''),
                                    'previous_level': previous_level}
        previous = stage
