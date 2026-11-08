from copy import deepcopy

import pytest

from arknights_unpacker.extraction.level_variants import apply_level_tags


def _tag(tag_id, *effects, group=None, required=False, sort=0):
    return {
        "id": tag_id, "score": 0, "group": group, "required": required, "sort": sort,
        "effects": [
            {"key": key, "statically_applicable": True, "blackboard": [
                {"key": field, "value": 0.0, "valueStr": value}
                for field, value in args.items()
            ]}
            for key, args in effects
        ],
    }


def test_groups_switch_wave_and_branch_actions_without_touching_routes():
    regular = {"actionType": 0, "key": "enemy_regular", "routeIndex": 7, "preDelay": 1.0}
    original = {"actionType": 6, "key": "trap#1", "hiddenGroup": "route"}
    replacement = {"actionType": 6, "key": "trap#7", "hiddenGroup": "la_dscout"}
    unrelated = {"actionType": 0, "key": "enemy_other", "hiddenGroup": "untouched"}
    branch_action = {"actionType": 0, "key": "enemy_scout", "hiddenGroup": "la_dscout",
                     "routeIndex": 5, "count": 2}
    level = {
        "waves": [{"fragments": [{"actions": [regular, original, replacement, unrelated]}]}],
        "branches": {"scout": {"phases": [{"actions": [branch_action]}]}},
        "routes": [{"startPosition": {"row": 1, "col": 1}}],
        "extraRoutes": [{"endPosition": {"row": 1, "col": 0}}],
    }
    before = deepcopy(level)
    tags = [
        _tag("enemy_skyland_3_a", ("level_hidden_group_enable", {"key": "la_dscout"}),
             ("level_hidden_group_disable", {"key": "route"}), group="skyland", sort=2),
        _tag("base", ("level_hidden_group_enable", {"key": "route"}), required=True),
    ]

    result = apply_level_tags(level, tags, {"base", "enemy_skyland_3_a"})
    changed = result["level"]

    assert result["selected_ids"] == ["base", "enemy_skyland_3_a"]
    assert changed["waves"][0]["fragments"][0]["actions"] == [
        regular, {**replacement, "hiddenGroup": None}, unrelated,
    ]
    assert changed["branches"]["scout"]["phases"][0]["actions"] == [
        {**branch_action, "hiddenGroup": None},
    ]
    assert changed["routes"] == before["routes"]
    assert changed["extraRoutes"] == before["extraRoutes"]
    assert result["changes"]["enabled_groups"] == result["changes"]["disabled_groups"] == 1
    assert result["unapplied"] == []
    assert level == before


def test_enemy_replacement_keeps_route_timing_and_other_action_keys():
    source = "enemy_1034_laxe"
    target = "enemy_1339_bhrgrd"
    spawn = {"actionType": 0, "key": source, "routeIndex": 3, "preDelay": 5.0}
    info = {"actionType": 5, "key": source, "preDelay": 1.0}
    other = {"actionType": 6, "key": source}
    level = {"waves": [{"fragments": [{"actions": [info, spawn, other]}]}],
             "branches": {"extra": {"phases": [{"actions": [spawn.copy()]}]}}}
    tag = _tag("replacement", ("level_enemy_replace", {"key": source, "value": target}),
               ("enemy_attribute_mul", {}))

    result = apply_level_tags(level, [tag], ["replacement"])

    assert result["level"]["waves"][0]["fragments"][0]["actions"] == [
        {**info, "key": target}, {**spawn, "key": target}, other,
    ]
    assert result["level"]["branches"]["extra"]["phases"][0]["actions"] == [{**spawn, "key": target}]
    assert result["changes"]["replaced_actions"] == 3
    assert len(result["unapplied"]) == 1
    assert "enemy_attribute_mul" in result["unapplied"][0]
    assert spawn["key"] == source


def test_forbidden_location_appends_unique_in_bounds_row_column_pairs():
    level = {"mapData": {"map": {"rowSize": 8, "columnSize": 12}},
             "tilesDisallowToLocate": [{"row": 5, "col": 10}]}
    tags = [
        _tag("good", ("global_forbid_location", {"location": "(5,10)|(5,6)"})),
        _tag("bad", ("global_forbid_location", {"location": "(1,2)|(10,5)"})),
    ]

    result = apply_level_tags(level, tags, ["good", "bad"])

    assert result["level"]["tilesDisallowToLocate"] == [{"row": 5, "col": 10}, {"row": 5, "col": 6}]
    assert result["changes"]["forbidden_tiles"] == 1
    assert len(result["unapplied"]) == 1
    assert "global_forbid_location" in result["unapplied"][0]


@pytest.mark.parametrize("selected", [[], ["base"], ["base", "a", "b"], ["base", "a", "unknown"]])
def test_invalid_required_exclusive_or_unknown_selection_is_rejected(selected):
    tags = [_tag("base", required=True), _tag("a", group="one", required=True),
            _tag("b", group="one", required=True)]
    with pytest.raises(ValueError):
        apply_level_tags({}, tags, selected)
    assert apply_level_tags({}, tags, ["base", "b"])["selected_ids"] == ["base", "b"]
