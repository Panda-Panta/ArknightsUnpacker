"""Read repeatable, targetless cast animations from original enemy prefabs."""
import math
from struct import unpack


def spine_animation_durations(payload, is_json):
    from spine_asset.v38 import SkeletonBinary, SkeletonJson

    class ActorSkeletonBinary(SkeletonBinary):
        def _read_animation(self, name, skeleton_data):
            # spine-asset 1.1.1 reads floats as little endian, whereas the original
            # Spine 3.8 binary animation keys use big endian (as does Pixi).
            self._reader.read_float32 = self._read_animation_float
            return super()._read_animation(name, skeleton_data)

        def _read_animation_float(self):
            return unpack(">f", self._reader._stream.read(4))[0]

    skeleton = (SkeletonJson().read_skeleton_data(payload.decode("utf-8"))
                if is_json else ActorSkeletonBinary().read_skeleton_data(payload))
    return {animation.name: animation.duration for animation in skeleton.animations}


def read_single_skill(row):
    """Decode the cooldown of an enemy with one authored skill."""
    if row.SkillsLength() != 1:
        return None
    skill = row.Skills(0)
    key = skill.PrefabKey()
    if not key or skill.SpCost() > 0:
        return None
    cooldown, initial = skill.Cooldown(), skill.InitCooldown()
    if not (math.isfinite(cooldown) and cooldown > 0 and math.isfinite(initial) and initial >= 0):
        return None
    return key.decode(), cooldown, initial


def _skill_node(transform, name):
    for ref in transform.m_Children:
        child = ref.read()
        obj = child.m_GameObject.read()
        if obj.m_Name == name:
            return obj
        if (node := _skill_node(child, name)) is not None:
            return node
    return None


def _mono_type(reader, tree, pointer):
    script = pointer(reader, tree["m_Script"]).read()
    return script.m_ClassName


def _animated_cast(components):
    supported = {"AnimatedActionToOwnerAbility", "AnimatedActionToTargetAbility",
                 "EmptyAnimatedAbility", "MeleeAttack", "RangedAttack", "CrossRangedAttack"}
    casts = [tree for name, (_, tree) in components.items() if name in supported]
    return casts[0] if len(casts) == 1 else None


def _channeling_phases(channeling, duration, resolve_animation, durations):
    # The native coroutine reserves the begin/end durations and plays the
    # looping clip for the rest of the ability's cast time.
    alternate = ("_overrideDownAnimation", "_overrideUpAnimation",
                 "_waitForAttachFinishEvent", "_earlyFinishEndIdleAnimation",
                 "_fireAttackFinishEvent", "_delayToFireAttackSkillEvent", "_fireAnimEndEvent",
                 "_onlyPlayBeginAnimWhenFirstAttack", "_delayToAnimateEndAnimation",
                 "_playIdleAnimInTheEnd")
    if any(channeling.get(key) for key in alternate):
        return None
    bundle = channeling["_default"]
    begin, loop, end = (resolve_animation(bundle[key]) for key in ("beginAnim", "loopAnim", "endAnim"))
    if not (begin and loop and end and not begin["loop"] and loop["loop"] and not end["loop"]):
        return None
    begin_length = durations[begin["clip"]] / begin["speed"]
    end_length = durations[end["clip"]] / end["speed"]
    if not (0 < begin_length < duration - end_length < duration):
        return None
    return [{"clip": clip["clip"], "clipSpeed": clip["speed"], "loop": clip["loop"], "start": start}
            for clip, start in ((begin, 0), (loop, begin_length), (end, duration - end_length))]


def _periodic_profile(timing, skill, ability, resolve_animation, durations, channeling=None):
    _, cooldown, initial = timing
    if (skill.get("_maxTriggerTime") != -1 or skill.get("_checkParentActive")
            or skill.get("_castLikeAttack") or not skill.get("_familyMask", 0) & 2):
        return None
    if (not ability.get("_allowNoTarget") or ability.get("_escapeTime")
            or ability.get("_downAnimKey") or ability.get("_upAnimKey")
            or ability.get("_waitForProjectileInvalid") or ability.get("_fireAttackFinishWhenProjectileInvalid")
            or ability.get("_waitForAnimEndWhenProjectileInvalid")):
        return None
    phases = None
    if channeling is None and ability.get("_timeMode") == 1 and not ability.get("_preDelay"):
        clip = resolve_animation(ability.get("_animKey"))
        if not clip or clip["loop"]:
            return None
        duration = durations[clip["clip"]] / clip["speed"]
        clip_name, clip_speed = clip["clip"], clip["speed"]
    elif channeling is not None and ability.get("_timeMode") == 2 and not ability.get("_animKey"):
        duration = ability["_cooldown"]
        if not 0 <= ability.get("_preDelay", 0) < duration:
            return None
        phases = _channeling_phases(channeling, duration, resolve_animation, durations)
        if phases is None:
            return None
        clip_name, clip_speed = phases[0]["clip"], phases[0]["clipSpeed"]
    else:
        return None
    # EnemySkill::Init uses the serialized overwrite when nonnegative.
    # EnemySkill::_OnCastFinish restarts the full database cooldown.
    overwrite = skill.get("_overwriteInitCooldown", -1)
    interval = duration + cooldown
    if not (math.isfinite(duration) and duration > 0 and math.isfinite(interval) and interval > duration):
        return None
    profile = {"clip": clip_name, "clipSpeed": clip_speed,
               "firstAt": overwrite if overwrite >= 0 else initial,
               "interval": interval, "duration": duration}
    if phases:
        profile["phases"] = phases
    return profile


def periodic_attack(timing, enemy, behaviour, transform, resolve_animation, durations, pointer, components):
    """Read one unconditional cast in combat state from original ability fields."""
    modes = behaviour.get("_modes") or ()
    if not timing or len(modes) != 1 or behaviour.get("_delayToBorn"):
        return None
    mode = pointer(enemy, modes[0]).read_typetree()
    if not mode.get("_combat", {}).get("m_PathID"):
        return None
    node = _skill_node(transform.read(), timing[0])
    if node is None:
        return None
    mono = {}
    for reader in components(node):
        if reader.type.name == "MonoBehaviour":
            tree = reader.read_typetree()
            if tree.get("m_Enabled"):
                mono[_mono_type(reader, tree, pointer)] = reader, tree
    if "EnemySkill" not in mono:
        return None
    reader, skill = mono["EnemySkill"]
    trigger_ref = skill.get("_trigger", {})
    if not trigger_ref.get("m_PathID"):
        return None
    trigger = pointer(reader, trigger_ref)
    trigger_tree = trigger.read_typetree()
    if not trigger_tree.get("m_Enabled") or _mono_type(trigger, trigger_tree, pointer) != "AlwaysTrigger":
        return None
    ability = _animated_cast(mono)
    channeling = mono.get("ThreePartChannelingAnimation", (None, None))[1]
    return _periodic_profile(timing, skill, ability, resolve_animation, durations, channeling) if ability else None
