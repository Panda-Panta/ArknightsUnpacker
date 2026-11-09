import flatbuffers
import pytest

from arknights_unpacker.contracts import CancelToken


def test_targeted_stage_decode_skips_unrelated_root_fields():
    from arknights_unpacker.extraction.level_metadata import _read_stages

    builder = flatbuffers.Builder(256)
    fields = {
        5: builder.CreateString("main_07-16"),
        6: builder.CreateString("Obt/Main/level_main_07-16"),
        7: builder.CreateString("main_7"),
        8: builder.CreateString("7-18"),
        9: builder.CreateString("爱国者之死"),
    }
    builder.StartObject(10)
    for slot, value in fields.items():
        builder.PrependUOffsetTRelativeSlot(slot, value, 0)
    builder.PrependInt32Slot(1, 1, 0)
    stage = builder.EndObject()
    key = builder.CreateString("main_07-16")
    builder.StartObject(2)
    builder.PrependUOffsetTRelativeSlot(0, key, 0)
    builder.PrependUOffsetTRelativeSlot(1, stage, 0)
    entry = builder.EndObject()
    builder.StartVector(4, 1, 4)
    builder.PrependUOffsetTRelative(entry)
    stages = builder.EndVector()
    builder.StartObject(2)
    builder.PrependUOffsetTRelativeSlot(0, stages, 0)
    builder.PrependInt32Slot(1, 2147483647, 0)
    builder.Finish(builder.EndObject())

    result = _read_stages(bytes(128) + bytes(builder.Output()), CancelToken().check)
    assert result == {"main_07-16": {
        "level_id": "Obt/Main/level_main_07-16", "zone_id": "main_7",
        "code": "7-18", "title": "爱国者之死", "difficulty": 1,
    }}


def test_metadata_joins_exact_level_paths_and_prefers_normal_stage():
    from arknights_unpacker.extraction.level_metadata import _assemble

    stages = {
        "main_07-16#f#": {"level_id": "Obt/Main/level_main_07-16", "zone_id": "main_7",
                         "code": "7-18（突袭）", "title": "突袭标题", "difficulty": 2},
        "main_07-16": {"level_id": "Obt/Main/level_main_07-16", "zone_id": "main_7",
                      "code": "7-18", "title": "爱国者之死", "difficulty": 1},
        "wk_fly_5": {"level_id": "Obt/Weekly/level_weekly_fly_5", "zone_id": "weekly_6",
                     "code": "CA-5", "title": "战略要道净空", "difficulty": 1},
        "a001_01": {"level_id": "Activities/A001/level_a001_01", "zone_id": "act13d2_zone1",
                     "code": "GT-1", "title": "日正当中", "difficulty": 1},
        "ignored": {"level_id": None, "zone_id": "main_7", "code": None, "title": None, "difficulty": 1},
    }
    zones = {"main_7": "第七章 · 苦难摇篮", "weekly_6": "空中威胁", "act13d2_zone1": "滴水村周边"}
    activities = {"names": {"act13d2": "骑兵与猎人·复刻", "act3autochess": "卫戍协议：规程"},
                  "zones": {"act13d2_zone1": "act13d2"}}
    levels, chapters = _assemble(stages, zones, activities, {"rogue_6": "沉沦者的黑流树海"}, CancelToken().check)
    assert len(levels) == 3
    assert levels["gamedata/levels/obt/main/level_main_07-16"] == {
        "code": "7-18", "title": "爱国者之死", "name": "爱国者之死",
        "chapter_id": "main_7", "chapter": "第七章 · 苦难摇篮",
    }
    assert levels["gamedata/levels/obt/weekly/level_weekly_fly_5"]["code"] == "CA-5"
    assert levels["gamedata/levels/activities/a001/level_a001_01"]["chapter"] == "骑兵与猎人·复刻 · 滴水村周边"
    assert chapters["gamedata/levels/obt/roguelike/ro6/"] == {"chapter_id": "rogue_6", "chapter": "沉沦者的黑流树海"}
    assert chapters["gamedata/levels/activities/act3autochess/"]["chapter"] == "卫戍协议：规程"


def test_mode_metadata_fills_missing_chapter_and_uses_one_label_source():
    from arknights_unpacker.extraction.level_metadata import _enrich_mode_levels

    path = "gamedata/levels/obt/legion/lt05/level_lt05_01"
    levels = {path: {"code": "LT-1", "title": "蜂拥而上", "name": "蜂拥而上", "chapter": None}}
    records = [
        {"level_id": "Obt/Legion/LT05/level_lt05_01", "chapter_id": "tower_n_05",
         "code": "LT-1（其他变体）", "title": "其他变体"},
        {"level_id": "Obt/Roguelike/RO1/level_rogue1_1-1", "chapter_id": "rogue_1",
         "code": "ISW-NO", "title": "与虫为伴"},
    ]
    _enrich_mode_levels(levels, records, {"tower_n_05": "多索雷斯在建地块", "rogue_1": "傀影与猩红孤钻"}, CancelToken().check)
    assert levels[path]["code"] == "LT-1"
    assert levels[path]["chapter"] == "多索雷斯在建地块"
    assert levels["gamedata/levels/obt/roguelike/ro1/level_rogue1_1-1"]["name"] == "与虫为伴"


def test_invalid_target_dictionary_is_rejected():
    from arknights_unpacker.extraction.level_metadata import _read_stages

    with pytest.raises(ValueError, match="关卡表"):
        _read_stages(b"", CancelToken().check)
