"""Exercise temporary preview ownership through the real Qt window and queue.

The tiny service writes a local file instead of invoking the Unity worker; the
window/dialog lifecycle and resulting filesystem assertions are real.
"""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QFileDialog, QMessageBox

from arknights_unpacker.contracts import ExtractionResult, ReportArtifact
from arknights_unpacker.ui.preview_cache import PreviewCache, legacy_preview_paths
from arknights_unpacker.ui.report_preview import ObjectsDialog, ReportArtifactsDialog
from test_explorer import make_window, wait_idle


def test_object_preview_cache_is_removed_when_its_dialog_closes(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    package = tmp_path / 'game' / 'fixture.ab'
    package.parent.mkdir()
    package.write_bytes(b'fixture-package-stays-read-only')
    output_roots = []

    def extract(paths, output, **kwargs):
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        text = output / 'object.txt'
        text.write_text('actual object preview file', encoding='utf-8')
        output_roots.append(output)
        return ExtractionResult(status='succeeded', outputs=[{'path': str(text)}])

    services.extract = extract
    window.objects(str(package))
    wait_idle(qtbot, window)
    dialog = window._dialogs[-1]
    dialog.table.selectRow(0)
    dialog.request(True)
    wait_idle(qtbot, window)

    cache = output_roots[0]
    assert cache.is_relative_to(services.data_root / 'preview')
    assert (cache / 'object.txt').read_text(encoding='utf-8') in dialog.preview.toPlainText()
    assert cache.exists(), 'A currently displayed preview must stay usable.'
    dialog.close()
    assert not cache.exists(), 'Closing its only preview window should release the temporary files.'
    assert package.read_bytes() == b'fixture-package-stays-read-only'


def test_switching_display_releases_only_the_previous_owned_preview(qtbot, tmp_path):
    cache = PreviewCache(tmp_path / 'data')
    dialog = ObjectsDialog(str(tmp_path / 'game' / 'fixture.ab'))
    qtbot.addWidget(dialog)
    first, second = cache.allocate('objects'), cache.allocate('objects')
    for lease, content in [(first, 'first'), (second, 'second')]:
        (lease.path / 'object.txt').write_text(content, encoding='utf-8')
        dialog.track_preview(lease)
        lease.finish()
    dialog.show_file(first.path / 'object.txt', preview_lease=first)
    assert first.path.exists()
    dialog.show_file(second.path / 'object.txt', preview_lease=second)
    assert not first.path.exists()
    assert second.path.exists()
    assert dialog.preview.toPlainText() == 'second'
    external = tmp_path / 'exports' / 'user-copy.txt'
    external.parent.mkdir()
    external.write_text('formal user file', encoding='utf-8')
    dialog.show_file(external)
    assert not second.path.exists()
    dialog.close()
    assert external.read_text(encoding='utf-8') == 'formal user file'


def test_closed_dialog_does_not_accept_late_producer_results(qtbot, tmp_path):
    cache = PreviewCache(tmp_path / 'data')
    lease = cache.allocate('objects')
    source = lease.path / 'late.txt'
    source.write_text('late producer result', encoding='utf-8')
    dialog = ObjectsDialog(str(tmp_path / 'fixture.ab'))
    qtbot.addWidget(dialog)
    dialog.track_preview(lease)
    original = dialog.preview.toPlainText()
    dialog.reject()
    assert dialog.preview_closed and source.exists()
    dialog.show_file(source, preview_lease=lease)
    assert dialog.preview.toPlainText() == original
    lease.finish()
    assert not lease.path.exists()


def test_report_dialog_releases_cache_but_keeps_original_saved_copy(qtbot, tmp_path, monkeypatch):
    cache = PreviewCache(tmp_path / 'data')
    lease = cache.allocate('reports')
    source = lease.path / 'page.png'
    image = QImage(173, 89, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.cyan)
    image.setText('source-note', 'keep original metadata')
    assert image.save(str(source))
    expected = source.read_bytes()
    dialog = ReportArtifactsDialog([ReportArtifact(str(source), 'png')], preview_only=True, preview_lease=lease)
    qtbot.addWidget(dialog)
    lease.finish()
    dialog.zoom.setValue(25)
    forbidden = cache.roots[0] / 'manual-copy.png'
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(str(args[-1])))
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args, **kwargs: (str(forbidden), ''))
    dialog.save_original()
    assert not forbidden.exists() and '预览缓存' in warnings[-1]
    saved = tmp_path / 'exports' / 'saved-original.png'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args, **kwargs: (str(saved), ''))
    dialog.save_original()
    dialog.close()
    assert not lease.path.exists()
    assert saved.read_bytes() == expected


def test_report_html_open_keeps_cache_until_program_shutdown(qtbot, tmp_path):
    cache = PreviewCache(tmp_path / 'data')
    lease = cache.allocate('reports')
    html = lease.path / 'report.html'
    html.write_text('<html><body>offline preview</body></html>', encoding='utf-8')
    dialog = ReportArtifactsDialog([ReportArtifact(str(html), 'html')], preview_only=True, preview_lease=lease)
    qtbot.addWidget(dialog)
    lease.finish()
    opened = []
    dialog.html_open_requested.connect(opened.append)
    dialog.request_html()
    dialog.close()
    assert opened == [str(html)]
    assert html.exists()
    cache.shutdown()
    assert not lease.path.exists()


def test_legacy_output_helper_never_owns_an_ordinary_export(tmp_path):
    import json
    data = tmp_path / 'data'
    history = data / 'queue'
    history.mkdir(parents=True)
    output = data / 'previews' / ('a' * 32)
    identifier = 'b' * 32
    record = {'schema': 1, 'job_id': identifier, 'title': '导出选中资料', 'output': str(output),
              'request': {'operation': 'report', 'preview': False, 'output': str(output)}}
    target = history / (identifier + '.json')
    target.write_text(json.dumps(record), encoding='utf-8')
    assert not legacy_preview_paths(data, history)
    record['request']['preview'] = True
    target.write_text(json.dumps(record), encoding='utf-8')
    assert legacy_preview_paths(data, history) == {output}
