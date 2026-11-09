from threading import Event, get_ident
from types import SimpleNamespace

from arknights_unpacker.ui.main_window import MainWindow
from test_explorer import MockServices, wait_idle


LEVEL = 'gamedata/levels/activities/act3autochess/level_act3autochess_01'
OLD_LEVEL = 'gamedata/levels/activities/act2autochess/level_act2autochess_01'


def modes():
    return [
        {'id': 'autochess', 'name': '卫戍协议', 'supported': True,
         'resources': ['gamedata/excel/activity_table071163'], 'level_paths': [LEVEL, OLD_LEVEL]},
        {'id': 'roguelike', 'name': '集成战略', 'supported': False,
         'resources': ['gamedata/excel/roguelike_topic_table'], 'level_paths': []},
    ]


def catalog(root, version, entries):
    return {'root': str(root), 'resource_version': version, 'modes': entries, 'diagnostics': []}


def season(activity_id='act3autochess', season_id='V3_1'):
    return {
        'activity_id': activity_id, 'season_id': season_id, 'title': f'序列 {season_id}',
        'strategies': [{'id': 'band_amiya', 'name': '阿米娅', 'title': '众志合一',
                        'description': '【众志合一】\n全体干员攻击力提升', 'hp': 25, 'unlock': None}],
        'bonds': [{'id': 'yan', 'name': '炎', 'description': '攻击力 +{0:0%}',
                   'activation': 3, 'thresholds': [3, 6], 'threshold_type': '人数',
                   'scalings': [{'index': 0, 'base': .23, 'per_stack': .009, 'cap': None, 'format': '0%'}]}],
        'shops': [{'id': 'standard', 'name': '标准模拟',
                   'upgrade_prices': [5, 8, 10, 11, 11, None],
                   'operator_slots': [3, 4, 4, 4, 4, 5], 'equipment_slots': [1] * 6}],
        'refresh_cost': 1, 'diagnostics': [],
    }


class GameplayServices(MockServices):
    def __init__(self, folder):
        super().__init__(folder)
        self.gameplay_catalog = None
        self.version = 'first'
        self.started = Event()
        self.release = None
        self.fail_version = None
        self.unsupported = False

    def scan(self, root, **kwargs):
        result = super().scan(root, **kwargs)
        self.gameplay_catalog = catalog(root, self.version, modes())
        return result

    def load_gameplay(self, root, mode_id, resource_version, **kwargs):
        self.calls.append(('gameplay', root, mode_id, resource_version, get_ident()))
        if self.release is not None and resource_version == 'first':
            self.started.set()
            assert self.release.wait(3), '等待测试释放旧请求超时'
        if resource_version == self.fail_version:
            self.fail_version = None
            raise ValueError('此版本未匹配')
        current = season(season_id='V3_1' if resource_version == 'first' else 'V3_2')
        if self.unsupported:
            current.update(strategies=[], bonds=[], shops=[], diagnostics=['赛季详情布局待适配。'])
        return {'game_version': '79.2.0', 'resource_version': resource_version,
                'seasons': [current, season('act2autochess', 'V2_1')], 'diagnostics': []}

    def load_gameplay_level(self, root, logical_path, resource_version, **kwargs):
        self.calls.append(('level', root, logical_path, resource_version, get_ident()))
        return {'level_id': 'level_act3autochess_01', 'map_size': [7, 9],
                'route_count': 2, 'wave_count': 3, 'enemy_ids': ['enemy_01'], 'diagnostics': []}


def make_gameplay(qtbot, tmp_path):
    services = GameplayServices(tmp_path)
    window = MainWindow(services)
    qtbot.addWidget(window)
    window.monitor_timer.stop()
    window.scan_priority.setCurrentIndex(window.scan_priority.findData('files_only'))
    game = tmp_path / 'game'
    game.mkdir()
    window.root_edit.setText(str(game))
    return window, services, game


def test_scan_builds_tabs_once_and_loads_details_only_when_opened(qtbot, tmp_path):
    window, services, game = make_gameplay(qtbot, tmp_path)
    view = window.pages.widget('gameplay')
    assert view is not None
    assert '扫描' in view.status.text()
    window.scan()
    wait_idle(qtbot, window)
    assert [view.modes.tabText(i) for i in range(view.modes.count())] == ['卫戍协议', '集成战略']
    autochess = view.modes.widget(0)
    assert not [call for call in services.calls if call[0] == 'gameplay']

    view.modes.setCurrentIndex(1)
    window.pages.select('gameplay')
    assert '待适配' in view.modes.currentWidget().status.text()
    assert 'roguelike_topic_table' in view.modes.currentWidget().resources.toPlainText()
    assert not [call for call in services.calls if call[0] == 'gameplay']
    view.modes.setCurrentIndex(0)
    wait_idle(qtbot, window)
    assert '79.2.0' in autochess.status.text()
    assert autochess.strategies.detail.toPlainText().count('众志合一') == 1
    assert '每层 +0.9 个百分点' in autochess.bonds.detail.toPlainText()
    assert '概率未知' in autochess.shops.detail.toPlainText()
    loads = [call for call in services.calls if call[0] == 'gameplay']
    assert len(loads) == 1 and loads[0][1:4] == (str(game), 'autochess', 'first')
    assert loads[0][4] != get_ident()

    autochess.season.setCurrentIndex(1)
    window.scan()
    wait_idle(qtbot, window)
    assert view.modes.count() == 2
    assert view.modes.widget(0) is autochess
    assert autochess.season.currentData() == ('act2autochess', 'V2_1')
    assert len([call for call in services.calls if call[0] == 'gameplay']) == 1


def test_level_selection_uses_only_the_selected_season_and_is_lazy(qtbot, tmp_path):
    window, services, game = make_gameplay(qtbot, tmp_path)
    window.scan()
    wait_idle(qtbot, window)
    window.pages.select('gameplay')
    wait_idle(qtbot, window)
    panel = window.pages.widget('gameplay').modes.currentWidget()
    assert panel.levels.items.count() == 1
    assert not [call for call in services.calls if call[0] == 'level']
    panel.sections.setCurrentWidget(panel.levels)
    panel.levels.items.setCurrentRow(0)
    wait_idle(qtbot, window)
    assert '7 × 9' in panel.levels.detail.toPlainText()
    assert 'enemy_01' in panel.levels.detail.toPlainText()
    assert [call[1:4] for call in services.calls if call[0] == 'level'] == [(str(game), LEVEL, 'first')]

    panel.season.setCurrentIndex(1)
    assert panel.levels.items.count() == 1
    assert 'act2autochess' in panel.levels.items.item(0).text()
    assert 'enemy_01' not in panel.levels.detail.toPlainText()


def test_ignores_old_result_after_switch_and_retry_remains_explicit(qtbot, tmp_path):
    window, services, game = make_gameplay(qtbot, tmp_path)
    window.scan()
    wait_idle(qtbot, window)
    services.release = Event()
    window.pages.select('gameplay')
    qtbot.waitUntil(services.started.is_set)
    controller = window.pages._pages['gameplay']
    other = tmp_path / 'other'
    other.mkdir()
    try:
        controller.set_root(other)
        services.gameplay_catalog = catalog(other, 'second', modes())
        services.fail_version = 'second'
        controller.scanned(SimpleNamespace(root=other), None, None)
    finally:
        services.release.set()
    wait_idle(qtbot, window)

    panel = controller.view.modes.currentWidget()
    assert panel.season.count() == 0
    assert '此版本未匹配' in panel.status.text()
    assert not panel.retry.isHidden()
    panel.retry.click()
    wait_idle(qtbot, window)
    assert panel.season.currentData() == ('act3autochess', 'V3_2')
    assert '此版本未匹配' not in panel.status.text()
    assert [call[1:4] for call in services.calls if call[0] == 'gameplay'] == [
        (str(game), 'autochess', 'first'), (str(other), 'autochess', 'second'),
        (str(other), 'autochess', 'second'),
    ]

    services.gameplay_catalog = catalog(other, 'third', [])
    controller.scanned(SimpleNamespace(root=other), None, None)
    assert controller.view.modes.count() == 0
    assert '未识别到' in controller.view.status.text()


def test_displays_missing_resources_and_current_season_diagnostics_inline(qtbot, tmp_path):
    window, services, game = make_gameplay(qtbot, tmp_path)
    controller = window.pages._pages['gameplay']
    entries = modes()
    entries[0]['available'] = False
    services.gameplay_catalog = catalog(game, 'first', entries)
    controller.scanned(SimpleNamespace(root=game), None, None)
    window.pages.select('gameplay')
    panel = controller.view.modes.currentWidget()
    assert '缺少数据资源' in panel.status.text()
    assert not [call for call in services.calls if call[0] == 'gameplay']

    services.unsupported = True
    services.gameplay_catalog = catalog(game, 'first', modes())
    controller.scanned(SimpleNamespace(root=game), None, None)
    wait_idle(qtbot, window)
    assert panel.season_note.text() == '赛季详情布局待适配。'
    assert not panel.season_note.isHidden()
    panel.season.setCurrentIndex(1)
    assert panel.season_note.isHidden()
