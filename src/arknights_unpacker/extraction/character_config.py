"""Read the two observed AVG character configuration layouts in one place."""
from __future__ import annotations


def iter_character_groups(env, check=lambda: None, on_error=None):
    """Yield normalized groups, retaining readers and explicit Unity references.

    Only structures with a sprites list are recognized; names are not evidence
    that a texture is a body, face or alpha mask. Resolution remains file-local.
    """
    config_index = 0
    for reader in env.objects:
        check()
        if reader.type.name != 'MonoBehaviour':
            continue
        try:
            tree = reader.read_typetree()
        except Exception:
            continue  # Unrelated MonoBehaviours may have no available type tree.
        if not isinstance(tree, dict):
            continue
        if isinstance(tree.get('spriteGroups'), list):
            groups = tree['spriteGroups']
            schema = 'spriteGroups'
        elif isinstance(tree.get('sprites'), list):
            groups = [tree]
            schema = 'sprites'
        else:
            continue
        for group_index, group in enumerate(groups):
            check()
            if not isinstance(group, dict) or not isinstance(group.get('sprites'), list):
                if on_error:
                    on_error(f'角色配置 {reader.path_id} 第{group_index + 1}组缺少图片列表')
                continue
            yield {'id': f'{config_index}:{group_index}', 'reader': reader,
                   'config_id': str(reader.path_id), 'group_index': group_index,
                   'schema': schema, 'entries': group['sprites'],
                   'face_pos': group.get('facePos', group.get('FacePos')),
                   'face_size': group.get('faceSize', group.get('FaceSize')),
                   'game_object': tree.get('m_GameObject')}
        config_index += 1
