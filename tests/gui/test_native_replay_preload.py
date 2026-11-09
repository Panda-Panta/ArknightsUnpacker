from threading import Event

from PySide6.QtWidgets import QPushButton

from arknights_unpacker import paths
from arknights_unpacker.application import AppServices
from arknights_unpacker.ui.level_native_preview import NativeReplayPreloader
from arknights_unpacker.ui.main_window import MainWindow


def test_new_stage_prepares_before_play_and_uses_a_separate_queue(qtbot, tmp_path, monkeypatch):
    services = AppServices(tmp_path / 'data', tmp_path / 'exports')
    game_root = str(tmp_path / 'game')
    version = 'installed-revision'
    stage = 'gamedata/levels/activities/new_event/level_new_event_04'
    other = 'gamedata/levels/obt/recalrune/level_recalrune_01-04'
    catalog = {'root': game_root, 'resource_version': version, 'diagnostics': [], 'levels': [
        {'id': stage, 'name': '新增关卡', 'category': '特殊活动', 'available': True, 'is_new': True},
        {'id': other, 'name': '矩阵关卡', 'category': '全息作战矩阵', 'available': True, 'is_new': False},
    ]}
    services.level_catalog = catalog
    services.load_level_metadata = lambda *_args, **_kwargs: {'levels': {}, 'chapters': {}, 'diagnostics': []}
    services.load_level_preview_info = lambda *_args, **_kwargs: {
        'resource_version': version, 'map_size': (5, 7), 'wave_count': 2, 'route_count': 4}
    calls, played, cache, tokens = [], [], {}, []
    allow_finish = Event()
    services.cached_native_level_replay = lambda _root, stage_id, _version, **_kwargs: cache.get(stage_id)

    def load(root, stage_id, revision, _directory, *, native, prewarm, cancel, **_options):
        tokens.append(cancel)
        calls.append((root, stage_id, revision, native, prewarm, _options['tag_ids']))
        while not allow_finish.wait(.02):
            cancel.check()
        cache[stage_id] = {'level_id': stage_id, 'resource_version': revision,
                           'spawns': 12, 'duration': 60.0, 'native_assets': str(tmp_path)}
        return cache[stage_id]

    services.load_level_replay = load
    project = tmp_path / 'scripts/level_preview/native_player'
    project.mkdir(parents=True)
    (project / 'Godot.exe').touch()
    monkeypatch.setattr(paths, 'resource_root', lambda: tmp_path)
    monkeypatch.setattr(NativeReplayPreloader, '_open_player',
                        lambda _self, preview, result: played.append((preview.request.path, result)))
    window = MainWindow(services)
    qtbot.addWidget(window)
    window.show()
    page = window.pages._pages['levels']
    page._set_catalog(catalog)
    window.pages.select('levels')
    page.view.search.setText('新增关卡')
    page.view.table.selectRow(0)
    try:
        qtbot.waitUntil(lambda: len(calls) == 1, timeout=3500)
        assert calls == [(game_root, stage, version, True, True, None)]
        assert window.native_replay_queue.busy

        page.view.preview_button.click()
        dialog = page._preview_dialog
        button = next(item for item in dialog.findChildren(QPushButton) if '原生回放' in item.text())
        qtbot.waitUntil(lambda: '地图 5×7' in dialog.detail.text())
        assert window.native_replay_queue.busy
        button.click()
        assert '完成后自动播放' in dialog.replay_status.text()
        assert not button.isEnabled()

        allow_finish.set()
        qtbot.waitUntil(lambda: len(played) == 1)
        assert played[0] == (stage, cache[stage])
        assert len(calls) == 1 and not window.native_replay_queue.busy
        dialog.close()

        page.view.preview_button.click()
        dialog = page._preview_dialog
        button = next(item for item in dialog.findChildren(QPushButton) if '原生回放' in item.text())
        assert '已准备' in dialog.replay_status.text()
        button.click()
        assert len(played) == 2 and len(calls) == 1
        dialog.close()

        allow_finish.clear()
        page._apply_tags(other, ['chosen-tag'], None)
        page.view.search.setText('矩阵关卡')
        page.view.table.selectRow(0)
        qtbot.waitUntil(lambda: len(calls) == 2, timeout=3500)
        assert calls[-1] == (game_root, other, version, True, True, ('chosen-tag',))
        page.view.search.setText('新增关卡')
        page.view.table.selectRow(0)
        qtbot.waitUntil(lambda: not window.native_replay_queue.busy, timeout=3500)
        assert tokens[-1].cancelled and other not in cache
    finally:
        allow_finish.set()
        window.close()
        qtbot.waitUntil(lambda: not window.native_replay_queue.busy and not window.queue.busy)
