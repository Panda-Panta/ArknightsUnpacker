import json
from threading import Event
from types import SimpleNamespace

from PySide6.QtWidgets import QDialog

from arknights_unpacker.application import AppServices
from arknights_unpacker.extraction import gameplay
from arknights_unpacker.library import scan as scan_module
from arknights_unpacker.ui.level_preview_window import LevelPreviewWindow
from arknights_unpacker.ui.preview_cache import PreviewCache


MAIN_LEVEL = 'gamedata/levels/obt/main/level_main_00-01'
NEW_LEVEL = 'gamedata/levels/activities/act55side/level_act55side_01'


def test_standalone_scans_new_levels_and_restores_the_saved_catalog(qtbot, tmp_path, monkeypatch):
    game = tmp_path / 'game'
    game.mkdir()
    bundle = game / 'map.ab'
    bundle.write_bytes(b'UnityFS-test')
    index = game / 'map.idx'
    manifest = game / 'hot_update_list.json'
    reads = []

    def install_revision(version, levels):
        index.write_text(json.dumps({'assets': [{'assetName': path, 'bundle': 'map.ab'}
                                                for path in levels]}), encoding='utf-8')
        manifest.write_text(json.dumps({'versionId': version, 'manifestName': index.name, 'abInfos': [
            {'name': bundle.name, 'md5': '0000', 'abSize': bundle.stat().st_size},
        ]}), encoding='utf-8')

    def read_index(path):
        reads.append(path)
        return json.loads(path.read_text(encoding='utf-8'))

    def metadata(root, version, **_):
        return {'resource_version': version, 'levels': {MAIN_LEVEL: {'code': '0-1', 'name': '坍塌'}},
                'chapters': {}, 'diagnostics': []}

    monkeypatch.setattr(gameplay, 'read_resource_manifest', read_index)
    def unexpected_digest(*_args):
        raise AssertionError('关卡目录扫描不应读取整包做哈希')
    monkeypatch.setattr(scan_module, '_digest', unexpected_digest)
    install_revision('rev-1', [MAIN_LEVEL])
    data_dir, output_dir = tmp_path / 'data', tmp_path / 'exports'
    first = AppServices(data_dir, output_dir)
    monkeypatch.setattr(first, 'load_level_metadata', metadata)
    window = LevelPreviewWindow(first)
    qtbot.addWidget(window)
    window.show()
    try:
        window.root_edit.setText(str(game))
        window.scan_button.click()
        view = window.page.view
        qtbot.waitUntil(lambda: view.model.rowCount() == 1 and not window.queue.busy)
        assert window.tabs.count() == 1 and window.tabs.currentWidget() is view
        assert view.model.index(0, 0).data() == '0-1'
        assert first.scan_snapshot is None

        install_revision('rev-2', [MAIN_LEVEL, NEW_LEVEL])
        window.scan_button.click()
        qtbot.waitUntil(lambda: view.model.rowCount() == 2 and not window.queue.busy)
        view.only_new.setChecked(True)
        assert [row['id'] for row in view.model.rows] == [NEW_LEVEL]
        saved_catalog = first.level_catalog
    finally:
        window.close()
        qtbot.waitUntil(lambda: not window.isVisible())
        first.shutdown()

    restored = AppServices(data_dir, output_dir)
    monkeypatch.setattr(restored, 'load_level_metadata', metadata)
    reopened = LevelPreviewWindow(restored)
    qtbot.addWidget(reopened)
    reopened.show()
    try:
        qtbot.waitUntil(lambda: reopened.page.view.model.rowCount() == 2 and not reopened.queue.busy)
        assert reopened.root_edit.text() == str(game)
        assert restored.level_catalog == saved_catalog
        assert len(reads) == 2
        reopened.page.view.only_new.setChecked(True)
        assert [row['id'] for row in reopened.page.view.model.rows] == [NEW_LEVEL]
    finally:
        reopened.close()
        qtbot.waitUntil(lambda: not reopened.isVisible())
        restored.shutdown()


def test_standalone_waits_for_owned_jobs_and_protects_preview_leases(qtbot, tmp_path):
    other_cache = PreviewCache(tmp_path)
    other = other_cache.allocate('objects')
    window = LevelPreviewWindow(SimpleNamespace(data_root=tmp_path, config={}))
    qtbot.addWidget(window)
    window.show()
    lease = window.preview_cache.allocate('objects')
    dialog = QDialog(window.page.view)
    window._track_dialog(dialog)
    dialog.finished.connect(lambda *_: lease.release())
    dialog.show()
    native_started, release_native = Event(), Event()
    foreground_started, release_foreground = Event(), Event()

    def wait_for_release(started, release, *, emit, cancel):
        emit({'message': '准备关卡', 'current': 2, 'total': 4})
        started.set()
        release.wait(5)
        cancel.check()

    native = window.native_replay_queue.submit('原生回放', lambda **kw: wait_for_release(
        native_started, release_native, **kw))
    window.native_replay_queue.settled.connect(lambda _: lease.finish())
    foreground = window.queue.submit('关卡详情', lambda **kw: wait_for_release(
        foreground_started, release_foreground, **kw))
    try:
        qtbot.waitUntil(lambda: foreground_started.is_set() and native_started.is_set())
        qtbot.waitUntil(lambda: window.progress.value() == 50)
        assert other.path.is_dir()
        window.cancel_button.click()
        assert foreground.token.cancelled and not native.token.cancelled
        window.close()
        assert native.token.cancelled and window.isVisible()
        assert not dialog.isVisible() and lease.path.is_dir()

        release_foreground.set()
        qtbot.waitUntil(lambda: not window.queue.busy)
        assert window.isVisible() and lease.path.is_dir()
        release_native.set()
        qtbot.waitUntil(lambda: not window.isVisible())
        assert not lease.path.exists()
        assert other.path.is_dir()
    finally:
        release_foreground.set()
        release_native.set()
        window.close()
        qtbot.waitUntil(lambda: not window.isVisible())
        other.finish()
        other.release()
