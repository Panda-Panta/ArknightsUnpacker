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
