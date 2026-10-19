"""Normalize decoded tables without concealing missing vectors or failed references."""
import copy
import hashlib
import json
import time
from ..contracts import GameDataSnapshot, TableSourceSet, as_jsonable
from .normalize import normalize_table

NORMALIZATION_VERSION = 1
CORE = ('character_table', 'skill_table', 'building_data', 'uniequip_table', 'battle_equip_table', 'favor_table')


def stable_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf8')).hexdigest()


def equipment(tables):
    table = tables.get('uniequip_table', {})
    return table.get('equipDict', {}) if isinstance(table, dict) else {}


def is_badge(record):
    return record.get('type') == 'INITIAL' or record.get('typeName1') == 'INITIAL' or record.get('uniEquipType') == 'INITIAL'


def load_gamedata(sources: TableSourceSet) -> GameDataSnapshot:
    tables, refs = {}, {}
    diagnostics = list(sources.diagnostics)
    for name, decoded in sources.tables.items():
        if not isinstance(decoded.data, dict):
            diagnostics.append(f'{name}: expected object, got {type(decoded.data).__name__}')
            continue
        tables[name] = normalize_table(name, decoded.data, diagnostics)
        refs[name] = {**as_jsonable(decoded.source), 'table': name, 'field_evidence': copy.deepcopy(decoded.field_evidence)}
        diagnostics.extend(f'{name}: {message}' for message in decoded.diagnostics)
        evidence = decoded.field_evidence
        if evidence.get('duplicate_keys') or evidence.get('duplicate_ids'):
            diagnostics.append(f'{name}: duplicate keys or IDs in source')
    for name in CORE:
        if name not in tables:
            diagnostics.append(f'missing core table: {name}')
    indices = {'operators': [], 'forms': {}, 'summons': [], 'reverse': {}, 'modules': {}, 'origins': {}, 'non_operator_diagnostics': []}
    characters = tables.get('character_table', {})
    patch = tables.get('char_patch_table', {})
    for char_id, record in patch.get('patchChars', {}).items():
        if char_id in characters and characters[char_id] != record:
            diagnostics.append(f'{char_id}: conflicting base and patch character records')
        elif char_id not in characters:
            characters[char_id] = copy.deepcopy(record)
            indices['origins'][char_id] = 'char_patch_table'
    for parent, info in patch.get('infos', {}).items():
        for form in info.get('tmplIds', []):
            if form != parent:
                indices['forms'][form] = parent
    def depend(table, key, owner):
        reverse_key = f'{table}:{key}'
        indices['reverse'].setdefault(reverse_key, []).append(owner)
    for char_id, ch in characters.items():
        if not isinstance(ch, dict):
            diagnostics.append(f'character_table/{char_id}: invalid record'); continue
        if char_id.startswith('char_') and not ch.get('isNotObtainable', False):
            indices['operators'].append(char_id)
        else:
            indices['summons'].append(char_id)
        for field in ('phases', 'skills', 'talents', 'favorKeyFrames', 'potentialRanks') if char_id in indices['operators'] else ():
            if field not in ch or ch[field] is None:
                diagnostics.append(f'character_table/{char_id}/{field}: missing or null, not confirmed empty')
        for sk in ch.get('skills') or []:
            skill_id = sk.get('skillId')
            depend('skill_table', skill_id, char_id)
            if skill_id not in tables.get('skill_table', {}):
                target_diagnostics = diagnostics if char_id in indices['operators'] else indices['non_operator_diagnostics']
                target_diagnostics.append(f'{char_id}: broken skill_table reference {skill_id}')
        bchar = tables.get('building_data', {}).get('chars', {}).get(indices['forms'].get(char_id, char_id), {})
        for slot in bchar.get('buffChar') or []:
            for entry in slot.get('buffData') or []:
                buff_id = entry.get('buffId'); depend('building_data.buffs', buff_id, char_id)
                if buff_id not in tables.get('building_data', {}).get('buffs', {}):
                    diagnostics.append(f'{char_id}: broken building_data buff {buff_id}')
    for equip_id, equip in equipment(tables).items():
        if is_badge(equip):
            continue
        char_id = equip.get('tmplId') or equip.get('charId')
        indices['modules'].setdefault(char_id, []).append(equip_id)
        depend('battle_equip_table', equip_id, char_id)
        if char_id not in characters:
            # A deliberately trimmed reference may lack unrelated characters; still diagnostic.
            diagnostics.append(f'{equip_id}: broken character reference {char_id}')
        if equip_id not in tables.get('battle_equip_table', {}):
            diagnostics.append(f'{equip_id}: missing battle_equip_table record')
    tables['_indexes'] = indices
    tables['_normalization_version'] = NORMALIZATION_VERSION
    semantic = {k: v for k, v in tables.items() if not k.startswith('_')}
    digest = stable_digest({'version': sources.version, 'resource_version': sources.resource_version, 'locale': sources.locale, 'tables': semantic})
    const = tables.get('gamedata_const', {})
    # Source-set version is authoritative; differing per-table evidence blocks baseline promotion.
    versions = {ref.get('field_evidence', {}).get('version') for ref in refs.values()} - {None, '', 'unknown'}
    if len(versions) > 1:
        diagnostics.append('mixed table versions: ' + ', '.join(sorted(versions)))
    if const.get('dataVersion') and sources.version not in ('unknown', const.get('dataVersion')):
        # Upstream uses v078 versus stream names: do not infer equivalence from spelling.
        pass
    return GameDataSnapshot(digest, sources.version, sources.resource_version, tables, refs, diagnostics, sources.complete and not diagnostics, time.time(), locale=sources.locale)
