"""Read selectable RecalRune indicators from the active client resources."""
from __future__ import annotations

from pathlib import Path

from ..contracts import null_progress
from ..gamedata.descriptions import render_description
from .decoder import normalize_flatbuffer, schema
from .tables import load_local_tables


_TABLE = 'crisis_v2_table'
_LEVEL_PREFIX = 'gamedata/levels/'
_RECAL_RUNE_PREFIX = 'obt/recalrune/'
_STATIC_EFFECTS = frozenset({
    'level_hidden_group_enable',
    'level_hidden_group_disable',
    'level_enemy_replace',
    'global_forbid_location',
})


def _text(value):
    return value.decode('utf-8') if isinstance(value, bytes) else value


def _level_id(path):
    path = path.replace('\\', '/').lower().removeprefix(_LEVEL_PREFIX)
    return path.removesuffix('.bytes').removesuffix('.json').removesuffix('.txt')


def _default_tags(tags):
    # Sort before breaking ties so the first displayed tag also wins by default.
    tags.sort(key=lambda tag: tag['sort'])
    winners = {}
    for tag in tags:
        group = tag['group']
        if group and (group not in winners or tag['score'] > winners[group]['score']):
            winners[group] = tag
    for tag in tags:
        group = tag['group']
        tag['selected'] = not group or winners[group] is tag
    return tags


def _stage_tags(stage, cancel):
    tags = []
    ids = set()
    fixed_name = _text(stage.FixedRuneSeriesName())
    for index in range(stage.RunesLength()):
        if cancel:
            cancel.check()
        entry = stage.Runes(index)
        rune = entry.Value()
        packed = rune.PackedRune()
        rune_id = _text(rune.RuneId())
        if not rune_id or rune_id != _text(entry.Key()) or rune_id in ids or packed is None:
            raise ValueError('全息作战矩阵指标记录无法确认。')
        ids.add(rune_id)
        description_raw = _text(packed.Description()) or ''
        display_text = description_raw.replace('\\r\\n', '\\n').replace('\\r', '\\n')
        description, _ = render_description(display_text)
        name = fixed_name if rune_id == 'base' else None
        name = name or next((line.strip() for line in description.splitlines() if line.strip()), rune_id)
        effects = []
        for action_index in range(packed.RunesLength()):
            action = packed.Runes(action_index)
            key = _text(action.Key())
            # Read only the action and its arguments. The PC selector layout
            # differs from the vendored schema and is not needed here.
            blackboard = [
                normalize_flatbuffer(action.Blackboard(i))[0]
                for i in range(action.BlackboardLength())
            ]
            effects.append({'key': key, 'blackboard': blackboard,
                            'statically_applicable': key in _STATIC_EFFECTS})
        first = effects[0] if effects else {}
        tags.append({
            'id': rune_id,
            'name': name,
            'description': description,
            'description_raw': description_raw,
            'score': rune.Score(),
            'group': _text(rune.ExclusiveGroupId()) or None,
            'required': rune.Essential(),
            'sort': rune.SortId(),
            'effect_key': first.get('key'),
            'blackboard': first.get('blackboard', []),
            'effects': effects,
        })
    return _default_tags(tags)


def _decode_level_tags(raw, table, level_id, cancel):
    if len(raw) < 132:
        raise ValueError('指标数据长度不足。')
    root = schema(table).ROOT_TYPE.GetRootAs(raw[128:])
    recal = root.RecalRuneData()
    if recal is not None:
        for season_index in range(recal.SeasonsLength()):
            season = recal.Seasons(season_index).Value()
            for stage_index in range(season.StagesLength()):
                stage = season.Stages(stage_index).Value()
                if _level_id(_text(stage.LevelId()) or '') == level_id:
                    return {'tags': _stage_tags(stage, cancel), 'found': True}, {'format': 'flatbuffers'}
    return {'tags': [], 'found': False}, {'format': 'flatbuffers'}


def load_level_tags(root, logical_path, resource_version, *, emit=null_progress, cancel=None):
    """Match the exact level and version, leaving ordinary levels without tag controls."""
    if cancel:
        cancel.check()
    level_id = _level_id(logical_path)
    result = {'tags': [], 'diagnostics': [], 'resource_version': resource_version}
    if not level_id.startswith(_RECAL_RUNE_PREFIX):
        return result
    tables = load_local_tables(
        Path(root), None, emit=emit, cancel=cancel, names={_TABLE},
        decoders={_TABLE: lambda raw, table: _decode_level_tags(raw, table, level_id, cancel)},
        expected_resource_version=resource_version,
    )
    result['resource_version'] = tables.resource_version
    result['diagnostics'] = list(tables.diagnostics)
    decoded = tables.tables.get(_TABLE)
    if decoded and decoded.data['found']:
        result['tags'] = decoded.data['tags']
    else:
        result['diagnostics'].append('当前资源中未确认该关卡的全息作战矩阵指标。')
    return result
