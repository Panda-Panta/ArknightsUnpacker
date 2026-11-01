"""Automatic object selection and embedded preview ownership use real Qt events."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from arknights_unpacker.ui.preview_cache import PreviewCache
from arknights_unpacker.ui.report_preview import ObjectsDialog


def rows():
    return [{'id': 'unknown', 'type': 'MonoBehaviour', 'name': '配置'},
            {'id': 'unsupported-video', 'type': 'VideoClip', 'previewable': False},
            {'id': 'image', 'type': 'Texture2D', 'name': '立绘'},
            {'id': 'text', 'type': 'TextAsset', 'name': '说明'},
            {'id': 'audio', 'type': 'AudioClip', 'name': '语音'}]


def owned_text(cache, name, text):
    lease = cache.allocate('objects')
    path = lease.path / name
    path.write_text(text, encoding='utf-8')
    lease.finish()
    return lease, path


def test_object_discovery_automatically_previews_first_supported_object(qtbot, tmp_path):
    dialog = ObjectsDialog(str(tmp_path / 'fixture.ab'))
    qtbot.addWidget(dialog)
    requests = []
    dialog.extract_requested.connect(lambda source, ids, preview: requests.append((source, ids, preview)))
    dialog.set_objects(rows())
    qtbot.waitUntil(lambda: bool(requests), timeout=1500)
    assert requests == [(str(tmp_path / 'fixture.ab'), ['image'], True)]
    assert dialog.auto_preview.isChecked()


def test_selection_changes_debounce_and_multi_selection_never_auto_previews(qtbot, tmp_path):
    dialog = ObjectsDialog(str(tmp_path / 'fixture.ab'))
    qtbot.addWidget(dialog)
    requests = []
    dialog.extract_requested.connect(lambda source, ids, preview: requests.append(ids))
    dialog.set_objects(rows())
    qtbot.waitUntil(lambda: bool(requests), timeout=1500)
    generation = dialog.preview_generation
    dialog.table.selectRow(3)
    assert dialog.preview_generation > generation
    dialog.table.selectRow(4)
    qtbot.waitUntil(lambda: len(requests) == 2, timeout=1500)
    assert requests == [['image'], ['audio']]
    dialog.table.selectAll()
    qtbot.wait(350)
    assert requests == [['image'], ['audio']]
    dialog.table.clearSelection()
    qtbot.wait(350)
    assert requests == [['image'], ['audio']]


def test_auto_preview_can_be_disabled_while_manual_preview_and_extraction_remain(qtbot, tmp_path):
    dialog = ObjectsDialog(str(tmp_path / 'fixture.ab'), auto_preview=False)
    qtbot.addWidget(dialog)
    requests = []
    dialog.extract_requested.connect(lambda source, ids, preview: requests.append((ids, preview)))
    dialog.set_objects(rows())
    dialog.table.selectRow(3)
    qtbot.wait(350)
    assert requests == []
    dialog.request(True)
    dialog.table.selectAll()
    dialog.request(False)
    assert requests[0] == (['text'], True)
    assert set(requests[1][0]) == {row['id'] for row in rows()} and requests[1][1] is False
    dialog.table.selectRow(4)
    dialog.auto_preview.setChecked(True)
    qtbot.waitUntil(lambda: len(requests) == 3, timeout=1500)
    assert requests[-1] == (['audio'], True)


def test_stale_results_and_failures_cannot_replace_the_current_embedded_preview(qtbot, tmp_path):
    cache = PreviewCache(tmp_path / 'data')
    dialog = ObjectsDialog(str(tmp_path / 'fixture.ab'), auto_preview=False)
    qtbot.addWidget(dialog)
    dialog.set_objects(rows())
    dialog.table.selectRow(2)
    first_generation = dialog.preview_generation
    first, first_path = owned_text(cache, 'first.txt', 'first selected object')
    assert dialog.show_files([{'path': str(first_path)}], preview_lease=first, generation=first_generation)
    dialog.table.selectRow(3)
    assert not first_path.exists()
    current, current_path = owned_text(cache, 'current.txt', 'current selected object')
    assert dialog.show_files([{'path': str(current_path)}], preview_lease=current, generation=dialog.preview_generation)
    late, late_path = owned_text(cache, 'late.txt', 'stale object')
    assert not dialog.show_files([str(late_path)], preview_lease=late, generation=first_generation)
    dialog.preview_failed('outdated failure', generation=first_generation)
    assert dialog.preview.toPlainText() == 'current selected object'
    assert current_path.exists() and not late_path.exists()
    dialog.close()
    assert not current_path.exists()


def test_panel_stops_media_before_releasing_replaced_or_closed_preview_leases(qtbot, tmp_path, monkeypatch):
    cache = PreviewCache(tmp_path / 'data')
    dialog = ObjectsDialog(str(tmp_path / 'fixture.ab'), auto_preview=False)
    qtbot.addWidget(dialog)
    first, first_path = owned_text(cache, 'first.txt', 'first')
    second, second_path = owned_text(cache, 'second.txt', 'second')
    dialog.show_file(first_path, preview_lease=first)
    events = []
    clear = dialog.preview_panel.clear
    shutdown = dialog.preview_panel.shutdown
    first_release, second_release = first.release, second.release
    monkeypatch.setattr(dialog.preview_panel, 'clear', lambda: (events.append('clear'), clear())[-1])
    monkeypatch.setattr(dialog.preview_panel, 'shutdown', lambda: (events.append('shutdown'), shutdown())[-1])
    monkeypatch.setattr(first, 'release', lambda: (events.append('release-first'), first_release())[-1])
    monkeypatch.setattr(second, 'release', lambda: (events.append('release-second'), second_release())[-1])
    dialog.show_file(second_path, preview_lease=second)
    assert events.index('clear') < events.index('release-first')
    events.clear()
    dialog.close()
    assert events.index('shutdown') < events.index('release-second')


def test_right_preview_uses_available_height_and_fits_new_image(qtbot, tmp_path):
    image_path = tmp_path / 'large.png'
    image = QImage(2400, 1800, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.cyan)
    assert image.save(str(image_path))
    dialog = ObjectsDialog(str(tmp_path / 'fixture.ab'), auto_preview=False)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.show_file(image_path)
    qtbot.waitUntil(lambda: dialog.picture.pixmap() is not None and not dialog.picture.pixmap().isNull())
    qtbot.waitUntil(lambda: dialog.picture.width() <= dialog.image_scroll.viewport().width() and
                   dialog.picture.height() <= dialog.image_scroll.viewport().height(), timeout=1500)
    assert dialog.splitter.widget(1) is dialog.preview_panel
    assert dialog.image_scroll.maximumHeight() > 320
    assert dialog.image_scroll.height() > 320
    dialog.image_zoom.setValue(150)
    qtbot.wait(20)
    assert dialog.picture.width() == 3600


def test_close_cancels_pending_auto_preview_and_rejects_late_files(qtbot, tmp_path):
    dialog = ObjectsDialog(str(tmp_path / 'fixture.ab'))
    qtbot.addWidget(dialog)
    requests = []
    dialog.extract_requested.connect(lambda *args: requests.append(args))
    dialog.set_objects(rows())
    generation = getattr(dialog, 'preview_generation', 0)
    dialog.close()
    qtbot.wait(350)
    assert requests == []
    cache = PreviewCache(tmp_path / 'data')
    late, late_path = owned_text(cache, 'late.txt', 'late')
    assert not dialog.show_files([late_path], preview_lease=late, generation=generation)
    assert not late_path.exists() and dialog.preview_closed
