"""Resolve authored weighted choices for a seeded battle preview."""
from __future__ import annotations

import re
from random import Random


_CHOICE_ACTIONS = {0, 6, 13}  # Spawn, activate predefined, empty.
_ACTIVATE_PREDEFINED = 6
# trap_086_larva is ENEMY in its prefab. sktok_larva attaches the summon
# passive that advances branch_id when the owner is destroyed.
_ENEMY_DESTRUCTION_TRIGGERS = {'trap_086_larva'}
_PASSIVE_TILE_TYPES = {'tile_road', 'tile_wall', 'tile_floor', 'tile_forbidden',
                       'tile_start', 'tile_end', 'tile_telin', 'tile_telout'}
_DIRECTIONAL_LARVA_BRANCH = re.compile(r'(?:north|south)_[rs][0-9]+\Z')
_SANDBOX_WOOD = 'trap_515_xb2wdo'
# These original resource and dialog prefab modes have no attack trigger.
_SANDBOX_PASSIVE_PREDEFINES = {_SANDBOX_WOOD, 'trap_516_xb2wod', 'trap_517_xb2stn',
                               'trap_522_xb2dor', 'trap_530_xb2gtr', 'trap_531_xb2str', 'trap_532_xb2shb'}


def _resolve_actions(actions, rng):
    groups = {}
    for index, action in enumerate(actions):
        group = action.get('randomSpawnGroupKey')
        if group:
            groups.setdefault(group, []).append(index)

    resolved = {}
    for indices in groups.values():
        choices = [actions[index] for index in indices]
        if any(choice.get('actionType', 0) not in _CHOICE_ACTIONS
               or choice.get('randomType', 0) != 0 or choice.get('refreshType', 0) != 0
               or type(choice.get('weight')) is not int or choice['weight'] < 0
               for choice in choices):
            continue
        total = sum(choice['weight'] for choice in choices)
        if total <= 0:
            continue
        draw = rng.randrange(total)
        for index, choice in zip(indices, choices):
            draw -= choice['weight']
            if draw < 0:
                break
        pack = choice.get('randomSpawnGroupPackKey')
        for option_index, option in zip(indices, choices):
            if (choice.get('key') and option.get('key') and
                    (option_index == index or (pack and option.get('randomSpawnGroupPackKey') == pack))):
                selected = dict(option)
                selected.pop('randomSpawnGroupKey', None)
                selected.pop('randomSpawnGroupPackKey', None)
                resolved[option_index] = selected
            else:
                resolved[option_index] = None

    return [resolved.get(index, action) for index, action in enumerate(actions)
            if index not in resolved or resolved[index] is not None]


def resolve_replay_waves(level, seed):
    """Keep one weighted option per wave/fragment/group, using the preview seed.

    The client uses battle or run RNG state. This preview reproduces the
    authored alternatives and weights with its own deterministic seed.
    Run-dependent choices remain marked so the scheduler can report them.
    """
    rng = Random(seed)
    waves = [dict(wave, fragments=[
        dict(fragment, actions=_resolve_actions(fragment.get('actions') or (), rng))
        for fragment in wave.get('fragments') or ()
    ]) for wave in level.get('waves') or ()]
    return dict(level, waves=waves)


def _branch_references(value, branch_ids):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in branch_ids:
                yield key
            yield from _branch_references(item, branch_ids)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _branch_references(item, branch_ids)
    elif isinstance(value, str) and value in branch_ids:
        yield value


def _passive_context(level, actions, passive_tiles):
    if (any(level.get(key) for key in ('globalBuffs', 'operaConfig', 'runes', 'optionalRunes'))
            or any((level.get('hardPredefines') or {}).values())
            or any(action.get('actionType', 0) not in {0, 1, 4, 5, 6, 13} for action in actions)):
        return False
    tiles = (level.get('mapData') or {}).get('tiles') or ()
    return bool(tiles) and all(tile.get('tileKey') in passive_tiles for tile in tiles)


def _present_predefines(level, activated):
    for collection, rows in (level.get('predefines') or {}).items():
        for row in rows or ():
            alias = row.get('alias')
            if alias in activated or (collection.endswith('Insts') and row.get('hidden') is not True):
                yield alias, collection, (row.get('inst') or {}).get('characterKey')


def _unopposed_destruction_owners(level, actions, activated, harmless_tokens, passive_tiles):
    if not _passive_context(level, actions, passive_tiles):
        return None
    present = list(_present_predefines(level, activated))
    aliases = {alias for alias, _, _ in present}
    if not aliases.issuperset(activated) or any(collection != 'tokenInsts' or character not in harmless_tokens
                                             for _, collection, character in present):
        return None
    return aliases


def _directional_larva_branches(level, branches, owners, references):
    # The client advances a branch by ID. Directional larva routes without a
    # matching placed owner are unused alternatives in the authored layout.
    routes = level.get('extraRoutes') or ()

    def spawn(branch):
        phases = branch.get('phases') or ()
        if len(phases) != 1 or phases[0].get('preDelay'):
            return None, None
        actions = phases[0].get('actions') or ()
        if len(actions) != 1:
            return None, None
        action = actions[0]
        index = action.get('routeIndex')
        if (action.get('actionType') != 0 or action.get('count') != 1 or action.get('preDelay')
                or action.get('hiddenGroup') or action.get('randomSpawnGroupKey')
                or not isinstance(index, int) or not 0 <= index < len(routes)):
            return None, None
        return action.get('key'), routes[index].get('startPosition')

    placed_summons = set()
    for branch_id, position in owners.items():
        enemy, origin = spawn(branches[branch_id])
        if position and origin == position and enemy:
            placed_summons.add(enemy)
    dormant = set()
    for branch_id in set(branches).difference(owners, references):
        if _DIRECTIONAL_LARVA_BRANCH.fullmatch(branch_id):
            enemy, origin = spawn(branches[branch_id])
            if enemy in placed_summons and origin and origin not in owners.values():
                dormant.add(branch_id)
    return dormant


def inactive_replay_branches(level, *, sandbox_timed=False):
    """Find branches owned by inactive or unopposed destruction-trigger instances.

    Call after tag selection and weighted choices. Unrecognized trigger shapes
    and any other references remain unresolved. ``sandbox_timed`` requires an
    installed V3 substage binding and a verified authored timeout.
    """
    branches = level.get('branches') or {}
    if not branches:
        return set()

    branch_ids = set(branches)
    groups = set(level.get('enabledHiddenGroups') or ())
    wave_actions = [action
                    for wave in level.get('waves') or ()
                    for fragment in wave.get('fragments') or ()
                    for action in fragment.get('actions') or ()
                    if action.get('hiddenGroup') is None or action['hiddenGroup'] in groups]
    # A remaining branch may itself activate a hidden instance.
    actions = wave_actions + [action for branch in branches.values()
                              for phase in branch.get('phases') or ()
                              for action in phase.get('actions') or ()]
    activated = {action.get('key') for action in actions
                 if action.get('actionType') == _ACTIVATE_PREDEFINED and action.get('key')}
    unopposed = _unopposed_destruction_owners(level, actions, activated,
                                            _ENEMY_DESTRUCTION_TRIGGERS, _PASSIVE_TILE_TYPES)
    resource_owners = None
    if sandbox_timed and all(action.get('key') == 'enemy_7067_xbcrag'
                             for action in wave_actions if action.get('actionType', 0) == 0):
        # The original crab's active mode has no attack. Without deployment, no
        # entity harvests the enemy-side wood and triggers sktok_xb2wdo.
        resource_owners = _unopposed_destruction_owners(level, actions, activated, _SANDBOX_PASSIVE_PREDEFINES,
                                                      _PASSIVE_TILE_TYPES | {'tile_richfd', 'tile_xbdpsea'})

    references = set(_branch_references({k: v for k, v in level.items()
                                        if k not in {'predefines', 'branches'}}, branch_ids))
    references.update(_branch_references(list(branches.values()), branch_ids))
    dormant_owners = set()
    larva_owners = {}
    for collection, rows in (level.get('predefines') or {}).items():
        for row in rows or ():
            alias = row.get('alias')
            character = (row.get('inst') or {}).get('characterKey')
            hidden_and_inactive = (collection in {'characterInsts', 'tokenInsts'}
                                   and row.get('hidden') is True and alias and alias not in activated)
            resource_trigger = (collection == 'tokenInsts' and character == _SANDBOX_WOOD
                                and row.get('skillIndex') == 0 and alias in (resource_owners or ())
                                and any(entry.get('key') == 'action_index' and entry.get('value') == 0
                                        for entry in row.get('overrideSkillBlackboard') or ()))
            larva_trigger = (collection == 'tokenInsts' and character in _ENEMY_DESTRUCTION_TRIGGERS
                             and row.get('skillIndex') == 0 and alias in (unopposed or ()))
            for key, value in row.items():
                if key == 'overrideSkillBlackboard' and (hidden_and_inactive or resource_trigger or larva_trigger):
                    for entry in value or ():
                        if entry.get('key') == 'branch_id' and entry.get('valueStr') in branch_ids:
                            branch_id = entry['valueStr']
                            dormant_owners.add(branch_id)
                            if character in _ENEMY_DESTRUCTION_TRIGGERS:
                                larva_owners[branch_id] = row.get('position')
                        else:
                            references.update(_branch_references(entry, branch_ids))
                else:
                    references.update(_branch_references(value, branch_ids))
    if unopposed is not None and larva_owners and not references.intersection(larva_owners):
        dormant_owners.update(_directional_larva_branches(level, branches, larva_owners, references))
    return dormant_owners - references
