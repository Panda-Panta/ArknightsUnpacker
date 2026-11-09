from math import cos, pi, sin
from types import SimpleNamespace

import pytest

from arknights_unpacker.extraction import level_actor_assets
from arknights_unpacker.extraction.level_actor_assets import _resolve_animation


def test_mode_hook_resolves_authored_keys_and_applies_exclusion_first():
    move = {"clip": "run", "speed": 1.0, "loop": True}
    altered = {"clip": "form_a_run", "speed": 0.75, "loop": True}
    mapped = {"Move": move, "Move_A": altered}
    hook = {"_replaceAnimPairs": [{"fromAnimKey": "Move", "toAnimKey": "Move_A"}]}

    assert _resolve_animation(mapped, {}, "Move") == move
    assert _resolve_animation(mapped, hook, "Move") == altered
    assert _resolve_animation(mapped, {**hook, "_excludeAnimKeys": ["Move"]}, "Move") is None
    assert _resolve_animation({"Move": move}, hook, "Move") is None


def test_spine_graphic_plane_keeps_prefab_axes_and_parent_translation(monkeypatch):
    def vector(values, fields="xyz"):
        return SimpleNamespace(**dict(zip(fields, values)))

    bundle = object()
    root = SimpleNamespace(assets_file=bundle, path_id=0)
    parent = SimpleNamespace(
        object_reader=SimpleNamespace(assets_file=bundle, path_id=1),
        m_LocalPosition=vector((4., 5., 6.)),
        m_LocalRotation=vector((-sin(pi / 12), 0., 0., cos(pi / 12)), "xyzw"),
        m_LocalScale=vector((-.19, .24, .24)),
        m_Father=SimpleNamespace(read=lambda: SimpleNamespace(object_reader=root)),
    )
    node = SimpleNamespace(
        object_reader=SimpleNamespace(assets_file=bundle, path_id=2),
        m_LocalPosition=vector((1., 0., 0.)),
        m_LocalRotation=vector((0., 0., 0., 1.), "xyzw"),
        m_LocalScale=vector((1., 1., 1.)),
        m_Father=SimpleNamespace(read=lambda: parent),
    )
    graphic = SimpleNamespace(read=lambda: node)
    monkeypatch.setattr(level_actor_assets, "_pointer", lambda *_: graphic)
    monkeypatch.setattr(level_actor_assets, "_components", lambda *_: ())
    monkeypatch.setattr(level_actor_assets, "_transform", lambda *_: graphic)

    scale, offset, axes = level_actor_assets._graphic_transform(None, {"m_GameObject": {}}, root)

    assert scale == 1.
    assert offset == [3.81, 5., -6.]
    assert axes[0] == pytest.approx([-.19, 0., 0.])
    assert axes[1] == pytest.approx([0., .24 * cos(pi / 6), .12])

    parent.m_LocalScale = vector((.24, .24, .24))
    assert level_actor_assets._graphic_transform(None, {"m_GameObject": {}}, root) == (
        .24, [4.24, 5., -6.], None)
