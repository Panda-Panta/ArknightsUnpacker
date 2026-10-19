"""Static panel components; conditional battle bonuses are deliberately separate."""
from .descriptions import blackboard_map

ATTRIBUTES = {'maxHp': ('生命上限', ''), 'atk': ('攻击', ''), 'def': ('防御', ''), 'magicResistance': ('法术抗性', ''), 'cost': ('初始部署费用', ''), 'respawnTime': ('再部署时间', '秒'), 'blockCnt': ('阻挡数', ''), 'baseAttackTime': ('基础攻击间隔', '秒'), 'attackSpeed': ('基础攻击速度', '')}
ATTR_KEYS = {'MAX_HP':'maxHp', 'ATK':'atk', 'DEF':'def', 'MAGIC_RESISTANCE':'magicResistance', 'COST':'cost', 'RESPAWN_TIME':'respawnTime', 'BLOCK_CNT':'blockCnt', 'BASE_ATTACK_TIME':'baseAttackTime', 'ATTACK_SPEED':'attackSpeed', 'max_hp':'maxHp', 'magic_resistance':'magicResistance', 'respawn_time':'respawnTime', 'block_cnt':'blockCnt', 'base_attack_time':'baseAttackTime', 'attack_speed':'attackSpeed'}


def attribute_key(key):
    return ATTR_KEYS.get(key, key)


def interpolate(frames, level):
    frames = sorted(frames or [], key=lambda f: f['level'])
    if not frames:
        return {}
    below = max((f for f in frames if f['level'] <= level), key=lambda f: f['level'], default=frames[0])
    above = min((f for f in frames if f['level'] >= level), key=lambda f: f['level'], default=frames[-1])
    result = {}
    ratio = (level - below['level']) / (above['level']-below['level']) if above['level'] != below['level'] else 0
    for key, value in below['data'].items():
        other = above['data'].get(key, value)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            result[key] = value + (other-value) * ratio
        else:
            result[key] = value
    return result


def trust_level(tables, trust, diagnostics):
    frames = tables.get('favor_table', {}).get('favorFrames')
    if not frames:
        diagnostics.append('favor_table/favorFrames missing: trust attributes unresolved')
        return None
    eligible = [frame['data'] for frame in frames if frame.get('data', {}).get('percent', 999) <= trust]
    if not eligible:
        return 0
    return max(eligible, key=lambda f: f['percent']).get('battlePhase')


def panel(tables, ch, phase, level, rank, trust, module_attrs, diagnostics):
    base = interpolate(ch['phases'][phase].get('attributesKeyFrames'), level)
    favor_level = trust_level(tables, trust, diagnostics)
    favor = interpolate(ch.get('favorKeyFrames'), favor_level) if favor_level is not None else {}
    potential = {}
    unresolved = set()
    for p in (ch.get('potentialRanks') or [])[:rank]:
        modifiers = ((p.get('buff') or {}).get('attributes') or {}).get('attributeModifiers') or []
        for mod in modifiers:
            key = attribute_key(mod.get('attributeType'))
            if mod.get('formulaItem') not in ('ADDITION', 0) or mod.get('loadFromBlackboard') or mod.get('fetchBaseValueFromSourceEntity'):
                diagnostics.append(f'unsupported potential modifier: {mod}')
                unresolved.add(key)
                continue
            potential[key] = potential.get(key, 0) + mod['value']
    modules = {attribute_key(a['key']): a['value'] for a in module_attrs}
    out = []
    for key, (label, unit) in ATTRIBUTES.items():
        b, t, p, m = base.get(key), favor.get(key), potential.get(key, 0), modules.get(key, 0)
        if b is None:
            diagnostics.append(f'attributes/{key}: missing base')
        if t is None:
            diagnostics.append(f'attributes/{key}: missing trust component')
        value = b+t+p+m if b is not None and t is not None and key not in unresolved else None
        # Exact keyframes are returned unchanged; interpolation remains full precision.
        out.append({'key':key, 'label':label, 'base':b, 'trust':t, 'potential':p, 'module':m, 'value':value, 'unit':unit})
    return out
