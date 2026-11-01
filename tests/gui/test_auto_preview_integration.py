"""Automatic object previews through the real window, queue and cache lifecycle."""
import threading
from pathlib import Path

from PySide6.QtCore import Qt

from arknights_unpacker.contracts import ExtractionResult
from test_explorer import make_window, wait_idle


def objects(*names):
    return [{'id': name, 'type': 'TextAsset', 'name': name, 'logical_path': name + '.json'} for name in names]


def test_opening_objects_previews_decoded_result_independent_of_export_settings(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    package = tmp_path / 'fixture.ab'
    package.write_bytes(b'unchanged input')
    services.objects = lambda *a, **kw: objects('first')
    calls = []

    def extract(paths, output, **kwargs):
        calls.append(kwargs)
        raw, decoded = Path(output) / 'first.bytes', Path(output) / 'first.json'
        raw.write_bytes(b'\x00\xff\x00encoded')
        decoded.write_text('{"decoded": "readable result"}', encoding='utf-8')
        return ExtractionResult(outputs=[{'path': str(raw), 'kind': 'text_raw'},
                                         {'path': str(decoded), 'kind': 'text_json'}])

    services.extract = extract
    window.settings.mode.setCurrentIndex(window.settings.mode.findData('raw'))
    for check in window.settings.kinds.values():
        check.setChecked(False)
    window.objects(str(package))
    qtbot.waitUntil(lambda: bool(calls), timeout=2500)
    wait_idle(qtbot, window)
    dialog = window._dialogs[-1]
    qtbot.waitUntil(lambda: 'readable result' in dialog.preview.toPlainText())
    assert dialog.preview_panel.current_path.name == 'first.json'
    assert calls[0]['mode'] == 'auto' and calls[0]['kinds'] == ['text']
    assert calls[0]['remember_output'] is False
    assert services.config['output_root'] == str(tmp_path / 'exports')
    assert package.read_bytes() == b'unchanged input'


def test_fast_selection_coalesces_to_latest_without_displaying_stale_result(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    services.objects = lambda *a, **kw: objects('first', 'middle', 'latest')
    started, release = threading.Event(), threading.Event()
    calls = []
    paths = []

    def extract(sources, output, **kwargs):
        name = kwargs['object_ids'][sources[0]][0]
        calls.append(name)
        if name == 'first':
            started.set()
            assert release.wait(8)
        target = Path(output) / (name + '.json')
        target.write_text(name, encoding='utf-8')
        paths.append(target)
        return ExtractionResult(outputs=[{'path': str(target), 'kind': 'text_json'}])

    services.extract = extract
    window.objects(str(tmp_path / 'fixture.ab'), auto_preview=False)
    wait_idle(qtbot, window)
    dialog = window._dialogs[-1]
    dialog.table.selectRow(0)
    dialog.request(True)
    try:
        qtbot.waitUntil(started.is_set)
        dialog.auto_preview.setChecked(True)
        dialog.table.selectRow(1)
        qtbot.wait(320)
        dialog.table.selectRow(2)
        qtbot.wait(320)
        assert calls == ['first']
        release.set()
        qtbot.waitUntil(lambda: dialog.preview.toPlainText() == 'latest', timeout=8000)
        wait_idle(qtbot, window)
        assert calls == ['first', 'latest']
        assert not paths[0].exists()
        assert paths[-1].exists()
        assert not window._object_preview_jobs and not window._object_preview_pending
    finally:
        release.set()
        wait_idle(qtbot, window)


def test_closing_objects_drops_pending_preview_without_reopening(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    services.objects = lambda *a, **kw: objects('first', 'latest')
    started, release = threading.Event(), threading.Event()
    calls, roots = [], []

    def extract(sources, output, **kwargs):
        calls.append(kwargs['object_ids'][sources[0]][0])
        roots.append(Path(output))
        started.set()
        assert release.wait(8)
        path = Path(output) / 'object.txt'
        path.write_text('late output', encoding='utf-8')
        return ExtractionResult(outputs=[{'path': str(path)}])

    services.extract = extract
    window.objects(str(tmp_path / 'fixture.ab'), auto_preview=False)
    wait_idle(qtbot, window)
    dialog = window._dialogs[-1]
    dialog.table.selectRow(0)
    dialog.request(True)
    try:
        qtbot.waitUntil(started.is_set)
        dialog.auto_preview.setChecked(True)
        dialog.table.selectRow(1)
        qtbot.wait(320)
        dialog.close()
        release.set()
        wait_idle(qtbot, window)
        qtbot.wait(50)
        assert calls == ['first']
        assert not window._dialogs and not window._object_preview_pending
        assert all(not root.exists() for root in roots)
    finally:
        release.set()
        wait_idle(qtbot, window)


def test_video_setting_legacy_default_and_explicit_disabled_roundtrip(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    assert window.settings.kinds['video'].isChecked()
    window.settings.kinds['video'].setChecked(False)
    window.settings.commit()
    assert services.config['extraction_video'] is False
    from arknights_unpacker.ui.settings import SettingsView
    restored = SettingsView(services.config, services.data_root)
    qtbot.addWidget(restored)
    assert not restored.kinds['video'].isChecked()
