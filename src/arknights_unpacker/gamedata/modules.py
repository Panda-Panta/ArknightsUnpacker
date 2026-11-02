"""Module stage totals and explicit effect scope, including hidden implementation records."""
from ..contracts import BuildSpec, ModuleProfile
from .attributes import ATTRIBUTES, attribute_key
from .build import build_state, metadata
from .candidates import choose, condition, potential_delta
from .descriptions import blackboard_map, render_description
from .repository import equipment, is_badge
from .module_comparison import add_comparisons


def build_module(data, equip_id, spec=None):
    spec = spec or BuildSpec()
    equip = equipment(data.tables).get(equip_id)
    if not equip or is_badge(equip):
        raise ValueError(f'unknown or INITIAL module: {equip_id}')
    char_id = equip.get('tmplId') or equip.get('charId', '')
    ch = data.tables.get('character_table', {}).get(char_id, {})
    p = ModuleProfile(equip_id, char_id, ch.get('name', char_id), equip.get('uniEquipName', equip_id), '-'.join(str(equip[x]) for x in ('typeName1', 'typeName2') if equip.get(x)))
    p.metadata = metadata(data, 'uniequip_table', '/equipDict/' + equip_id)
    p.metadata.update({'unlock_condition':equip.get('unlockEvolvePhase') and {'phase':equip.get('unlockEvolvePhase'), 'level':equip.get('unlockLevel', 1)}, 'raw_metadata':equip, 'special_equip':equip.get('isSpecialEquip', False), 'special_equip_description':equip.get('specialEquipDesc')})
    if not ch:
        p.diagnostics.append('owning character missing'); return p
    phase, level, rank = build_state(ch, spec)
    terms = data.tables.get('gamedata_const', {}).get('termDescriptionDict', {})
    base_trait_candidate = choose((ch.get('trait') or {}).get('candidates'),phase,level,rank) or {}
    base_trait, base_ds = render_description(base_trait_candidate.get('overrideDescripton') or ch.get('description'),base_trait_candidate.get('blackboard'),terms)
    battle = data.tables.get('battle_equip_table', {}).get(equip_id)
    if not battle:
        p.diagnostics.append(f'battle_equip_table/{equip_id}: missing'); return p
    for raw in sorted(battle.get('phases') or [], key=lambda x: x['equipLevel']):
        stage = {'level':raw['equipLevel'], 'attributes':[], 'trait':base_trait, 'talents':[], 'diagnostics':list(base_ds), 'hidden_effects':[], 'token_effects':[], 'token_attributes':raw.get('tokenAttributeBlackboard'), 'scope':{}, 'effects':[], 'source':metadata(data,'battle_equip_table',f'/{equip_id}/phases/{len(p.phases)}')['source']}
        for attribute in raw.get('attributeBlackboard') or []:
            key = attribute_key(attribute['key'])
            stage['attributes'].append({'key':key, 'label':ATTRIBUTES.get(key, (key, ''))[0], 'value':attribute.get('value'), 'raw_key':attribute['key']})
        for part in raw.get('parts') or []:
            scope = {k:part.get(k) for k in ('isToken', 'validInGameTag', 'validInMapTag') if part.get(k)}
            target = part.get('target')
            # A part's recipient/condition does not constrain this stage's
            # separate, operator-owned attributeBlackboard totals.
            bundle = part.get('overrideTraitDataBundle') if target in ('TRAIT','TRAIT_DATA_ONLY','DISPLAY','OVERWRITE_BATTLE_DATA') else part.get('addOrOverrideTalentDataBundle')
            candidates = (bundle or {}).get('candidates') or []
            selected = choose(candidates, phase, level, rank)
            if not selected:
                if candidates:
                    stage['diagnostics'].append(f'{part.get("resKey")}: no unlocked candidate')
                elif target not in ('TRAIT', 'TRAIT_DATA_ONLY', 'TALENT', 'TALENT_DATA_ONLY'):
                    stage['diagnostics'].append(f'unknown module target: {target}')
                continue
            baseline = choose(candidates, phase, level, 0)
            board = blackboard_map(selected.get('blackboard'))
            if target == 'OVERWRITE_BATTLE_DATA' and board.get('game_tag_meta'):
                scope['game_tag_meta'] = board['game_tag_meta']
                stage['scope'].update(scope)
            raw_description = selected.get('description') or selected.get('upgradeDescription') or selected.get('overrideDescripton') or ''
            inherited_board = None
            if not raw_description and target == 'TALENT':
                index = selected.get('talentIndex')
                talents = ch.get('talents') or []
                if isinstance(index,int) and 0 <= index < len(talents):
                    inherited = choose(talents[index].get('candidates'),phase,level,rank) or {}
                    raw_description = inherited.get('description') or ''
                    inherited_board = inherited.get('blackboard')
            addition = selected.get('additionalDescription') or ''
            if addition:
                raw_description = raw_description + ('\n' if raw_description else '') + addition
            term_definitions = []
            description, ds = render_description(raw_description, selected.get('blackboard'), terms, inherited=inherited_board,
                                                term_definitions=term_definitions if target in ('TALENT', 'TALENT_DATA_ONLY') else None)
            effect = {'name':selected.get('name', ''), 'description':description, 'potential_delta':potential_delta(selected, baseline), 'target':target, 'talent_index':selected.get('talentIndex'), 'operation':'replace' if selected.get('overrideDescripton') or target in ('TALENT','TALENT_DATA_ONLY') else 'append', 'scope':{**scope, 'validModeIndices':selected.get('validModeIndices'), 'tokenKey':selected.get('tokenKey')}, 'unlock_condition':condition(selected), 'blackboard':selected.get('blackboard')}
            if term_definitions:
                effect['term_definitions'] = term_definitions
            stage['effects'].append(effect)
            stage['diagnostics'].extend(ds)
            if part.get('isToken'):
                stage['token_effects'].append(effect)
            # DATA_ONLY denotes an implementation target, not a visibility
            # verdict. Real records can carry a public upgradeDescription.
            hidden = selected.get('isHideTalent') or target == 'OVERWRITE_BATTLE_DATA' or (target in ('TALENT_DATA_ONLY','TRAIT_DATA_ONLY') and not description.strip())
            if hidden:
                stage['hidden_effects'].append(effect)
            elif part.get('isToken'):
                pass
            elif target in ('TRAIT','TRAIT_DATA_ONLY','DISPLAY'):
                if selected.get('overrideDescripton'):
                    stage['trait'] = description
                else:
                    stage['trait'] += ('\n' if stage['trait'] and description else '') + description
            else:
                stage['talents'].append(effect)
        p.phases.append(stage)
        p.diagnostics.extend(stage['diagnostics'])
    if not p.phases:
        p.diagnostics.append('no module phases parsed')
    else:
        add_comparisons(data, ch, spec, p, base_trait)
    return p
