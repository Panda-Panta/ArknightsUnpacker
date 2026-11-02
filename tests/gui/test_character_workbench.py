"""Automatic composition previews bind export to the latest successful options."""
from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QPushButton

from arknights_unpacker.ui.character_workbench import CharacterWorkbench
from arknights_unpacker.ui.preview_cache import PreviewCache


def catalog():
    return {'groups': [
        {'id': '0:0', 'title': '姿态一', 'face_pos': [462, 116], 'face_size': [86, 89],
         'base_id': '0:0:2', 'entries': [
             {'id': '0:0:0', 'name': '微笑', 'alias': 'smile', 'role': 'face', 'width': 128, 'height': 128},
             {'id': '0:0:1', 'name': '全身变体', 'alias': '', 'role': 'whole', 'width': 1024, 'height': 1024},
             {'id': '0:0:2', 'name': '底图', 'alias': '', 'role': 'base', 'width': 1024, 'height': 1024}]},
        {'id': '0:1', 'title': '姿态二', 'face_pos': [12, 20], 'face_size': [42, 53],
         'base_id': '0:1:1', 'entries': [
             {'id': '0:1:0', 'name': '惊讶', 'alias': '', 'role': 'face', 'width': 64, 'height': 64},
             {'id': '0:1:1', 'name': '第二底图', 'alias': '', 'role': 'base', 'width': 1280, 'height': 1280}]}],
        'diagnostics': []}


def make_dialog(qtbot, tmp_path):
    dialog = CharacterWorkbench(str(tmp_path / 'fixture.ab'))
    qtbot.addWidget(dialog)
    return dialog


def automatic_catalog(dialog, qtbot, data=None):
    requests = []
    dialog.preview_requested.connect(requests.append)
    dialog.set_catalog(catalog() if data is None else data)
    qtbot.waitUntil(lambda: len(requests) == 1, timeout=1500)
    return requests


def preview_png(cache, name='composition.png'):
    lease = cache.allocate('objects')
    path = lease.path / name
    image = QImage(64, 96, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    image.setPixelColor(10, 10, Qt.GlobalColor.red)
    assert image.save(str(path))
    lease.finish()
    return lease, path


def test_manual_preview_button_is_absent_and_empty_catalog_never_submits(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    assert not hasattr(dialog, 'preview_button')
    assert all(button.text() != '预览合成' and button.objectName() != 'previewCharacterComposition'
               for button in dialog.findChildren(QPushButton))
    requests = []
    dialog.preview_requested.connect(requests.append)
    assert not dialog.export_button.isEnabled() and not dialog.batch_button.isEnabled()
    dialog.set_catalog({'groups': [], 'diagnostics': ['引用的图片位于未安装依赖包']})
    assert '引用的图片位于未安装依赖包' in dialog.diagnostics.text()
    dialog.load_failed('无法读取角色配置')
    qtbot.wait(400)
    assert requests == [] and not dialog.batch_button.isEnabled()
    assert '无法读取角色配置' in dialog.status.text()
    dialog.close()


def test_catalog_load_and_group_switch_automatically_preview_correct_defaults(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    data = catalog()
    original = deepcopy(data)
    requests = automatic_catalog(dialog, qtbot, data)
    assert requests == [{'group_id': '0:0', 'base_id': '0:0:2', 'face_id': '0:0:0',
                         'x': 462, 'y': 116, 'width': 86, 'height': 89}]
    dialog.group_choice.setCurrentIndex(1)
    qtbot.waitUntil(lambda: len(requests) == 2, timeout=1500)
    assert requests[1] == {'group_id': '0:1', 'base_id': '0:1:1', 'face_id': '0:1:0',
                           'x': 12, 'y': 20, 'width': 42, 'height': 53}
    assert data == original
    dialog.close()


def test_continuous_edits_debounce_to_latest_options_and_reset_is_automatic(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    requests = automatic_catalog(dialog, qtbot)
    exports = []
    dialog.export_requested.connect(exports.append)
    dialog.base_choice.setCurrentIndex(dialog.base_choice.findData('0:0:1'))
    dialog.x_spin.setValue(-20)
    dialog.y_spin.setValue(350)
    dialog.width_spin.setValue(100)
    dialog.height_spin.setValue(140)
    assert len(requests) == 1 and not dialog.export_button.isEnabled()
    qtbot.waitUntil(lambda: len(requests) == 2, timeout=1500)
    assert requests[1] == {'group_id': '0:0', 'base_id': '0:0:1', 'face_id': '0:0:0',
                           'x': -20, 'y': 350, 'width': 100, 'height': 140}
    qtbot.wait(350)
    assert len(requests) == 2
    dialog.export_button.click()
    assert exports == []
    dialog.reset_button.click()
    qtbot.waitUntil(lambda: len(requests) == 3, timeout=1500)
    assert requests[2] == requests[0]
    dialog.close()


def test_typing_a_position_previews_after_pause_without_leaving_the_field(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    requests = automatic_catalog(dialog, qtbot)
    dialog.show()
    dialog.x_spin.setFocus()
    dialog.x_spin.selectAll()
    qtbot.keyClicks(dialog.x_spin, '507')
    qtbot.waitUntil(lambda: len(requests) == 2, timeout=1500)
    assert requests[1]['x'] == 507
    assert dialog.x_spin.hasFocus()
    qtbot.wait(350)
    assert len(requests) == 2
    dialog.close()


def test_successful_auto_preview_unlocks_export_until_parameters_change(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    requests = automatic_catalog(dialog, qtbot)
    exports = []
    dialog.export_requested.connect(exports.append)
    cache = PreviewCache(tmp_path / 'data')
    lease, path = preview_png(cache)
    dialog.track_preview(lease)
    assert dialog.show_files([{'path': str(path), 'kind': 'character_expression'}], lease, dialog.preview_generation)
    assert dialog.preview_panel.image_path == path.resolve()
    dialog.export_button.click()
    assert exports == requests and exports[0] is not dialog.successful_options
    dialog.x_spin.setValue(463)
    assert not dialog.export_button.isEnabled() and not path.exists()
    dialog.export_button.click()
    assert len(exports) == 1
    qtbot.waitUntil(lambda: len(requests) == 2, timeout=1500)
    assert requests[1]['x'] == 463
    dialog.close()


def test_stale_result_cannot_replace_latest_auto_preview_or_unlock_export(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    requests = automatic_catalog(dialog, qtbot)
    old = dialog.preview_generation
    dialog.y_spin.setValue(200)
    assert dialog.preview_generation > old
    qtbot.waitUntil(lambda: len(requests) == 2, timeout=1500)
    cache = PreviewCache(tmp_path / 'data')
    first, first_path = preview_png(cache, 'old.png')
    assert not dialog.show_files([{'path': str(first_path)}], first, old)
    assert not first_path.exists() and not dialog.export_button.isEnabled()
    current, current_path = preview_png(cache, 'current.png')
    assert dialog.show_files([{'path': str(current_path)}], current, dialog.preview_generation)
    status = dialog.status.text()
    dialog.preview_failed('过期失败', generation=old)
    assert dialog.status.text() == status and dialog.export_button.isEnabled()
    dialog.close()
    assert not current_path.exists()


def test_whole_body_and_no_face_choices_automatically_preview_without_overlay_controls(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    requests = automatic_catalog(dialog, qtbot)
    dialog.face_choice.setCurrentIndex(dialog.face_choice.findData('0:0:1'))
    assert not dialog.x_spin.isEnabled() and not dialog.width_spin.isEnabled()
    assert '整幅' in dialog.placement_hint.text()
    qtbot.waitUntil(lambda: len(requests) == 2, timeout=1500)
    assert requests[1]['face_id'] == '0:0:1'
    dialog.face_choice.setCurrentIndex(dialog.face_choice.findData(''))
    assert not dialog.y_spin.isEnabled()
    qtbot.waitUntil(lambda: len(requests) == 3, timeout=1500)
    assert requests[2]['face_id'] == ''
    dialog.face_choice.setCurrentIndex(dialog.face_choice.findData('0:0:0'))
    qtbot.waitUntil(lambda: len(requests) == 4, timeout=1500)
    assert dialog.x_spin.isEnabled() and dialog.width_spin.minimum() == 1
    dialog.close()


def test_batch_uses_config_only_while_manual_edit_has_an_automatic_preview(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    requests = automatic_catalog(dialog, qtbot)
    batches, exports = [], []
    dialog.batch_requested.connect(lambda: batches.append('batch'))
    dialog.export_requested.connect(exports.append)
    dialog.x_spin.setValue(-99)
    dialog.batch_button.click()
    assert batches == ['batch'] and exports == []
    qtbot.waitUntil(lambda: len(requests) == 2, timeout=1500)
    assert requests[1]['x'] == -99 and batches == ['batch']
    dialog.close()


def test_close_stops_pending_auto_preview_before_it_submits(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    requests = []
    dialog.preview_requested.connect(requests.append)
    dialog.set_catalog(catalog())
    dialog.x_spin.setValue(99)
    dialog.close()
    qtbot.wait(400)
    assert dialog.preview_closed and requests == []


def test_close_releases_current_and_inflight_leases_after_stopping_preview(qtbot, tmp_path, monkeypatch):
    dialog = make_dialog(qtbot, tmp_path)
    automatic_catalog(dialog, qtbot)
    cache = PreviewCache(tmp_path / 'data')
    shown, path = preview_png(cache)
    pending = cache.allocate('objects')
    dialog.track_preview(shown)
    dialog.track_preview(pending)
    assert dialog.show_files([{'path': str(path)}], shown, dialog.preview_generation)
    events = []
    shutdown = dialog.preview_panel.shutdown
    shown_release, pending_release = shown.release, pending.release
    monkeypatch.setattr(dialog.preview_panel, 'shutdown', lambda: (events.append('shutdown'), shutdown())[-1])
    monkeypatch.setattr(shown, 'release', lambda: (events.append('shown'), shown_release())[-1])
    monkeypatch.setattr(pending, 'release', lambda: (events.append('pending'), pending_release())[-1])
    dialog.close()
    assert events.index('shutdown') < events.index('shown') and events.index('shutdown') < events.index('pending')
    assert not path.exists()
    pending.finish()
    assert not pending.path.exists()
    late, late_path = preview_png(cache, 'late.png')
    assert not dialog.show_files([{'path': str(late_path)}], late, dialog.preview_generation)
    assert not late_path.exists()


def test_failed_auto_preview_does_not_loop_but_reset_and_edits_can_retry(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    requests = automatic_catalog(dialog, qtbot)
    dialog.preview_failed('所选表情引用了缺失的图片', generation=dialog.preview_generation)
    qtbot.wait(600)
    assert len(requests) == 1 and '缺失' in dialog.status.text()
    assert dialog.batch_button.isEnabled() and not dialog.export_button.isEnabled()
    dialog.reset_button.click()
    qtbot.waitUntil(lambda: len(requests) == 2, timeout=1500)
    assert requests[1] == requests[0]
    dialog.x_spin.setValue(500)
    qtbot.waitUntil(lambda: len(requests) == 3, timeout=1500)
    assert requests[2]['x'] == 500
    dialog.close()


def test_return_with_successful_auto_preview_does_not_export_or_resubmit(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    requests = automatic_catalog(dialog, qtbot)
    cache = PreviewCache(tmp_path / 'data')
    lease, path = preview_png(cache)
    assert dialog.show_files([{'path': str(path)}], lease, dialog.preview_generation)
    exports, batches = [], []
    dialog.export_requested.connect(exports.append)
    dialog.batch_requested.connect(lambda: batches.append(True))
    dialog.show()
    for control in (dialog.base_choice, dialog.face_choice, dialog.x_spin):
        control.setFocus()
        qtbot.keyClick(control, Qt.Key.Key_Return)
        assert dialog.isVisible()
    qtbot.wait(350)
    assert len(requests) == 1 and exports == [] and batches == []
    dialog.close()


def test_non_image_auto_result_fails_without_unlocking_export_or_looping(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    requests = automatic_catalog(dialog, qtbot)
    cache = PreviewCache(tmp_path / 'data')
    lease = cache.allocate('objects')
    path = lease.path / 'result.json'
    path.write_text('{"diagnostics": []}', 'utf-8')
    lease.finish()
    assert not dialog.show_files([{'path': str(path)}], lease, dialog.preview_generation)
    assert '没有生成' in dialog.status.text()
    assert not dialog.export_button.isEnabled() and not path.exists()
    qtbot.wait(350)
    assert len(requests) == 1
    dialog.close()
