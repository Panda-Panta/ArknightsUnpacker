"""Export a named Unity battle scene from the active PC resource index."""
from argparse import ArgumentParser
from collections import Counter
from functools import lru_cache
from io import BytesIO
import json
from pathlib import Path
import struct

import numpy as np
from PIL import Image
from UnityPy.classes import PPtr
from UnityPy.helpers.MeshHelper import MeshHandler

from arknights_unpacker.extraction.engine import validate_output_root
from arknights_unpacker.extraction.manifest import read_resource_manifest
from arknights_unpacker.extraction.unity import load_bundle
from arknights_unpacker.library.discover import discover_installation, safe_path
from arknights_unpacker.library.resolver import collect_manifests
from arknights_unpacker.paths import atomic_json


REFLECT_Z = np.diag([1., 1., -1.])


def _open_scene(installation, logical, version, *, extension='.unity'):
    manifests, problems = collect_manifests(installation)
    manifest = manifests.get("hot") or manifests.get("base")
    if not manifest or manifest.get("versionId") != version:
        raise ValueError(f"活动资源版本与请求不一致：{version} {' '.join(problems)}")
    layers = {key: installation.source_roots[key] for key in ("hot", "base")
              if key in installation.source_roots}
    indices = [safe_path(root, manifest["manifestName"]) for root in layers.values()]
    index_path = next((path for path in indices if path.is_file()), None)
    if index_path is None:
        raise FileNotFoundError(f"活动资源索引不可用：{manifest['manifestName']}")
    index = read_resource_manifest(index_path)
    candidates = [asset for asset in index["assets"]
                  if asset["assetName"] == logical and asset["path"] == f'dyn/{logical}{extension}']
    if len(candidates) != 1:
        raise ValueError(f"活动索引未找到唯一 Unity 资源：{logical}{extension}")
    asset = candidates[0]
    bundle = index["bundles"][asset["bundle_index"]]
    entries = {key: {row["name"]: row for row in value["abInfos"]}
               for key, value in manifests.items()}
    active = entries.get("hot") or entries["base"]

    def locate(name):
        info = active[name]
        for layer, root in layers.items():
            if layer == "base":
                base = entries.get("base", {}).get(name, {})
                if any(base.get(field) != info.get(field) for field in ("abSize", "hash", "md5")):
                    continue
            path = safe_path(root, name)
            if path.is_file() and path.stat().st_size == info["abSize"]:
                return path
        raise FileNotFoundError(f"活动资源包不可用：{name}")

    env = load_bundle(locate(bundle["name"]))
    objects = tuple(env.objects)
    dependencies = dict.fromkeys(index["bundles"][i]["name"] for i in bundle["dependencies"])
    for name in dependencies:
        if name != bundle["name"]:
            env.load_file(str(locate(name)))
    return env, objects, asset


def _vector(value, fields="xyz"):
    return np.array([getattr(value, field) for field in fields])


def _srgb_to_linear(value):
    value = min(1., max(0., value))
    return value / 12.92 if value <= .04045 else ((value + .055) / 1.055)**2.4


def _pose(transform):
    x, y, z, w = _vector(transform.m_LocalRotation, "xyzw")
    matrix = np.eye(4)
    matrix[:3, :3] = np.array([
        [1 - 2*(y*y + z*z), 2*(x*y - z*w), 2*(x*z + y*w)],
        [2*(x*y + z*w), 1 - 2*(x*x + z*z), 2*(y*z - x*w)],
        [2*(x*z - y*w), 2*(y*z + x*w), 1 - 2*(x*x + y*y)],
    ]) * _vector(transform.m_LocalScale)
    matrix[:3, 3] = _vector(transform.m_LocalPosition)
    return matrix


def _hierarchy(objects):
    transforms = {obj.path_id: obj.read() for obj in objects if obj.type.name == "Transform"}
    by_game = {item.m_GameObject.path_id: key for key, item in transforms.items()}

    @lru_cache(None)
    def resolve(path_id):
        transform = transforms[path_id]
        game_object = transform.m_GameObject.read()
        name, pose, active = game_object.m_Name, _pose(transform), bool(game_object.m_IsActive)
        parent = transform.m_Father.path_id
        if parent in transforms:
            prefix, parent_pose, parent_active = resolve(parent)
            return f"{prefix}/{name}", parent_pose @ pose, active and parent_active
        return name, pose, active

    return by_game, resolve


class _Glb:
    def __init__(self):
        self.bin = bytearray()
        self.texture_cache = {}
        self.doc = {"asset": {"version": "2.0", "generator": "ArknightsUnpacker"},
                    "scene": 0, "scenes": [{"nodes": []}]}

    def add(self, name, item):
        items = self.doc.setdefault(name, [])
        items.append(item)
        return len(items) - 1

    def view(self, data, **fields):
        self.bin.extend(b"\0" * (-len(self.bin) % 4))
        result = self.add("bufferViews", {
            "buffer": 0, "byteOffset": len(self.bin), "byteLength": len(data), **fields,
        })
        self.bin.extend(data)
        return result

    def accessor(self, values, kind, *, index=False, bounds=False):
        values = np.asarray(values, dtype="<u4" if index else "<f4")
        view = self.view(values.tobytes(), target=34963 if index else 34962)
        row = {"bufferView": view, "componentType": 5125 if index else 5126,
               "count": len(values), "type": kind}
        if bounds:
            row.update(min=values.min(axis=0).tolist(), max=values.max(axis=0).tolist())
        return self.add("accessors", row)

    def texture(self, reader, normal):
        key = (reader.assets_file.name, reader.path_id, normal)
        if key in self.texture_cache:
            return self.texture_cache[key]
        texture = reader.read()
        image = texture.image
        if normal and texture.m_TextureFormat in (12, 27, 29):
            rgba = np.asarray(image.convert("RGBA"), dtype=np.float32) / 255.
            x = 2 * rgba[..., 0] * rgba[..., 3] - 1
            y = 2 * rgba[..., 1] - 1
            z = np.sqrt(np.maximum(0., 1 - x*x - y*y))
            image = Image.fromarray(((np.stack([x, y, z], -1) * .5 + .5) * 255).astype("uint8"))
        elif not normal and texture.m_ColorSpace == 0:
            rgba = np.asarray(image.convert("RGBA"), dtype=np.float32) / 255.
            rgb = rgba[..., :3]
            rgba[..., :3] = np.where(rgb <= .0031308, rgb * 12.92, 1.055 * rgb**(1/2.4) - .055)
            image = Image.fromarray(np.clip(np.rint(rgba * 255), 0, 255).astype("uint8"))
        payload = BytesIO()
        image.save(payload, format="PNG")
        image_index = self.add("images", {"name": texture.m_Name, "mimeType": "image/png",
                                        "bufferView": self.view(payload.getvalue())})
        self.texture_cache[key] = self.add("textures", {"source": image_index})
        return self.texture_cache[key]

    def finish(self, path):
        self.bin.extend(b"\0" * (-len(self.bin) % 4))
        self.doc["buffers"] = [{"byteLength": len(self.bin)}]
        data = json.dumps(self.doc, separators=(",", ":"), allow_nan=False).encode()
        data += b" " * (-len(data) % 4)
        with path.open("wb") as stream:
            stream.write(struct.pack("<4sIII4s", b"glTF", 2, 28 + len(data) + len(self.bin), len(data), b"JSON"))
            stream.write(data)
            stream.write(struct.pack("<I4s", len(self.bin), b"BIN\0"))
            stream.write(self.bin)


def _material(glb, reader, cache, materials):
    identity = reader.assets_file.name, reader.path_id
    if identity in cache:
        return cache[identity]
    material = reader.read()
    shader = material.m_Shader.read()
    shader_name = getattr(getattr(shader, "m_ParsedForm", None), "m_Name", None) or shader.m_Name
    saved = material.m_SavedProperties
    floats = {name: value for name, value in saved.m_Floats if np.isfinite(value)}
    colors = {name: _vector(value, "rgba").tolist() for name, value in saved.m_Colors
              if np.isfinite(_vector(value, "rgba")).all()}
    textures = {name: value for name, value in saved.m_TexEnvs if value.m_Texture}
    tint = colors.get("_Color", [1, 1, 1, 1])
    pbr = {"baseColorFactor": [*map(_srgb_to_linear, tint[:3]), min(1., max(0., tint[3]))],
           "metallicFactor": min(1., max(0., floats.get("_Metallic", 0.))),
           "roughnessFactor": 1. - min(1., max(0., floats.get("_Glossiness", .1)))}
    item = {"name": material.m_Name, "pbrMetallicRoughness": pbr,
            "extras": {"unityShader": shader_name, "unityKeywords": material.m_ValidKeywords,
                       "unityFloats": floats, "unityColors": colors, "unityTextures": {}}}
    for slot, value in textures.items():
        target = value.m_Texture.deref()
        texture = target.read()
        sx, sy = _vector(value.m_Scale, "xy")
        ox, oy = _vector(value.m_Offset, "xy")
        item["extras"]["unityTextures"][slot] = {
            "name": texture.m_Name, "colorSpace": texture.m_ColorSpace,
            "scale": [sx, sy], "offset": [ox, oy],
        }
        if slot in ("_MainTex", "_BumpMap"):
            texture_info = {"index": glb.texture(target, slot == "_BumpMap")}
            if (sx, sy, ox, oy) != (1., 1., 0., 0.):
                texture_info["extensions"] = {"KHR_texture_transform": {
                    "scale": [sx, sy], "offset": [ox, 1 - sy - oy],
                }}
                if "KHR_texture_transform" not in glb.doc.setdefault("extensionsUsed", []):
                    glb.doc["extensionsUsed"].append("KHR_texture_transform")
            if slot == "_MainTex":
                pbr["baseColorTexture"] = texture_info
            else:
                item["normalTexture"] = {**texture_info, "scale": floats.get("_BumpScale", 1.)}
    mode = floats.get("_Mode", 0)
    if mode == 1:
        item.update(alphaMode="MASK", alphaCutoff=floats.get("_Cutoff", .5))
    elif mode >= 2 or "AlphaBlend" in shader_name:
        item.update(alphaMode="BLEND", doubleSided=True)
    if shader_name.startswith(("Unlit/", "Torappu/Particles/")):
        if "KHR_materials_unlit" not in glb.doc.setdefault("extensionsUsed", []):
            glb.doc["extensionsUsed"].append("KHR_materials_unlit")
        item["extensions"] = {"KHR_materials_unlit": {}}
    materials[material.m_Name] = shader_name
    cache[identity] = glb.add("materials", item)
    return cache[identity]


def _meshes(objects, by_game, hierarchy):
    filters = {}
    cached = {}
    for reader in objects:
        if reader.type.name == "MeshFilter":
            mesh_filter = reader.read()
            filters[mesh_filter.m_GameObject.path_id] = mesh_filter.m_Mesh

    for reader in objects:
        if reader.type.name != "MeshRenderer":
            continue
        renderer = reader.read()
        game_id = renderer.m_GameObject.path_id
        name, pose, active = hierarchy(by_game[game_id])
        if not active or not renderer.m_Enabled:
            continue
        if not (pointer := filters.get(game_id)):
            yield name, None, None, None, None
            continue
        asset = pointer.deref()
        key = (asset.assets_file.name, asset.path_id)
        if key not in cached:
            mesh = asset.read()
            geometry = MeshHandler(mesh)
            geometry.process()
            cached[key] = mesh, geometry, geometry.get_triangles()
        mesh, geometry, triangles = cached[key]
        batch = renderer.m_StaticBatchInfo
        if batch.subMeshCount:
            first = batch.firstSubMesh
            indices = range(first, first + batch.subMeshCount)
            # Static-batch vertices already live in the batch root coordinate space.
            root = renderer.m_StaticBatchRoot.path_id
            pose = hierarchy(root)[1] if root else np.eye(4)
        else:
            indices = range(len(triangles))
        yield name, renderer, pose, (mesh, geometry, triangles), indices


def _primitive(glb, renderer, pose, source, sub, material):
    mesh, geometry, triangles = source
    faces = np.asarray(triangles[sub]) + (mesh.m_SubMeshes[sub].baseVertex or 0)
    vertices, indices = np.unique(faces, return_inverse=True)
    faces = indices.reshape(-1, 3)
    linear = REFLECT_Z @ pose[:3, :3]
    if np.linalg.det(linear) < 0:
        faces = faces[:, [0, 2, 1]]
    points = np.asarray(geometry.m_Vertices)[vertices, :3] @ linear.T + REFLECT_Z @ pose[:3, 3]
    normals = np.asarray(geometry.m_Normals)[vertices, :3] @ np.linalg.inv(linear)
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1.e-8)
    attrs = {"POSITION": glb.accessor(points, "VEC3", bounds=True),
             "NORMAL": glb.accessor(normals, "VEC3")}
    if geometry.m_Tangents is not None:
        tangents = np.asarray(geometry.m_Tangents)[vertices, :4].copy()
        tangent = tangents[:, :3] @ linear.T
        tangent -= (tangent * normals).sum(axis=1, keepdims=True) * normals
        tangents[:, :3] = tangent / np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1.e-8)
        tangents[:, 3] *= np.sign(np.linalg.det(linear))
        attrs["TANGENT"] = glb.accessor(tangents, "VEC4")
    if geometry.m_UV0 is not None:
        uv0 = np.asarray(geometry.m_UV0)[vertices, :2].copy()
        uv0[:, 1] = 1 - uv0[:, 1]
        attrs["TEXCOORD_0"] = glb.accessor(uv0, "VEC2")
    if renderer.m_LightmapIndex < 65534 and geometry.m_UV1 is not None:
        uv1 = np.asarray(geometry.m_UV1)[vertices, :2].copy()
        # A Unity static batch already has atlas UVs. Ordinary meshes keep local UVs.
        if not renderer.m_StaticBatchInfo.subMeshCount:
            sx, sy, ox, oy = _vector(renderer.m_LightmapTilingOffset, "xyzw")
            uv1 = uv1 * [sx, sy] + [ox, oy]
        uv1[:, 1] = 1 - uv1[:, 1]
        attrs["TEXCOORD_1"] = glb.accessor(uv1, "VEC2")
    return {"attributes": attrs, "material": material,
            "indices": glb.accessor(faces.ravel(), "SCALAR", index=True)}, len(vertices), len(faces)


def _scene_settings(objects, by_game, hierarchy, output):
    cameras, lights, atlases, anchors = [], [], [], []
    map_effects = None
    for reader in objects:
        kind = reader.type.name
        if kind in ("Camera", "Light", "MonoBehaviour"):
            data = reader.read_typetree()
            name, pose, active = hierarchy(by_game[data["m_GameObject"]["m_PathID"]])
            point = REFLECT_Z @ pose[:3, 3]
            ray = REFLECT_Z @ pose[:3, 2]
            if kind == "Camera" and active and data["m_Enabled"]:
                cameras.append({"name": name, "position": point.tolist(), "target": (point + ray).tolist(),
                                "fov": data["field of view"], "orthographic": data["orthographic"]})
            elif kind == "Light" and active and data["m_Enabled"]:
                lights.append({"name": name, "type": data["m_Type"], "baking": data["m_Lightmapping"],
                               "color": [data["m_Color"][axis] for axis in "rgb"],
                               "intensity": data["m_Intensity"], "rayDirection": ray.tolist(),
                               "shadow": bool(data["m_Shadows"]["m_Type"])})
            elif kind == "MonoBehaviour":
                if "_gridPos" in data and active:
                    grid = data["_gridPos"]
                    anchors.append({"row": grid["row"], "col": grid["col"], "position": point.tolist()})
                if "_effectSettings" in data:
                    map_effects = data["_effectSettings"]
        if kind == "LightmapSettings":
            for index, atlas in enumerate(reader.read_typetree()["m_Lightmaps"]):
                entry = {}
                for field, ref in atlas.items():
                    if ref["m_PathID"]:
                        texture = PPtr(**ref, assetsfile=reader.assets_file).read()
                        name = f"atlas-{index}-{field}.png"
                        texture.image.save(output / name)
                        entry[field] = {"image": name, "format": texture.m_LightmapFormat}
                atlases.append(entry)
    return cameras, lights, atlases, anchors, map_effects


def _grid_axes(anchors):
    if len(anchors) < 3:
        return None
    tile_basis = [[1., row["col"], row["row"]] for row in anchors]
    points = [row["position"][:2] for row in anchors]
    result, _, rank, _ = np.linalg.lstsq(tile_basis, points, rcond=None)
    if rank != 3 or np.max(np.abs(np.asarray(tile_basis) @ result - points)) > .15:
        return None
    return [np.append(np.round(axis, decimals=3), 0.).tolist() for axis in result]


def extract_scene(game_root, scene_asset, resource_version, output, *, cancel=None):
    installation = discover_installation(game_root)
    output = validate_output_root(output, [installation.root])
    env, objects, asset = _open_scene(installation, scene_asset, resource_version)
    by_game, hierarchy = _hierarchy(objects)
    output.mkdir(parents=True, exist_ok=True)
    glb = _Glb()
    counts = Counter()
    materials, material_cache = {}, {}
    runtime_meshes = []
    for name, renderer, pose, source, indices in _meshes(objects, by_game, hierarchy):
        if cancel is not None:
            cancel.check()
        if renderer is None:
            runtime_meshes.append(name)
            continue
        primitives = []
        for slot, sub in enumerate(indices):
            if not source[2][sub]:
                continue
            material = _material(glb, renderer.m_Materials[slot].deref(), material_cache, materials)
            primitive, vertices, triangles = _primitive(glb, renderer, pose, source, sub, material)
            primitives.append(primitive)
            counts.update(vertices=vertices, triangles=triangles)
        if primitives:
            local_name = name.rsplit("/", 1)[-1]
            mesh_id = glb.add("meshes", {"name": local_name, "primitives": primitives})
            node = glb.add("nodes", {"name": local_name, "mesh": mesh_id, "extras": {
                "unityHierarchy": name, "unityLightmapIndex": renderer.m_LightmapIndex,
            }})
            glb.doc["scenes"][0]["nodes"].append(node)
            counts.update(meshes=1, static_batches=int(bool(renderer.m_StaticBatchInfo.subMeshCount)))
    if not counts["meshes"]:
        raise ValueError(f"场景没有可导出的静态网格：{scene_asset}")
    model = f"{asset['name']}.glb"
    cameras, lights, atlases, anchors, map_effects = _scene_settings(objects, by_game, hierarchy, output)
    glb.finish(output / model)
    camera = next((item for item in cameras if item["name"].endswith("/Camera") and not item["orthographic"]), None)
    sun = next((item for item in lights if item["type"] == 1 and item["baking"] != 2), None)
    grid = _grid_axes(anchors)
    layout_diagnostics = []
    if not camera:
        layout_diagnostics.append("场景没有可确认的主透视镜头，需要运行时相机。")
    if not sun:
        layout_diagnostics.append("场景没有可确认的主方向光。")
    if not grid:
        layout_diagnostics.append("场景格点坐标未能确定。")
    if len(atlases) != 1 or not {"m_Lightmap", "m_ShadowMask"} <= atlases[0].keys():
        layout_diagnostics.append("当前播放器需要单张烘焙光照图和独立阴影遮罩。")
    receipt = {"asset": model, "source": asset, "resourceVersion": resource_version,
               "geometry": dict(counts), "materials": materials, "tileAnchors": anchors,
               "cameras": cameras, "lights": lights, "lightmaps": atlases, "mapEffects": map_effects,
               "runtimeMeshes": runtime_meshes, "grid": grid, "layoutDiagnostics": layout_diagnostics}
    atomic_json(output / "scene-metadata.json", receipt)
    if not layout_diagnostics:
        layout = {"asset": model, "camera": camera, "sun": sun, "ambient": .3,
                  "origin": grid[0], "columns": grid[1], "rows": grid[2], "props": [],
                  "lightMap": atlases[0]["m_Lightmap"]["image"],
                  "battleLighting": {"shadowMask": atlases[0]["m_ShadowMask"]["image"]}}
        atomic_json(output / "scene-layout.json", layout)
    return receipt


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("game_root", type=Path)
    parser.add_argument("scene_asset", help="Exact scene assetName from the active resource index")
    parser.add_argument("resource_version")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    receipt = extract_scene(args.game_root, args.scene_asset, args.resource_version, args.output)
    print(json.dumps({"asset": receipt["asset"], **receipt["geometry"],
                      "layoutDiagnostics": receipt["layoutDiagnostics"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
