from copy import deepcopy

import pytest

from arknights_unpacker.extraction.level_variants import apply_level_tags, apply_replay_move_speeds


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


def test_crisis_indicators_need_one_connected_path_and_respect_exclusions():
    tags = [
        {**_tag("left"), "name": "左路", "excludes": ["right"]},
        {**_tag("right"), "name": "右路"},
        {**_tag("goal"), "name": "终点"},
    ]
    graph = {"start_ids": ["start"], "nodes": {
        "start": {"adjacent": ["left", "right"]},
        "left": {"adjacent": ["start", "goal"]},
        "right": {"adjacent": ["start", "goal"]},
        "goal": {"adjacent": ["left", "right"]},
    }}

    assert apply_level_tags({}, tags, ["right", "goal"], graph=graph)["selected_ids"] == ["right", "goal"]
    with pytest.raises(ValueError, match="未连接"):
        apply_level_tags({}, tags, ["goal"], graph=graph)
    with pytest.raises(ValueError, match="互斥"):
        apply_level_tags({}, tags, ["left", "right"], graph=graph)


def _runtime_effect(effect_key, **values):
    return {"key": effect_key, "statically_applicable": False, "blackboard": [
        {"key": field, "value": 0.0 if isinstance(value, str) else value,
         "valueStr": value if isinstance(value, str) else None}
        for field, value in values.items()
    ]}


def test_no_deployment_replay_applies_targeted_move_speed_and_preserves_other_effects():
    tag = _tag("combat")
    tag["effects"] = [
        _runtime_effect("enemy_attribute_mul", enemy="enemy_kodo|enemy_scout", move_speed=1.8),
        _runtime_effect("enemy_attribute_additive_mul", max_hp=0.2),
        _runtime_effect("env_gbuff_new_with_verify", key="enemy_damage_scale[phy][additive]", damage_scale=-0.25),
    ]
    original = {"enemy_kodo": {"moveSpeed": 0.5, "clip": "Walk"}, "enemy_other": {"moveSpeed": 1.0}}
    assert len(apply_level_tags({}, [tag], ["combat"])["unapplied"]) == 3

    result = apply_level_tags({}, [tag], ["combat"], no_deployment=True)
    assert result["unapplied"] == []
    assert result["selected_ids"] == ["combat"]
    assert len(result["not_simulated"]) == 2
    assert apply_replay_move_speeds(original, result["move_speed_modifiers"]) == {
        "enemy_kodo": {"moveSpeed": pytest.approx(0.9), "clip": "Walk"},
        "enemy_other": {"moveSpeed": 1.0},
    }
    assert original["enemy_kodo"]["moveSpeed"] == 0.5


def test_no_deployment_does_not_accept_unknown_buffs_or_movement_effects():
    tag = _tag("unknown")
    tag["effects"] = [
        _runtime_effect("enemy_attribute_additive_mul", enemy="enemy_test", move_speed=0.2),
        _runtime_effect("env_gbuff_new_with_verify", key="environment_unknown", damage_scale=1),
        _runtime_effect("enemy_skill_blackb_mul", enemy="enemy_test", skill="Unknown", atk=2),
    ]
    result = apply_level_tags({}, [tag], ["unknown"], no_deployment=True)
    assert len(result["unapplied"]) == 3
    assert result["move_speed_modifiers"] == result["not_simulated"] == []


def test_no_deployment_accepts_alternate_deployment_and_combat_choices():
    tag = _tag("alternative")
    tag["effects"] = [
        _runtime_effect("char_respawntime_add", value=200),
        _runtime_effect("char_cost_add", value=25),
        _runtime_effect("char_attribute_mul", char="trap_086_larva", max_hp=3),
        _runtime_effect("env_gbuff_new_with_verify", key="enemy_damage_scale[mag][additive]", damage_scale=-0.25),
    ]
    result = apply_level_tags({}, [tag], ["alternative"], no_deployment=True)
    assert result["unapplied"] == result["move_speed_modifiers"] == []
    assert len(result["not_simulated"]) == 4
