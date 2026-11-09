"""Export progress must not replace the page the user is working in."""
from pathlib import Path
import threading

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from arknights_unpacker.contracts import GameInstallation, ReportArtifact
from arknights_unpacker.ui.models import selected_records
from test_explorer import make_window, wait_idle


def prepared_window(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    services.load_data(str(tmp_path))
    window.refresh_entities()
    window.operators.table.selectRow(0)
    window.modules.table.selectRow(0)
    wait_idle(qtbot, window)
    calls = []
    control = {'started': threading.Event(), 'release': threading.Event(), 'blocked': False, 'fail': False}

    def export(operators, modules, output, formats, **kw):
        calls.append((operators, modules, output, kw['options']))
        control['started'].set()
        if control['blocked']:
            assert control['release'].wait(5)
        if control['fail']:
            raise ValueError('page-focus failure fixture')
        root = Path(output)
        root.mkdir(parents=True, exist_ok=True)
        png = root / 'page.png'
        image = QImage(40, 80, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.cyan)
        assert image.save(str(png))
        html = root / 'page.html'
        html.write_text('<html><body>page focus fixture</body></html>', 'utf-8')
        return [ReportArtifact(str(png), 'png'), ReportArtifact(str(html), 'html')]

    services.export = export
    return window, services, control, calls


def selection(window):
    return [[row['id'] for row in selected_records(view.table)] for view in (window.operators, window.modules)]


@pytest.mark.parametrize('page', ['operators', 'modules', 'settings'])
@pytest.mark.parametrize('preview', [False, True])
@pytest.mark.parametrize('fail', [False, True])
def test_report_keeps_current_page_and_selected_entities_through_success_or_failure(qtbot, tmp_path, page, preview, fail):
    window, services, control, calls = prepared_window(qtbot, tmp_path)
    window.pages.select(page)
    widget = window.tabs.currentWidget()
    selected = selection(window)
    kind = 'modules' if page == 'modules' else 'operators'
    identity = 'equip_fixture' if kind == 'modules' else 'char_fixture'
    control.update(blocked=True, fail=fail)
    window.export(kind, [identity], preview=preview)
    try:
        qtbot.waitUntil(control['started'].is_set)
        assert window.tabs.currentWidget() is widget
        assert window.pages.current_id() == page
        assert selection(window) == selected
    finally:
        control['release'].set()
        wait_idle(qtbot, window)
    assert window.tabs.currentWidget() is widget and window.pages.current_id() == page
    assert selection(window) == selected
    assert len(calls) == 1
    assert bool(window._dialogs) == (not fail)


def test_preview_font_refresh_and_export_button_preserve_underlying_page(qtbot, tmp_path):
    window, services, control, calls = prepared_window(qtbot, tmp_path)
    window.pages.select('operators')
    operator_widget = window.tabs.currentWidget()
    selected = selection(window)
    qtbot.mouseClick(window.operators.preview_selected, Qt.MouseButton.LeftButton)
    wait_idle(qtbot, window)
    assert window.tabs.currentWidget() is operator_widget
    dialog = window._dialogs[-1]
    window.pages.select('settings')
    settings_widget = window.tabs.currentWidget()
    dialog.font_picker.path_edit.setText('fixture-font.ttf')
    qtbot.waitUntil(lambda: len(calls) == 2 and not window.queue.busy, timeout=5000)
    assert dialog.export_button.isEnabled()
    assert window._dialogs == [dialog]
    assert window.tabs.currentWidget() is settings_widget
    assert selection(window) == selected
    qtbot.mouseClick(dialog.export_button, Qt.MouseButton.LeftButton)
    wait_idle(qtbot, window)
    assert len(calls) == 3 and calls[-1][3].font_path == 'fixture-font.ttf'
    assert window.tabs.currentWidget() is settings_widget
    assert selection(window) == selected


def test_manual_tasks_page_keeps_active_reports_and_hides_internal_reads(qtbot, tmp_path):
    window, services, control, calls = prepared_window(qtbot, tmp_path)
    window.pages.select('operators')
    services.restore = lambda root, **kw: {'snapshot': None}
    game = tmp_path / 'game'
    game.mkdir()
    services.installation = GameInstallation(game, 'fixture-profile')
    window.root_edit.setText(str(game))
    window.restore_previous()
    wait_idle(qtbot, window)
    package = game / 'fixture.ab'
    package.write_bytes(b'objects fixture')
    window.objects(str(package), auto_preview=False)
    wait_idle(qtbot, window)
    object_dialog = window._dialogs[-1]
    object_dialog.close()
    window.preview_reports('operators', ['char_fixture'])
    wait_idle(qtbot, window)
    preview = window._dialogs[-1]
    qtbot.mouseClick(preview.export_button, Qt.MouseButton.LeftButton)
    wait_idle(qtbot, window)
    window.pages.select('jobs')
    assert window.tabs.currentWidget() is window.jobs
    titles = [window.jobs.table.item(row, 0).text() for row in range(window.jobs.table.rowCount())]
    assert any(title.startswith('预览选中资料') for title in titles)
    assert any(title.startswith('导出选中资料') for title in titles)
    assert not any(title.startswith(('查看资料', '读取内部对象', '读取上次扫描')) for title in titles)
    count = len(window._dialogs)
    row = next(index for index, title in enumerate(titles) if title.startswith('预览选中资料'))
    window.jobs.table.selectRow(row)
    window.jobs.preview_artifacts()
    assert len(window._dialogs) == count and preview.isVisible()
