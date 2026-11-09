"""Export the original moving Spine actors referenced by a PC stage."""
import argparse
from io import BytesIO
import json
import math
from pathlib import Path
import re

import numpy as np
from UnityPy.classes import PPtr

from arknights_unpacker.extraction.decoder import schema
from arknights_unpacker.extraction.images import combine_alpha
from arknights_unpacker.extraction.manifest import read_resource_manifest
from arknights_unpacker.extraction.tables import load_local_tables
from arknights_unpacker.extraction.unity import load_bundle, raw_text
from arknights_unpacker.library.discover import discover_installation, safe_path
from arknights_unpacker.library.resolver import load_catalog
from arknights_unpacker.paths import atomic_json, validate_output

from .level_actor_attacks import periodic_attack, read_single_skill, spine_animation_durations
from .level_scene_assets import REFLECT_Z, _pose


def _float(value):
    return float(format(value, ".7g"))


def _enemy_database(root, levels, version):
    def decode(raw, name):
        database = schema(name).ROOT_TYPE.GetRootAs(raw[128:])
        selected = {}
        for i in range(database.EnemiesLength()):
            entry = database.Enemies(i)
            key = entry.Key().decode()
            if key not in levels:
                continue
            wanted = levels[key]
            rows = {}
            for j in range(entry.ValueLength()):
                row = entry.Value(j)
                rows[row.Level()] = row.EnemyData()
            if wanted not in rows:
                raise ValueError(f"{key}: 敌人数据库没有等级 {wanted}")
            info = {}
            # Undefined fields in a level override retain the base level's value.
            for level in dict.fromkeys((0, wanted)):
                row = rows.get(level)
                if row is None:
                    continue
                attrs = row.Attributes()
                if not row.SkillsIsNone():
                    info["singleSkill"] = read_single_skill(row)
                values = {"name": row.Name(), "prefabKey": row.PrefabKey(),
                          "moveSpeed": attrs.MoveSpeed() if attrs is not None else None}
                for field, value in values.items():
                    if value is not None and value.MDefined():
                        original = value.MValue()
                        info[field] = original.decode() if isinstance(original, bytes) else _float(original)
            selected[key] = info
        return selected, {"format": "flatbuffers"}

    result = load_local_tables(root, None, names={"enemy_database"},
                               decoders={"enemy_database": decode}, expected_resource_version=version)
    data = result.tables.get("enemy_database")
    if data is None:
        raise ValueError("读取敌人数据库失败：" + "；".join(result.diagnostics))
    missing = set(levels) - data.data.keys()
    if missing:
        raise ValueError("敌人数据库缺少：" + "、".join(sorted(missing)))
    return data.data


def _pointer(owner, fields):
    return PPtr(**fields, assetsfile=owner.assets_file).deref()


def _components(game_object):
    return [(component.component if hasattr(component, "component") else component[1]).deref()
            for component in game_object.m_Component]


def _transform(components):
    return next(component for component in components if component.type.name == "Transform")


def _animator(prefab):
    # The root Enemy component links the animator that drives the actual actor.
    root = prefab.read()
    components = _components(root)
    for component in components:
        if component.type.name != "MonoBehaviour":
            continue
        behaviour = component.read_typetree()
        animator_ref = behaviour.get("_animator", {})
        if not animator_ref.get("m_PathID"):
            continue
        animator = _pointer(component, animator_ref)
        tree = animator.read_typetree()
        if {"_skeleton", "_animations"} <= tree.keys():
            shadow_ref = behaviour.get("_shadow", {})
            shadow = ((component, shadow_ref) if shadow_ref.get("m_PathID")
                      and not behaviour.get("_hideShadowOnReset") else None)
            return _transform(components), animator, tree, shadow, component, behaviour
    raise ValueError(f"{root.m_Name}: prefab 没有指向 Spine 动画器的敌人组件")


def _initial_mode_hook(enemy, behaviour):
    # Enemy::_GetDefaultModeIndex starts at zero. Runtime talent overrides and
    # subsequent phase transitions depend on combat state.
    modes = behaviour.get("_modes") or ()
    if not modes or not modes[0].get("m_PathID"):
        return {}
    mode = _pointer(enemy, modes[0])
    hook_ref = mode.read_typetree().get("_animatorHooker") or {}
    if not hook_ref.get("m_PathID"):
        return {}
    hook = _pointer(mode, hook_ref)
    data = hook.read_typetree()
    script = _pointer(hook, data["m_Script"]).read()
    return data if script.m_ClassName == "SimpleUnitAnimatorHooker" else {}


def _resolve_animation(mapped, hook, key):
    # SimpleUnitAnimatorHooker excludes a key before looking for a replacement.
    if key in hook.get("_excludeAnimKeys", ()):
        return None
    for pair in hook.get("_replaceAnimPairs", ()):
        if pair["fromAnimKey"] == key:
            key = pair["toAnimKey"]
            break
    animation = mapped.get(key)
    return animation if animation and animation["speed"] > 0 else None


def _graphic_transform(skeleton, tree, prefab_transform):
    owner = _pointer(skeleton, tree["m_GameObject"]).read()
    node = _transform(_components(owner)).read()
    offset = np.zeros(3)
    scale = 1.0
    while (node.object_reader.assets_file, node.object_reader.path_id) != (
            prefab_transform.assets_file, prefab_transform.path_id):
        x, y, z = node.m_LocalScale.x, node.m_LocalScale.y, node.m_LocalScale.z
        if x <= 0 or not (math.isclose(x, y, abs_tol=1e-6) and math.isclose(x, z, abs_tol=1e-6)):
            raise ValueError("Spine prefab 使用了当前预览器不支持的非均匀或负缩放")
        v = np.array([node.m_LocalRotation.x, node.m_LocalRotation.y, node.m_LocalRotation.z])
        w = node.m_LocalRotation.w
        point = offset * x
        # Unity quaternion rotates the child's current offset before translation.
        offset = point + 2 * np.cross(v, np.cross(v, point) + w * point)
        offset += np.array([node.m_LocalPosition.x, node.m_LocalPosition.y, node.m_LocalPosition.z])
        scale *= x
        if not node.m_Father:
            raise ValueError("Spine 节点不属于目标敌人 prefab")
        node = node.m_Father.read()
    return _float(scale), [_float(offset[0]), _float(offset[1]), _float(-offset[2])]


def _shadow_renderers(node, parent_pose):
    transform = node.read()
    owner = transform.m_GameObject.read()
    if not owner.m_IsActive:
        return
    pose = parent_pose @ _pose(transform)
    for component in _components(owner):
        if component.type.name == "SpriteRenderer":
            renderer = component.read()
            if renderer.m_Enabled and renderer.m_Sprite:
                yield renderer, pose
    for child in transform.m_Children:
        yield from _shadow_renderers(child.deref(), pose)


def _shadow_sprite(component, prefab_transform):
    if component is None or component.type.name != "MonoBehaviour":
        return None
    data = component.read_typetree()
    if not data.get("m_Enabled") or any(data.get(key) for key in (
            "_autoAttachToGround", "_enableAdvanced", "_alwaysUseSpineOffset", "_specialInit")):
        return None
    owner = _pointer(component, data["m_GameObject"]).read()
    node = _transform(_components(owner))
    # The shadow is authored below the actor root. Include any intermediate pose.
    ancestors = []
    parent = node.read().m_Father
    while parent and (parent.assetsfile, parent.path_id) != (
            prefab_transform.assets_file, prefab_transform.path_id):
        transform = parent.read()
        ancestors.append(transform)
        parent = transform.m_Father
    if not parent:
        return None
    pose = np.eye(4)
    for transform in reversed(ancestors):
        if not transform.m_GameObject.read().m_IsActive:
            return None
        pose = pose @ _pose(transform)
    renderers = list(_shadow_renderers(node, pose))
    if len(renderers) != 1:
        return None
    renderer, pose = renderers[0]
    sprite = renderer.m_Sprite.read()
    render = sprite.m_RD
    # Atlas/packed, tiled and sliced sprites need their own UV/mesh handling.
    if (renderer.m_DrawMode != 0 or sprite.m_SpriteAtlas or sprite.m_AtlasTags
            or render.settingsRaw & 1 or render.downscaleMultiplier != 1
            or not sprite.m_PixelsToUnits or sprite.m_Pivot is None):
        return None
    left = render.textureRectOffset.x - sprite.m_Rect.width * sprite.m_Pivot.x
    bottom = render.textureRectOffset.y - sprite.m_Rect.height * sprite.m_Pivot.y
    right = left + render.textureRect.width
    top = bottom + render.textureRect.height
    vertices = []
    for x, y in ((left, bottom), (right, bottom), (left, top), (right, top)):
        x = (-x if renderer.m_FlipX else x) / sprite.m_PixelsToUnits
        y = (-y if renderer.m_FlipY else y) / sprite.m_PixelsToUnits
        point = REFLECT_Z @ (pose @ np.array([x, y, 0, 1]))[:3]
        vertices.append([_float(value) for value in point])
    png = BytesIO()
    sprite.image.save(png, format="PNG")
    color = renderer.m_Color
    return {"texture": "shadow/sprite.png", "vertices": vertices,
            "color": [_float(color.r), _float(color.g), _float(color.b)],
            "opacity": _float(color.a)}, png.getvalue()


def _spine_files(skeleton_data, spine):
    skeleton = _pointer(skeleton_data, spine["skeletonJSON"]).read()
    payload = raw_text(skeleton)
    is_json = payload.lstrip().startswith(b"{")
    durations = spine_animation_durations(payload, is_json)
    if len(spine["atlasAssets"]) != 1:
        raise ValueError(f"{skeleton.m_Name}: 预览需要一个 Atlas 资源，可包含多页贴图")
    atlas_data = _pointer(skeleton_data, spine["atlasAssets"][0])
    atlas = atlas_data.read_typetree()
    atlas_bytes = raw_text(_pointer(atlas_data, atlas["atlasFile"]).read())
    pages = re.findall(r"(?mi)^([^\r\n]+\.(?:png|jpg|jpeg))\r?$", atlas_bytes.decode("utf-8"))
    if not pages or len(pages) != len(atlas["materials"]) or len(set(pages)) != len(pages):
        raise ValueError(f"{skeleton.m_Name}: Atlas 页与材质引用不匹配")

    # Pixi locates the original atlas by the skeleton file's base name.
    suffix = ".json" if is_json else ".skel"
    files = {f"actor{suffix}": payload, "actor.atlas": atlas_bytes}
    for page, material_ref in zip(pages, atlas["materials"]):
        material = _pointer(atlas_data, material_ref)
        textures = dict(material.read_typetree()["m_SavedProperties"]["m_TexEnvs"])
        rgb = _pointer(material, textures["_MainTex"]["m_Texture"]).read().image
        alpha = textures.get("_AlphaTex", {}).get("m_Texture", {})
        image = (combine_alpha(rgb, _pointer(material, alpha).read().image)
                 if alpha.get("m_PathID") else rgb.convert("RGBA"))
        if Path(page).suffix.lower() not in {".png"}:
            raise ValueError(f"{skeleton.m_Name}: 无法无损导出非 PNG Atlas 页 {page}")
        output = BytesIO()
        image.save(output, format="PNG")
        files[page] = output.getvalue()
    return suffix, files, pages, durations


def _extract_prefab(prefab, logical, skill_timings):
    prefab_transform, animator, tree, shadow, enemy, behaviour = _animator(prefab)
    skeleton = _pointer(animator, tree["_skeleton"])
    renderer = skeleton.read_typetree()
    skeleton_data = _pointer(skeleton, renderer["skeletonDataAsset"])
    spine = skeleton_data.read_typetree()
    suffix, files, pages, durations = _spine_files(skeleton_data, spine)
    mapped = {a["animKey"]: {"clip": a["animName"], "speed": _float(a["speed"]),
                            "loop": bool(a["loop"])}
              for a in tree["_animations"] if a["animName"] in durations}
    hook = _initial_mode_hook(enemy, behaviour)
    idle = _resolve_animation(mapped, hook, "Idle")
    attack = _resolve_animation(mapped, hook, "Attack")
    # Enemy::PlayMoveAnim plays Idle when Unit::ContainsAnimation reports no Move.
    move = _resolve_animation(mapped, hook, "Move") or idle
    if not move or spine["scale"] <= 0:
        raise ValueError(f"{logical}: 没有可播放的原始 Move 或 Idle 动画")
    scale, offset = _graphic_transform(skeleton, renderer, prefab_transform)
    config = {
        "skeleton": f"actor{suffix}", "atlas": "actor.atlas", "texturePages": pages,
        "skeletonScale": _float(spine["scale"]), "graphicScale": scale,
        "actorOffset": offset, "actorOffsetUnits": "prefab-root-local world units (Unity x,y,-z)",
        "clip": move["clip"], "clipSpeed": move["speed"], "clipLoop": move["loop"], "animations": mapped,
        "prefabAsset": logical, "skeletonDataName": spine["m_Name"],
        "skeletonDataPathId": str(skeleton_data.path_id),
    }
    if idle:
        config.update(idleClip=idle["clip"], idleClipSpeed=idle["speed"], idleClipLoop=idle["loop"])
    if attack:
        config.update(attackClip=attack["clip"], attackClipSpeed=attack["speed"])
    if shadow is not None:
        try:
            shadow_sprite = _shadow_sprite(_pointer(*shadow), prefab_transform)
        except (KeyError, OSError, ValueError) as error:
            # A missing optional shadow asset cannot invalidate a playable actor.
            config["shadowDiagnostic"] = str(error)
        else:
            if shadow_sprite is not None:
                config["shadow"], payload = shadow_sprite
                files[config["shadow"]["texture"]] = payload
    def resolve_animation(key):
        return _resolve_animation(mapped, hook, key)

    attacks = {
        timing: periodic_attack(timing, enemy, behaviour, prefab_transform, resolve_animation,
                                durations, _pointer, _components)
        for timing in skill_timings if timing is not None
    }
    return config, files, attacks


def extract_actors(root, enemy_ids, resource_version, output_dir, *, enemy_levels=None, cancel=None):
    """Return actor configs keyed by enemy ID. Paths are relative to output_dir.

    The default enemy database level is 0. Per-level gameplay effects, routes,
    and move multipliers belong to the caller's playback configuration.
    """
    levels = dict.fromkeys(enemy_ids, 0)
    if not levels:
        return {}
    for enemy_id in levels:
        if not isinstance(enemy_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", enemy_id):
            raise ValueError(f"无效敌人 ID：{enemy_id}")
        levels[enemy_id] = (enemy_levels or {}).get(enemy_id, 0)
    installation = discover_installation(root)
    destination = validate_output(output_dir, installation.root)
    catalog = load_catalog(installation)
    if catalog.manifest.get("versionId") != resource_version:
        raise ValueError("活动资源版本已变化，请重新扫描")
    index_name = catalog.manifest["manifestName"]
    index = next((p for layer in ("hot", "base") if layer in installation.source_roots
                  and (p := safe_path(installation.source_roots[layer], index_name)).is_file()), None)
    if index is None:
        raise FileNotFoundError(index_name)
    manifest = read_resource_manifest(index)
    enemy_db = _enemy_database(installation.root, levels, resource_version)
    prefix = "battle/prefabs/enemies/"
    requested = {}
    for enemy_id, enemy in enemy_db.items():
        prefab_key = enemy.get("prefabKey")
        if not prefab_key:
            raise ValueError(f"{enemy_id}: 敌人数据库没有可用 prefabKey")
        logical = prefab_key if prefab_key.startswith(prefix) else prefix + prefab_key
        requested.setdefault(logical, []).append(enemy_id)
    by_bundle = {}
    for asset in manifest["assets"]:
        logical = asset["assetName"]
        if logical in requested and asset["path"].endswith(".prefab"):
            by_bundle.setdefault(asset["bundle_index"], {})[logical] = asset["path"]
    missing = set(requested) - {logical for group in by_bundle.values() for logical in group}
    if missing:
        raise FileNotFoundError("活动资源索引没有敌人 prefab：" + "、".join(sorted(missing)))

    def installed(name):
        resource = catalog.resources.get(name)
        return Path(resource.path) if resource is not None and resource.path else None

    prepared = {}
    for bundle_index, assets in by_bundle.items():
        if cancel is not None:
            cancel.check()
        bundle = manifest["bundles"][bundle_index]
        source = installed(bundle["name"])
        if source is None:
            raise FileNotFoundError(bundle["name"])
        env = load_bundle(source)
        for i in dict.fromkeys(bundle["dependencies"]):
            dependency = installed(manifest["bundles"][i]["name"])
            if dependency is not None and dependency != source:
                env.load_file(str(dependency), is_dependency=True)
        container = env.container
        for logical, path in assets.items():
            prefab = container[path]
            try:
                skill_timings = {enemy_db[enemy_id].get("singleSkill") for enemy_id in requested[logical]}
                config, files, attacks = _extract_prefab(prefab, logical, skill_timings)
            except (KeyError, FileNotFoundError, ValueError) as error:
                raise ValueError(f"{logical}: {error}") from error
            for enemy_id in requested[logical]:
                info = enemy_db[enemy_id]
                actor = {**config, "enemyLevel": levels[enemy_id], "name": info.get("name")}
                if (profile := attacks.get(info.get("singleSkill"))) is not None:
                    actor["periodicAttack"] = profile
                if (speed := info.get("moveSpeed")) is not None and speed > 0:
                    actor["moveSpeed"] = speed
                prepared[enemy_id] = actor, files

    result = {}
    for enemy_id in levels:
        actor, files = prepared[enemy_id]
        folder = f"actors/{enemy_id}"
        for name, payload in files.items():
            path = safe_path(destination, f"{folder}/{name}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        for name in ("skeleton", "atlas"):
            actor[name] = f"{folder}/{actor[name]}"
        actor["texturePages"] = [f"{folder}/{page}" for page in actor["texturePages"]]
        if "shadow" in actor:
            actor["shadow"] = {**actor["shadow"], "texture": f"{folder}/{actor['shadow']['texture']}"}
        result[enemy_id] = actor
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--resource-version", required=True)
    parser.add_argument("enemy_ids", nargs="+")
    args = parser.parse_args()
    actors = extract_actors(args.root, args.enemy_ids, args.resource_version, args.output)
    atomic_json(args.output / "actors.json", actors)


if __name__ == "__main__":
    main()
