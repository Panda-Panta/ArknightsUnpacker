from pathlib import Path

import pytest

from arknights_unpacker.contracts import CancelToken, CancelledError, GameInstallation, ResolvedResource, ResourceCatalog


ROOT = "game"
MAIN = "gamedata/levels/obt/main/level_main_00-01"
SIDE = "gamedata/levels/activities/act55side/level_act55side_01"
ROGUE = "gamedata/levels/obt/roguelike/ro6/dlc1/level_rogue6_b-3_dlc1"
AUTOCHESS = "gamedata/levels/activities/act3autochess/level_act3autochess_m12/level_act3autochess_m12_sub_03"


def _sources(*rows):
    index = {"assets": [
        {"assetName": logical, "bundle": bundle} for logical, bundle, _ in rows
    ]}
    catalog = ResourceCatalog(GameInstallation(Path(ROOT), "profile"), resources={
        bundle: ResolvedResource(bundle, path) for _, bundle, path in rows
    })
    return index, catalog


def test_catalog_classifies_exact_levels_and_keeps_unavailable_rows():
    from arknights_unpacker.extraction.level_catalog import build_level_catalog

    index, catalog = _sources(
        (MAIN, "main.bin", "installed-main"),
        (SIDE, "side.bin", "installed-side"),
        (ROGUE, "rogue.bin", None),
        (AUTOCHESS, "active.bin", "installed-activity"),
        ("gamedata/levels/enemydata/enemy_database", "enemies.bin", "installed-enemies"),
        ("gamedata/levels/levels_meta", "meta.bin", "installed-meta"),
        ("battle/prefabs/level_main_00-01", "prefab.bin", "installed-prefab"),
    )
    result = build_level_catalog(ROOT, "A", index, catalog, None, CancelToken())
    levels = {row["id"]: row for row in result["levels"]}
    assert {key: row["category"] for key, row in levels.items()} == {
        MAIN: "主线", SIDE: "支线", ROGUE: "集成战略", AUTOCHESS: "特殊活动",
    }
    assert levels[MAIN]["name"] == "main_00-01"
    assert not levels[ROGUE]["available"]
    assert all(not row["is_new"] for row in levels.values())
    assert result["root"] == ROOT and result["resource_version"] == "A"


def test_logical_additions_are_new_and_repeat_keeps_labels():
    from arknights_unpacker.extraction.level_catalog import build_level_catalog

    first_index, first_catalog = _sources((MAIN, "old.bin", "original-main"))
    first = build_level_catalog(ROOT, "A", first_index, first_catalog, None, CancelToken())
    next_index, next_catalog = _sources(
        (MAIN, "changed.bin", "moved-main"),
        (SIDE, "new.bin", None),
    )
    second = build_level_catalog(ROOT, "B", next_index, next_catalog, first, CancelToken())
    same_version = build_level_catalog(ROOT, "A", next_index, next_catalog, first, CancelToken())
    repeated = build_level_catalog(ROOT, "B", next_index, next_catalog, second, CancelToken())
    third = build_level_catalog(ROOT, "C", next_index, next_catalog, repeated, CancelToken())
    other_root = build_level_catalog("another", "B", next_index, next_catalog, first, CancelToken())
    assert [row["id"] for row in second["levels"] if row["is_new"]] == [SIDE]
    assert [row["id"] for row in same_version["levels"] if row["is_new"]] == [SIDE]
    assert repeated == second
    assert not any(row["is_new"] for row in third["levels"])
    assert not any(row["is_new"] for row in other_root["levels"])


def test_untrustworthy_or_empty_index_cannot_replace_previous_catalog():
    from arknights_unpacker.extraction.level_catalog import build_level_catalog

    conflicting, catalog = _sources((MAIN, "one.bin", "path1"), (MAIN, "two.bin", "path2"))
    for index in ({}, {"assets": []}, conflicting):
        result = build_level_catalog(ROOT, "A", index, catalog, None, CancelToken())
        assert not result["levels"]
        assert result["diagnostics"]


def test_missing_bundle_and_suffix_alias_are_distinguished():
    from arknights_unpacker.extraction.level_catalog import build_level_catalog

    index, catalog = _sources((MAIN, "one.bin", "path1"), (SIDE, "two.bin", "path2"))
    index["assets"][0]["bundle"] = "one"
    index["assets"][1]["bundle"] = "unbound"
    levels = build_level_catalog(ROOT, "A", index, catalog, None, CancelToken())
    assert {row["id"]: row["available"] for row in levels["levels"]} == {MAIN: True, SIDE: False}
    assert any("绑定" in message for message in levels["diagnostics"])


def test_catalog_preserves_cancellation():
    from arknights_unpacker.extraction.level_catalog import build_level_catalog

    token = CancelToken()
    token.cancel()
    index, catalog = _sources((MAIN, "one.bin", "path"))
    with pytest.raises(CancelledError):
        build_level_catalog(ROOT, "A", index, catalog, None, token)
