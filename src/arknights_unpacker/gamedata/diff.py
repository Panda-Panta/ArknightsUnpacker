"""Stable entity differences across compatible complete snapshots."""
from ..contracts import EntityChangeSet, as_jsonable
from .operators import build_operator
from .modules import build_module
from .repository import equipment, is_badge, stable_digest


def _business(value):
    if isinstance(value, dict):
        return {key:_business(item) for key,item in value.items() if key not in ('metadata', 'source', 'sources', 'diagnostics', 'comparison')}
    if isinstance(value, list):
        return [_business(x) for x in value]
    return value


def _raw_operator(data, char_id):
    ch = data.tables.get('character_table', {}).get(char_id)
    result = {'character':ch, 'building':data.tables.get('building_data', {}).get('chars', {}).get(char_id), 'skills':{}, 'buffs':{}, 'modules':{}}
    for ref, owners in data.tables.get('_indexes', {}).get('reverse', {}).items():
        if char_id not in owners:
            continue
        table, key = ref.split(':', 1)
        if table == 'building_data.buffs':
            result['buffs'][key] = data.tables.get('building_data', {}).get('buffs', {}).get(key)
        elif table == 'skill_table':
            result['skills'][key] = data.tables.get(table, {}).get(key)
        elif table == 'battle_equip_table':
            result['modules'][key] = {'battle':data.tables.get(table, {}).get(key), 'meta':equipment(data.tables).get(key)}
    return result


def _fields(before, after):
    return [{'field':key, 'before':before.get(key), 'after':after.get(key)} for key in sorted(before.keys() | after.keys()) if stable_digest(before.get(key)) != stable_digest(after.get(key))]


def _without_text(value):
    if isinstance(value,dict):
        return {key:_without_text(item) for key,item in value.items() if key not in ('name','description','trait','potentials')}
    if isinstance(value,list):
        return [_without_text(item) for item in value]
    return value


def compare_entities(old, new):
    result = EntityChangeSet(old.snapshot_id if old else None, new.snapshot_id)
    if old is None:
        result.diagnostics.append('首次发现，历史未知：已建立快照，不确认已有实体为新增。')
        return result
    blocked = False
    unknown_locale = any(not isinstance(locale,str) or not locale.strip() or locale.lower() == 'unknown' for locale in (old.locale,new.locale))
    if unknown_locale:
        def installation_profile(snapshot):
            installation = snapshot.sources.get('_installation',{})
            profile = installation.get('profile_id') if isinstance(installation,dict) else None
            return profile if isinstance(profile,str) and profile.strip() else None
        old_profile,new_profile = installation_profile(old),installation_profile(new)
        if old_profile and old_profile == new_profile:
            result.diagnostics.append('区服未知，仅比较同一安装位置内容，不能确认服务器发布')
        else:
            result.diagnostics.append('区服未知且不是同一安装位置：需声明区服后才能确认新增或变更')
            blocked = True
    elif old.locale != new.locale:
        result.diagnostics.append('incompatible locale: cannot confirm entity changes')
        blocked = True
    if old.tables.get('_normalization_version') != new.tables.get('_normalization_version'):
        result.diagnostics.append('incompatible normalization version: cannot compare')
        blocked = True
    if not old.complete or not new.complete:
        result.diagnostics.append('incomplete or inconsistent snapshot: confirmed changes blocked')
        blocked = True
    if blocked:
        return result
    old_ids = set(old.tables.get('_indexes', {}).get('operators', []))
    new_ids = set(new.tables.get('_indexes', {}).get('operators', []))
    # Include obtainability transitions for previously known playable records.
    old_chars, new_chars = old.tables.get('character_table', {}), new.tables.get('character_table', {})
    ids = old_ids | new_ids
    for char_id in sorted(ids):
        before_raw, after_raw = _raw_operator(old, char_id), _raw_operator(new, char_id)
        before = _business(as_jsonable(build_operator(old, char_id))) if char_id in old_chars else {}
        after = _business(as_jsonable(build_operator(new, char_id))) if char_id in new_chars else {}
        changes = _fields(before, after)
        raw_changed = stable_digest(before_raw) != stable_digest(after_raw)
        if not changes and not raw_changed:
            continue
        kind = 'added' if char_id not in old_chars else 'removed' if char_id not in new_chars else 'modified'
        if kind == 'added' and char_id in new.tables.get('_indexes', {}).get('forms', {}):
            kind = 'form_added'
        fields = [change['field'] for change in changes]
        categories = []
        if 'attributes' in fields:
            categories.append('attributes')
        for key in ('skills','talents','building_skills','modules','trait','name','summary'):
            if key in fields:
                categories.append(key)
        if not changes:
            categories.append('raw_fields_only')
        elif stable_digest(_without_text(before)) == stable_digest(_without_text(after)):
            categories.append('text_only')
        result.operators.append({'char_id':char_id, 'id':char_id, 'name':new_chars.get(char_id, old_chars.get(char_id, {})).get('name', char_id), 'kind':kind, 'categories':categories, 'fields':fields, 'changes':changes, 'raw_changed':raw_changed, 'difference_type':'cross_version', 'baseline_version':old.version, 'current_version':new.version})
    old_eq = {k:v for k,v in equipment(old.tables).items() if not is_badge(v)}
    new_eq = {k:v for k,v in equipment(new.tables).items() if not is_badge(v)}
    for equip_id in sorted(old_eq.keys() | new_eq.keys()):
        before = _business(as_jsonable(build_module(old, equip_id))) if equip_id in old_eq else {}
        after = _business(as_jsonable(build_module(new, equip_id))) if equip_id in new_eq else {}
        changes = _fields(before, after)
        raw_before = [old_eq.get(equip_id), old.tables.get('battle_equip_table', {}).get(equip_id)]
        raw_after = [new_eq.get(equip_id), new.tables.get('battle_equip_table', {}).get(equip_id)]
        raw_changed = stable_digest(raw_before) != stable_digest(raw_after)
        if not changes and not raw_changed:
            continue
        record = new_eq.get(equip_id, old_eq.get(equip_id, {}))
        result.modules.append({'equip_id':equip_id, 'id':equip_id, 'char_id':record.get('charId'), 'name':record.get('uniEquipName', equip_id), 'kind':'added' if equip_id not in old_eq else 'removed' if equip_id not in new_eq else 'modified', 'fields':[x['field'] for x in changes], 'changes':changes, 'raw_changed':raw_changed, 'categories':['raw_fields_only'] if not changes else ['module_effects'], 'difference_type':'cross_version', 'baseline_version':old.version, 'current_version':new.version})
    return result
