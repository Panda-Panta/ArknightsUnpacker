from types import SimpleNamespace

from PIL import Image

from arknights_unpacker.extraction.level_scene_assets import _Glb, _material


def test_standard_material_exports_emission_and_keeps_metallic_channels():
    file = SimpleNamespace(name='scene.cab')
    scale = SimpleNamespace(x=1., y=1.)
    offset = SimpleNamespace(x=0., y=0.)
    pixels = (20, 45, 60, 180)
    source = Image.new('RGBA', (1, 1), pixels)

    def tex(name, path_id):
        data = SimpleNamespace(m_Name=name, m_ColorSpace=1, image=source)
        reader = SimpleNamespace(assets_file=file, path_id=path_id, read=lambda: data)
        return SimpleNamespace(m_Texture=SimpleNamespace(deref=lambda: reader), m_Scale=scale, m_Offset=offset)

    shader = SimpleNamespace(m_Name='Torappu/Scene/StandardRealtimeShadow')
    properties = SimpleNamespace(m_Floats=[], m_Colors=[('_EmissionColor', SimpleNamespace(r=.8, g=0., b=0., a=1.))],
                                 m_TexEnvs=[('_EmissionMap', tex('fixture_E', 2)),
                                            ('_MetallicGlossMap', tex('fixture_M', 3))])
    material = SimpleNamespace(m_Name='fixture', m_Shader=SimpleNamespace(read=lambda: shader),
                               m_ValidKeywords=['_EMISSION', '_METALLICGLOSSMAP'], m_SavedProperties=properties)
    reader = SimpleNamespace(assets_file=file, path_id=1, read=lambda: material)
    model = _Glb()
    metallic_maps = {}

    index = _material(model, reader, {}, {}, metallic_maps=metallic_maps)

    exported = model.doc['materials'][index]
    assert exported['emissiveFactor'] == [((.8 + .055) / 1.055)**2.4, 0., 0.]
    assert exported['emissiveTexture'] == {'index': 0}
    asset = exported['extras']['unityTextures']['_MetallicGlossMap']['lightingAsset']
    name, texture = metallic_maps[('scene.cab', 3)]
    assert asset == name
    assert texture.image.getpixel((0, 0)) == pixels
