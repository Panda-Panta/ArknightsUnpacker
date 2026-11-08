from pytest import raises

from arknights_unpacker.contracts import CancelledError, CancelToken, ResolvedResource


MAIN = "gamedata/levels/obt/main/level_main_07-16"
CRISIS = "gamedata/levels/obt/crisis/v2/level_crisis_v2_01-01"
PREFAB = "gamedata/levels/activities/act3autochess/level_m01/level_m01_sub_02"
UNMATCHED = "gamedata/levels/activities/act1side/level_main_07-16"


def _entry(level, kind, bundle):
    relative = level.removeprefix("gamedata/levels/")
    folder, extension = ("scenes", "unity") if kind == "scene" else ("battle/prefabs/levelprefabs", "prefab")
    asset = f"{folder}/{relative}/{relative.rsplit('/', 1)[-1]}"
    return {"assetName": asset, "path": f"dyn/{asset}.{extension}", "bundle": bundle}


def test_matches_strict_scene_and_prefab_paths_and_reports_installed_source():
    from arknights_unpacker.extraction.level_scenes import find_level_scenes

    scene = _entry(MAIN, "scene", "main.ab")
    crisis = _entry(CRISIS, "scene", "crisis.ab")
    prefab = _entry(PREFAB, "prefab", "prefab.ab")
    wrong_type = _entry(UNMATCHED, "scene", "main.ab")
    wrong_type["path"] = wrong_type["path"].removesuffix(".unity") + ".prefab"
    index = {"assets": [scene, crisis, prefab, scene.copy(), wrong_type]}
    resources = {
        "main.ab": ResolvedResource("main.ab", "source/main.ab"),
        "crisis.ab": ResolvedResource("crisis.ab", None),
        "prefab.ab.bin": ResolvedResource("prefab.ab.bin", "source/prefab.ab.bin"),
    }

    assert find_level_scenes(index, resources, iter([MAIN, CRISIS, PREFAB, UNMATCHED]), CancelToken()) == {
        MAIN: {"asset": scene["assetName"], "kind": "scene", "bundle": "main.ab", "available": True},
        CRISIS: {"asset": crisis["assetName"], "kind": "scene", "bundle": "crisis.ab", "available": False},
        PREFAB: {"asset": prefab["assetName"], "kind": "prefab", "bundle": "prefab.ab", "available": True},
    }


def test_omits_conflicting_sources_and_honors_cancellation():
    from arknights_unpacker.extraction.level_scenes import find_level_scenes

    index = {"assets": [
        _entry(MAIN, "scene", "first.ab"),
        _entry(MAIN, "scene", "second.ab"),
        _entry(CRISIS, "scene", "crisis.ab"),
        _entry(CRISIS, "prefab", "crisis-prefab.ab"),
    ]}
    cancel = CancelToken()
    assert find_level_scenes(index, {}, [MAIN, CRISIS], cancel) == {}
    cancel.cancel()
    with raises(CancelledError):
        find_level_scenes(index, {}, [], cancel)
