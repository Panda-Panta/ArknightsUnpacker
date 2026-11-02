"""Changing a report font refreshes the same owned preview through the real queue."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import threading

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog

from arknights_unpacker.contracts import ExportFormat, OperatorProfile, ReportDocument, ReportOptions
from arknights_unpacker.reports import export_report
from arknights_unpacker.ui.report_preview import ReportArtifactsDialog
from test_explorer import make_window, wait_idle


@pytest.fixture
def fonts():
    paths = [Path('C:/Windows/Fonts/consola.ttf'), Path('C:/Windows/Fonts/arial.ttf')]
    if not all(path.is_file() for path in paths):
        paths = [Path('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'),
                 Path('/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf')]
    if not all(path.is_file() for path in paths):
        pytest.skip('需要两份真实字体比较字形')
    return [str(path) for path in paths]


def setup_preview(qtbot, tmp_path, fonts):
    window, services = make_window(qtbot, tmp_path)
    services.load_data(str(tmp_path))
    calls = []
    control = {'hold': None, 'started': threading.Event(), 'release': threading.Event(), 'fail': False}

    def export(operators, modules, output, formats, **kw):
        options = replace(kw['options'])
        calls.append({'options': options, 'output': Path(output), 'remember': kw['remember_output'],
                      'thread': threading.get_ident()})
        if control['hold'] == options.font_path:
            control['started'].set()
            assert control['release'].wait(5)
        if control['fail']:
            raise ValueError('selected-font failure fixture')
        profile = OperatorProfile('char_fixture', 'Font preview WWW iii', trait='Font glyphs WWW iii ' * 4,
                                  talents=[{'name':'Font annotation', 'description':'Font change Aa Bb 123'}])
        return export_report(ReportDocument(profile.name, operators=[profile], options=options), Path(output), formats,
                             cancel=kw.get('cancel'), emit=kw.get('emit'))

    services.export = export
    options = ReportOptions(width=500, font_size=18, font_path=fonts[0])
    window.export('operators', ['char_fixture'], preview=True, report_options=options)
    wait_idle(qtbot, window)
    dialog = window._dialogs[-1]
    return window, services, dialog, calls, control


def choose(dialog, path, index=0):
    dialog.font_picker.set_font(path, index)
    dialog.font_picker.font_changed.emit(path, index)


def wait_font(qtbot, window, dialog, path):
    qtbot.waitUntil(lambda: not window.queue.busy and dialog.successful_options.font_path == path
                   and dialog.export_button.isEnabled(), timeout=7000)


def test_same_window_refreshes_real_font_pixels_and_formal_export_uses_current_success(qtbot, tmp_path, fonts):
    window, services, dialog, calls, _ = setup_preview(qtbot, tmp_path, fonts)
    initial = Path(dialog.pages.currentData())
    first_digest = sha256(initial.read_bytes()).hexdigest()
    first_root = dialog._preview_lease.path
    dialog.zoom.setValue(120)
    choose(dialog, fonts[1])
    assert not dialog.export_button.isEnabled()
    wait_font(qtbot, window, dialog, fonts[1])
    assert window._dialogs == [dialog]
    assert dialog.zoom.value() == 120
    assert sha256(Path(dialog.pages.currentData()).read_bytes()).hexdigest() != first_digest
    assert not first_root.exists()
    assert all(call['thread'] != threading.get_ident() for call in calls)
    assert services.config.get('report_font_path', '') == ''
    assert window.settings.report_options().font_path == ''
    qtbot.mouseClick(dialog.export_button, Qt.MouseButton.LeftButton)
    wait_idle(qtbot, window)
    assert calls[-1]['remember'] and calls[-1]['options'].font_path == fonts[1]
    assert calls[-1]['options'].font_index == 0
    formal = window._dialogs[-1]
    assert formal is not dialog and formal.font_picker is None


def test_rapid_switches_wait_for_producer_and_apply_only_latest_selection(qtbot, tmp_path, fonts):
    window, services, dialog, calls, control = setup_preview(qtbot, tmp_path, fonts)
    control['hold'] = fonts[1]
    old_path = dialog.pages.currentData()
    choose(dialog, fonts[1])
    qtbot.waitUntil(control['started'].is_set)
    choose(dialog, fonts[0])
    qtbot.wait(180)
    choose(dialog, fonts[1])
    qtbot.wait(180)
    choose(dialog, fonts[0])
    qtbot.wait(180)
    assert len(calls) == 2
    assert dialog.pages.currentData() == old_path
    assert not dialog.export_button.isEnabled()
    control['release'].set()
    wait_font(qtbot, window, dialog, fonts[0])
    assert len(calls) == 3
    assert [call['options'].font_path for call in calls] == [fonts[0], fonts[1], fonts[0]]
    assert window._dialogs == [dialog]
    assert not calls[1]['output'].exists()
    assert calls[-1]['output'].exists()


def test_failed_refresh_keeps_previous_image_and_can_recover(qtbot, tmp_path, fonts, monkeypatch):
    window, services, dialog, calls, control = setup_preview(qtbot, tmp_path, fonts)
    old_path = Path(dialog.pages.currentData())
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (fonts[1], ''))
    control['fail'] = True
    qtbot.mouseClick(dialog.font_picker.choose_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: len(calls) == 2 and not window.queue.busy, timeout=5000)
    assert dialog.pages.currentData() == str(old_path) and old_path.exists()
    assert dialog.successful_options.font_path == fonts[0]
    assert dialog.font_picker.font_path == fonts[0]
    assert dialog.export_button.isEnabled()
    assert '失败' in dialog.font_status.text()
    assert not calls[-1]['output'].exists()
    control['fail'] = False
    qtbot.mouseClick(dialog.font_picker.choose_button, Qt.MouseButton.LeftButton)
    assert not dialog.export_button.isEnabled()
    wait_font(qtbot, window, dialog, fonts[1])
    assert window._dialogs == [dialog]


def test_closing_during_font_refresh_does_not_reopen_and_releases_all_generations(qtbot, tmp_path, fonts):
    window, services, dialog, calls, control = setup_preview(qtbot, tmp_path, fonts)
    first_root = calls[0]['output']
    control['hold'] = fonts[1]
    choose(dialog, fonts[1])
    qtbot.waitUntil(control['started'].is_set)
    active_root = calls[-1]['output']
    choose(dialog, fonts[0])
    qtbot.wait(180)
    dialog.close()
    assert not window._dialogs and not first_root.exists()
    assert active_root.exists(), 'Producer owns its files until settled.'
    control['release'].set()
    wait_idle(qtbot, window)
    qtbot.wait(200)
    assert len(calls) == 2 and not window._dialogs
    assert not active_root.exists() and not window._preview_jobs


def test_open_html_of_replaced_generation_remains_until_shutdown(qtbot, tmp_path, fonts, monkeypatch):
    window, services, dialog, calls, _ = setup_preview(qtbot, tmp_path, fonts)
    opened = []
    dialog.html_open_requested.disconnect()
    dialog.html_open_requested.connect(opened.append)
    old_html = Path(dialog.html_files.currentData())
    assert old_html.is_file()
    dialog.request_html()
    assert opened == [str(old_html)]
    choose(dialog, fonts[1])
    wait_font(qtbot, window, dialog, fonts[1])
    new_root = calls[-1]['output']
    dialog.close()
    assert old_html.exists() and not new_root.exists()
    window.close()
    assert not calls[0]['output'].exists()


def test_changed_source_binding_rejects_font_refresh_without_new_export(qtbot, tmp_path, fonts):
    window, services, dialog, calls, _ = setup_preview(qtbot, tmp_path, fonts)
    services.gamedata.snapshot_id = 'new-source'
    choose(dialog, fonts[1])
    qtbot.waitUntil(lambda: '失败' in dialog.font_status.text(), timeout=3000)
    assert len(calls) == 1
    assert dialog.font_picker.font_path == fonts[0]
    assert dialog.successful_options.font_path == fonts[0]
    assert Path(dialog.pages.currentData()).exists()


def test_closing_queued_font_refresh_cleans_only_its_lease(qtbot, tmp_path, fonts):
    window, services, dialog, calls, _ = setup_preview(qtbot, tmp_path, fonts)
    started, release = threading.Event(), threading.Event()

    def unrelated(**kw):
        started.set()
        assert release.wait(5)
        kw['cancel'].check()

    other = window.queue.submit('unrelated retained task', unrelated)
    qtbot.waitUntil(started.is_set)
    choose(dialog, fonts[1])
    try:
        qtbot.waitUntil(lambda: any(job.status == '排队中' and (job.request or {}).get('preview')
                                   for job in window.queue.jobs), timeout=3000)
        pending = next(job for job in window.queue.jobs if job.status == '排队中')
        root = window._preview_jobs[pending.job_id].path
        dialog.close()
        assert pending.status == '已取消'
        assert not root.exists()
        assert window.queue.active is other and not other.token.cancelled
        assert len(calls) == 1
    finally:
        release.set()
        wait_idle(qtbot, window)
    assert len(calls) == 1


def test_collection_face_index_is_preserved_for_preview_and_formal_export(qtbot, tmp_path, fonts):
    collection = Path('C:/Windows/Fonts/msyh.ttc')
    if not collection.is_file():
        pytest.skip('需要本机微软雅黑TTC两字形')
    window, services, dialog, calls, _ = setup_preview(qtbot, tmp_path, fonts)
    choose(dialog, str(collection), 1)
    wait_font(qtbot, window, dialog, str(collection))
    assert dialog.successful_options.font_index == 1
    assert calls[-1]['options'].font_index == 1
    qtbot.mouseClick(dialog.export_button, Qt.MouseButton.LeftButton)
    wait_idle(qtbot, window)
    assert calls[-1]['remember']
    assert calls[-1]['options'].font_path == str(collection)
    assert calls[-1]['options'].font_index == 1
