import json
from PySide6.QtCore import Qt

from arknights_unpacker.ui.level_catalog_page import LevelCatalogView


def catalog():
    return {
        'root': 'game', 'resource_version': 'resource-1', 'diagnostics': [],
        'levels': [
            {'id': 'gamedata/levels/obt/main/level_main_00-01', 'name': '坍塌', 'code': '0-1',
             'chapter_id': 'main_0', 'chapter': '序章 · 黑暗时代·上', 'category': '主线',
             'available': True, 'is_new': False},
            {'id': 'gamedata/levels/obt/roguelike/level_rogue_01', 'name': '险路伏击',
             'chapter_id': 'IS02', 'chapter': '傀影与猩红孤钻',
             'category': '集成战略', 'available': True, 'is_new': True, 'preview_ready': True},
            {'id': 'gamedata/levels/activities/act3autochess/level_act3autochess_01', 'name': '卫戍协议',
             'category': '特殊活动', 'available': False, 'is_new': True, 'preview_ready': True},
        ],
    }


def test_category_search_and_new_filter_round_trip(qtbot):
    view = LevelCatalogView()
    qtbot.addWidget(view)
    view.set_catalog(catalog())
    assert [view.categories.tabText(i) for i in range(view.categories.count())] == [
        '全部', '主线', '集成战略', '特殊活动',
    ]
    assert view.model.rowCount() == 3
    view.only_new.setChecked(True)
    assert view.model.rowCount() == 2
    view.categories.setCurrentIndex(2)
    view.search.setText('ROGUE_01')
    assert [row['name'] for row in view.model.rows] == ['险路伏击']

    restored = LevelCatalogView()
    qtbot.addWidget(restored)
    restored.restore_state(view.save_state())
    restored.set_catalog(catalog())
    assert restored.only_new.isChecked()
    assert restored.search.text() == 'ROGUE_01'
    assert restored.categories.tabText(restored.categories.currentIndex()) == '集成战略'
    assert restored.model.rowCount() == 1


def test_preview_opens_for_any_selected_level_and_double_click(qtbot):
    view = LevelCatalogView()
    qtbot.addWidget(view)
    result = catalog()
    view.set_catalog(result)
    view.search.setText('坍塌')
    view.table.selectRow(0)
    assert '已安装' in view.details.text()
    assert '待校验' in view.details.text()
    assert view.preview_button.isEnabled()

    view.search.setText('卫戍协议')
    view.table.selectRow(0)
    assert '未安装' in view.details.text()
    assert view.preview_button.isEnabled()
    view.resize(1040, 680)
    view.show()
    index = view.model.index(0, 0)
    position = view.table.visualRect(index).center()
    qtbot.mouseClick(view.table.viewport(), Qt.MouseButton.LeftButton, pos=position)
    with qtbot.waitSignal(view.preview_requested) as emitted:
        qtbot.mouseDClick(view.table.viewport(), Qt.MouseButton.LeftButton, pos=position)
    assert emitted.args == [result['levels'][2]['id']]

    view.search.setText('险路')
    view.table.selectRow(0)
    with qtbot.waitSignal(view.preview_requested) as emitted:
        view.preview_button.click()
    assert emitted.args == [result['levels'][1]['id']]

    view.set_catalog(None)
    assert not view.preview_button.isEnabled()
    assert view.model.rowCount() == 0


def test_chapter_and_game_code_match_search_and_survive_restore(qtbot):
    view = LevelCatalogView()
    qtbot.addWidget(view)
    result = catalog()
    result['levels'].extend([
        {'id': 'gamedata/levels/obt/main/level_main_07-16', 'name': '爱国者之死', 'code': '7-18',
         'chapter_id': 'main_7', 'chapter': '第七章 · 苦难摇篮', 'category': '主线',
         'available': True, 'is_new': True},
        {'id': 'gamedata/levels/obt/main/level_main_10-01', 'name': '第十章关卡',
         'chapter_id': 'main_10', 'chapter': '第十章 · 破碎日冕', 'category': '主线',
         'available': True, 'is_new': False},
        {'id': 'gamedata/levels/obt/main/level_internal', 'name': None,
         'category': '主线', 'available': True, 'is_new': True},
    ])
    view.set_catalog(result)
    view.categories.setCurrentIndex(1)
    assert [view.chapters.itemText(i) for i in range(view.chapters.count())] == [
        '全部章节', '序章 · 黑暗时代·上', '第七章 · 苦难摇篮', '第十章 · 破碎日冕', '未知章节',
    ]
    view.chapters.setCurrentText('未知章节')
    assert view.model.rowCount() == 1
    assert view.model.index(0, 1).data() == 'level_internal'
    view.chapters.setCurrentText('第七章 · 苦难摇篮')
    view.only_new.setChecked(True)
    for query in ('7-18', 'main_7', '苦难摇篮', 'main_07-16'):
        view.search.setText(query)
        assert view.model.rowCount() == 1
        assert view.model.index(0, 0).data() == '7-18'
        assert view.model.index(0, 1).data() == '爱国者之死'
    view.table.selectRow(0)
    assert '第七章 · 苦难摇篮' in view.details.text()
    assert view.selected_name.text() == '7-18 · 爱国者之死'

    state = json.loads(json.dumps(view.save_state()))
    restored = LevelCatalogView()
    qtbot.addWidget(restored)
    restored.restore_state(state)
    restored.set_catalog(result)
    assert restored.chapters.currentText() == '第七章 · 苦难摇篮'
    assert restored.model.rowCount() == 1
    restored.search.clear()
    restored.categories.setCurrentIndex(2)
    assert restored.chapters.currentText() == '全部章节'
    assert restored.model.rowCount() == 1
