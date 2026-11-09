"""Apply statically verifiable indicator effects to a copy of LevelData."""
from collections.abc import Collection
from copy import deepcopy
from math import isfinite
import re


_GROUP_ENABLE = "level_hidden_group_enable"
_GROUP_DISABLE = "level_hidden_group_disable"
_ENEMY_REPLACE = "level_enemy_replace"
_FORBID_LOCATION = "global_forbid_location"
_ENEMY_ACTIONS = {0, 1, 5}  # SPAWN, PREVIEW_CURSOR, DISPLAY_ENEMY_INFO
_ENEMY_ID = re.compile(r"enemy_[a-z0-9_]+")
_LOCATION = re.compile(r"\(\s*([0-9]{1,6})\s*,\s*([0-9]{1,6})\s*\)")
_ENEMY_ATTRIBUTE_EFFECTS = {"enemy_attribute_add", "enemy_attribute_additive_mul", "enemy_attribute_mul"}
_COMBAT_ATTRIBUTES = {"max_hp", "atk", "def", "magic_resistance", "atk_speed", "base_attack_time", "taunt_level"}
_DEPLOYMENT_EFFECTS = {"global_placable_char_num_add": "value", "global_cost_recovery_mul": "scale",
                       "char_respawntime_add": "value", "char_cost_add": "value"}
_POLLUTION_DAMAGE = {"polluted_damage_low", "polluted_damage_high"}
_POLLUTION_TALENT_DAMAGE = {f"{talent}.{field}" for talent in ("polluteddie", "pollutedarea")
                            for field in _POLLUTION_DAMAGE}


def _selected_tags(tags, selected_ids):
    selected = set(selected_ids)
    unknown = selected.difference(tag["id"] for tag in tags)
    if unknown:
        raise ValueError(f"未知指标：{', '.join(sorted(unknown))}")

    active = []
    selected_groups = set()
    required_groups = set()
    for tag in sorted(tags, key=lambda item: item["sort"]):
        tag_id, group = tag["id"], tag.get("group")
        if tag.get("required"):
            if group:
                required_groups.add(group)
            elif tag_id not in selected:
                raise ValueError(f"缺少必选指标：{tag_id}")
        if tag_id not in selected:
            continue
        if group:
            if group in selected_groups:
                raise ValueError(f"同组指标只能选一项：{group}")
            selected_groups.add(group)
        active.append(tag)
    missing = required_groups - selected_groups
    if missing:
        raise ValueError(f"缺少必选指标组：{', '.join(sorted(missing))}")
    return active


def _validate_indicator_graph(graph, active):
    selected = {tag['id'] for tag in active}
    for tag in active:
        if selected.intersection(tag.get('excludes') or ()):
            raise ValueError(f"存在互斥指标：{tag['name']}。")
    nodes = graph['nodes']
    reachable = set(graph['start_ids'])
    pending = list(reachable)
    while pending:
        for adjacent in nodes[pending.pop()]['adjacent']:
            if adjacent in selected and adjacent not in reachable:
                reachable.add(adjacent)
                pending.append(adjacent)
    disconnected = [tag['name'] for tag in active if tag['id'] not in reachable]
    if disconnected:
        raise ValueError('所选指标尚未连接到赛季起点：' + '、'.join(disconnected))


def _action_phases(level):
    for wave in level.get("waves") or ():
        yield from wave.get("fragments") or ()
    for branch in (level.get("branches") or {}).values():
        yield from branch.get("phases") or ()


def _locations(value, grid):
    # In H11-1's 8×12 grid, the second axis reaches 10.
    positions = []
    for token in value.split("|"):
        match = _LOCATION.fullmatch(token.strip())
        if match is None:
            return None
        row, col = map(int, match.groups())
        if row >= (grid.get("rowSize") or 0) or col >= (grid.get("columnSize") or 0):
            return None
        positions.append((row, col))
    return positions


def _replay_arguments(effect):
    result = {}
    for row in effect.get("blackboard") or ():
        field = row["key"].lower()
        if field in result:
            return None
        text = row.get("valueStr")
        result[field] = row.get("value") if text is None else text
    return result


def _finite_number(value):
    return type(value) in {int, float} and isfinite(value)


def _finite_values(arguments):
    return bool(arguments) and all(_finite_number(value) for value in arguments.values())


def _enemy_targets(value):
    if not isinstance(value, str):
        return ()
    targets = tuple(dict.fromkeys(value.split("|")))
    return targets if all(_ENEMY_ID.fullmatch(target) for target in targets) else ()


def _combat_only_replay_effect(key, arguments):
    """Identify verified effects outside unopposed spawn and movement playback."""
    if key == "char_attribute_mul":
        values = {name: value for name, value in arguments.items() if name != "char"}
        return values.keys() <= _COMBAT_ATTRIBUTES and _finite_values(values)
    if key in _DEPLOYMENT_EFFECTS:
        return arguments.keys() == {_DEPLOYMENT_EFFECTS[key]} and _finite_values(arguments)
    if key == "enemy_attackradius_mul":
        return arguments.keys() <= {"enemy", "scale"} and _finite_number(arguments.get("scale"))
    if key == "env_gbuff_new_with_verify":
        buff = arguments.get("key")
        if buff in {"enemy_damage_scale[phy][additive]", "enemy_damage_scale[mag][additive]"}:
            return arguments.keys() == {"key", "damage_scale"} and _finite_number(arguments["damage_scale"])
        if buff == "recalv2_chara_polluted_ep_damage":
            return (arguments.keys() == {"key", "ep_damage", "modifier_custom_key"}
                    and arguments["modifier_custom_key"] == "is_enemy_polluted_t"
                    and _finite_number(arguments["ep_damage"]))
    if key == "enemy_talent_blackb_mul":
        return arguments.keys() <= _POLLUTION_TALENT_DAMAGE and _finite_values(arguments)
    if key == "enemy_skill_blackb_mul":
        values = {name: value for name, value in arguments.items() if name not in {"enemy", "skill"}}
        if not _finite_values(values):
            return False
        if arguments.get("skill") == "PollutedRangedAtk":
            return values.keys() <= _POLLUTION_DAMAGE
        # The scout's Awake only raises attack after it receives damage.
        targets = _enemy_targets(arguments.get("enemy"))
        return (arguments.get("skill") == "Awake" and values.keys() == {"atk"} and bool(targets)
                and all(target == "enemy_1073_dscout" or target.startswith("enemy_1073_dscout_")
                        for target in targets))
    return False


def _classify_replay_effect(effect, label):
    arguments = _replay_arguments(effect)
    if arguments is None:
        return None, False
    key = effect.get("key")
    if key in _ENEMY_ATTRIBUTE_EFFECTS:
        values = {name: value for name, value in arguments.items() if name != "enemy"}
        if not _finite_values(values) or not values.keys() <= _COMBAT_ATTRIBUTES | {"move_speed"}:
            return None, False
        if "move_speed" not in values:
            return None, True
        targets = _enemy_targets(arguments.get("enemy"))
        factor = values["move_speed"]
        if key != "enemy_attribute_mul" or not targets or factor <= 0:
            return None, False
        return {"enemy_ids": targets, "factor": factor, "source": label}, len(values) > 1
    return None, _combat_only_replay_effect(key, arguments)


def apply_replay_move_speeds(actors, modifiers):
    """Apply explicit selected enemy movement multipliers without changing source configs."""
    changed = dict(actors)
    sources = {}
    for modifier in modifiers:
        for enemy_id in modifier["enemy_ids"]:
            if enemy_id not in actors:
                continue
            if enemy_id in sources:
                raise ValueError(f"{enemy_id}：存在多条移动速度指标，叠加规则待验证。"
                                 f"{sources[enemy_id]}、{modifier['source']}。")
            sources[enemy_id] = modifier["source"]
            speed = actors[enemy_id].get("moveSpeed")
            if not _finite_number(speed) or speed <= 0:
                raise ValueError(f"{enemy_id}：缺少可应用指标的原始移动速度。")
            modified = speed * modifier["factor"]
            if not isfinite(modified) or modified <= 0:
                raise ValueError(f"{enemy_id}：指标应用后的移动速度无效。")
            changed[enemy_id] = {**actors[enemy_id], "moveSpeed": modified}
    return changed


def apply_level_tags(level: dict, tags: list[dict], selected_ids: Collection[str], *, graph=None,
                     no_deployment=False) -> dict:
    """Return a copied level, selected IDs, changes and unsupported effects.

    Apply effects in tag sort order. A later command for the same hidden group
    overrides the earlier command, as when a challenge disables the base group.
    Invalid combinations raise ValueError before any effects are evaluated.
    Unopposed playback may defer verified combat-only effects and collect
    movement multipliers for application after reading the original enemy data.
    """
    active = _selected_tags(tags, selected_ids)
    if graph is not None:
        _validate_indicator_graph(graph, active)
    variant = deepcopy(level)
    groups = {}
    replacements = {}
    unapplied = []
    not_simulated = []
    move_speed_modifiers = []
    changes = dict(enabled_groups=0, disabled_groups=0, enabled_actions=0,
                   disabled_actions=0, replaced_actions=0, forbidden_tiles=0)
    grid = (variant.get("mapData") or {}).get("map") or {}
    forbidden = variant.get("tilesDisallowToLocate") or []
    occupied = {(position["row"], position["col"]) for position in forbidden}

    for tag in active:
        for effect in tag["effects"]:
            key = effect.get("key") or "未知指令"
            label = f"{tag['id']} · {key}"
            if not effect.get("statically_applicable"):
                if no_deployment:
                    modifier, combat_only = _classify_replay_effect(effect, label)
                    if modifier is not None:
                        move_speed_modifiers.append(modifier)
                    if combat_only:
                        not_simulated.append(f"{label}：无部署回放不模拟此战斗或部署效果。")
                    if modifier is not None or combat_only:
                        continue
                unapplied.append(f"{label}：预览未实现。")
                continue
            arguments = {
                row["key"]: row["valueStr"] for row in effect.get("blackboard") or ()
                if isinstance(row.get("valueStr"), str)
            }
            source = arguments.get("key", "")
            if key in {_GROUP_ENABLE, _GROUP_DISABLE} and source:
                groups[source] = (key == _GROUP_ENABLE, label)
            elif key == _ENEMY_REPLACE:
                target = arguments.get("value", "")
                if _ENEMY_ID.fullmatch(source) and _ENEMY_ID.fullmatch(target) and source != target:
                    replacements[source] = (target, label)
                else:
                    unapplied.append(f"{label}：敌人替换参数无效。")
            elif key == _FORBID_LOCATION:
                positions = _locations(arguments.get("location", ""), grid)
                if positions is None:
                    unapplied.append(f"{label}：禁部署坐标无法确认。")
                    continue
                for row, col in positions:
                    if (row, col) not in occupied:
                        occupied.add((row, col))
                        forbidden.append({"row": row, "col": col})
                        changes["forbidden_tiles"] += 1
            else:
                unapplied.append(f"{label}：预览未实现或缺少参数。")

    if changes["forbidden_tiles"]:
        variant["tilesDisallowToLocate"] = forbidden

    matched_groups = set()
    matched_replacements = set()
    if groups or replacements:
        for phase in _action_phases(variant):
            actions = phase.get("actions")
            if not actions:
                continue
            kept = []
            for action in actions:
                group = action.get("hiddenGroup")
                if group in groups:
                    matched_groups.add(group)
                    if not groups[group][0]:
                        changes["disabled_actions"] += 1
                        continue
                    action["hiddenGroup"] = None
                    changes["enabled_actions"] += 1
                source = action.get("key")
                if source in replacements and action.get("actionType") in _ENEMY_ACTIONS:
                    action["key"] = replacements[source][0]
                    matched_replacements.add(source)
                    changes["replaced_actions"] += 1
                kept.append(action)
            phase["actions"] = kept

    for group, (enabled, label) in groups.items():
        if group in matched_groups:
            changes["enabled_groups" if enabled else "disabled_groups"] += 1
        else:
            unapplied.append(f"{label}：关卡未找到敌群 {group}。")
    for source, (_, label) in replacements.items():
        if source not in matched_replacements:
            unapplied.append(f"{label}：关卡未找到可替换动作 {source}。")

    return {"level": variant, "selected_ids": [tag["id"] for tag in active],
            "changes": changes, "unapplied": list(dict.fromkeys(unapplied)),
            "not_simulated": list(dict.fromkeys(not_simulated)), "move_speed_modifiers": move_speed_modifiers}
