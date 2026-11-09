"""Add the client’s original entrance and destination prefabs to a scene."""
from collections import defaultdict

import numpy as np

from arknights_unpacker.library.discover import discover_installation

from .engine import validate_output_root
from .level_scene_assets import (
    _Glb, _hierarchy, _material, _meshes, _open_scene, _prefab_objects, _primitive, _srgb_to_linear,
)


_GATES = {'tile_start', 'tile_end'}
_HEIGHTS = {0: 0., 1: .4}


def _tile_height(layout, tile):
    height_type = tile['heightType']
    return layout.get('highlandHeight', _HEIGHTS[1]) if height_type == 1 else _HEIGHTS[height_type]


def _gate_positions(level, layout):
    data = level['mapData']
    grid = data['map']
    columns, rows = grid['columnSize'], grid['rowSize']
    tiles, indices = data['tiles'], grid['matrixData']
    if not columns or not rows or len(indices) != columns * rows:
        raise ValueError('关卡格点与地图尺寸不匹配。')
    origin, col_axis, row_axis = (np.asarray(layout[key], dtype=float) for key in ('origin', 'columns', 'rows'))
    gates = defaultdict(list)
    for index, tile_id in enumerate(indices):
        if not 0 <= tile_id < len(tiles):
            raise ValueError('关卡格点引用了无效的地块。')
        tile = tiles[tile_id]
        key = tile['tileKey']
        if key in _GATES:
            row_from_top, col = divmod(index, columns)
            row = rows - 1 - row_from_top
            position = origin + col * col_axis + row * row_axis
            position[2] += _tile_height(layout, tile)
            gates[key].append(position.tolist())
    return gates


def _export_mesh_prop(root, objects, output, *, mount=None):
    by_game, hierarchy = _hierarchy(objects)
    inverse_root = np.linalg.inv(hierarchy(by_game[root.path_id])[1])
    if mount is not None:
        inverse_root = mount @ inverse_root
    tints = {}
    for reader in objects:
        if reader.type.name == 'MonoBehaviour':
            data = reader.read_typetree()
            tint = data.get('_color')
            if isinstance(tint, dict) and {'r', 'g', 'b', 'a'} <= tint.keys():
                tints[data['m_GameObject']['m_PathID']] = [*(_srgb_to_linear(tint[channel]) for channel in 'rgb'),
                                                        tint['a']]

    glb = _Glb()
    for name, renderer, pose, mesh, indices in _meshes(objects, by_game, hierarchy):
        if renderer is None:
            continue
        primitives = []
        for slot, sub in enumerate(indices):
            if not mesh[2][sub]:
                continue
            index = _material(glb, renderer.m_Materials[slot].deref(), {}, {})
            material = glb.doc['materials'][index]
            shader = material['extras']['unityShader']
            if shader.startswith('Torappu/Particles/'):
                material.update(alphaMode='BLEND', doubleSided=True)
                material['extras']['unityBlend'] = 'additive' if 'Additive' in shader else 'alpha'
                tint = tints.get(renderer.m_GameObject.path_id)
                if tint is not None:
                    material['pbrMetallicRoughness']['baseColorFactor'] = tint
            primitive, _, _ = _primitive(glb, renderer, inverse_root @ pose, mesh, sub, index)
            primitives.append(primitive)
        if primitives:
            local_name = name.rsplit('/', 1)[-1]
            mesh_id = glb.add('meshes', {'name': local_name, 'primitives': primitives})
            node = glb.add('nodes', {'name': local_name, 'mesh': mesh_id})
            glb.doc['scenes'][0]['nodes'].append(node)
    if not glb.doc['scenes'][0]['nodes']:
        raise ValueError(f'原版预制体没有可导出的网格：{root.read().m_Name}')
    glb.finish(output)


def configure_scene_tiles(game_root, resource_version, level, output, layout, *, cancel=None):
    """Append original static gate meshes at their positions from the level grid."""
    gates = _gate_positions(level, layout)
    if not gates:
        return
    installation = discover_installation(game_root)
    output = validate_output_root(output, [installation.root])
    output.mkdir(parents=True, exist_ok=True)
    props = []
    bundle_cache = {}
    for key, positions in gates.items():
        if cancel is not None:
            cancel.check()
        asset = f'{key}.glb'
        _, objects, source = _open_scene(installation, f'battle/prefabs/effects/{key}', resource_version,
                                        extension='.prefab', bundle_cache=bundle_cache)
        root, objects = _prefab_objects(objects, source['path'])
        _export_mesh_prop(root, objects, output / asset)
        props.append({'asset': asset, 'positions': positions})
    layout.setdefault('props', []).extend(props)
