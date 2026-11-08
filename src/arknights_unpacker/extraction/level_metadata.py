"""Resolve display labels from the active PC tables, keyed by indexed level paths."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re
import struct

from flatbuffers.table import Table

from ..contracts import CancelToken, null_progress
from .decoder import schema
from .level_catalog import is_level_path
from .tables import load_local_tables


def _text(value: bytes | None) -> str | None:
    return (value.decode("utf-8").strip() or None) if value else None


def _root(raw, name):
    if len(raw) < 132:
        raise ValueError(f"关卡表 {name} 缺少 FlatBuffers 数据")
    return schema(name).ROOT_TYPE.GetRootAs(raw[128:])


def _entries(root, field, check, *, optional=False):
    count = getattr(root, field + "Length")()
    if count > 100_000 or count < 0 or (not count and not optional):
        raise ValueError(f"关卡表的 {field} 字典尺寸无效")
    getter = getattr(root, field)
    for i in range(count):
        check()
        yield getter(i)


def _records(root, field, identity, project, check):
    records = {}
    for entry in _entries(root, field, check):
        key = _text(entry.Key())
        value = entry.Value()
        if not key or key in records or value is None or _text(getattr(value, identity)()) != key:
            raise ValueError(f"关卡表的 {field} 键与数据标识不一致")
        records[key] = project(value)
    return records


def _read_stages(raw, check):
    # Only read the stable StageData fields. Other stage_table fields shifted in PC.
    return _records(_root(raw, "stage_table"), "Stages", "StageId", lambda row: {
        **_level_fields(row),
        "zone_id": _text(row.ZoneId()),
        "difficulty": row.Difficulty(),
    }, check)


def _level_fields(row):
    return {"level_id": _text(row.LevelId()), "code": _text(row.Code()), "title": _text(row.Name())}


def _join_labels(*labels):
    return " · ".join(dict.fromkeys(label for label in labels if label)) or None


def _read_zones(raw, check):
    return _records(
        _root(raw, "zone_table"), "Zones", "ZoneId",
        lambda row: _join_labels(_text(row.ZoneNameFirst()), _text(row.ZoneNameSecond())),
        check,
    )


def _read_activities(raw, check):
    root = _root(raw, "activity_table")
    names = _records(root, "BasicInfo", "Id", lambda row: _text(row.Name()), check)
    zones = {}
    for entry in _entries(root, "ZoneToActivity", check, optional=True):
        key, activity_id = _text(entry.Key()), _text(entry.Value())
        if not key or not activity_id or key in zones:
            raise ValueError("活动表的分区绑定无效")
        zones[key] = activity_id
    return {"names": names, "zones": zones}


def _read_rogue_topics(raw, check):
    # The root Topics vector is independent of the vendor's newer Details layouts.
    root = _root(raw, "roguelike_topic_table")
    topics = _records(root, "Topics", "Id", lambda row: _text(row.Name()), check)
    detail_type = schema("roguelike_topic_table").clz_Torappu_RoguelikeTopicDetail
    levels = []
    try:
        for entry in _entries(root, "Details", check, optional=True):
            topic_id = _text(entry.Key())
            source = entry._tab
            offset = source.Offset(6)
            if not offset or topic_id not in topics:
                raise ValueError("主题详情与主题索引不一致")
            # A generated game field named Init shadows this class's constructor helper.
            detail = detail_type()
            detail._tab = Table(source.Bytes, source.Indirect(source.Pos + offset))
            records = _records(detail, "Stages", "Id", _level_fields, check)
            levels.extend({**record, "chapter_id": topic_id} for record in records.values())
    except (ValueError, IndexError, struct.error) as error:
        return {"topics": topics, "levels": [], "diagnostics": [f"集成战略关卡标题不可用：{error}"]}
    return {"topics": topics, "levels": levels, "diagnostics": []}


def _read_towers(raw, check):
    root = _root(raw, "climb_tower_table")
    names = _records(root, "Towers", "Id", lambda row: _text(row.Name()), check)
    levels = _records(root, "Levels", "Id", lambda row: {
        **_level_fields(row), "chapter_id": _text(row.TowerId()),
    }, check)
    return {"names": names, "levels": list(levels.values())}


_READERS = {
    "stage_table": _read_stages,
    "zone_table": _read_zones,
    "activity_table": _read_activities,
    "roguelike_topic_table": _read_rogue_topics,
    "climb_tower_table": _read_towers,
}


def _level_path(level_id):
    if not level_id:
        return None
    path = "gamedata/levels/" + level_id.casefold()
    return path if is_level_path(path) else None


def _choose_stage(entries, path):
    # Multiple UI stages can share a map. Keep the normal, named record when present.
    basename = path.rsplit("/", 1)[-1].removeprefix("level_")
    _, stage = min(entries, key=lambda item: (
        not bool(item[1]["code"]), item[1]["difficulty"] != 1, "#" in item[0],
        item[0] != basename, not bool(item[1]["title"]), item[0],
    ))
    return stage


def _assemble(stages, zones, activities, rogue_topics, check):
    activity_names = activities.get("names", {})
    zone_activities = activities.get("zones", {})
    by_path = defaultdict(list)
    for stage_id, stage in stages.items():
        check()
        if (path := _level_path(stage["level_id"])) is not None:
            by_path[path].append((stage_id, stage))

    levels = {}
    for path, entries in by_path.items():
        check()
        stage = _choose_stage(entries, path)
        zone_id = stage["zone_id"]
        activity_id = zone_activities.get(zone_id)
        activity_name, zone_name = activity_names.get(activity_id), zones.get(zone_id)
        chapter = _join_labels(activity_name, zone_name)
        chapter_id = activity_id if activity_name and not zone_name else zone_id
        levels[path] = {
            "name": stage["title"], "code": stage["code"], "title": stage["title"],
            "chapter_id": chapter_id, "chapter": chapter,
        }

    chapters = {
        f"gamedata/levels/activities/{key}/": {"chapter_id": key, "chapter": name}
        for key, name in activity_names.items() if name and re.fullmatch(r"[a-z0-9_-]+", key)
    }
    for key, name in rogue_topics.items():
        match = re.fullmatch(r"rogue_([0-9]+)", key)
        if match and name:
            chapters[f"gamedata/levels/obt/roguelike/ro{match[1]}/"] = {"chapter_id": key, "chapter": name}
    return levels, chapters


def _enrich_mode_levels(levels, records, chapter_names, check):
    for row in records:
        check()
        path = _level_path(row["level_id"])
        if path is None:
            continue
        chapter_id = row["chapter_id"]
        current = levels.setdefault(path, {"chapter_id": chapter_id, "chapter": None})
        if not current.get("chapter") and chapter_names.get(chapter_id):
            current.update(chapter_id=chapter_id, chapter=chapter_names[chapter_id])
        if not current.get("title") and not current.get("code"):
            current.update(name=row["title"], title=row["title"], code=row["code"])


def load_level_metadata(root, resource_version, *, emit=null_progress, cancel=None):
    """Load optional map labels for the version already selected by the index scan."""
    cancel = cancel or CancelToken()

    def decode(raw, name):
        return _READERS[name](raw, cancel.check), {"format": "level_metadata_flatbuffers"}

    result = load_local_tables(
        Path(root), None, emit, cancel, names=set(_READERS),
        decoders=dict.fromkeys(_READERS, decode), expected_resource_version=resource_version,
    )
    tables = {key: record.data for key, record in result.tables.items()}
    rogue = tables.get("roguelike_topic_table", {})
    tower = tables.get("climb_tower_table", {})
    levels, chapters = _assemble(
        tables.get("stage_table", {}), tables.get("zone_table", {}),
        tables.get("activity_table", {}), rogue.get("topics", {}), cancel.check,
    )
    _enrich_mode_levels(levels, rogue.get("levels", []), rogue.get("topics", {}), cancel.check)
    _enrich_mode_levels(levels, tower.get("levels", []), tower.get("names", {}), cancel.check)
    diagnostics = [*result.diagnostics, *rogue.get("diagnostics", [])]
    missing = sorted(_READERS.keys() - tables.keys())
    if missing:
        diagnostics.append("关卡元数据表不可用：" + "、".join(missing))
    return {"resource_version": result.resource_version, "levels": levels,
            "chapters": chapters, "diagnostics": diagnostics}
