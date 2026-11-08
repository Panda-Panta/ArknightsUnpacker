"""Apply statically verifiable RecalRune effects to a copy of LevelData."""
from collections.abc import Collection
from copy import deepcopy
import re


_GROUP_ENABLE = "level_hidden_group_enable"
_GROUP_DISABLE = "level_hidden_group_disable"
_ENEMY_REPLACE = "level_enemy_replace"
_FORBID_LOCATION = "global_forbid_location"
_ENEMY_ACTIONS = {0, 1, 5}  # SPAWN, PREVIEW_CURSOR, DISPLAY_ENEMY_INFO
_ENEMY_ID = re.compile(r"enemy_[a-z0-9_]+")
_LOCATION = re.compile(r"\(\s*([0-9]{1,6})\s*,\s*([0-9]{1,6})\s*\)")


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


def apply_level_tags(level: dict, tags: list[dict], selected_ids: Collection[str]) -> dict:
    """Return a copied level, selected IDs, changes and unsupported effects.

    Apply effects in tag sort order. A later command for the same hidden group
    overrides the earlier command, as when a challenge disables the base group.
    Invalid combinations raise ValueError before any effects are evaluated.
    """
    active = _selected_tags(tags, selected_ids)
    variant = deepcopy(level)
    groups = {}
    replacements = {}
    unapplied = []
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
            "changes": changes, "unapplied": list(dict.fromkeys(unapplied))}
