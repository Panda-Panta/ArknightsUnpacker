from importlib import import_module
from types import SimpleNamespace

from PIL import Image
import pytest

from arknights_unpacker.contracts import CancelledError


class Reader:
    def __init__(self, object_id, kind, tree, file, image=None):
        self.path_id, self.type = object_id, SimpleNamespace(name=kind)
        self.tree, self.assets_file, self.picture = tree, file, image
        self.reads = 0

    def read_typetree(self):
        return self.tree

    def read(self):
        self.reads += 1
        return SimpleNamespace(image=self.picture)


def ref(object_id, file_id=0):
    return {'m_FileID': file_id, 'm_PathID': object_id}


def sprite(object_id, name, size, color, file, *, crop=None, offset=(0, 0)):
    image = Image.new('RGBA', crop or size, color)
    return Reader(object_id, 'Sprite', {
        'm_Name': name, 'm_Rect': {'width': size[0], 'height': size[1]},
        'm_RD': {'textureRectOffset': {'x': offset[0], 'y': offset[1]}}}, file, image)


def item(object_id, *, whole=False, alpha=0):
    return {'sprite': ref(object_id), 'alphaTex': ref(alpha), 'alias': '', 'isWholeBody': int(whole)}


def environment(*, new=False, second=False, crop=False, no_faces=False):
    file = object()
    body = sprite(10, 'body', (8, 8), (255, 0, 0, 255), file,
                  crop=(4, 6) if crop else None, offset=(2, 1) if crop else (0, 0))
    face = sprite(11, 'smile', (2, 2), (0, 255, 0, 255), file)
    whole = sprite(12, 'whole', (8, 8), (0, 0, 255, 255), file)
    entries = [item(11), item(12, whole=True), item(10)]
    pos, size = {'x': 3, 'y': 2}, {'x': 2, 'y': 3}
    if no_faces:
        entries, pos, size = [item(12), item(10)], {'x': -1, 'y': -1}, {'x': 0, 'y': 0}
    group = {'sprites': entries, 'facePos': pos, 'faceSize': size}
    tree = {'m_GameObject': ref(100)}
    if new:
        tree['spriteGroups'] = [group]
    else:
        tree.update(sprites=entries, FacePos=pos, FaceSize=size)
    objects = [Reader(1, 'MonoBehaviour', tree, file), body, face, whole,
               Reader(2, 'MonoBehaviour', {'m_GameObject': ref(100), 'm_Sprite': ref(10)}, file)]
    if second:
        other = sprite(20, 'other-body', (10, 10), (0, 0, 255, 255), file)
        objects.append(other)
        tree['spriteGroups'].append({'sprites': [item(11), item(20)],
                                     'facePos': {'x': 1, 'y': 1}, 'faceSize': {'x': 4, 'y': 4}})
    return SimpleNamespace(objects=objects, container={})


@pytest.fixture
def characters(monkeypatch):
    module = import_module('arknights_unpacker.extraction.characters')
    monkeypatch.setattr(module, 'material_alpha_pairs', lambda env, on_error=None: {})
    monkeypatch.setattr(module, 'sprite_image', lambda obj, data, env, pairs: (data.image.copy(), None))
    return module


@pytest.mark.parametrize('new', [False, True])
def test_catalog_old_and_new_config_preserves_roles_and_does_not_decode_pixels(characters, new):
    env = environment(new=new)
    result = characters.character_catalog(env)
    assert not result['diagnostics']
    group, = result['groups']
    assert group['face_pos'] == [3, 2] and group['face_size'] == [2, 3]
    assert [entry['role'] for entry in group['entries']] == ['face', 'whole', 'base']
    assert group['base_id'] == group['entries'][-1]['id']
    assert len({entry['id'] for entry in group['entries']}) == 3
    assert all(reader.reads == 0 for reader in env.objects)


def test_auto_groups_do_not_mix_bases_and_whole_body_is_a_replacement(characters):
    images = list(characters.iter_character_images(environment(new=True, second=True)))
    assert not [image for image in images if image.get('error')]
    assert len(images) == 5
    by_group = {}
    for item in images:
        by_group.setdefault(item['metadata']['group_id'], []).append(item)
    assert len(by_group) == 2
    assert {tuple(item['image'].size) for item in by_group['0:0']} == {(8, 8)}
    assert {tuple(item['image'].size) for item in by_group['0:1']} == {(10, 10)}
    whole, = [item for item in by_group['0:0'] if item['metadata']['mode'] == 'whole']
    assert whole['image'].getpixel((0, 0)) == (0, 0, 255, 255)


def test_full_body_legacy_group_with_no_face_rect_keeps_each_whole_variant(characters):
    env = environment(no_faces=True)
    group, = characters.character_catalog(env)['groups']
    assert [item['role'] for item in group['entries']] == ['whole', 'base']
    assert len(list(characters.iter_character_images(env))) == 2


def test_sprite_crop_is_restored_to_logical_canvas_before_face_placement(characters):
    env = environment(crop=True)
    group, = characters.character_catalog(env)['groups']
    image, metadata = characters.render_character(env, {'group_id': group['id'], 'face_id': group['entries'][0]['id']})
    assert image.size == (8, 8)
    assert image.getpixel((0, 0)) == (0, 0, 0, 0)
    assert image.getpixel((2, 1)) == (255, 0, 0, 255)
    assert image.getpixel((3, 2)) == (0, 255, 0, 255)
    assert image.getpixel((4, 4)) == (0, 255, 0, 255)
    assert metadata['face_pos'] == [3, 2] and metadata['face_size'] == [2, 3]


def test_manual_position_size_and_base_only_are_explicit(characters):
    env = environment()
    group, = characters.character_catalog(env)['groups']
    options = {'group_id': group['id'], 'base_id': group['base_id'],
               'face_id': group['entries'][0]['id'], 'x': 0, 'y': 0, 'width': 1, 'height': 1}
    image, metadata = characters.render_character(env, options)
    assert image.getpixel((0, 0)) == (0, 255, 0, 255)
    assert image.getpixel((1, 0)) == (255, 0, 0, 255)
    assert metadata['face_pos'] == [0, 0] and metadata['face_size'] == [1, 1]
    options['face_id'] = ''
    base, metadata = characters.render_character(env, options)
    assert base.getpixel((0, 0)) == (255, 0, 0, 255)
    assert metadata['mode'] == 'base'


def test_manual_whole_ignores_overlay_rectangle_and_keeps_original_pixels(characters):
    env = environment()
    group, = characters.character_catalog(env)['groups']
    image, metadata = characters.render_character(env, {'group_id': group['id'],
        'face_id': group['entries'][1]['id'], 'x': 900, 'y': 900, 'width': 1, 'height': 1})
    assert image.size == (8, 8) and image.getpixel((0, 0)) == (0, 0, 255, 255)
    assert metadata['mode'] == 'whole'


@pytest.mark.parametrize('options', [{'width': 0}, {'height': -1}, {'x': float('nan')},
                                    {'width': 10**9}, {'x': 1000}, {'face_id': 'another-group'}])
def test_invalid_manual_input_never_produces_a_plausible_picture(characters, options):
    env = environment()
    group, = characters.character_catalog(env)['groups']
    request = {'group_id': group['id'], 'face_id': group['entries'][0]['id'], **options}
    with pytest.raises(ValueError):
        characters.render_character(env, request)


def test_bad_reference_is_reported_without_hiding_good_other_group(characters):
    env = environment(new=True, second=True)
    env.objects[0].tree['spriteGroups'][0]['sprites'][0]['sprite'] = ref(11, 2)
    catalog = characters.character_catalog(env)
    assert len(catalog['groups']) == 1 and catalog['diagnostics']
    results = list(characters.iter_character_images(env))
    assert any(item.get('error') for item in results)
    assert len([item for item in results if item.get('image')]) == 2


def test_conflicting_alpha_remains_an_error_instead_of_opaque_success(characters, monkeypatch):
    def conflict(*args):
        raise ValueError('Alpha引用冲突')
    monkeypatch.setattr(characters, 'sprite_image', conflict)
    results = list(characters.iter_character_images(environment()))
    assert results and all(item.get('error') for item in results)


def test_cancel_is_never_converted_to_partial_image_error(characters):
    def cancel():
        raise CancelledError('cancelled')
    with pytest.raises(CancelledError):
        list(characters.iter_character_images(environment(), check=cancel))
