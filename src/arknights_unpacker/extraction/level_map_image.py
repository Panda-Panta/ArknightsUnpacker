"""Bind the official map preview artwork to the exact active level and resource."""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
import hashlib
from pathlib import Path
import re
from uuid import uuid4

from ..contracts import CancelToken, null_progress
from ..library.discover import discover_installation, safe_path
from ..library.resolver import load_catalog
from .level_catalog import is_level_path
from .manifest import read_resource_manifest
from .unity import load_bundle


_PREVIEW_FOLDER = "arts/ui/stage/mappreviews/"
_PREVIEW_ASSET = re.compile(re.escape(_PREVIEW_FOLDER) + r"[a-z0-9_-]+")


def _sources(index, cancel):
    sources, ambiguous = {}, set()
    for position, entry in enumerate(index.get("assets", ())):
        if position % 2048 == 0:
            cancel.check()
        asset = entry.get("assetName") or ""
        if not _PREVIEW_ASSET.fullmatch(asset) or entry.get("path") != f"dyn/{asset}.png":
            continue
        bundle = entry["bundle"]
        if asset in sources and sources[asset] != bundle:
            ambiguous.add(asset)
        sources[asset] = bundle
    cancel.check()
    return {asset: bundle for asset, bundle in sources.items() if asset not in ambiguous}


def _resource(resources, bundle):
    if not bundle:
        return None
    return resources.get(bundle) or resources.get(bundle + ".bin")


def find_level_map_images(index, resources, level_ids, cancel):
    """Find installed official PNGs by unique level basename or verified stage ID."""
    sources = _sources(index, cancel)
    stage_ids = level_ids if isinstance(level_ids, Mapping) else {}
    names = {
        path: path.rsplit("/", 1)[-1].removeprefix("level_")
        for path in level_ids if is_level_path(path)
    }
    counts = Counter(names.values())
    matches = {}
    for path, name in names.items():
        cancel.check()
        candidates = [name] if counts[name] == 1 else []
        stage_id = stage_ids.get(path)
        if stage_id and stage_id not in candidates:
            candidates.append(stage_id)
        for key in candidates:
            asset = _PREVIEW_FOLDER + key
            resource = _resource(resources, sources.get(asset))
            if resource is not None and resource.path:
                matches[path] = asset
                break
    usage = Counter(matches.values())
    return {path: asset for path, asset in matches.items() if usage[asset] == 1}


def _stamp(path):
    try:
        info = path.stat()
    except FileNotFoundError:
        return None
    return info.st_size, info.st_mtime_ns


def _preview_image(environment, expected_path, cancel):
    images = {"Sprite": {}, "Texture2D": {}}
    for path, pointer in environment.container.items():
        cancel.check()
        if path != expected_path:
            continue
        reader = pointer.deref()
        if reader.type.name in images:
            images[reader.type.name][(id(reader.assets_file), reader.path_id)] = reader
    # The imported Sprite preserves the region and Unity's explicit alpha.
    candidates = images["Sprite"] or images["Texture2D"]
    if len(candidates) != 1:
        raise ValueError("原图容器没有唯一匹配的图片对象。")
    return next(iter(candidates.values())).read().image


def load_level_map_image(root, logical_asset, resource_version, output_dir, *,
                         emit=null_progress, cancel=None):
    """Export the installed game artwork at its native size into the preview cache."""
    from .engine import validate_output_root

    cancel = cancel or CancelToken()
    cancel.check()
    if not _PREVIEW_ASSET.fullmatch(logical_asset):
        raise ValueError("无效的关卡原图资源路径。")
    installation = discover_installation(root)
    output = validate_output_root(output_dir, [installation.root])
    folders = [installation.source_roots[layer] for layer in ("hot", "base")
               if layer in installation.source_roots]
    manifests = [safe_path(folder, "hot_update_list.json") for folder in folders]
    observed = {path: _stamp(path) for path in manifests}
    catalog = load_catalog(installation)
    if not resource_version or resource_version == "unknown" or catalog.manifest.get("versionId") != resource_version:
        raise ValueError("关卡原图的资源版本已变化，请重新扫描。")
    index_name = catalog.manifest.get("manifestName")
    if not index_name:
        raise ValueError("当前资源清单没有活动索引。")
    index_file = next((path for folder in folders if (path := safe_path(folder, index_name)).is_file()), None)
    if index_file is None:
        raise FileNotFoundError("活动资源索引未安装。")
    observed[index_file] = _stamp(index_file)
    index = read_resource_manifest(index_file)
    resource = _resource(catalog.resources, _sources(index, cancel).get(logical_asset))
    if resource is None or not resource.path:
        raise ValueError("当前活动索引没有可用的关卡原图。")
    source = safe_path(installation.source_roots[resource.layer], resource.logical_key)
    observed[source] = _stamp(source)
    payload = source.read_bytes()
    if len(payload) != resource.size or (
        re.fullmatch(r"[0-9a-fA-F]{32}", resource.expected_hash)
        and hashlib.md5(payload).hexdigest() != resource.expected_hash.lower()
    ):
        raise OSError("关卡原图包与活动资源清单不一致。")
    cancel.check()
    emit({"kind": "progress", "stage": "map_image", "path": logical_asset})
    image = _preview_image(load_bundle(source, data=payload), f"dyn/{logical_asset}.png", cancel)
    cancel.check()

    output.mkdir(parents=True, exist_ok=True)
    target = output / f"map-{uuid4().hex}.png"
    temp = target.with_suffix(".partial")
    try:
        image.save(temp, format="PNG")
        cancel.check()
        if any(_stamp(path) != previous for path, previous in observed.items()):
            raise OSError("原图资源在读取期间发生变化，请重新扫描。")
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)
    return {"path": str(target), "resource_version": resource_version, "logical_asset": logical_asset}
