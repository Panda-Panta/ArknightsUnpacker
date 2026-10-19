"""Explicit PC-FBS enum/field mappings, calibrated against fixed same-ID records.

Evidence: artifacts/M5M7/enum_calibration.json. These maps do not assume enum
ordinals are interchangeable (profession is a bitmask and respawn is 21).
"""
ENUMS = {
    'phase':{0:'PHASE_0',1:'PHASE_1',2:'PHASE_2'},
    'profession':{1:'WARRIOR',2:'SNIPER',4:'TANK',8:'MEDIC',16:'SUPPORT',32:'CASTER',64:'SPECIAL',128:'TOKEN',256:'TRAP',512:'PIONEER'},
    'rarity':{i:f'TIER_{i+1}' for i in range(6)},
    'attributeType':{0:'MAX_HP',1:'ATK',2:'DEF',3:'MAGIC_RESISTANCE',4:'COST',7:'ATTACK_SPEED',21:'RESPAWN_TIME'},
    'formulaItem':{0:'ADDITION'},
    'skillType':{0:'PASSIVE',1:'MANUAL',2:'AUTO'},
    # The fixed GameData mirror itself retains numeric 8; preserve it without
    # inventing a symbolic name. Passive presentation uses skillType instead.
    'spType':{1:'INCREASE_WITH_TIME',2:'INCREASE_WHEN_ATTACK',4:'INCREASE_WHEN_TAKEN_DAMAGE',8:8},
    'durationType':{0:'NONE',1:'AMMO'},
    'target':{1:'TRAIT',2:'TRAIT_DATA_ONLY',3:'TALENT',4:'TALENT_DATA_ONLY',5:'DISPLAY',6:'OVERWRITE_BATTLE_DATA'},
    'roomType':{1:'CONTROL',2:'POWER',4:'MANUFACTURE',16:'DORMITORY',32:'MEETING',64:'HIRE',512:'TRADING',1024:'WORKSHOP',2048:'TRAINING',8192:'RECYCLE'},
}


def normalize_table(table, value, diagnostics, path=''):
    if isinstance(value, list):
        return [normalize_table(table,item,diagnostics,path+'/'+str(i)) for i,item in enumerate(value)]
    if not isinstance(value,dict):
        return value
    out = {}
    for key,item in value.items():
        new_key = 'def' if key == 'def_' else key
        mapping = ENUMS.get(key)
        if key in ('profession','rarity') and table not in ('character_table','char_patch_table'):
            mapping = None
        if key == 'type' and '/potentialRanks/' in path:
            mapping = {0:'BUFF',1:'CUSTOM'}
        elif key == 'type' and table == 'uniequip_table' and path.startswith('/equipDict/') and path.count('/') == 2:
            mapping = {0:'INITIAL',1:'ADVANCED'}
        if mapping is not None and isinstance(item,int) and not isinstance(item,bool):
            if item not in mapping:
                diagnostics.append(f'{table}{path}/{key}: unknown enum {item}')
            item = mapping.get(item,item)
        if key in ('blackboard','attributeBlackboard') and isinstance(item,list):
            converted = []
            for entry in item:
                if isinstance(entry,(list,tuple)) and len(entry)>=2:
                    converted.append({'key':entry[0], 'value':entry[1], 'valueStr':entry[2] if len(entry)>2 else None})
                else:
                    converted.append(entry)
            item = converted
        out[new_key] = normalize_table(table,item,diagnostics,path+'/'+new_key)
    return out
