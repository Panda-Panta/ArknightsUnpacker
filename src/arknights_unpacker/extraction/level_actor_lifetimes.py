"""Recognize a stationary enemy's authored reveal and self-removal."""
from math import isfinite
from struct import unpack_from

from .tables import load_local_tables


def read_stationary_lifetime_data(sp, skills):
    if sp is None or skills is None or sp.SpType() != 1:
        return None
    rate, initial, limit = sp.Increment(), sp.InitSp(), sp.MaxSp()
    if not isfinite(rate) or rate <= 0 or not 0 <= initial < limit:
        return None
    charged = [skill for index in range(skills.SkillsLength())
               if (skill := skills.Skills(index)).SpCost() > 0]
    if len(charged) != 1:
        return None
    skill = charged[0]
    key, cost = skill.PrefabKey(), skill.SpCost()
    if not key or not initial < cost <= limit or skill.InitCooldown() != 0 or skill.Cooldown() != 0:
        return None
    parameters = {}
    for index in range(skill.BlackboardLength()):
        field = skill.Blackboard(index)
        if field.Key() and not field.ValueStr():
            parameters[field.Key().decode()] = field.Value()
    return {'key': key.decode(), 'castAfter': (cost - initial) / rate, 'parameters': parameters}


def _bson_templates(raw, _name):
    from bson import loads

    if len(raw) < 5 or unpack_from('<i', raw)[0] != len(raw) or raw[-1] != 0:
        raise ValueError('原版战斗增益模板格式不受支持。')
    return loads(raw), {'format': 'bson'}


def _templates(root, version, cancel):
    name = 'buff_template_data'
    result = load_local_tables(root, None, cancel=cancel, names={name}, decoders={name: _bson_templates},
                               logical_names={name: 'gamedata/battle/buff_template_data'},
                               expected_resource_version=version)
    table = result.tables.get(name)
    if table is None:
        raise ValueError('读取战斗增益模板失败：' + '；'.join(result.diagnostics))
    return table.data


def _reveal_mode(template):
    events = template.get('eventToActions') or {}
    if set(events) != {'ON_BUFF_START', 'ON_BUFF_FINISH'}:
        return None
    start, finish = events['ON_BUFF_START'], events['ON_BUFF_FINISH']
    if len(start) != 1 or len(finish) != 2:
        return None
    transition = start[0]
    mode = transition.get('_modeIndex')
    if type(mode) is not int or mode < 1:
        return None
    if transition != {
        '$type': 'Torappu.Battle.Action.Nodes+SwitchMode, Assembly-CSharp',
        '_modeIndex': mode, '_loadModeFromBlackboard': False, '_restoreDefault': False,
        '_restartFSM': True, '_targetType': 'BUFF_OWNER',
    }:
        return None
    if finish != [
        {'$type': 'Torappu.Battle.Action.Nodes+IfTarget, Assembly-CSharp', '_targetType': 'BUFF_OWNER',
         '_motionMask': 'ALL', '_checkTargetAlive': True, '_checkApplyWay': False,
         '_checkTargetUnitType': False, '_unitType': 'ENEMY', '_applyWay': 'NONE',
         '_checkTargetFree': False, '_checkMotionTargetFree': False},
        {'$type': 'Torappu.Battle.Action.Nodes+InstantKill, Assembly-CSharp', '_targetType': 'BUFF_OWNER',
         '_killSource': False, '_noSource': False, '_withdrawIfRallyPoint': False,
         '_resultIfInRallyPointMode': False, '_skipReborn': False, '_noReason': False,
         '_markReachExit': False, '_switchState': False},
    ]:
        return None
    return mode


def stationary_lifetime(prefab, info, game_root, resource_version, cancel=None):
    """Return a no-deployment profile only for a verified owner-only timer."""
    from .level_actor_assets import _animator, _components, _pointer, _resolve_animation
    from .level_actor_attacks import _mono_type, _skill_node

    timing = info.get('stationaryLifetimeData')
    if timing is None:
        return None
    transform, _, animator, _, enemy, behaviour = _animator(prefab)
    modes = behaviour.get('_modes') or ()
    if len(modes) < 2 or behaviour.get('_delayToBorn'):
        return None
    node = _skill_node(transform.read(), timing['key'])
    if node is None:
        return None
    components = {}
    for reader in _components(node):
        if reader.type.name == 'MonoBehaviour' and (tree := reader.read_typetree()).get('m_Enabled'):
            components[_mono_type(reader, tree, _pointer)] = (reader, tree)
    if set(components) != {'EnemySkill', 'ActiveBuffAbility', 'AlwaysTrigger'}:
        return None
    reader, skill = components['EnemySkill']
    if (skill.get('_maxTriggerTime') != 1 or skill.get('_overwriteInitCooldown') != -1
            or skill.get('_checkParentActive') or skill.get('_castLikeAttack')
            or not skill.get('_ignoreSilence') or skill.get('_familyMask') != 3):
        return None
    trigger_ref = skill.get('_trigger') or {}
    if not trigger_ref.get('m_PathID') or _pointer(reader, trigger_ref) is not components['AlwaysTrigger'][0]:
        return None
    _, ability = components['ActiveBuffAbility']
    if (ability.get('_selector', {}).get('m_PathID') or any(ability.get(key) for key in (
            '_waitForAttackEvent', '_waitForCasting', '_preDelay', '_escapeTime', '_passiveBuffs'))):
        return None
    buffs = ability.get('_buffs') or ()
    if len(buffs) != 1:
        return None
    buff = buffs[0]
    if (buff.get('lifeTimeType') != 1 or buff.get('loadFromDB') or buff.get('isDurableBuff')
            or buff.get('lifeTime') != 0 or buff.get('remainingTimeKey') or buff.get('triggerLifeType')
            or buff.get('blackboard') or not buff.get('templateKey')):
        return None
    duration = timing['parameters'].get(buff.get('durationKey'))
    if duration is None or not isfinite(duration) or duration <= 0:
        return None
    template = _templates(game_root, resource_version, cancel).get(buff['templateKey'], {})
    mode = _reveal_mode(template)
    if mode is None or mode >= len(modes):
        return None
    initial_mode = _pointer(enemy, modes[0]).read_typetree()
    if initial_mode.get('_animatorHooker', {}).get('m_PathID'):
        return None
    animation_map = {entry['animKey']: {'clip': entry['animName'], 'speed': entry['speed'],
                                      'loop': bool(entry['loop'])}
                     for entry in animator['_animations']}
    initial = _resolve_animation(animation_map, {}, 'Idle')
    if initial is None or initial['clip'] != 'Hide':
        return None
    visible_mode = _pointer(enemy, modes[mode])
    hook_ref = visible_mode.read_typetree().get('_animatorHooker') or {}
    if not hook_ref.get('m_PathID'):
        return None
    hook = _pointer(visible_mode, hook_ref)
    hook_data = hook.read_typetree()
    if _mono_type(hook, hook_data, _pointer) != 'SimpleUnitAnimatorHooker':
        return None
    shown = _resolve_animation(animation_map, hook_data, 'Idle')
    if shown is None or shown['clip'] == initial['clip']:
        return None
    return {'appearAfter': timing['castAfter'], 'retireAfter': timing['castAfter'] + duration,
            'visibleClip': shown['clip'], 'visibleClipSpeed': shown['speed'], 'visibleClipLoop': shown['loop']}
