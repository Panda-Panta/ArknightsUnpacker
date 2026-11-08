"""Find the original Unity scene or level prefab recorded for each map."""
from __future__ import annotations

from collections import defaultdict

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
