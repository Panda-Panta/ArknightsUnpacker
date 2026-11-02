"""AVG config pointers supply missing Sprite alpha without guessing names."""
from types import SimpleNamespace

from PIL import Image
import pytest
from UnityPy.classes import PPtr
from UnityPy.export import SpriteHelper

from arknights_unpacker.extraction import images


class Reader:
    def __init__(self, identity, kind, data, asset):
        self.path_id, self.type = identity, SimpleNamespace(name=kind)
        self.data, self.assets_file = data, asset
        asset.objects[identity] = self

    def read(self):
        return self.data

    parse_as_object = read

    def read_typetree(self):
        return self.data.tree if hasattr(self.data, 'tree') else self.data


class SpriteData:
    @property
    def image(self):
        return SpriteHelper.get_image_from_sprite(self)


def reference(identity, file_id=0):
    return {'m_FileID': file_id, 'm_PathID': identity}


def configured_environment(monkeypatch, schema='spriteGroups', alpha=20, alpha_file=0,
                           texture_rect=(0, 0, 4, 3), rotation=0):
    asset = SimpleNamespace(objects={}, _cache={})
    rgb = Image.new('RGBA', (4, 3), (23, 70, 110, 255))
    mask = Image.new('RGBA', (4, 3))
    mask.putdata([(value * 20, 255, 0, 255) for value in range(12)])
    texture = Reader(10, 'Texture2D', SimpleNamespace(image=rgb, m_Width=4, m_Height=3), asset)
    alpha_reader = Reader(20, 'Texture2D', SimpleNamespace(image=mask), asset)
    x, y, width, height = texture_rect
    data = SpriteData()
    data.assets_file = asset
    data.m_SpriteAtlas, data.m_AtlasTags = None, []
    data.m_RD = SimpleNamespace(texture=PPtr(m_FileID=0, m_PathID=10, assetsfile=asset),
                                alphaTexture=PPtr(m_FileID=0, m_PathID=0, assetsfile=asset),
                                textureRect=SimpleNamespace(x=x, y=y, width=width, height=height),
                                settingsRaw=2 | (1 | rotation << 2 if rotation else 0))
    data.tree = {'m_Rect': {'x': 0, 'y': 0, 'width': width, 'height': height},
                 'm_Offset': {'x': 0, 'y': 0}, 'm_AtlasTags': [], 'm_SpriteAtlas': reference(0),
                 'm_RD': {'texture': reference(10), 'textureRect': {'x': x, 'y': y, 'width': width, 'height': height},
                          'textureRectOffset': {'x': 0, 'y': 0}, 'settingsRaw': data.m_RD.settingsRaw}}
    sprite = Reader(30, 'Sprite', data, asset)
    entry = {'sprite': reference(30), 'alphaTex': reference(alpha, alpha_file)}
    group = {'sprites': [entry], 'facePos': {'x': 1, 'y': 1}, 'faceSize': {'x': 1, 'y': 1}}
    config = Reader(40, 'MonoBehaviour', {'spriteGroups': [group]} if schema == 'spriteGroups' else group, asset)
    env = SimpleNamespace(objects=[texture, alpha_reader, sprite, config])
    monkeypatch.setattr(SpriteHelper, 'get_image_from_texture2d',
                        lambda data, flip=True: data.image if flip else data.image.transpose(Image.Transpose.FLIP_TOP_BOTTOM))
    return env, texture, alpha_reader, sprite, config


@pytest.mark.parametrize('schema', ['spriteGroups', 'sprites'])
def test_texture_uses_config_reference_and_red_channel_without_mutation(monkeypatch, schema):
    env, texture, alpha, sprite, config = configured_environment(monkeypatch, schema)
    original = texture.data.image.tobytes()
    result, evidence = images.texture_image(texture, texture.read(), env, images.material_alpha_pairs(env))
    assert list(result.getchannel('A').getdata()) == list(alpha.read().image.getchannel('R').getdata())
    assert result.getpixel((0, 0))[:3] == (23, 70, 110)
    assert evidence['alpha'] == '20' and evidence['configurations'][0]['config_id'] == '40'
    assert texture.data.image.tobytes() == original


@pytest.mark.parametrize('rotation', [0, 1, 2, 3, 4])
def test_sprite_preserves_unity_crop_rotation_and_source_metadata(monkeypatch, rotation):
    env, texture, alpha, sprite, config = configured_environment(monkeypatch, texture_rect=(1, 0, 2, 3), rotation=rotation)
    original_render = sprite.data.m_RD
    result, evidence = images.sprite_image(sprite, sprite.read(), env, images.material_alpha_pairs(env))
    expected = texture.read().image.copy()
    expected.putalpha(alpha.read().image.getchannel('R'))
    expected = expected.transpose(Image.Transpose.FLIP_TOP_BOTTOM).crop((1, 0, 3, 3))
    if rotation:
        expected = expected.transpose({1: Image.Transpose.FLIP_LEFT_RIGHT, 2: Image.Transpose.FLIP_TOP_BOTTOM,
                                       3: Image.Transpose.ROTATE_180, 4: Image.Transpose.ROTATE_270}[rotation])
    expected = expected.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    assert result.size == expected.size and result.tobytes() == expected.tobytes()
    assert evidence['sprite'] == '30'
    assert sprite.data.m_RD is original_render and original_render.alphaTexture.path_id == 0


def test_zero_config_alpha_keeps_embedded_alpha(monkeypatch):
    env, texture, alpha, sprite, config = configured_environment(monkeypatch, alpha=0)
    texture.data.image.putalpha(71)
    result, evidence = images.sprite_image(sprite, sprite.read(), env, images.material_alpha_pairs(env))
    assert result.getchannel('A').getextrema() == (71, 71) and evidence is None


def test_same_ids_in_other_serialized_file_do_not_inherit_pairing(monkeypatch):
    env, texture, alpha, sprite, config = configured_environment(monkeypatch)
    other, other_texture, _, other_sprite, _ = configured_environment(monkeypatch, alpha=0)
    pairs = images.material_alpha_pairs(env)
    result, evidence = images.texture_image(other_texture, other_texture.read(), other, pairs)
    assert result.getchannel('A').getextrema() == (255, 255) and evidence is None
    result, evidence = images.sprite_image(other_sprite, other_sprite.read(), other, pairs)
    assert result.getchannel('A').getextrema() == (255, 255) and evidence is None


@pytest.mark.parametrize('alpha_id,alpha_file,expected', [(999, 0, '缺失'), (20, 1, '外部')])
def test_unresolvable_explicit_alpha_is_reported(monkeypatch, alpha_id, alpha_file, expected):
    env, texture, alpha, sprite, config = configured_environment(monkeypatch, alpha=alpha_id, alpha_file=alpha_file)
    diagnostics = []
    pairs = images.material_alpha_pairs(env, diagnostics.append)
    for obj, helper in ((texture, images.texture_image), (sprite, images.sprite_image)):
        with pytest.raises(ValueError, match=expected):
            helper(obj, obj.read(), env, pairs)


def test_conflicting_config_alpha_is_not_guessed(monkeypatch):
    env, texture, alpha, sprite, config = configured_environment(monkeypatch)
    Reader(21, 'Texture2D', SimpleNamespace(image=alpha.read().image), texture.assets_file)
    config.data['spriteGroups'][0]['sprites'].append({'sprite': reference(30), 'alphaTex': reference(21)})
    pairs = images.material_alpha_pairs(env)
    for obj, helper in ((texture, images.texture_image), (sprite, images.sprite_image)):
        with pytest.raises(ValueError, match='冲突'):
            helper(obj, obj.read(), env, pairs)


def test_material_and_character_config_share_confirmed_pair(monkeypatch):
    env, texture, alpha, sprite, config = configured_environment(monkeypatch)
    material = Reader(50, 'Material', {'m_SavedProperties': {'m_TexEnvs': {
        '_MainTex': {'m_Texture': reference(10)}, '_AlphaTex': {'m_Texture': reference(20)}}}}, texture.assets_file)
    env.objects.append(material)
    result, evidence = images.texture_image(texture, texture.read(), env, images.material_alpha_pairs(env))
    assert result.getchannel('A').getextrema() == (0, 220)
    assert evidence['materials'] == ['50'] and evidence['configurations'][0]['config_id'] == '40'


def test_alias_detection_uses_same_corrected_sprite_path(monkeypatch):
    env, texture, alpha, sprite, config = configured_environment(monkeypatch)
    pairs = images.material_alpha_pairs(env)
    aliases, redundant = images.full_texture_sprite_aliases(env, pairs, lambda: None)
    assert aliases == {id(texture): ['30']} and redundant == {id(sprite)}


def test_name_without_configuration_does_not_pair_texture(monkeypatch):
    env, texture, alpha, sprite, config = configured_environment(monkeypatch)
    env.objects.remove(config)
    alpha.data.m_Name = 'rgb[alpha]'
    texture.data.m_Name = 'rgb'
    result, evidence = images.texture_image(texture, texture.read(), env, images.material_alpha_pairs(env))
    assert result.getchannel('A').getextrema() == (255, 255) and evidence is None


def test_existing_sprite_alpha_cannot_be_overridden_by_conflicting_config(monkeypatch):
    env, texture, alpha, sprite, config = configured_environment(monkeypatch)
    sprite.data.m_RD.alphaTexture = PPtr(m_FileID=0, m_PathID=21, assetsfile=sprite.assets_file)
    with pytest.raises(ValueError, match='冲突'):
        images.sprite_image(sprite, sprite.read(), env, images.material_alpha_pairs(env))


def test_missing_or_external_sprite_is_diagnosed_without_name_fallback(monkeypatch):
    env, texture, alpha, sprite, config = configured_environment(monkeypatch)
    for reference_value, expected in ((reference(999), '缺失'), (reference(30, 1), '外部')):
        config.data['spriteGroups'][0]['sprites'][0]['sprite'] = reference_value
        diagnostics = []
        pairs = images.material_alpha_pairs(env, diagnostics.append)
        result, evidence = images.texture_image(texture, texture.read(), env, pairs)
        assert evidence is None and result.getchannel('A').getextrema() == (255, 255)
        assert any(expected in message for message in diagnostics)


def test_external_sprite_rgb_is_not_combined_with_local_alpha(monkeypatch):
    env, texture, alpha, sprite, config = configured_environment(monkeypatch)
    sprite.data.tree['m_RD']['texture']['m_FileID'] = 1
    sprite.data.m_RD.texture.m_FileID = 1
    diagnostics = []
    pairs = images.material_alpha_pairs(env, diagnostics.append)
    assert any('外部' in message for message in diagnostics)
    with pytest.raises(ValueError, match='外部'):
        images.sprite_image(sprite, sprite.read(), env, pairs)


def test_raw_export_preserves_serialized_bytes_without_reading_character_config(monkeypatch, tmp_path):
    from arknights_unpacker.contracts import ExtractionRequest
    from arknights_unpacker.extraction import engine

    env, texture, alpha, sprite, config = configured_environment(monkeypatch)
    texture.get_raw_data = lambda: b'original-texture-serialized'
    sprite.get_raw_data = lambda: b'original-sprite-serialized'
    config.read_typetree = lambda: pytest.fail('raw export read character configuration')
    monkeypatch.setattr(engine, 'load_bundle', lambda source: env)
    source = tmp_path / 'source.ab'
    source.write_bytes(b'UnityFS-fixture')
    request = ExtractionRequest([str(source)], str(tmp_path / 'out'), mode='raw', kinds=['image'],
                                object_ids={str(source): ['10', '30']})
    result = engine.run_extraction(request)
    assert result.status == 'succeeded'
    from pathlib import Path
    assert {item['object_id']: Path(item['path']).read_bytes() for item in result.outputs} == {
        '10': b'original-texture-serialized', '30': b'original-sprite-serialized'}
