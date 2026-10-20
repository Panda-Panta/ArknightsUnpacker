"""Image export keeps native pixels and decides its stable path before writing."""
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
import pytest

from arknights_unpacker.contracts import CancelToken, ExtractionRequest
from arknights_unpacker.extraction.engine import run_extraction


class Picture:
    def __init__(self, object_id, name, image, kind="Texture2D"):
        self.path_id = object_id
        self.type = SimpleNamespace(name=kind)
        self.data = SimpleNamespace(m_Name=name, image=image)

    def read(self):
        return self.data

    def get_raw_data(self):
        return (self.type.name + str(self.path_id)).encode()


class Material:
    type = SimpleNamespace(name="Material")
    path_id = 30

    def read_typetree(self):
        return {"m_SavedProperties": {"m_TexEnvs": {
            "_MainTex": {"m_Texture": {"m_FileID": 0, "m_PathID": 10}},
            "_AlphaTex": {"m_Texture": {"m_FileID": 0, "m_PathID": 20}},
        }}}


def bundle(objects):
    return SimpleNamespace(objects=objects, container={})


def request(tmp_path, names=("source.ab",), selected=None):
    paths = []
    for name in names:
        path = tmp_path / name
        path.write_bytes(b"UnityFS-test-image-layout")
        paths.append(str(path))
    return ExtractionRequest(paths, str(tmp_path / "out"), kinds=["image"],
                             object_ids={paths[0]: selected} if selected else {})


def picture(object_id=10, name="picture", size=(137, 59), kind="Texture2D"):
    return Picture(object_id, name, Image.new("RGBA", size, (13, 71, 29, 255)), kind)


def extract(req, env, emit=lambda event: None, cancel=None):
    with patch("arknights_unpacker.extraction.engine.load_bundle", return_value=env):
        return run_extraction(req, emit, cancel)


def test_one_picture_is_saved_directly_in_task_root(tmp_path):
    req = request(tmp_path)
    result = extract(req, bundle([picture()]))
    assert result.status == "succeeded" and len(result.outputs) == 1
    item = result.outputs[0]
    assert Path(item["path"]).parent == Path(req.output_root)
    assert item["image_layout"] == "flat" and item["selected_image_count"] == 1
    assert not [path for path in Path(req.output_root).iterdir() if path.is_dir()]


def test_multiple_pictures_have_one_source_directory(tmp_path):
    req = request(tmp_path)
    result = extract(req, bundle([picture(10), picture(20, "other")]))
    parents = {Path(item["path"]).parent for item in result.outputs}
    assert len(parents) == 1 and next(iter(parents)).parent == Path(req.output_root)
    assert all(item["image_layout"] == "package" and item["selected_image_count"] == 2
               for item in result.outputs)


def test_selecting_one_picture_from_larger_package_is_flat(tmp_path):
    req = request(tmp_path, selected=["20"])
    result = extract(req, bundle([picture(10), picture(20, "selected")]))
    assert len(result.outputs) == 1 and result.outputs[0]["object_id"] == "20"
    assert Path(result.outputs[0]["path"]).parent == Path(req.output_root)
    assert result.outputs[0]["selected_image_count"] == 1


def test_nonimage_members_do_not_make_a_single_picture_package_directory(tmp_path):
    req = request(tmp_path)
    nonimage = SimpleNamespace(path_id=90, type=SimpleNamespace(name="TextAsset"))
    result = extract(req, bundle([picture(), nonimage]))
    assert len(result.outputs) == 1
    assert Path(result.outputs[0]["path"]).parent == Path(req.output_root)


@pytest.mark.parametrize("kind,size", [("Texture2D", (137, 59)), ("Sprite", (37, 23))])
def test_native_texture_and_cropped_sprite_pixel_dimensions(tmp_path, kind, size):
    req = request(tmp_path)
    original = picture(size=size, kind=kind)
    result = extract(req, bundle([original]))
    assert len(result.outputs) == 1
    with Image.open(result.outputs[0]["path"]) as saved:
        assert saved.size == size and saved.tobytes() == original.data.image.tobytes()
    assert result.outputs[0]["image_size"] == list(size)


def test_explicit_alpha_resizes_mask_only_and_keeps_rgb_dimensions(tmp_path):
    req = request(tmp_path, selected=["10"])
    rgb = picture(size=(137, 59))
    alpha = Picture(20, "alpha", Image.new("RGB", (1, 1), (91, 91, 91)))
    result = extract(req, bundle([rgb, alpha, Material()]))
    assert len(result.outputs) == 1
    with Image.open(result.outputs[0]["path"]) as saved:
        assert saved.size == (137, 59)
        assert saved.getchannel("A").getextrema() == (91, 91)
        assert saved.getpixel((0, 0))[:3] == (13, 71, 29)
    assert result.outputs[0]["image_pairing"]["alpha"] == "20"
    assert result.outputs[0]["image_size"] == [137, 59]


def test_two_single_picture_packages_and_retry_do_not_overwrite(tmp_path):
    req = request(tmp_path, names=("first.ab", "second.ab"))
    env = bundle([picture(name="same")])
    first = extract(req, env)
    initial = {item["path"]: Path(item["path"]).read_bytes() for item in first.outputs}
    second = extract(req, env)
    paths = [Path(item["path"]) for item in first.outputs + second.outputs]
    assert len(paths) == len(set(paths)) == 4
    assert all(path.parent == Path(req.output_root) for path in paths)
    assert all(Path(path).read_bytes() == data for path, data in initial.items())


def test_duplicate_image_names_and_ids_still_have_unique_files(tmp_path):
    req = request(tmp_path)
    result = extract(req, bundle([picture(10, "same"), picture(10, "same")]))
    assert len({item["path"] for item in result.outputs}) == 2
    assert all(Path(item["path"]).is_file() for item in result.outputs)


def test_decode_failure_keeps_preselected_multi_picture_layout_and_emitted_path(tmp_path):
    req = request(tmp_path)

    class BrokenPicture(Picture):
        def read(self):
            raise ValueError("deliberate broken texture")

    events = []
    broken = BrokenPicture(20, "broken", None)
    result = extract(req, bundle([picture(), broken]), events.append)
    assert result.status == "partial" and len(result.outputs) == len(result.errors) == 1
    item = result.outputs[0]
    assert item["image_layout"] == "package" and item["selected_image_count"] == 2
    assert Path(item["path"]).parent.parent == Path(req.output_root)
    assert item["path"] == next(event["path"] for event in events if event["kind"] == "output")


def test_spine_relative_files_keep_their_group_when_single_picture_is_flat(tmp_path):
    req = request(tmp_path)
    req.kinds = ["image", "spine"]
    group = {"id": "70", "name": "hero", "object_ids": {"70", "10"},
             "files": [("hero.atlas", b"hero.png\nsize: 137,59\n", "spine_atlas"),
                       ("hero.png", picture().data.image, "spine_texture")]}
    with patch("arknights_unpacker.extraction.spine.iter_spine_groups", return_value=iter([group])):
        result = extract(req, bundle([picture()]))
    assert result.status == "succeeded"
    group_items = [item for item in result.outputs if item["kind"].startswith("spine_")]
    assert {Path(item["path"]).name for item in group_items} == {"hero.atlas", "hero.png"}
    assert len({Path(item["path"]).parent for item in group_items}) == 1
    assert Path(group_items[0]["path"]).parent.parent.parent == Path(req.output_root)
    image = next(item for item in result.outputs if item["kind"] == "image")
    assert Path(image["path"]).parent == Path(req.output_root)


def test_cancel_keeps_emitted_final_paths_in_result_manifest(tmp_path):
    req = request(tmp_path)
    token = CancelToken()
    events = []

    def emit(event):
        events.append(event)
        if event["kind"] == "output":
            token.cancel()

    result = extract(req, bundle([picture(10), picture(20)]), emit, token)
    assert result.status == "cancelled" and len(result.outputs) == 1
    output_event = next(event for event in events if event["kind"] == "output")
    assert Path(output_event["path"]).is_file()
    assert result.outputs[0]["path"] == output_event["path"]
    manifest = json.loads((Path(req.output_root) / "extraction-result.json").read_text("utf-8"))
    assert manifest["outputs"] == result.outputs
    assert not any(event["kind"] == "object_complete" for event in events)
    assert not list(Path(req.output_root).rglob("*.partial"))


def test_completed_image_paths_are_stable_through_completion_and_manifest(tmp_path):
    req = request(tmp_path)
    events = []

    def emit(event):
        if event["kind"] == "output":
            assert Path(event["path"]).is_file()
        events.append(event)

    result = extract(req, bundle([picture()]), emit)
    assert [event["kind"] for event in events] == ["progress", "output", "object_complete"]
    assert result.outputs[0]["path"] == events[1]["path"]
    assert Path(events[1]["path"]).parent == Path(req.output_root)
    manifest = json.loads((Path(req.output_root) / "extraction-result.json").read_text("utf-8"))
    assert manifest["outputs"] == result.outputs


def full_picture_aliases(size=(137, 59)):
    texture = picture(10, "whole", size)
    texture.data.m_Width, texture.data.m_Height = size
    sprite = picture(20, "whole", size, "Sprite")
    sprite.read_typetree = lambda: sprite.tree
    rect = {"x": 0.0, "y": 0.0, "width": float(size[0]), "height": float(size[1])}
    sprite.tree = {"m_Rect": deepcopy(rect), "m_IsPolygon": False, "m_AtlasTags": [],
                   "m_SpriteAtlas": {"m_FileID": 0, "m_PathID": 0},
                   "m_RD": {"texture": {"m_FileID": 0, "m_PathID": 10},
                            "textureRect": deepcopy(rect), "settingsRaw": 64,
                            "textureRectOffset": {"x": 0, "y": 0}, "downscaleMultiplier": 1}}
    return texture, sprite


def test_automatic_full_texture_sprite_alias_is_one_flat_picture_and_completes_both_ids(tmp_path):
    req = request(tmp_path)
    events = []
    result = extract(req, bundle(full_picture_aliases()), events.append)
    assert result.status == "succeeded" and len(result.outputs) == 1
    item = result.outputs[0]
    assert item["object_id"] == "10" and item["image_aliases"] == ["20"]
    assert item["selected_image_count"] == 1 and item["selected_image_object_count"] == 2
    assert Path(item["path"]).parent == Path(req.output_root)
    complete = [event for event in events if event["kind"] == "object_complete"]
    assert len(complete) == 1 and complete[0]["object_ids"] == ["10", "20"]
    from arknights_unpacker.ui.job_history import extraction_completion
    _, completed = extraction_completion([{"events": events}])
    assert completed[str(Path(req.paths[0]).resolve())] == {"10", "20"}


def test_full_alias_plus_an_independent_image_keeps_package_layout(tmp_path):
    req = request(tmp_path)
    result = extract(req, bundle([*full_picture_aliases(), picture(30, "independent")]))
    assert len(result.outputs) == 2
    assert all(item["image_layout"] == "package" and item["selected_image_count"] == 2 for item in result.outputs)


def test_full_alias_can_precede_its_texture_without_losing_completion(tmp_path):
    req = request(tmp_path)
    texture, sprite = full_picture_aliases()
    events = []
    result = extract(req, bundle([sprite, texture]), events.append)
    assert len(result.outputs) == 1 and result.outputs[0]["object_id"] == "10"
    assert events[-1]["object_ids"] == ["10", "20"]


def test_local_sprite_texture_reference_does_not_cross_serialized_files(tmp_path):
    req = request(tmp_path)
    texture, sprite = full_picture_aliases()
    texture.assets_file = object()
    sprite.assets_file = object()
    result = extract(req, bundle([texture, sprite]))
    assert len(result.outputs) == 2


def test_cancelled_alias_output_does_not_complete_either_object(tmp_path):
    req = request(tmp_path)
    token = CancelToken()
    events = []

    def emit(event):
        events.append(event)
        if event["kind"] == "output":
            token.cancel()

    result = extract(req, bundle(full_picture_aliases()), emit, token)
    assert result.status == "cancelled" and len(result.outputs) == 1
    assert not any(event["kind"] == "object_complete" for event in events)
    from arknights_unpacker.ui.job_history import extraction_completion
    sources, completed = extraction_completion([{"events": events, "result": vars(result)}])
    assert not sources and not completed


@pytest.mark.parametrize("condition", ["crop", "rotation", "atlas", "pixels", "external", "polygon"])
def test_cropped_rotated_atlas_or_different_sprite_is_not_discarded(tmp_path, condition):
    req = request(tmp_path)
    texture, sprite = full_picture_aliases()
    if condition == "crop":
        sprite.tree["m_RD"]["textureRect"]["width"] = 30
        sprite.tree["m_Rect"]["width"] = 30
        sprite.data.image = sprite.data.image.crop((0, 0, 30, 59))
    elif condition == "rotation":
        sprite.tree["m_RD"]["settingsRaw"] = 69
    elif condition == "atlas":
        sprite.tree["m_SpriteAtlas"]["m_PathID"] = 99
    elif condition == "pixels":
        sprite.data.image.putpixel((0, 0), (255, 255, 255, 0))
    elif condition == "external":
        sprite.tree["m_RD"]["texture"]["m_FileID"] = 1
    else:
        sprite.tree["m_IsPolygon"] = True
    result = extract(req, bundle([texture, sprite]))
    assert result.status == "succeeded" and len(result.outputs) == 2
    assert {item["object_id"] for item in result.outputs} == {"10", "20"}


@pytest.mark.parametrize("selection,expected", [(["20"], {"20"}), (["10", "20"], {"10", "20"})])
def test_explicit_sprite_object_selection_is_respected(tmp_path, selection, expected):
    req = request(tmp_path, selected=selection)
    result = extract(req, bundle(full_picture_aliases()))
    assert {item["object_id"] for item in result.outputs} == expected
    assert all(item["image_size"] == [137, 59] for item in result.outputs)


def test_raw_full_texture_and_sprite_keep_both_serialized_objects(tmp_path):
    req = request(tmp_path)
    req.mode = "raw"
    result = extract(req, bundle(full_picture_aliases()))
    assert len(result.outputs) == 2
    assert all(item["kind"] == "image_serialized" for item in result.outputs)
