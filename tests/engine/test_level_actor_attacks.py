from struct import pack

from arknights_unpacker.extraction.level_actor_attacks import _periodic_profile, spine_animation_durations


def test_spine_binary_duration_uses_big_endian_frame_times():
    header = b"\x01\x073.8.99" + bytes(16) + b"\0"
    empty_skeleton = bytes(9)
    # One animation with one draw-order keyframe at 1.75 seconds.
    animation = b"\x01\x06Skill" + bytes(6) + b"\x01" + pack(">f", 1.75) + b"\0\0"

    assert spine_animation_durations(header + empty_skeleton + animation, False) == {"Skill": 1.75}


def test_periodic_profile_resets_cooldown_after_clip_and_requires_targetless_cast():
    timing = ("Roar", 5.0, 2.0)
    skill = {"_maxTriggerTime": -1, "_familyMask": 3, "_overwriteInitCooldown": 3}
    ability = {"_allowNoTarget": True, "_timeMode": 1, "_animKey": "Skill"}
    durations = {"Skill": 1.5}

    def resolve(clip):
        return {"clip": clip, "speed": 1.0, "loop": False}

    assert _periodic_profile(timing, skill, ability, resolve, durations) == {
        "clip": "Skill", "clipSpeed": 1.0, "firstAt": 3, "interval": 6.5, "duration": 1.5,
    }
    assert _periodic_profile(timing, skill, {**ability, "_allowNoTarget": False},
                             resolve, durations) is None


def test_channeling_preserves_authored_begin_and_end_and_loops_in_between():
    timing = ("FourDirAttack", 20.0, 10.0)
    skill = {"_maxTriggerTime": -1, "_familyMask": 3}
    ability = {"_allowNoTarget": True, "_timeMode": 2, "_cooldown": 5, "_preDelay": 3}
    bundle = {"beginAnim": "Skill_Begin", "loopAnim": "Skill_Loop", "endAnim": "Skill_End"}
    durations = {"Skill_Begin": 0.5, "Skill_Loop": 1.0, "Skill_End": 1.5}

    def resolve(clip):
        return {"clip": clip, "speed": 1.0, "loop": clip == "Skill_Loop"}

    profile = _periodic_profile(timing, skill, ability, resolve, durations, {"_default": bundle})

    assert profile == {
        "clip": "Skill_Begin", "clipSpeed": 1.0, "firstAt": 10.0, "interval": 25.0, "duration": 5,
        "phases": [
            {"clip": "Skill_Begin", "clipSpeed": 1.0, "loop": False, "start": 0},
            {"clip": "Skill_Loop", "clipSpeed": 1.0, "loop": True, "start": 0.5},
            {"clip": "Skill_End", "clipSpeed": 1.0, "loop": False, "start": 3.5},
        ],
    }
