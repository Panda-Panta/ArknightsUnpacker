from pathlib import Path
import threading
import time

from arknights_unpacker.application import AppServices
from arknights_unpacker.contracts import GameDataSnapshot, OperatorProfile, CancelledError
from arknights_unpacker.ui.main_window import MainWindow


def test_window_reopens_saved_scan_and_data_without_scanning_or_decoding(qtbot, tmp_path):
    game = tmp_path / 'game'
    game.mkdir()
    (game / 'one.ab').write_bytes(b'UnityFS-test-input')
    data_dir = tmp_path / 'app-data'
    first = AppServices(data_dir)
    scanned = first.scan(game)
    first.store.save_data_snapshot(first.installation.profile_id, GameDataSnapshot(
        'saved-data', 'fixture-version', 'fixture-resources',
        {'character_table': {'char_saved': {'name': '已保存干员', 'rarity': 'TIER_6', 'profession': 'CASTER'}}},
        complete=True, created_at=scanned['snapshot'].finished_at))
    first.shutdown()

    restored = AppServices(data_dir)
    def forbidden(*args, **kwargs):
        raise AssertionError('Opening saved results must not scan or decode the game again')
    restored.scan = forbidden
    restored.load_data = forbidden
    window = MainWindow(restored)
    qtbot.addWidget(window)
    window.show()
    try:
        qtbot.waitUntil(lambda: restored.gamedata is not None and not window.queue.busy, timeout=10000)
        assert restored.scan_snapshot.snapshot_id == scanned['snapshot'].snapshot_id
        assert window.explorer.model.rowCount() == 1
        assert window.operators.model.rows[0]['name'] == '已保存干员'
        assert window.updates.model.rowCount() == 1
        assert '恢复' in window.session_label.text() or '已保存' in window.session_label.text()
        assert restored.store.latest_scan(restored.installation.profile_id).snapshot_id == scanned['snapshot'].snapshot_id
    finally:
        window.close()
        restored.shutdown()


def test_switching_installation_clears_previous_profile_details(qtbot, tmp_path, monkeypatch):
    from test_explorer import wait_idle
    first_game, second_game = tmp_path / 'first-game', tmp_path / 'second-game'
    for game in (first_game, second_game):
        game.mkdir()
        (game / 'one.ab').write_bytes(b'UnityFS-test')
    services = AppServices(tmp_path / 'data')
    scanned = services.scan(first_game)
    services.store.save_data_snapshot(services.installation.profile_id, GameDataSnapshot(
        'A', 'A', 'A', {'character_table': {'char_A': {'name': 'Alpha'}}},
        created_at=scanned['snapshot'].finished_at))
    monkeypatch.setattr(services, 'operator_profile', lambda *args: OperatorProfile('char_A', 'Alpha'))
    window = MainWindow(services)
    qtbot.addWidget(window)
    window.show()
    try:
        qtbot.waitUntil(lambda: services.gamedata is not None and not window.queue.busy, timeout=10000)
        window.operators.table.selectRow(0)
        wait_idle(qtbot, window)
        assert 'Alpha' in window.operators.details.toPlainText()
        monkeypatch.setattr(services.runner, 'run', lambda *args, **kwargs: {})
        monkeypatch.setattr('arknights_unpacker.gamedata.load_gamedata', lambda *args: GameDataSnapshot(
            'B', 'B', 'B', {'character_table': {'char_B': {'name': 'Beta'}}}, created_at=time.time()))
        window.root_edit.setText(str(second_game))
        window.load_data()
        wait_idle(qtbot, window)
        assert window.operators.model.rows[0]['name'] == 'Beta'
        assert 'Alpha' not in window.operators.details.toPlainText()
    finally:
        window.close()
        services.shutdown()


def test_close_during_restore_preserves_previous_view_state(qtbot, tmp_path, monkeypatch):
    game = tmp_path / 'game'
    game.mkdir()
    services = AppServices(tmp_path / 'data')
    old = {'root': str(game), 'tab': 2, 'operators': {'selected_id': 'char_saved', 'search': 'saved'}}
    services.config.update(game_root=str(game), view_states={str(game): old})
    services.save_config()
    started = threading.Event()
    def restore(root, emit=None, cancel=None):
        started.set()
        while not cancel.cancelled:
            time.sleep(.005)
        raise CancelledError('cancelled before restored data returned')
    monkeypatch.setattr(services, 'restore', restore)
    window = MainWindow(services)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(started.is_set, timeout=5000)
    window.close()
    qtbot.waitUntil(lambda: not window.queue.busy and not window.isVisible(), timeout=5000)
    assert services.config['view_states'][str(game)] == old
    services.shutdown()


def test_close_before_startup_timer_does_not_restore_hidden_window(qtbot, tmp_path, monkeypatch):
    services = AppServices(tmp_path / 'data')
    services.config['game_root'] = str(tmp_path)
    called = []
    monkeypatch.setattr(services, 'restore', lambda *args, **kwargs: called.append(1) or {})
    window = MainWindow(services)
    qtbot.addWidget(window)
    window.close()
    qtbot.wait(100)
    assert not called
    assert not window.queue.busy
    services.shutdown()
