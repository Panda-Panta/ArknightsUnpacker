"""Read the PC seasonal Stronghold Protocol layout without decoding unrelated activities."""
from __future__ import annotations

from collections import defaultdict
import math
import re
import struct

from .decoder import normalize_flatbuffer, schema


_ACTIVITY_ID = re.compile(r"act\d+v?autochess", re.ASCII)
_SEASON_ID = re.compile(r"V\d+_\d+", re.ASCII)
_MARKUP = re.compile(r"</>|<[@$][\w.-]+>|\{@unlock\}")
_PLACEHOLDER = re.compile(r"\{(\d+):([^{}]+)\}")


class _Table:
    """Bounded access to slots whose layout differs from the pinned CN schema."""

    def __init__(self, data: bytes, position: int):
        if position < 4 or position + 4 > len(data):
            raise ValueError("表偏移无效")
        vtable = position - struct.unpack_from("<i", data, position)[0]
        if vtable < 0 or vtable + 4 > len(data):
            raise ValueError("字段索引偏移无效")
        width, object_size = struct.unpack_from("<HH", data, vtable)
        if width < 4 or width % 2 or vtable + width > len(data) or object_size < 4 or position + object_size > len(data):
            raise ValueError("字段索引尺寸无效")
        self.data, self.position = data, position
        self._vtable, self._width, self._object_size = vtable, width, object_size

    def field(self, slot: int, size: int) -> int | None:
        offset = struct.unpack_from("<H", self.data, self._vtable + slot)[0] if slot < self._width else 0
        if not offset:
            return None
        if offset < 4 or offset + size > self._object_size:
            raise ValueError(f"字段 {slot} 超出表范围")
        return self.position + offset

    def _relative(self, position: int) -> int:
        displacement = struct.unpack_from("<I", self.data, position)[0]
        target = position + displacement
        if displacement < 4 or target + 4 > len(self.data):
            raise ValueError("引用偏移无效")
        return target

    def child(self, slot: int) -> _Table:
        field = self.field(slot, 4)
        if field is None:
            raise ValueError(f"缺少子表字段 {slot}")
        return _Table(self.data, self._relative(field))

    def text(self, slot: int) -> str | None:
        field = self.field(slot, 4)
        if field is None:
            return None
        start = self._relative(field)
        length = struct.unpack_from("<I", self.data, start)[0]
        end = start + 4 + length
        if end >= len(self.data) or self.data[end] != 0:
            raise ValueError(f"文本字段 {slot} 尺寸无效")
        return self.data[start + 4:end].decode("utf-8")

    def number(self, slot: int, fmt: str = "<i", default=None):
        field = self.field(slot, struct.calcsize(fmt))
        return default if field is None else struct.unpack_from(fmt, self.data, field)[0]

    def _vector(self, slot: int) -> range:
        field = self.field(slot, 4)
        if field is None:
            return range(0)
        start = self._relative(field)
        count = struct.unpack_from("<I", self.data, start)[0]
        end = start + 4 + 4 * count
        if end > len(self.data):
            raise ValueError(f"数组字段 {slot} 尺寸无效")
        return range(start + 4, end, 4)

    def tables(self, slot: int):
        return (_Table(self.data, self._relative(position)) for position in self._vector(slot))

    def ints(self, slot: int) -> list[int]:
        return [struct.unpack_from("<i", self.data, position)[0] for position in self._vector(slot)]


def _index(table, slot, check, *, integer=False):
    records = {}
    for entry in table.tables(slot):
        check()
        key = entry.number(4) if integer else entry.text(4)
        if not key or key in records:
            raise ValueError(f"字段 {slot} 的字典键缺失或重复")
        records[key] = entry
    return records


def _records(table, slot, check):
    return {key: entry.child(6) for key, entry in _index(table, slot, check).items()}


def _label(record, key, slot):
    label = record.text(slot)
    if record.text(4) != key or not label:
        raise ValueError(f"记录 {key} 的标识或文本不匹配")
    return label


def _display(text):
    return _MARKUP.sub("", text.replace("\\n", "\n")) if text is not None else None


def _normalize_leaf(table, cls):
    leaf = cls()
    leaf.Init(table.data, table.position)
    return normalize_flatbuffer(leaf)[0]


def _strategies(season, metadata, effects, check):
    result = []
    for key, record in _records(season, 42, check).items():
        check()
        description = _label(record, key, 12)
        effect_id = record.text(16)
        result.append({
            "id": key,
            "name": _label(metadata[key], key, 6),
            "title": _label(effects[effect_id], effect_id, 12),
            "description": _display(description),
            "hp": record.number(14),
            "unlock": _display(metadata[key].text(10)),
        })
    return result


def _scalings(parameters, actions, description, check):
    mappings = list(parameters.tables(4))
    if not mappings:
        return []
    blackboard = defaultdict(set)
    pair_type = schema("activity_table").clz_Torappu_Blackboard_DataPair
    for action in actions.tables(6):
        for pair in action.tables(6):
            check()
            # The pinned DataPair layout still matches this PC leaf.
            key = pair.text(4)
            pair.field(6, 4)
            if key and pair.text(8) is None:
                value = _normalize_leaf(pair, pair_type)["value"]
                if value is not None:
                    blackboard[key].add(value)
    formats = {int(index): spec for index, spec in _PLACEHOLDER.findall(description)}
    result = []
    for index, mapping in enumerate(mappings):
        check()
        base, increment = blackboard[mapping.text(4)], blackboard[mapping.text(6)]
        if len(base) != 1 or len(increment) != 1:
            raise ValueError("盟约动态参数缺少唯一的原始数值")
        cap = mapping.number(8, "<f")
        result.append({
            "index": index,
            "base": next(iter(base)),
            "per_stack": next(iter(increment)),
            "cap": float(format(cap, ".7g")) if cap is not None and math.isfinite(cap) else None,
            "format": formats.get(index),
        })
    return result


def _bonds(season, effects, check):
    parameters = _records(season, 48, check)
    actions = _index(season, 54, check)
    result = []
    for key, record in _records(season, 44, check).items():
        check()
        effect_id = record.text(20)
        parameter = parameters[effect_id]
        description = _display(_label(effects[effect_id], effect_id, 14))
        result.append({
            "id": key,
            "name": _label(record, key, 6),
            "description": description,
            "activation": record.number(12),
            "thresholds": parameter.ints(8),
            "threshold_type": {1: "人数", 2: "层数"}.get(parameter.number(6, "<B")),
            "scalings": _scalings(parameter, actions[effect_id], description, check),
        })
    return result


def _shops(season, modes, check):
    profiles = _index(season, 56, check)
    if season.field(76, 4) is not None:
        training = _index(season.child(76), 20, check)
        if set(profiles) & set(training):
            raise ValueError("普通和入门调度档位重复")
        profiles.update(training)

    level_type = schema("activity_table").clz_Torappu_ActAutoChessData_ActAutoChessShopLevelData
    result = []
    for key, profile in profiles.items():
        check()
        levels = _index(profile, 6, check, integer=True)
        if not levels or sorted(levels) != list(range(1, len(levels) + 1)):
            raise ValueError("调度档位不连续")
        rows = []
        for level, entry in sorted(levels.items()):
            check()
            table = entry.child(6)
            # Validate leaf fields before passing them to the generated reader.
            for slot in (4, 6, 8, 10):
                table.field(slot, 4)
            table.text(12)
            row = _normalize_leaf(table, level_type)
            if row["shopLevel"] != level or any(row[name] < 0 for name in ("initialUpgradePrice", "charChessCount", "itemCount")):
                raise ValueError("调度档位数据不匹配")
            rows.append(row)
        result.append({
            "id": key,
            "name": _label(modes[key], key, 6),
            "upgrade_prices": [row["initialUpgradePrice"] for row in rows[:-1]] + [None],
            "operator_slots": [row["charChessCount"] for row in rows],
            "equipment_slots": [row["itemCount"] for row in rows],
        })
    return result


def _season_details(season, metadata, check):
    # These independently keyed dictionaries let the PC layout prove itself.
    modes = _records(season, 4, check)
    effects = _records(season, 50, check)
    strategies = _strategies(season, metadata, effects, check)
    bonds = _bonds(season, effects, check)
    shops = _shops(season, modes, check)
    if not (strategies and bonds and shops):
        raise ValueError("策略、盟约或调度配置不完整")
    return {
        "strategies": strategies, "bonds": bonds, "shops": shops,
        "refresh_cost": season.child(38).number(4),
    }


def _decode(raw, check):
    payload = raw[128:]
    root = _Table(payload, struct.unpack_from("<I", payload)[0])
    common = root.child(56)
    versions = _records(common, 4, check)
    metadata = _records(common, 10, check)
    activities = _index(root.child(18), 90, check)
    basics = _index(root, 4, check)
    if not activities or not all(_ACTIVITY_ID.fullmatch(key) for key in activities):
        raise ValueError("未找到已知的赛季活动字典")

    result = []
    for activity_id, activity in activities.items():
        check()
        title = _label(basics[activity_id].child(6), activity_id, 10)
        for season_id, entry in _index(activity, 6, check).items():
            check()
            version = versions[season_id]
            if not _SEASON_ID.fullmatch(season_id) or version.text(4) != season_id or version.text(6) != activity_id:
                raise ValueError("赛季标识和活动索引不匹配")
            try:
                details = _season_details(entry.child(6), metadata, check)
            except (KeyError, ValueError, struct.error) as error:
                details = {"strategies": [], "bonds": [], "shops": [], "refresh_cost": None}
                diagnostics = [f"卫戍协议赛季 {season_id} 的详情布局待适配（{error}）"]
            else:
                diagnostics = []
            result.append({
                "activity_id": activity_id, "season_id": season_id, "title": title,
                **details, "diagnostics": diagnostics,
            })
    if not result:
        raise ValueError("活动字典没有赛季")
    return result


def decode_autochess(raw: bytes, *, cancel=None) -> list[dict]:
    """Decode verified PC seasonal tables. Older or shifted layouts stay unparsed."""
    check = cancel.check if cancel is not None else lambda: None
    check()
    try:
        return _decode(raw, check)
    except (KeyError, ValueError, struct.error) as error:
        raise ValueError(f"卫戍协议活动表布局待适配（{error}）") from error
