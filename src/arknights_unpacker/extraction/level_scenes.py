"""Find the original Unity scene or level prefab recorded for each map."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .level_catalog import is_level_path


_SOURCES = (
    ("scenes", "scene", "unity"),
    ("battle/prefabs/levelprefabs", "prefab", "prefab"),
)


def level_scene_sources(level):
    if not is_level_path(level):
        return
    relative = level.removeprefix('gamedata/levels/')
    leaf = relative.rsplit('/', 1)[-1]
    for folder, kind, extension in _SOURCES:
        yield f'{folder}/{relative}/{leaf}', kind, extension


def find_level_scenes(index, resources, level_ids, cancel):
    """Bind full level paths to Unity assets and report the main bundle's availability."""
    cancel.check()
    expected = {}
    for level in level_ids:
        cancel.check()
        for asset, kind, extension in level_scene_sources(level):
            expected[asset] = (level, kind, f"dyn/{asset}.{extension}")
    if not expected:
        return {}

    matches = defaultdict(set)
    for position, entry in enumerate(index.get("assets", ())):
        if position % 2048 == 0:
            cancel.check()
        asset = entry.get("assetName")
        target = expected.get(asset)
        if target is None:
            continue
        level, kind, container_path = target
        bundle = entry.get("bundle")
        if entry.get("path") == container_path and isinstance(bundle, str) and bundle:
            matches[level].add((asset, kind, bundle))

    cancel.check()
    result = {}
    for level, candidates in matches.items():
        if len(candidates) == 1:
            asset, kind, bundle = next(iter(candidates))
            resource = resources.get(bundle) or resources.get(bundle + ".bin")
            result[level] = {"asset": asset, "kind": kind, "bundle": bundle,
                             "available": bool(resource and resource.path)}
    return result


def _read_holographic_sources(raw, check):
    from .level_metadata import _entries, _root, _text

    sources = defaultdict(set)
    table = _root(raw, 'crisis_v2_table').RecalRuneData()
    if table is None:
        return {}
    for entry in _entries(table, 'Seasons', check, optional=True):
        info = entry.Value()
        for stage_entry in _entries(info, 'Stages', check, optional=True):
            stage = stage_entry.Value()
            if _text(stage_entry.Key()) == _text(stage.StageId()):
                sources[_text(stage.LevelId())].add(_text(stage.LevelCode()))
    return {level_id: next(iter(codes)) for level_id, codes in sources.items() if len(codes) == 1}


def _holographic_sources(root, resource_version, cancel):
    from .level_metadata import _level_path, _read_stages
    from .tables import load_local_tables

    readers = {'crisis_v2_table': _read_holographic_sources, 'stage_table': _read_stages}

    def decode(raw, name):
        return readers[name](raw, cancel.check), {'format': 'level_scene_sources_flatbuffers'}

    result = load_local_tables(Path(root), None, cancel=cancel, names=set(readers),
                               decoders=dict.fromkeys(readers, decode),
                               expected_resource_version=resource_version)
    if not readers.keys() <= result.tables.keys():
        return {}
    stages = defaultdict(set)
    for row in result.tables['stage_table'].data.values():
        cancel.check()
        source = _level_path(row['level_id'])
        if row['code'] and source:
            stages[row['code']].add(source)
    return {_level_path(level_id): stages[code]
            for level_id, code in result.tables['crisis_v2_table'].data.items() if code}


def _map_tiles(level):
    data = level['mapData']
    grid, tiles = data['map'], data['tiles']
    return grid['rowSize'], grid['columnSize'], tuple(
        (tiles[index]['tileKey'], tiles[index]['heightType']) for index in grid['matrixData']
    )


def resolve_level_replay_scene(root, resource_version, level_id, level, cancel):
    """Resolve the original client scene on demand, including explicit Holographic reuse."""
    from ..library.discover import discover_installation, safe_path
    from ..library.resolver import collect_manifests
    from .gameplay import load_level_data
    from .manifest import read_resource_manifest

    installation = discover_installation(root)
    manifests, _ = collect_manifests(installation)
    active = manifests.get('hot') or manifests.get('base') or {}
    if active.get('versionId') != resource_version:
        raise ValueError('活动资源版本已变化，请重新扫描。')
    index_path = next((path for folder in installation.source_roots.values()
                       if (path := safe_path(folder, active['manifestName'])).is_file()), None)
    if index_path is None:
        raise FileNotFoundError('活动资源索引未安装。')
    index = read_resource_manifest(index_path)
    binding = find_level_scenes(index, {}, (level_id,), cancel).get(level_id)
    if binding is None and level_id.startswith('gamedata/levels/obt/recalrune/'):
        candidates = _holographic_sources(root, resource_version, cancel).get(level_id, ())
        matches = find_level_scenes(index, {}, candidates, cancel)
        if len(candidates) > 1:
            # Difficulty variants can carry the same UI code. Only exact source grids resolve such a tie.
            if level is None:
                _, level = load_level_data(root, level_id, resource_version, cancel=cancel)
            matches = {path: row for path, row in matches.items()
                       if _map_tiles(load_level_data(root, path, resource_version, cancel=cancel)[1])
                       == _map_tiles(level)}
        if len(matches) == 1:
            source, row = next(iter(matches.items()))
            binding = {**row, 'source_level': source}
    if binding is None:
        return None

    bundle = binding['bundle']
    entries = {layer: {row['name']: row for row in manifest['abInfos']
                       if row['name'] in (bundle, bundle + '.bin')}
               for layer, manifest in manifests.items()}
    current = entries['hot' if manifests.get('hot') else 'base']
    name = bundle if bundle in current else bundle + '.bin'
    if info := current.get(name):
        for layer, folder in installation.source_roots.items():
            candidate = entries.get(layer, {}).get(name, {})
            if any(candidate.get(field) != info.get(field) for field in ('abSize', 'hash', 'md5')):
                continue
            path = safe_path(folder, name)
            if path.is_file() and path.stat().st_size == info['abSize']:
                binding['available'] = True
                break
    return binding
