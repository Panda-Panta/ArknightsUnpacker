"""Identify level TextAssets in the active resource index without decoding maps."""
from __future__ import annotations

import re

from ..contracts import ResourceCatalog


_LEVEL_PATH = re.compile(r"gamedata/levels/(?:[a-z0-9_-]+/)*level_[a-z0-9_-]+")
_SIDE_STORY = re.compile(r"act[0-9]+side")
# Early SideStory assets kept their original folder names through later reruns.
_LEGACY_SIDE_STORIES = {
    "a001", "act3d0", "act5d0", "act9d0", "act11d0", "act12d0",
    "act13d5", "act15d0", "act16d5", "act18d0", "act18d3",
}
_OBT_CATEGORIES = {
    "main": "主线",
    "hard": "主线",
    "roguelike": "集成战略",
    "sandbox": "生息演算",
    "legion": "保全派驻",
    "campaign": "歼灭作战",
    "crisis": "危机合约",
    "memory": "悖论模拟",
    "guide": "教学",
    "training": "教学",
    "weekly": "资源关卡",
    "promote": "资源关卡",
    "rune": "特殊活动",
    "recalrune": "全息作战矩阵",
}


def is_level_path(path: str) -> bool:
    """Only indexed map data belongs in the list, not enemy/meta data or prefabs."""
    return isinstance(path, str) and _LEVEL_PATH.fullmatch(path) is not None


def _category(path: str) -> str:
    folders = path.split("/")
    if folders[2] == "obt" and len(folders) > 4:
        return _OBT_CATEGORIES.get(folders[3], "其他")
    if folders[2] == "activities" and len(folders) > 4:
        activity = folders[3]
        if _SIDE_STORY.fullmatch(activity) or activity in _LEGACY_SIDE_STORIES:
            return "支线"
        return "特殊活动"
    return "其他"


def _collect_levels(assets, resources, cancel):
    levels = {}
    for position, asset in enumerate(assets):
        if position % 2048 == 0:
            cancel.check()
        if not isinstance(asset, dict):
            raise ValueError("资源索引含无效记录")
        path = asset.get("assetName") or asset.get("path") or asset.get("name") or ""
        if not is_level_path(path):
            continue
        bundle = asset.get("bundle")
        if not isinstance(bundle, str) or not bundle:
            raise ValueError(f"关卡 {path} 缺少索引包")
        # Match the exact resource first, then the known suffix omission.
        if bundle not in resources and bundle + ".bin" in resources:
            bundle += ".bin"
        if path in levels and levels[path] != bundle:
            raise ValueError(f"关卡 {path} 对应多个索引包")
        levels[path] = bundle
    cancel.check()
    return levels


def _new_levels(paths, root, resource_version, previous):
    if not previous or previous.get("root") != root or not previous.get("levels"):
        return set()
    flags = {row["id"]: row["is_new"] for row in previous["levels"]}
    added = paths.keys() - flags.keys()
    if previous.get("resource_version") == resource_version:
        added.update(key for key, is_new in flags.items() if is_new)
    return added


def build_level_catalog(root: str, resource_version: str, index: dict,
                        catalog: ResourceCatalog, previous: dict | None, cancel) -> dict:
    """Create one row per logical map and compare only successful scans of this source."""
    cancel.check()
    result = {"root": root, "resource_version": resource_version, "levels": [], "diagnostics": []}
    assets = index.get("assets")
    if not resource_version or resource_version == "unknown" or not isinstance(assets, list):
        result["diagnostics"].append("关卡索引或资源版本不可用。")
        return result
    try:
        paths = _collect_levels(assets, catalog.resources, cancel)
    except ValueError as error:
        result["diagnostics"].append(f"关卡索引无法确认：{error}")
        return result
    if not paths:
        result["diagnostics"].append("活动资源索引未发现可识别的关卡。")
        return result

    new_levels = _new_levels(paths, root, resource_version, previous)
    unbound = 0
    for path, bundle in sorted(paths.items()):
        cancel.check()
        resource = catalog.resources.get(bundle)
        if resource is None:
            unbound += 1
        result["levels"].append({
            "id": path,
            "name": path.rsplit("/", 1)[-1].removeprefix("level_"),
            "category": _category(path),
            "available": bool(resource and resource.path),
            "is_new": path in new_levels,
        })
    if unbound:
        result["diagnostics"].append(f"{unbound} 个关卡的索引包缺少活动资源绑定。")
    return result
