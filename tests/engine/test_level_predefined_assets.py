from types import SimpleNamespace

import numpy as np
import pytest

from arknights_unpacker.extraction import level_predefined_assets as predefined
from arknights_unpacker.extraction.level_predefined_assets import _active_instances, _position, _skin_entry


def test_predefined_visibility_uses_instance_alias_and_first_activation():
    visible = {'inst': {'characterKey': 'char_112_siege'}, 'hidden': False}
    delayed = {'inst': {'characterKey': 'trap_086_larva'}, 'alias': 'scout', 'hidden': True}
    hidden = {**delayed, 'alias': 'regular'}
    card = {'inst': {'characterKey': 'char_150_snakek'}, 'hidden': True}
    level = {'predefines': {'characterInsts': [visible], 'tokenInsts': [delayed, hidden],
                            'characterCards': [card]}}
    replay = {'predefinedActivations': [{'key': 'scout', 'time': 12}, {'key': 'scout', 'time': 5},
                                        {'key': 'char_150_snakek', 'time': 10}, {'key': '', 'time': 0}]}

    assert list(_active_instances(level, replay)) == [
        ('characterInsts', visible, 'char_112_siege', 0.),
        ('tokenInsts', delayed, 'scout', 5),
    ]
    with pytest.raises(ValueError, match='missing-alias'):
        list(_active_instances(level, {'predefinedActivations': [{'key': 'missing-alias', 'time': 0}]}))


def test_predefined_uses_level_row_and_tile_height():
    level = {'mapData': {'map': {'columnSize': 2, 'rowSize': 2, 'matrixData': [0, 1, 0, 0]},
                         'tiles': [{'heightType': 0}, {'heightType': 1}]}}
    layout = {'origin': [-1, -2, 0], 'columns': [1, 0, 0], 'rows': [0, 1, 0], 'highlandHeight': .3}

    assert _position(level, layout, {'position': {'col': 1, 'row': 1}}) == [0., -1., .3]


def test_predefined_resolves_installed_skin_by_phase_or_explicit_id():
    basic = {'skinOrPrefabId': 'DefaultSkin', 'overwritePrefab': False}
    elite = {'skinOrPrefabId': 'EliteSkin', 'overwritePrefab': False}
    key = 'char_112_siege'
    skins = {'buildinEvolveMap': {key: [(0, 'basic'), (2, 'elite')]},
             'charSkins': {'basic': {'charId': key, 'battleSkin': basic},
                           'elite': {'charId': key, 'battleSkin': elite}}}
    row = {'inst': {'characterKey': key, 'phase': 2}}

    assert _skin_entry(skins, row) == elite
    assert _skin_entry(skins, {**row, 'skinId': 'basic'}) == basic


@pytest.mark.parametrize('class_name, fields, expected', [
    ('MeshAnimator', {'_animations': []}, 'mesh'),
    ('MeshChangeableAnimator', {'_animations': []}, 'mesh'),
    ('EmptyAnimator', {'_effectWhiteList': []}, 'empty'),
])
def test_predefined_distinguishes_native_mesh_and_empty_animators(monkeypatch, class_name, fields, expected):
    script = SimpleNamespace(read=lambda: SimpleNamespace(m_ClassName=class_name))
    monkeypatch.setattr(predefined, '_pointer', lambda *_: script)

    assert predefined._animator_kind(None, {'m_Script': {}, **fields}) == expected


@pytest.mark.parametrize('direction, expected', [(0, [2, 4, 0, 1]), (1, [3, 3, 0, 1]),
                                                 (2, [2, 2, 0, 1]), (3, [1, 3, 0, 1])])
def test_predefined_mesh_faces_using_its_authored_pivot(monkeypatch, direction, expected):
    asset = object()
    root = SimpleNamespace(assets_file=asset, path_id=10)
    pivot = SimpleNamespace(assets_file=asset, path_id=20)
    rotation = SimpleNamespace(x=0, y=0, z=0, w=1)
    scale = SimpleNamespace(x=1, y=1, z=1)
    root.read = lambda: SimpleNamespace(object_reader=root, m_LocalPosition=SimpleNamespace(x=0, y=0, z=0),
                                        m_LocalRotation=rotation, m_LocalScale=scale)
    child = SimpleNamespace(m_GameObject=SimpleNamespace(path_id=201), m_Children=[])
    pivot.read = lambda: SimpleNamespace(
        object_reader=pivot, m_GameObject=SimpleNamespace(path_id=200), m_Father=root,
        m_LocalPosition=SimpleNamespace(x=2, y=3, z=0), m_LocalRotation=rotation, m_LocalScale=scale,
        m_Children=[SimpleNamespace(read=lambda: child)],
    )
    monkeypatch.setattr(predefined, '_pointer', lambda *_: pivot)

    body_tree = {'_isFixedRotation': True, '_directionTransform': {'m_PathID': 20}}
    affected = predefined._mesh_direction_adjustments(None, body_tree, root, direction)

    assert set(affected) == {200, 201}
    np.testing.assert_allclose(affected[201] @ [2, 4, 0, 1], expected)
    assert predefined._mesh_direction_adjustments(None, {'_isFixedRotation': True}, root, direction) is None
