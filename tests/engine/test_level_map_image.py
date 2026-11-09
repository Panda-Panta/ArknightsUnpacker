import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

from arknights_unpacker.contracts import CancelToken, ResolvedResource


LEVEL = "gamedata/levels/obt/main/level_main_07-16"
ASSET = "arts/ui/stage/mappreviews/main_07-16"
PNG_PATH = f"dyn/{ASSET}.png"


def _row(asset=ASSET, bundle="map.ab", path=PNG_PATH):
    return {"assetName": asset, "bundle": bundle, "path": path, "name": asset.rsplit("/", 1)[-1]}


def test_find_requires_exact_game_asset_binding_and_unique_map_identity():
    from arknights_unpacker.extraction.level_map_image import find_level_map_images

    alias = "gamedata/levels/obt/weekly/level_weekly_fly_5"
    alternate = "gamedata/levels/activities/act1side/level_main_07-16"
    alias_asset = "arts/ui/stage/mappreviews/wk_fly_5"
    resources = {"map.ab": ResolvedResource("map.ab", "map-source")}
    index = {"assets": [
        _row(), _row(alias_asset, path=f"dyn/{alias_asset}.png"),
        _row("arts/ui/stage/mappreviews/other", path="dyn/arts/ui/stage/mappreviews/other.prefab"),
    ]}
    cancel = CancelToken()
    assert find_level_map_images(index, resources, [LEVEL, alias], cancel) == {LEVEL: ASSET}
    assert find_level_map_images(index, resources, {LEVEL: None, alias: "wk_fly_5"}, cancel) == {
        LEVEL: ASSET, alias: alias_asset,
    }
    assert find_level_map_images(index, resources, [LEVEL, alternate], cancel) == {}
    index["assets"].append(_row(bundle="other.ab"))
    assert find_level_map_images(index, resources, [LEVEL], cancel) == {}


@pytest.fixture
def map_installation(tmp_path):
    root = tmp_path / "game"
    root.mkdir()
    bundle = root / "map.ab"
    bundle.write_bytes(b"UnityFS-map")
    (root / "map.idx").write_bytes(b"fake-index")
    (root / "hot_update_list.json").write_text(json.dumps({
        "versionId": "real-version", "manifestName": "map.idx", "abInfos": [
            {"name": "map.ab", "md5": "0000", "abSize": bundle.stat().st_size},
        ],
    }), encoding="utf-8")
    return root


def _pointer(path_id, kind, color):
    image = Image.new("RGBA", (2, 3), color)
    reader = SimpleNamespace(
        path_id=path_id, type=SimpleNamespace(name=kind), assets_file=None,
        read=lambda: SimpleNamespace(image=image),
    )
    return SimpleNamespace(deref=lambda: reader)


def test_load_locks_version_and_exports_exact_native_sprite(monkeypatch, tmp_path, map_installation):
    from arknights_unpacker.extraction import level_map_image as module

    monkeypatch.setattr(module, "read_resource_manifest", lambda _: {"assets": [_row()]})
    environment = SimpleNamespace(container=SimpleNamespace(items=lambda: [
        (PNG_PATH, _pointer(1, "Texture2D", "red")),
        (PNG_PATH, _pointer(2, "Sprite", "blue")),
        (PNG_PATH + ".bak", _pointer(3, "Sprite", "black")),
    ]))
    monkeypatch.setattr(module, "load_bundle", lambda path, data: environment)
    output = tmp_path / "preview"
    with pytest.raises(ValueError, match="版本"):
        module.load_level_map_image(map_installation, ASSET, "stale-version", output)
    assert not output.exists()
    result = module.load_level_map_image(map_installation, ASSET, "real-version", output)
    assert result["resource_version"] == "real-version" and result["logical_asset"] == ASSET
    path = Path(result["path"])
    assert path.parent == output
    with Image.open(path) as image:
        assert image.size == (2, 3) and image.getpixel((0, 0)) == (0, 0, 255, 255)


def test_load_refuses_a_different_container_image(monkeypatch, tmp_path, map_installation):
    from arknights_unpacker.extraction import level_map_image as module

    monkeypatch.setattr(module, "read_resource_manifest", lambda _: {"assets": [_row()]})
    environment = SimpleNamespace(container={"dyn/unrelated.png": _pointer(1, "Sprite", "red")})
    monkeypatch.setattr(module, "load_bundle", lambda path, data: environment)
    with pytest.raises(ValueError, match="原图"):
        module.load_level_map_image(map_installation, ASSET, "real-version", tmp_path / "preview")
