from __future__ import annotations
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtCore import QTimer
from arknights_unpacker.contracts import (GameInstallation, ScanSnapshot, FileRecord, FileChangeSet,
    ResourceCatalog, GameDataSnapshot, EntityChangeSet, OperatorProfile, ModuleProfile, ReportArtifact, ExtractionResult)
from arknights_unpacker.ui.main_window import MainWindow
from arknights_unpacker.ui.jobs import JobQueue


class MockServices:
    """UI contract fixture; this does not exercise real decoders or game data."""
    def __init__(self, folder):
        self.data_root = folder / 'app-data'
        self.config = {'output_root': str(folder / 'exports')}
        self.installation = None
        self.scan_snapshot = self.file_changes = self.catalog = self.gamedata = self.entity_changes = None
        self.store = SimpleNamespace(list_data_snapshots=lambda profile: [])
        self.calls = []
        self.loaded = 0

    def save_config(self):
        pass

    def scan(self, root, hours=24, strict=False, emit=None, cancel=None):
        self.calls.append(('scan', root, hours, strict, threading.get_ident()))
        for _ in range(6):
            cancel.check()
            time.sleep(.01)
        self.installation = GameInstallation(Path(root), 'profile')
        now = time.time()
        self.scan_snapshot = ScanSnapshot('scan1', 'profile', root, now, now,
            [FileRecord('sample.AB', 1024, int(now * 1e9), '.AB', 'base', '立绘'),
             FileRecord('anon.bin', 2048, int(now * 1e9), '.bin', 'hot', '匿名资源')])
        self.file_changes = FileChangeSet(None, 'scan1')
        self.catalog = ResourceCatalog(self.installation)
        return {'snapshot': self.scan_snapshot, 'changes': self.file_changes, 'catalog': self.catalog}

    def load_data(self, root, emit=None, cancel=None):
        self.loaded += 1
        self.gamedata = GameDataSnapshot('data1', 'fixture-v1', 'fixture-resource', {})
        self.entity_changes = EntityChangeSet(None, 'data1')
        return self.gamedata

    def operators(self, **kw):
        return [{'id': 'char_fixture', 'name': '交互测试干员', 'rarity': 6, 'profession': '术师', 'status': 'added'}]

    def modules(self, **kw):
        return [{'id': 'equip_fixture', 'char_id': 'char_fixture', 'char_name': '交互测试干员', 'name': '交互测试模组', 'type': 'X', 'status': 'added'}]

    def operator_profile(self, entity_id, spec=None):
        return OperatorProfile(entity_id, '交互测试干员', skills=[{'name': '测试技能', 'description': '<测试文本>'}], diagnostics=['模拟资料'])

    def module_profile(self, entity_id, spec=None):
        return ModuleProfile(entity_id, 'char_fixture', '交互测试干员', '交互测试模组')

    def extract(self, paths, output, **kw):
        self.calls.append(('extract', paths, output, kw.get('object_ids')))
        return ExtractionResult()

    def objects(self, path, **kw):
        return [{'id': '123', 'type': 'TextAsset', 'name': 'fixture', 'logical_path': 'fixture.txt'}]

    def export(self, operators, modules, output, formats, **kw):
        self.calls.append(('export', operators, modules, output, formats))
        return [ReportArtifact(str(Path(output) / 'fixture.html'), 'html')]


def make_window(qtbot, tmp_path):
    services = MockServices(tmp_path)
    window = MainWindow(services)
    qtbot.addWidget(window)
    window.show()
    return window, services


def wait_idle(qtbot, window):
    qtbot.waitUntil(lambda: not window.queue.busy and all(j.status != '排队中' for j in window.queue.jobs), timeout=5000)


def test_scan_filter_multiselect_and_no_automatic_core_load(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    window.scan_priority.setCurrentIndex(window.scan_priority.findData('files_only'))
    game = tmp_path / 'game'
    game.mkdir()
    window.root_edit.setText(str(game))
    assert window.hours.value() == 24
    pulses = []
    timer = QTimer(window)
    timer.timeout.connect(lambda: pulses.append(1))
    timer.start(5)
    window.scan()
    wait_idle(qtbot, window)
    assert pulses, 'GUI event loop must continue while the service scans'
    assert services.loaded == 0
    assert services.calls[0][4] != threading.get_ident()
    assert window.explorer.model.rowCount() == 2
    window.explorer.ab_only.setChecked(True)
    assert window.explorer.model.rowCount() == 1
    assert window.explorer.model.rows[0]['path'] == 'sample.AB'
    assert window.explorer.tree.rootIndex().isValid()
    # Filtering is visual only: anonymous core packages remain in the snapshot.
    assert len(services.scan_snapshot.files) == 2
    window.explorer.ab_only.setChecked(False)
    window.explorer.table.selectAll()
    assert len(window.explorer.selected_paths()) == 2
    window.explorer.extract_selected()
    wait_idle(qtbot, window)
    assert len(next(c for c in services.calls if c[0] == 'extract')[1]) == 2
    assert '历史未知' in window.updates.summary.text()
    timer.stop()


def test_no_recent_records_has_explicit_empty_state(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    snapshot = ScanSnapshot('s', 'p', str(tmp_path), 1000000, 1000000, [FileRecord('old.ab', 1, 0)])
    window.updates.set_data(snapshot, FileChangeSet(None, 's'))
    assert window.updates.model.rowCount() == 0
    assert '没有记录' in window.updates.empty.text()


def test_normalized_installation_root_is_used_for_selected_paths(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    game = tmp_path / 'game'
    data = game / 'Arknights_Data'
    data.mkdir(parents=True)
    original_scan = services.scan
    def normalized_scan(root, **kw):
        assert Path(root) == data
        result = original_scan(str(game), **kw)
        for record in result['snapshot'].files:
            record.path = 'Arknights_Data/' + record.path
        return result
    services.scan = normalized_scan
    window.root_edit.setText(str(data))
    window.scan()
    wait_idle(qtbot, window)
    assert Path(window.root_edit.text()) == game
    assert window.explorer.root == game
    window.explorer.recursive.setChecked(True)
    window.explorer.table.selectAll()
    assert set(window.explorer.selected_paths()) == {str(data / 'sample.AB'), str(data / 'anon.bin')}


def test_queue_is_serial_and_failure_can_retry(qtbot):
    queue = JobQueue()
    order = []
    attempts = [0]
    def first(**kw):
        order.append('first-start')
        time.sleep(.04)
        order.append('first-end')
    def second(**kw):
        order.append('second')
        attempts[0] += 1
        if attempts[0] == 1:
            raise ValueError('模拟失败')
    queue.submit('first', first)
    queue.submit('second', second)
    qtbot.waitUntil(lambda: not queue.busy and len(order) == 3, timeout=5000)
    assert order == ['first-start', 'first-end', 'second']
    assert queue.jobs[1].status == '失败'
    queue.retry(1)
    qtbot.waitUntil(lambda: not queue.busy and attempts[0] == 2, timeout=5000)
    assert queue.jobs[-1].status == '成功'


def test_close_cancels_worker_before_destroying_window(qtbot, tmp_path):
    window, _ = make_window(qtbot, tmp_path)
    def slow(**kw):
        while True:
            kw['cancel'].check()
            time.sleep(.005)
    window.queue.submit('可取消模拟任务', slow)
    window.close()
    qtbot.waitUntil(lambda: not window.queue.busy, timeout=5000)
    qtbot.waitUntil(lambda: not window.isVisible(), timeout=5000)
    assert window.queue.jobs[-1].status == '已取消'


def test_extraction_retry_only_selects_failed_objects(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    paths = [str(tmp_path / 'fixture.ab')]
    calls = []
    retained = tmp_path / 'retained.png'
    retained.write_bytes(b'fixture-output')
    def extract(source_paths, output, **kw):
        calls.append((source_paths, kw.get('object_ids')))
        if len(calls) == 1:
            return ExtractionResult(status='partial', outputs=[{'object_id': '1', 'source': paths[0], 'path': str(retained)}],
                                    errors=[{'object_id': '2', 'source': paths[0], 'error': '模拟对象失败'}])
        return ExtractionResult()
    services.extract = extract
    services.objects = lambda path, **kw: [{'id': '1'}, {'id': '2'}]
    window.extract(paths)
    wait_idle(qtbot, window)
    window.queue.retry(0)
    wait_idle(qtbot, window)
    assert calls[1] == (paths, {paths[0]: ['2']})
