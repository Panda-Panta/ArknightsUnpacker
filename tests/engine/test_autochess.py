import flatbuffers
import pytest

from arknights_unpacker.contracts import CancelToken, CancelledError
from arknights_unpacker.extraction.autochess import decode_autochess


def _record(builder, *, refs=None, integers=None, floats=None):
    refs, integers, floats = refs or {}, integers or {}, floats or {}
    count = (max({4, *refs, *integers, *floats}) - 4) // 2 + 1
    builder.StartObject(count)
    for slot, value in refs.items():
        builder.PrependUOffsetTRelativeSlot((slot - 4) // 2, value, 0)
    for slot, value in integers.items():
        builder.PrependInt32Slot((slot - 4) // 2, value, 0)
    for slot, value in floats.items():
        builder.PrependFloat32Slot((slot - 4) // 2, value, 0)
    return builder.EndObject()


def _vector(builder, *values, integers=False):
    builder.StartVector(4, len(values), 4)
    for value in reversed(values):
        if integers:
            builder.PrependInt32(value)
        else:
            builder.PrependUOffsetTRelative(value)
    return builder.EndVector()


def _fixture(*, wrong_activity=False, extra_unknown_season=False):
    builder = flatbuffers.Builder(1024)
    string = builder.CreateString

    def record(*, refs=None, integers=None, floats=None):
        return _record(builder, refs=refs, integers=integers, floats=floats)

    def vector(*values, integers=False):
        return _vector(builder, *values, integers=integers)

    def entry(key, value):
        return record(refs={4: string(key), 6: value})

    activity_id, season_id = "act57autochess", "V12_9"
    activity_info = record(refs={4: string(activity_id), 10: string("卫戍协议·测试")})
    basic = vector(entry(activity_id, activity_info))
    season_info = record(refs={4: string(season_id), 6: string("act99autochess" if wrong_activity else activity_id)})
    versions = [entry(season_id, season_info)]
    band = record(refs={4: string("band_1"), 6: string("测试干员"), 10: string("通关一次")})
    band_metadata = vector(entry("band_1", band))

    mode = record(refs={4: string("mode_1"), 6: string("标准测试")})
    modes = vector(entry("mode_1", mode))
    strategy = record(
        refs={4: string("band_1"), 12: string("<@ba.vup>提升</>\\n生效"), 16: string("aceffect_band_1")},
        integers={14: 30},
    )
    strategies = vector(entry("band_1", strategy))
    bond = record(
        refs={4: string("yanShip"), 6: string("炎"), 8: string("基础说明"), 20: string("bondeffect_yan")},
        integers={12: 3},
    )
    bonds = vector(entry("yanShip", bond))
    scale = record(refs={4: string("atk_base"), 6: string("atk_increment")}, floats={8: 1.0})
    bond_scale = record(
        refs={4: vector(scale), 8: vector(3, 6, integers=True)},
        integers={6: 1},
    )
    scales = vector(entry("bondeffect_yan", bond_scale))
    band_effect = record(refs={4: string("aceffect_band_1"), 12: string("测试策略")})
    bond_effect = record(
        refs={4: string("bondeffect_yan"), 12: string("炎"), 14: string("攻击力提升 {0:0%}")},
    )
    effects = vector(entry("aceffect_band_1", band_effect), entry("bondeffect_yan", bond_effect))
    base = record(refs={4: string("atk_base")}, floats={6: 0.23})
    increment = record(refs={4: string("atk_increment")}, floats={6: 0.009})
    action = record(refs={4: string("add_atk"), 6: vector(base, increment)})
    actions = vector(entry("bondeffect_yan", vector(action)))

    levels = []
    for level, price in ((2, 99), (1, 5)):
        shop = record(integers={4: level, 6: price, 8: level + 1, 10: 1})
        levels.append(record(refs={6: shop}, integers={4: level}))
    shops = vector(entry("mode_1", vector(*levels)))
    season = record(refs={
        4: modes, 38: record(integers={4: 1}), 42: strategies, 44: bonds,
        48: scales, 50: effects, 54: actions, 56: shops,
    })
    seasons = [entry(season_id, season)]
    if extra_unknown_season:
        extra_id = "V12_10"
        extra_info = record(refs={4: string(extra_id), 6: string(activity_id)})
        versions.append(entry(extra_id, extra_info))
        seasons.append(entry(extra_id, record()))
    common = record(refs={4: vector(*versions), 10: band_metadata})
    activity = record(refs={90: vector(entry(activity_id, vector(*seasons)))})
    builder.Finish(record(refs={4: basic, 18: activity, 56: common}))
    return bytes(128) + bytes(builder.Output())


def test_decodes_recognized_season_and_joins_gameplay_details():
    season, = decode_autochess(_fixture())
    assert (season["activity_id"], season["season_id"], season["title"]) == (
        "act57autochess", "V12_9", "卫戍协议·测试",
    )
    strategy, = season["strategies"]
    assert (strategy["id"], strategy["name"], strategy["title"]) == ("band_1", "测试干员", "测试策略")
    assert (strategy["description"], strategy["hp"], strategy["unlock"]) == ("提升\n生效", 30, "通关一次")
    bond, = season["bonds"]
    assert (bond["activation"], bond["thresholds"], bond["threshold_type"]) == (3, [3, 6], "人数")
    assert bond["description"] == "攻击力提升 {0:0%}"
    assert bond["scalings"] == [{"index": 0, "base": 0.23, "per_stack": 0.009, "cap": 1.0, "format": "0%"}]
    shop, = season["shops"]
    assert (shop["id"], shop["upgrade_prices"], shop["operator_slots"], shop["equipment_slots"]) == (
        "mode_1", [5, None], [2, 3], [1, 1],
    )
    assert season["refresh_cost"] == 1 and not season["diagnostics"]


def test_unknown_season_is_kept_without_invalidating_other_seasons():
    seasons = {item["season_id"]: item for item in decode_autochess(_fixture(extra_unknown_season=True))}
    assert seasons["V12_9"]["strategies"]
    assert not seasons["V12_10"]["strategies"]
    assert seasons["V12_10"]["diagnostics"]


@pytest.mark.parametrize(
    "raw", [b"", bytes(132), _fixture(wrong_activity=True)],
    ids=["empty", "invalid-root", "activity-mismatch"],
)
def test_unrecognized_layout_does_not_return_data(raw):
    with pytest.raises(ValueError, match="卫戍协议"):
        decode_autochess(raw)


def test_cancelled_request_does_not_decode():
    token = CancelToken()
    token.cancel()
    with pytest.raises(CancelledError):
        decode_autochess(_fixture(), cancel=token)
