"""Priority checks expose entity results before the resource inventory starts."""
from arknights_unpacker.ui.main_window import MainWindow
from test_explorer import MockServices, wait_idle


def make_window(qtbot, tmp_path, mode=None):
    services = MockServices(tmp_path)
    if mode:
        services.config['scan_priority'] = mode
    window = MainWindow(services)
    qtbot.addWidget(window)
    game = tmp_path / 'game'
    game.mkdir()
    window.root_edit.setText(str(game))
    window.show()
    return window, services


def test_default_checks_entities_and_displays_them_before_scanning(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    original = services.scan
    observed = []

    def scan(*args, **kwargs):
        observed.append((services.loaded, len(window.operators.model.rows), len(window.modules.model.rows)))
        return original(*args, **kwargs)

    services.scan = scan
    window.scan()
    wait_idle(qtbot, window)
    assert observed == [(1, 1, 1)]
    assert window.scan_button.isEnabled()
    assert not window._scan_pending and not window._load_pending
    window.close()


def test_data_only_never_starts_full_scan_and_choice_is_saved(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    window.scan_priority.setCurrentIndex(window.scan_priority.findData('data_only'))
    window.scan()
    wait_idle(qtbot, window)
    assert services.loaded == 1
    assert not services.calls
    assert len(window.operators.model.rows) == 1
    assert services.config['scan_priority'] == 'data_only'
    assert window.scan_button.isEnabled()
    window.close()


def test_files_only_keeps_existing_no_core_load_behavior(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path, 'files_only')
    window.scan()
    wait_idle(qtbot, window)
    assert services.loaded == 0
    assert services.calls[0][0] == 'scan'
    assert window.explorer.model.rowCount() == 2
    window.close()


def test_cancelled_priority_check_does_not_start_inventory(qtbot, tmp_path):
    import threading
    import time
    window, services = make_window(qtbot, tmp_path)
    started = threading.Event()

    def load(root, emit=None, cancel=None):
        started.set()
        while not cancel.cancelled:
            time.sleep(.005)
        cancel.check()

    services.load_data = load
    window.scan()
    qtbot.waitUntil(started.is_set)
    window.queue.cancel()
    wait_idle(qtbot, window)
    assert not services.calls
    assert window.scan_button.isEnabled()
    assert not window._scan_pending and not window._load_pending
    window.close()


def test_missing_core_tables_still_allows_inventory_in_default_mode(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)

    def fail(*args, **kwargs):
        raise ValueError('fixture unreadable core data')

    services.load_data = fail
    window.scan()
    wait_idle(qtbot, window)
    assert services.calls[0][0] == 'scan'
    assert window.explorer.model.rowCount() == 2
    assert any(job.status == '失败' for job in window.queue.jobs)
    assert not window._scan_pending and not window._load_pending
    window.close()


def test_repeated_priority_run_keeps_pending_flags_and_blocks_duplicate_requests(qtbot, tmp_path):
    import threading
    window, services = make_window(qtbot, tmp_path)
    window.scan()
    wait_idle(qtbot, window)
    started = threading.Event()
    release = threading.Event()
    original = services.load_data

    def load(*args, **kwargs):
        started.set()
        while not release.wait(.005):
            kwargs['cancel'].check()
        return original(*args, **kwargs)

    services.load_data = load
    try:
        window.scan()
        qtbot.waitUntil(started.is_set)
        assert window._scan_pending and window._load_pending
        assert not window.scan_button.isEnabled()
        count = len(window.queue.jobs)
        window.scan()
        assert len(window.queue.jobs) == count
    finally:
        release.set()
        wait_idle(qtbot, window)
        window.close()


def test_data_only_switches_installation_without_retaining_old_inventory(qtbot, tmp_path, monkeypatch):
    from arknights_unpacker.application import AppServices
    from arknights_unpacker.contracts import GameDataSnapshot
    import arknights_unpacker.gamedata as gamedata
    first, second = tmp_path / 'first', tmp_path / 'second'
    first.mkdir()
    second.mkdir()
    (first / 'old.ab').write_bytes(b'first installation')
    (second / 'new.ab').write_bytes(b'second installation')
    services = AppServices(tmp_path / 'data', tmp_path / 'exports')
    services.scan(first)
    window = MainWindow(services)
    qtbot.addWidget(window)
    window.show()
    try:
        qtbot.waitUntil(lambda: window._view_state_ready and not window.queue.busy)
        assert window.explorer.model.rowCount() == 1
        monkeypatch.setattr(services.runner, 'run', lambda *a, **k: {})
        monkeypatch.setattr(gamedata, 'load_gamedata', lambda *a: GameDataSnapshot('B', 'B', 'B', {}))
        window.scan_priority.setCurrentIndex(window.scan_priority.findData('data_only'))
        window.root_edit.setText(str(second))
        window.scan()
        wait_idle(qtbot, window)
        assert services.scan_snapshot is None
        assert window.explorer.snapshot is None
        assert window.explorer.model.rowCount() == 0
    finally:
        window.close()
        services.shutdown()
