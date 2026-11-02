"""Compose AVG expressions from explicit sprite groups on their logical canvas."""
from __future__ import annotations

import math

from PIL import Image

from ..contracts import CancelledError
from .character_config import iter_character_groups
from .images import material_alpha_pairs, sprite_image


MAX_IMAGE_PIXELS = 80_000_000


def _key(reader, object_id=None):
    return id(getattr(reader, 'assets_file', None)), str(reader.path_id if object_id is None else object_id)


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{label}必须是有限数值')
    return value


def _pair(value, label):
    if not isinstance(value, dict):
        raise ValueError(f'缺少{label}')
    return [_number(value.get(axis), label) for axis in ('x', 'y')]


def _dimensions(width, height):
    width, height = round(_number(width, '宽度')), round(_number(height, '高度'))
    if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
        raise ValueError('图片尺寸必须为正数且不能超过8000万像素')
    return width, height


def _reference(objects, owner, reference, kind):
    if not isinstance(reference, dict) or not reference.get('m_PathID'):
        raise ValueError(f'缺少{kind}引用')
    if reference.get('m_FileID', 0) != 0:
        raise ValueError(f'{kind}引用位于外部依赖包，当前无法确认')
    reader = objects.get(_key(owner, reference['m_PathID']))
    if reader is None or reader.type.name != kind:
        raise ValueError(f'{kind}引用缺失或类型不符：{reference["m_PathID"]}')
    return reader


def _inventory(env, check):
    objects = {_key(reader): reader for reader in env.objects}
    defaults = {}
    for reader in env.objects:
        check()
        if reader.type.name != 'MonoBehaviour':
            continue
        try:
            tree = reader.read_typetree()
        except CancelledError:
            raise
        except Exception:
            continue
        if isinstance(tree, dict) and tree.get('m_Sprite', {}).get('m_PathID'):
            game_object = tree.get('m_GameObject', {})
            if game_object.get('m_FileID', 0) == 0:
                defaults.setdefault(_key(reader, game_object.get('m_PathID')), []).append(tree['m_Sprite'])
    groups, diagnostics = [], []
    for definition in iter_character_groups(env, check, diagnostics.append):
        try:
            check()
            entries = []
            for index, raw in enumerate(definition['entries']):
                check()
                if not isinstance(raw, dict):
                    raise ValueError('图片条目格式不正确')
                reader = _reference(objects, definition['reader'], raw.get('sprite'), 'Sprite')
                alpha = raw.get('alphaTex', {})
                if alpha.get('m_PathID'):
                    _reference(objects, definition['reader'], alpha, 'Texture2D')
                tree = reader.read_typetree()
                width, height = _dimensions(tree['m_Rect']['width'], tree['m_Rect']['height'])
                entries.append({'id': f'{definition["id"]}:{index}', 'name': str(tree.get('m_Name', '')),
                                'alias': str(raw.get('alias') or ''), 'width': width, 'height': height,
                                '_reader': reader, '_tree': tree, '_alpha': alpha,
                                '_whole': bool(raw.get('isWholeBody'))})
            if not entries:
                raise ValueError('图片组为空')
            position = _pair(definition['face_pos'], '表情位置')
            size = _pair(definition['face_size'], '表情尺寸')
            base = entries[-1]
            game_object = definition.get('game_object') or {}
            default_refs = defaults.get(_key(definition['reader'], game_object.get('m_PathID')), [])
            candidates = [entry for entry in entries for reference in default_refs
                          if reference.get('m_FileID', 0) == 0 and
                          str(reference.get('m_PathID')) == str(entry['_reader'].path_id)]
            if candidates:
                if len({entry['id'] for entry in candidates}) != 1:
                    raise ValueError('同一角色存在冲突的默认底图引用')
                candidate = candidates[0]
                if (candidate['width'], candidate['height']) != (base['width'], base['height']):
                    raise ValueError('默认底图与本组底图画布不一致')
                base = candidate
            no_face_rect = min(size) <= 0 or min(position) < 0
            if no_face_rect and any((entry['width'], entry['height']) != (base['width'], base['height']) for entry in entries):
                raise ValueError('表情定位未知，且图片并非完整全身变体')
            if not no_face_rect and (base['width'] < position[0] + size[0] or base['height'] < position[1] + size[1]):
                raise ValueError('配置表情区域超出底图画布')
            for entry in entries:
                entry['role'] = ('base' if entry is base else 'whole' if entry['_whole'] or no_face_rect or
                                 (entry['width'], entry['height']) == (base['width'], base['height']) else 'face')
            group = {**definition, 'title': f'{base["name"] or definition["config_id"]} · 第{definition["group_index"] + 1}组',
                     'face_pos': position, 'face_size': size, 'base_id': base['id'], 'entries': entries}
            groups.append(group)
        except CancelledError:
            raise
        except Exception as error:
            diagnostics.append(f'角色配置 {definition["config_id"]} 第{definition["group_index"] + 1}组：{error}')
    return groups, diagnostics


def character_catalog(env, check=lambda: None):
    """Read only group metadata; pixels are decoded only for requested rendering."""
    groups, diagnostics = _inventory(env, check)
    return {'groups': [{key: group[key] for key in ('id', 'title', 'face_pos', 'face_size', 'base_id')} |
                       {'entries': [{key: entry[key] for key in ('id', 'name', 'alias', 'role', 'width', 'height')}
                                    for entry in group['entries']]} for group in groups],
            'diagnostics': diagnostics}


def _canvas(entry, env, pairs, check, cache):
    if entry['id'] in cache:
        return cache[entry['id']]
    check()
    tree = entry['_tree']
    if tree.get('m_SpriteAtlas', {}).get('m_PathID') or tree.get('m_RD', {}).get('downscaleMultiplier', 1) != 1:
        raise ValueError('图集或降采样Sprite的逻辑画布尚无法确认')
    image, pairing = sprite_image(entry['_reader'], entry['_reader'].read(), env, pairs)
    image = image.convert('RGBA')
    width, height = entry['width'], entry['height']
    offset = tree.get('m_RD', {}).get('textureRectOffset')
    if offset is None:
        if image.size != (width, height):
            raise ValueError('裁切Sprite缺少逻辑画布偏移')
        offset = {'x': 0, 'y': 0}
    left = round(_number(offset.get('x'), 'Sprite横向偏移'))
    top = height - round(_number(offset.get('y'), 'Sprite纵向偏移')) - image.height
    if left < 0 or top < 0 or left + image.width > width or top + image.height > height:
        raise ValueError('裁切Sprite超出逻辑画布')
    canvas = Image.new('RGBA', (width, height))
    canvas.alpha_composite(image, (left, top))
    check()
    cache[entry['id']] = canvas, pairing
    return canvas, pairing


def _entry(group, entry_id):
    result = next((entry for entry in group['entries'] if entry['id'] == entry_id), None)
    if result is None:
        raise ValueError('所选图片不属于当前角色组')
    return result


def _render(env, group, options, pairs, check, cache):
    check()
    base = _entry(group, options.get('base_id') or group['base_id'])
    if base['role'] not in ('base', 'whole'):
        raise ValueError('所选底图不是完整角色图片')
    face_id = options.get('face_id') or ''
    face = _entry(group, face_id) if face_id else None
    selected = face if face is not None and face['role'] in ('base', 'whole') else base
    canvas, pairing = _canvas(selected, env, pairs, check, cache)
    image = canvas.copy()
    used = [selected]
    pairings = [pairing] if pairing else []
    position, size = None, None
    mode = 'whole' if face is not None and face['role'] in ('base', 'whole') else 'base'
    if face is not None and face['role'] == 'face':
        x = round(_number(options.get('x', group['face_pos'][0]), '横向位置'))
        y = round(_number(options.get('y', group['face_pos'][1]), '纵向位置'))
        width, height = _dimensions(options.get('width', group['face_size'][0]), options.get('height', group['face_size'][1]))
        if x >= image.width or y >= image.height or x + width <= 0 or y + height <= 0:
            raise ValueError('表情区域与底图画布没有交集')
        patch, face_pairing = _canvas(face, env, pairs, check, cache)
        check()
        patch = patch.resize((width, height), Image.Resampling.BILINEAR)
        image.alpha_composite(patch, (x, y))
        position, size, mode = [x, y], [width, height], 'face'
        used.append(face)
        if face_pairing:
            pairings.append(face_pairing)
    check()
    object_ids = {group['config_id']}
    for entry in used:
        object_ids.add(str(entry['_reader'].path_id))
        for reference in (entry['_alpha'], entry['_tree'].get('m_RD', {}).get('texture', {})):
            if reference.get('m_PathID'):
                object_ids.add(str(reference['m_PathID']))
    metadata = {'group_id': group['id'], 'group_title': group['title'], 'config_id': group['config_id'],
                'group_index': group['group_index'], 'schema': group['schema'], 'mode': mode,
                'entry_id': face['id'] if face is not None else base['id'],
                'base_id': base['id'], 'face_id': face_id, 'face_pos': position, 'face_size': size,
                'image_size': list(image.size), 'image_pairings': pairings, 'object_ids': sorted(object_ids)}
    return image, metadata


def render_character(env, options, check=lambda: None):
    """Render one explicit selection; full-body choices replace the whole image."""
    if not isinstance(options, dict):
        raise ValueError('表情合成选项必须为对象')
    groups, diagnostics = _inventory(env, check)
    group = next((group for group in groups if group['id'] == options.get('group_id')), None)
    if group is None:
        raise ValueError('所选角色组不可用' + ('：' + '；'.join(diagnostics) if diagnostics else ''))
    pairs = material_alpha_pairs(env)
    return _render(env, group, options, pairs, check, {})


def iter_character_images(env, options=None, check=lambda: None):
    """Yield images and explicit per-group failures without dropping other groups."""
    groups, diagnostics = _inventory(env, check)
    pairs = material_alpha_pairs(env, on_error=diagnostics.append)
    if options is not None:
        if not isinstance(options, dict):
            raise ValueError('表情合成选项必须为对象')
        group = next((group for group in groups if group['id'] == options.get('group_id')), None)
        if group is None:
            raise ValueError('所选角色组不可用' + ('：' + '；'.join(diagnostics) if diagnostics else ''))
        image, metadata = _render(env, group, options, pairs, check, {})
        entry = _entry(group, options.get('face_id') or options.get('base_id') or group['base_id'])
        yield {'name': f'{group["title"]}__{entry["alias"] or entry["name"]}', 'image': image,
               'metadata': metadata, 'object_ids': metadata['object_ids']}
        return
    for diagnostic in dict.fromkeys(diagnostics):
        check()
        yield {'name': '角色配置诊断', 'error': diagnostic, 'metadata': {}, 'object_ids': []}
    if not groups and not diagnostics:
        yield {'name': '角色配置诊断', 'error': '包内没有可识别的角色表情配置', 'metadata': {}, 'object_ids': []}
    for group in groups:
        cache = {}
        # Base first makes standalone use and later face previews predictable.
        entries = [_entry(group, group['base_id'])] + [entry for entry in group['entries'] if entry['id'] != group['base_id']]
        for entry in entries:
            check()
            name = f'{group["title"]}__{entry["alias"] or entry["name"]}'
            request = {'base_id': group['base_id'], 'face_id': '' if entry['role'] == 'base' else entry['id']}
            try:
                image, metadata = _render(env, group, request, pairs, check, cache)
                yield {'name': name, 'image': image, 'metadata': metadata, 'object_ids': metadata['object_ids']}
            except CancelledError:
                raise
            except Exception as error:
                yield {'name': name, 'error': str(error),
                       'metadata': {'group_id': group['id'], 'entry_id': entry['id']}, 'object_ids': []}
