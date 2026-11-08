"""Read map indicators from client resources or an imported Crisis V2 archive."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from ..contracts import null_progress
from ..gamedata.descriptions import render_description
from .decoder import normalize_flatbuffer, schema
from .tables import load_local_tables


_TABLE = 'crisis_v2_table'
_LEVEL_PREFIX = 'gamedata/levels/'
_RECAL_RUNE_PREFIX = 'obt/recalrune/'
_CRISIS_PREFIX = 'obt/crisis/v2/'
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


def _effect(key, blackboard):
    return {'key': key, 'blackboard': blackboard, 'statically_applicable': key in _STATIC_EFFECTS}


def _description(raw, effects=()):
    # A name reused by several effects is ambiguous unless the values agree.
    values = {}
    ambiguous = set()
    for effect in effects:
        for item in effect['blackboard']:
            key = item['key'].lower()
            value = item['valueStr'] if item['valueStr'] is not None else item['value']
            if key in values and values[key] != value:
                ambiguous.add(key)
            values[key] = value
    text = raw.replace('\\r\\n', '\\n').replace('\\r', '\\n')
    return render_description(text, {k: v for k, v in values.items() if k not in ambiguous})[0]


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
        description = _description(description_raw)
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
            effects.append(_effect(key, blackboard))
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


def _crisis_map(payload, level_id, cancel):
    # Only the season info is game configuration. Player deltas have no role
    # in this preview, including any completed keypoint or daily unlock state.
    if not isinstance(payload, dict):
        raise ValueError('文件不是危机合约指标对象。')
    info = payload.get('info', payload)
    if not isinstance(info, dict) or not isinstance(info.get('seasonId'), str):
        raise ValueError('文件没有危机合约赛季信息。')
    stages = info.get('mapStageDataMap')
    details = info.get('mapDetailDataMap')
    if not isinstance(stages, dict) or not isinstance(details, dict):
        raise ValueError('文件没有危机合约关卡和指标图。')
    matches = [
        (map_id, stage) for map_id, stage in stages.items()
        if isinstance(stage, dict) and isinstance(stage.get('levelId'), str)
        and _level_id(stage['levelId']) == level_id
    ]
    if len(matches) != 1:
        raise ValueError('指标文件中没有唯一匹配此关卡的地图。')
    map_id, stage = matches[0]
    detail = details.get(map_id)
    if not isinstance(detail, dict):
        raise ValueError('匹配的地图没有指标图。')
    graph, tags = _crisis_tags(detail, cancel)
    packs = []
    for pack_id, pack in (detail.get('bagDataMap') or {}).items():
        packs.append({
            'id': pack_id,
            'name': pack.get('slotPackFullName') or pack.get('slotPackName') or pack_id,
            'type': pack.get('slotPackType'),
            'score': pack.get('rewardScore'),
            'dimension': pack.get('dimension'),
            'tag_ids': [tag['id'] for tag in tags if tag['pack_id'] == pack_id],
        })
    return {
        'tags': tags,
        'graph': graph,
        'packs': packs,
        'source': {'season_id': info['seasonId'], 'map_id': map_id, 'map_name': stage.get('name'),
                   'stage_type': stage.get('stageType'), 'archive_timestamp': payload.get('ts')},
    }


def _crisis_tags(detail, cancel):
    node_map = detail.get('nodeDataMap')
    rune_map = detail.get('runeDataMap')
    if not isinstance(node_map, dict) or not isinstance(rune_map, dict):
        raise ValueError('指标图缺少节点或指标定义。')
    nodes = {}
    groups = defaultdict(list)
    for node_id, node in node_map.items():
        if cancel:
            cancel.check()
        if not isinstance(node, dict):
            raise ValueError('指标图包含无效节点。')
        kind = node.get('nodeType')
        adjacent = node.get('adjacentNodeList') or []
        group = node.get('mutualExclusionGroup') or None
        if (not isinstance(kind, str) or not isinstance(adjacent, list)
                or any(not isinstance(target, str) or target not in node_map for target in adjacent)
                or (group is not None and not isinstance(group, str))):
            raise ValueError('指标图包含无效节点、连线或互斥关系。')
        nodes[node_id] = {'type': kind, 'adjacent': adjacent}
        if kind == 'NORMAL' and group:
            groups[group].append(node_id)

    graph = {
        'start_ids': [node_id for node_id, node in nodes.items() if node['type'] == 'START'],
        'keypoint_ids': [node_id for node_id, node in nodes.items() if node['type'] == 'KEYPOINT'],
        'nodes': nodes,
    }
    if not graph['start_ids']:
        raise ValueError('指标图缺少可用起点。')
    tags = []
    for node_id, node in node_map.items():
        if nodes[node_id]['type'] != 'NORMAL':
            continue
        rune_id = node.get('runeId')
        rune = rune_map.get(rune_id) if isinstance(rune_id, str) else None
        if not isinstance(rune, dict) or rune.get('runeId') != rune_id:
            raise ValueError('指标节点没有对应的指标定义。')
        packed = rune.get('packedRune')
        score = rune.get('score')
        sort = rune.get('sortId', 0)
        if (not isinstance(packed, dict) or packed.get('id') != rune_id
                or not isinstance(score, int) or not isinstance(sort, int)):
            raise ValueError('指标定义没有有效的评分、顺序或执行数据。')
        effects = []
        for action in packed.get('runes') or []:
            board = [{'key': item['key'], 'value': item.get('value', 0), 'valueStr': item.get('valueStr')}
                     for item in action.get('blackboard') or []]
            effects.append(_effect(action['key'], board))
        first = effects[0] if effects else {}
        raw = packed.get('description') or ''
        group = node.get('mutualExclusionGroup') or None
        tags.append({
            'id': node_id,
            'rune_id': rune_id,
            'name': rune.get('runeName') or rune_id,
            'description': _description(raw, effects),
            'description_raw': raw,
            'score': score,
            'dimension': rune.get('dimension'),
            'group': group,
            'required': False,
            'sort': sort,
            'effect_key': first.get('key'),
            'blackboard': first.get('blackboard', []),
            'effects': effects,
            'selected': False,
            'requires': nodes[node_id]['adjacent'],
            'excludes': [other for other in groups.get(group, ()) if other != node_id],
            'pack_id': node.get('slotPackId'),
        })
    tags.sort(key=lambda tag: tag['sort'])
    return graph, tags


def _load_crisis_tags(level_id, resource_version, crisis_info_path, cancel):
    result = {'mode': 'crisis', 'tags': [], 'diagnostics': [], 'resource_version': resource_version}
    if crisis_info_path is None:
        result['diagnostics'].append('危机合约可选指标来自赛季服务器数据，请导入对应赛季的指标 JSON。')
        return result
    try:
        payload = json.loads(Path(crisis_info_path).read_text(encoding='utf-8-sig'))
        result.update(_crisis_map(payload, level_id, cancel))
    except (OSError, UnicodeError, json.JSONDecodeError):
        result['diagnostics'].append('无法读取危机合约指标 JSON。')
    except ValueError as error:
        result['diagnostics'].append(str(error))
    except (TypeError, KeyError, AttributeError):
        result['diagnostics'].append('危机合约指标 JSON 的字段格式不受支持。')
    return result


def load_level_tags(root, logical_path, resource_version, *, emit=null_progress, cancel=None,
                    crisis_info_path=None):
    """Match the exact level and source without applying one mode's rules to another."""
    if cancel:
        cancel.check()
    level_id = _level_id(logical_path)
    if level_id.startswith(_CRISIS_PREFIX):
        return _load_crisis_tags(level_id, resource_version, crisis_info_path, cancel)
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
