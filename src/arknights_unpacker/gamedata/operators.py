"""Operator profiles from a single immutable logical snapshot."""
from ..contracts import BuildSpec, OperatorProfile, as_jsonable
from .attributes import panel
from .build import build_state, metadata
from .candidates import choose, condition, potential_delta, unlocked
from .descriptions import render_description


def build_operator(data, char_id, spec=None):
    spec = spec or BuildSpec()
    ch = data.tables.get('character_table', {}).get(char_id)
    if not isinstance(ch, dict):
        raise KeyError(f'unknown operator: {char_id}')
    phase, level, rank = build_state(ch, spec)
    p = OperatorProfile(char_id, ch.get('name', char_id))
    p.diagnostics = list(data.diagnostics)
    origin = data.tables.get('_indexes', {}).get('origins', {}).get(char_id, 'character_table')
    prefix = '/patchChars' if origin == 'char_patch_table' else ''
    p.metadata = metadata(data, origin, prefix + '/' + char_id)
    p.summary = {'profession':ch.get('profession'), 'sub_profession':ch.get('subProfessionId'), 'rarity':ch.get('rarity'), 'phase':phase, 'level':level, 'potential':rank+1, 'trust':spec.trust, 'obtainable':not ch.get('isNotObtainable', False), 'appellation':ch.get('appellation'), 'form_of':data.tables.get('_indexes', {}).get('forms', {}).get(char_id)}
    terms = data.tables.get('gamedata_const', {}).get('termDescriptionDict', {})
    trait_candidate = choose((ch.get('trait') or {}).get('candidates'), phase, level, rank)
    if trait_candidate:
        p.trait, ds = render_description(trait_candidate.get('overrideDescripton') or trait_candidate.get('description') or ch.get('description'), trait_candidate.get('blackboard'), terms)
        p.diagnostics.extend(ds)
    else:
        p.trait, ds = render_description(ch.get('description'), terms=terms)
        p.diagnostics.extend(ds)
    for slot in ch.get('talents') or []:
        candidates = slot.get('candidates') or []
        candidate = choose(candidates, phase, level, rank)
        if not candidate or candidate.get('isHideTalent'):
            continue
        baseline = choose(candidates, phase, level, 0)
        description, ds = render_description(candidate.get('description'), candidate.get('blackboard'), terms)
        p.diagnostics.extend(ds)
        p.talents.append({'name':candidate.get('name', ''), 'description':description, 'potential_delta':potential_delta(candidate, baseline), 'unlock_condition':condition(candidate), 'blackboard':candidate.get('blackboard'), 'token_key':candidate.get('tokenKey')})
    for index, slot in enumerate(ch.get('skills') or [], 1):
        if not unlocked(condition(slot), phase, level):
            continue
        skill_id = slot.get('skillId')
        levels = data.tables.get('skill_table', {}).get(skill_id, {}).get('levels') or []
        if not levels:
            p.diagnostics.append(f'skill_table/{skill_id}: unparsed skills'); continue
        # Mastery is available only after its actual unlock; base max is level 7.
        mastery_conditions = slot.get('levelUpCostCond') or []
        mastered = len(levels) >= 10 and len(mastery_conditions) >= 3 and all(unlocked(x.get('unlockCond') or {}, phase, level) for x in mastery_conditions[:3])
        skill_level = 10 if mastered else min(len(levels), 7)
        record = levels[skill_level-1]
        description, ds = render_description(record.get('description'), record.get('blackboard'), terms, inherited={'duration':record.get('duration')})
        sp = record.get('spData') or {}
        p.skills.append({'index':index, 'id':skill_id, 'name':record.get('name', ''), 'level':'专精3' if mastered else f'等级{skill_level}', 'numeric_level':skill_level, 'sp_type':sp.get('spType'), 'trigger':record.get('skillType'), 'init_sp':sp.get('initSp'), 'sp_cost':sp.get('spCost'), 'duration':record.get('duration'), 'duration_type':record.get('durationType'), 'description':description, 'blackboard':record.get('blackboard') or [], 'diagnostics':ds, 'max_charge':sp.get('maxChargeTime'), 'source':metadata(data, 'skill_table', f'/{skill_id}/levels/{skill_level-1}')['source']})
        p.diagnostics.extend(ds)
    building = data.tables.get('building_data')
    if not building:
        p.diagnostics.append('building_data: 后勤数据未解析')
    else:
        bchar = building.get('chars', {}).get(data.tables.get('_indexes', {}).get('forms', {}).get(char_id, char_id))
        if bchar is None:
            p.diagnostics.append(f'building_data/chars/{char_id}: 后勤记录缺失')
        for slot in (bchar or {}).get('buffChar') or []:
            candidate = choose(slot.get('buffData'), phase, level, rank)
            if not candidate:
                continue
            buff = building.get('buffs', {}).get(candidate.get('buffId'))
            if not buff:
                p.diagnostics.append(f'building_data: unresolved buff {candidate.get("buffId")}'); continue
            description, ds = render_description(buff.get('description'), terms=terms)
            p.diagnostics.extend(ds)
            p.building_skills.append({'name':buff.get('buffName', ''), 'description':description, 'room':buff.get('roomType'), 'unlock':condition(candidate), 'id':candidate.get('buffId')})
    p.potentials = [x.get('description', '') for x in (ch.get('potentialRanks') or [])[:rank]]
    from .modules import build_module
    for equip_id in data.tables.get('_indexes', {}).get('modules', {}).get(char_id, []):
        p.modules.append(as_jsonable(build_module(data, equip_id, spec)))
    selected_attrs = []
    if spec.module_id:
        selected = next((m for m in p.modules if m['equip_id'] == spec.module_id), None)
        if not selected:
            raise ValueError('selected module does not belong to character or is INITIAL')
        selected_phase = next((v for v in selected['phases'] if v['level'] == spec.module_level), None)
        if selected_phase is None:
            p.diagnostics.append(f'{spec.module_id}: requested module level missing')
        elif selected['metadata'].get('special_equip') or any(selected_phase.get('scope', {}).values()):
            p.diagnostics.append(f'{spec.module_id}: conditional module cannot enter unconditional panel')
        elif not unlocked(selected['metadata'].get('unlock_condition') or {}, phase, level):
            p.diagnostics.append(f'{spec.module_id}: module not unlocked')
        else:
            selected_attrs = selected_phase['attributes']
            p.metadata['selected_module'] = {'id':spec.module_id, 'name':selected['name'], 'level':spec.module_level}
    p.attributes = panel(data.tables, ch, phase, level, rank, spec.trust, selected_attrs, p.diagnostics)
    for attribute in p.attributes:
        root_source = dict(p.metadata['source'])
        base_pointer = root_source.get('pointer', '')
        attribute['sources'] = {
            'base':{**root_source, 'pointer':base_pointer + f'/phases/{phase}/attributesKeyFrames'},
            'trust':{**root_source, 'pointer':base_pointer + '/favorKeyFrames', 'mapping_source':metadata(data, 'favor_table', '/favorFrames')['source']},
            'potential':{**root_source, 'pointer':base_pointer + '/potentialRanks'},
            'module':metadata(data, 'battle_equip_table', '/' + spec.module_id + '/phases')['source'] if spec.module_id else None,
        }
    return p
