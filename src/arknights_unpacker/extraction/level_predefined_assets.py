"""Resolve authored battle instances and export their installed Spine prefabs."""
from pathlib import Path
import re

import numpy as np

from arknights_unpacker.library.discover import discover_installation, safe_path

from .engine import validate_output_root
from .level_actor_assets import _components, _float, _pointer, _shadow_sprite, _spine_files, _transform
from .level_replay_tiles import _export_mesh_prop, _tile_height
from .level_scene_assets import REFLECT_Z, _open_scene, _pose, _prefab_objects
from .tables import load_local_tables


_PREFABS = 'battle/prefabs/'


def _active_instances(level, replay):
    predefines = level.get('predefines') or {}
    cards = {row.get('alias') or row['inst']['characterKey']
             for field in ('characterCards', 'tokenCards') for row in predefines.get(field) or ()}
    activations = {}
    for event in replay.get('predefinedActivations') or ():
        key, time = event['key'], event['time']
        if key:
            activations[key] = min(time, activations.get(key, time))

    for field in ('characterInsts', 'tokenInsts'):
        for row in predefines.get(field) or ():
            alias = row.get('alias') or row['inst']['characterKey']
            time = activations.pop(alias, None)
            start = time if row.get('hidden') else 0.
            if start is not None:
                yield field, row, alias, start
    unresolved = activations.keys() - cards
    if unresolved:
        raise ValueError('关卡预置物件别名不存在：' + '、'.join(sorted(unresolved)))


def _position(level, layout, placement):
    data = level['mapData']
    grid = data['map']
    columns, rows = grid['columnSize'], grid['rowSize']
    col, row = placement['position']['col'], placement['position']['row']
    if not (0 <= col < columns and 0 <= row < rows):
        raise ValueError(f'关卡预置物件不在地图格点内 ({col}, {row})')
    index = grid['matrixData'][(rows - row - 1) * columns + col]
    position = np.asarray(layout['origin']) + col * np.asarray(layout['columns']) + row * np.asarray(layout['rows'])
    position = position.astype(float)
    position[2] += _tile_height(layout, data['tiles'][index])
    return [_float(value) for value in position]


def _component_trees(objects):
    for component in objects:
        if component.type.name == 'MonoBehaviour':
            yield component, component.read_typetree()


def _actor_body(prefab):
    root = _components(prefab.read())
    return next(((reader, tree) for reader, tree in _component_trees(root)
                 if {'_animator', '_skinHolder', '_modes'} <= tree.keys()), (None, {}))


def _animator_kind(reader, tree):
    if '_animations' in tree and ('_skeleton' in tree or {'_front', '_back'} <= tree.keys()):
        return 'spine'
    if '_animations' in tree or '_effectWhiteList' in tree:
        name = _pointer(reader, tree['m_Script']).read().m_ClassName
        if name in ('MeshAnimator', 'MeshChangeableAnimator'):
            return 'mesh'
        if name == 'EmptyAnimator':
            return 'empty'
    return None


def _animator(reader, tree, objects):
    ref = tree.get('_animator', {})
    if ref.get('m_PathID'):
        animator = _pointer(reader, ref)
        animator_tree = animator.read_typetree()
        return animator, animator_tree, _animator_kind(animator, animator_tree)
    candidates = [(reader, tree, kind) for reader, tree in _component_trees(objects)
                  if tree.get('m_Enabled') and (kind := _animator_kind(reader, tree))]
    if len(candidates) != 1:
        raise ValueError('预制体没有唯一的已支持原版动画器')
    return candidates[0]


def _skin_entry(skins, row):
    key = row['inst']['characterKey']
    skin_id = row.get('skinId')
    if not skin_id:
        phase = row['inst'].get('phase') or 0
        eligible = [(value, skin) for value, skin in skins['buildinEvolveMap'].get(key, ()) if value <= phase]
        if eligible:
            _, skin_id = max(eligible)
    if not skin_id:
        return {}
    skin = skins['charSkins'].get(skin_id)
    if not skin or skin['charId'] != key:
        raise ValueError(f'{key}: 无法解析原版皮肤 {skin_id}')
    return skin.get('battleSkin') or {}


def _local_transform(node, root_transform):
    node = node.read()
    pose = np.eye(4)
    while (node.object_reader.assets_file, node.object_reader.path_id) != (
            root_transform.assets_file, root_transform.path_id):
        pose = _pose(node) @ pose
        if not node.m_Father:
            raise ValueError('Spine 节点不属于目标预制体')
        node = node.m_Father.read()
    return pose


def _export_visual(open_prefab, logical, skin, direction, map_theme, mesh_path):
    prefab, objects = open_prefab(logical)
    root_transform = _transform(_components(prefab.read()))
    body, body_tree = _actor_body(prefab)
    skin_logical = logical
    graphic_prefab, graphic_objects = prefab, objects
    graphic_root = root_transform
    mount = np.eye(4)
    animator_owner, animator_ref = body, body_tree
    if (default := body_tree.get('_defaultSkin')) and '_skins' in body_tree:
        # MapDependentTrap._TryLoadSkin reads Map.mapTheme and matches the prefab's skin list.
        trap_skins = body_tree['_skins'] or ()
        if map_theme is None and trap_skins:
            raise ValueError('地图缺少可核实的原版主题，无法选择预置物件皮肤')
        trap_skin = next((row['skinKey'] for row in trap_skins if row['theme'] == map_theme), default)
        skin_logical = f'{_PREFABS}skins/trap/{trap_skin.lower()}'
    else:
        skin_holder = body_tree.get('_skinHolder', {})
        if skin_holder.get('m_PathID') and not skin.get('overwritePrefab') and (skin_key := skin.get('skinOrPrefabId')):
            skin_logical = f'{_PREFABS}skins/character/{logical.rsplit("/", 1)[-1]}/{skin_key.lower()}'
            mount = _local_transform(_pointer(body, skin_holder), root_transform)
    if skin_logical != logical:
        graphic_prefab, graphic_objects = open_prefab(skin_logical)
        graphic_root = _transform(_components(graphic_prefab.read()))
        animator_owner, animator_ref = None, {}

    animator, tree, kind = _animator(animator_owner, animator_ref, graphic_objects)
    if kind == 'mesh':
        _export_mesh_prop(graphic_prefab, graphic_objects, mesh_path, mount=mount)
        return 'mesh', {'asset': mesh_path.name, 'prefabAsset': skin_logical,
                        'positions': [], 'activationTimes': []}
    if kind == 'empty' and not any(obj.type.name.endswith('Renderer') for obj in graphic_objects):
        if effect := body_tree.get('_startEffect'):
            raise ValueError(f'原版显示使用出生特效 {effect}，当前预览无法导出该特效')
        return 'invisible', None
    if kind != 'spine':
        raise ValueError('当前预览不支持预制体的原版动画器类型')

    # CharacterAnimator switches to the back configuration for the up direction.
    facing = 1 if body_tree.get('_isFixedRotation') else direction
    spine_ref = tree.get('_skeleton') or tree['_back' if facing == 0 else '_front']['skeleton']
    reader = _pointer(animator, spine_ref)
    renderer = reader.read_typetree()
    skeleton_data = _pointer(reader, renderer['skeletonDataAsset'])
    spine = skeleton_data.read_typetree()
    suffix, files, pages, names = _spine_files(skeleton_data, spine)
    idle = next((item for item in tree['_animations']
                 if item['animKey'] == 'Idle' and item['animName'] in names), None)
    if idle:
        clip, speed, loop = idle['animName'], idle['speed'], bool(idle['loop'])
    else:
        clip, speed, loop = renderer['_animationName'], renderer['timeScale'], bool(renderer['loop'])
    if clip not in names or speed <= 0 or spine['scale'] <= 0:
        raise ValueError(f'{skin_logical}: 没有可播放的原始待机动画')

    graphic_node = _transform(_components(_pointer(reader, renderer['m_GameObject']).read()))
    transform = mount @ _local_transform(graphic_node, graphic_root)
    axes = REFLECT_Z @ transform[:3, :2] * tree['_spineScale']
    if renderer['initialFlipX']:
        axes[:, 0] *= -1
    if renderer['initialFlipY']:
        axes[:, 1] *= -1
    config = {
        'skeleton': f'actor{suffix}', 'atlas': 'actor.atlas', 'texturePages': pages,
        'skeletonScale': _float(spine['scale']), 'graphicScale': 1.,
        'actorOffset': [_float(value) for value in REFLECT_Z @ transform[:3, 3]],
        'actorPlane': [[_float(value) for value in axis] for axis in axes.T],
        'clip': clip, 'clipSpeed': _float(speed), 'clipLoop': loop,
        'prefabAsset': logical, 'skinPrefabAsset': skin_logical,
        'skeletonDataName': spine['m_Name'], 'skeletonDataPathId': str(skeleton_data.path_id),
    }
    if (skin_name := renderer['initialSkinName']) and skin_name != 'default':
        config['initialSkin'] = skin_name
    shadow_ref = body_tree.get('_shadow', {})
    if shadow_ref.get('m_PathID') and not body_tree.get('_hideShadowOnRecycle'):
        shadow = _shadow_sprite(_pointer(body, shadow_ref), root_transform)
        if shadow is not None:
            config['shadow'], payload = shadow
            files[config['shadow']['texture']] = payload
    direction_sign = -1 if facing == 3 else 1
    return 'spine', (config, files, direction_sign)


def configure_scene_predefines(game_root, resource_version, level, replay, output, layout, *, cancel=None):
    """Add original preplaced operator and trap visuals at their authored activation times."""
    placements = list(_active_instances(level, replay))
    if not placements:
        return
    installation = discover_installation(game_root)
    destination = validate_output_root(output, [installation.root])
    destination.mkdir(parents=True, exist_ok=True)
    skins = None
    if any(field == 'characterInsts' or row.get('skinId') for field, row, *_ in placements):
        tables = load_local_tables(Path(game_root), None, cancel=cancel, names={'skin_table'},
                                   expected_resource_version=resource_version)
        skins = tables.tables['skin_table'].data
    bundle_cache, prefabs, visuals, configs = {}, {}, {}, {}
    events, mesh_props = [], []

    def open_prefab(logical):
        if logical not in prefabs:
            _, objects, asset = _open_scene(installation, logical, resource_version,
                                            extension='.prefab', bundle_cache=bundle_cache)
            prefabs[logical] = _prefab_objects(objects, asset['path'])
        return prefabs[logical]

    for field, row, alias, time in placements:
        if cancel is not None:
            cancel.check()
        key = row['inst']['characterKey']
        direction = row.get('direction', 0)
        skin = _skin_entry(skins, row) if skins is not None else {}
        group = 'characters' if field == 'characterInsts' else '[uc]tokens'
        prefab_key = skin.get('skinOrPrefabId') if skin.get('overwritePrefab') else key
        if not prefab_key or not re.fullmatch(r'[a-z0-9_#-]+', prefab_key, re.IGNORECASE) or direction not in range(5):
            raise ValueError(f'关卡预置物件数据无效：{alias}')
        logical = f'{_PREFABS}{group}/{prefab_key.lower()}'
        asset_key = logical, skin.get('skinOrPrefabId'), direction
        if asset_key not in visuals:
            actor_id = f'predefined-{len(visuals)}'
            try:
                kind, result = _export_visual(open_prefab, logical, skin, direction, layout.get('mapTheme'),
                                              safe_path(destination, f'{actor_id}.glb'))
            except (KeyError, OSError, ValueError) as error:
                raise ValueError(f'{alias} ({logical}): {error}') from error
            if kind == 'spine':
                config, files, direction_sign = result
                folder = f'actors/{actor_id}'
                for filename, payload in files.items():
                    path = safe_path(destination, f'{folder}/{filename}')
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(payload)
                for name in ('skeleton', 'atlas'):
                    config[name] = f'{folder}/{config[name]}'
                config['texturePages'] = [f'{folder}/{name}' for name in config['texturePages']]
                if 'shadow' in config:
                    config['shadow']['texture'] = f"{folder}/{config['shadow']['texture']}"
                configs[actor_id] = config
                result = actor_id, direction_sign
            elif kind == 'mesh':
                mesh_props.append(result)
            visuals[asset_key] = kind, result

        kind, result = visuals[asset_key]
        if kind == 'invisible':
            continue
        position = _position(level, layout, row)
        if kind == 'mesh':
            result['positions'].append(position)
            result['activationTimes'].append(time)
        else:
            actor_id, direction_sign = result
            events.append({'actorId': actor_id, 'key': alias, 'time': time,
                           'position': position, 'direction': direction_sign})
    if events:
        layout['predefinedActors'] = {'configs': configs, 'events': sorted(events, key=lambda event: event['time'])}
    if mesh_props:
        layout.setdefault('props', []).extend(mesh_props)
