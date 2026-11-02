"""Manual composition binds export to the exact successful preview options."""
from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

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


def preview_png(cache, name='composition.png'):
    lease = cache.allocate('objects')
    path = lease.path / name
    image = QImage(64, 96, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    image.setPixelColor(10, 10, Qt.GlobalColor.red)
    assert image.save(str(path))
    lease.finish()
    return lease, path


def test_loading_and_empty_or_failed_catalog_never_enable_actions(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    assert not dialog.preview_button.isEnabled()
    assert not dialog.export_button.isEnabled()
    assert not dialog.batch_button.isEnabled()
    dialog.set_catalog({'groups': [], 'diagnostics': ['引用的图片位于未安装依赖包']})
    assert '引用的图片位于未安装依赖包' in dialog.diagnostics.text()
    assert not dialog.preview_button.isEnabled() and not dialog.batch_button.isEnabled()
    dialog.load_failed('无法读取角色配置')
    assert '无法读取角色配置' in dialog.status.text()


def test_catalog_defaults_and_group_switch_use_each_groups_base_and_placement(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    data = catalog()
    original = deepcopy(data)
    dialog.set_catalog(data)
    assert dialog.group_choice.currentData() == '0:0'
    assert dialog.base_choice.currentData() == '0:0:2'
    assert dialog.face_choice.currentData() == '0:0:0'
    assert dialog.current_options() == {'group_id': '0:0', 'base_id': '0:0:2', 'face_id': '0:0:0',
                                        'x': 462, 'y': 116, 'width': 86, 'height': 89}
    dialog.group_choice.setCurrentIndex(1)
    assert dialog.current_options() == {'group_id': '0:1', 'base_id': '0:1:1', 'face_id': '0:1:0',
                                        'x': 12, 'y': 20, 'width': 42, 'height': 53}
    assert data == original, 'The window must not change the production catalog'


def test_manual_selection_and_reset_emit_exact_options_without_exporting_early(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    dialog.set_catalog(catalog())
    requests, exports = [], []
    dialog.preview_requested.connect(requests.append)
    dialog.export_requested.connect(exports.append)
    dialog.base_choice.setCurrentIndex(dialog.base_choice.findData('0:0:1'))
    dialog.x_spin.setValue(-20)
    dialog.y_spin.setValue(350)
    dialog.width_spin.setValue(100)
    dialog.height_spin.setValue(140)
    dialog.preview_button.click()
    assert requests == [{'group_id': '0:0', 'base_id': '0:0:1', 'face_id': '0:0:0',
                         'x': -20, 'y': 350, 'width': 100, 'height': 140}]
    dialog.export_button.click()
    assert exports == []
    dialog.reset_button.click()
    assert dialog.current_options() == {'group_id': '0:0', 'base_id': '0:0:2', 'face_id': '0:0:0',
                                        'x': 462, 'y': 116, 'width': 86, 'height': 89}


def test_successful_preview_unlocks_export_only_for_the_same_parameters(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    dialog.set_catalog(catalog())
    requests, exports = [], []
    dialog.preview_requested.connect(requests.append)
    dialog.export_requested.connect(exports.append)
    dialog.preview_button.click()
    generation = dialog.preview_generation
    cache = PreviewCache(tmp_path / 'data')
    lease, path = preview_png(cache)
    dialog.track_preview(lease)
    assert dialog.show_files([{'path': str(path), 'kind': 'character_expression'}], lease, generation)
    assert dialog.preview_panel.image_path == path.resolve()
    assert dialog.export_button.isEnabled()
    dialog.export_button.click()
    assert exports == requests
    assert exports[0] is not dialog.successful_options
    dialog.x_spin.setValue(463)
    assert not dialog.export_button.isEnabled()
    assert not path.exists(), 'A changed manual composition must release the stale image'
    dialog.export_button.click()
    assert len(exports) == 1


def test_old_generation_cannot_replace_preview_or_unlock_export(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    dialog.set_catalog(catalog())
    dialog.preview_button.click()
    old = dialog.preview_generation
    dialog.y_spin.setValue(200)
    dialog.preview_button.click()
    cache = PreviewCache(tmp_path / 'data')
    first, first_path = preview_png(cache, 'old.png')
    assert not dialog.show_files([{'path': str(first_path)}], first, old)
    assert not first_path.exists()
    assert not dialog.export_button.isEnabled()
    current, current_path = preview_png(cache, 'current.png')
    assert dialog.show_files([{'path': str(current_path)}], current, dialog.preview_generation)
    status = dialog.status.text()
    dialog.preview_failed('过期失败', generation=old)
    assert dialog.status.text() == status and dialog.export_button.isEnabled()
    dialog.close()
    assert not current_path.exists()


def test_whole_body_and_no_face_do_not_offer_unused_overlay_controls(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    dialog.set_catalog(catalog())
    dialog.face_choice.setCurrentIndex(dialog.face_choice.findData('0:0:1'))
    assert not dialog.x_spin.isEnabled() and not dialog.width_spin.isEnabled()
    assert '整幅' in dialog.placement_hint.text()
    assert dialog.preview_button.isEnabled()
    dialog.face_choice.setCurrentIndex(dialog.face_choice.findData(''))
    assert dialog.current_options()['face_id'] == ''
    assert not dialog.y_spin.isEnabled()
    dialog.face_choice.setCurrentIndex(dialog.face_choice.findData('0:0:0'))
    assert dialog.x_spin.isEnabled() and dialog.width_spin.minimum() == 1


def test_batch_uses_config_only_and_enter_in_numeric_field_does_not_export(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    dialog.set_catalog(catalog())
    calls, previews, exports = [], [], []
    dialog.batch_requested.connect(lambda: calls.append('batch'))
    dialog.preview_requested.connect(previews.append)
    dialog.export_requested.connect(exports.append)
    dialog.x_spin.setValue(-99)
    dialog.batch_button.click()
    assert calls == ['batch'] and previews == [] and exports == []
    dialog.show()
    dialog.x_spin.setFocus()
    qtbot.keyClick(dialog.x_spin, Qt.Key.Key_Return)
    assert calls == ['batch'] and previews == [] and exports == []
    assert dialog.isVisible()


def test_close_shuts_preview_before_releasing_current_and_inflight_leases(qtbot, tmp_path, monkeypatch):
    dialog = make_dialog(qtbot, tmp_path)
    dialog.set_catalog(catalog())
    dialog.preview_button.click()
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
    assert dialog.preview_closed and not path.exists()
    pending.finish()
    assert not pending.path.exists()
    late, late_path = preview_png(cache, 'late.png')
    assert not dialog.show_files([{'path': str(late_path)}], late, dialog.preview_generation)
    assert not late_path.exists()


def test_preview_failure_keeps_form_and_batch_available_but_export_disabled(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    dialog.set_catalog(catalog())
    dialog.preview_button.click()
    dialog.preview_failed('所选表情引用了缺失的图片', generation=dialog.preview_generation)
    assert '缺失' in dialog.status.text()
    assert dialog.preview_button.isEnabled() and dialog.batch_button.isEnabled()
    assert not dialog.export_button.isEnabled()


def test_enter_with_successful_preview_never_triggers_export_or_closes_window(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    dialog.set_catalog(catalog())
    dialog.preview_button.click()
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
    assert exports == [] and batches == []
    dialog.close()


def test_non_image_result_is_a_failure_and_cannot_unlock_export(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    dialog.set_catalog(catalog())
    dialog.preview_button.click()
    cache = PreviewCache(tmp_path / 'data')
    lease = cache.allocate('objects')
    path = lease.path / 'result.json'
    path.write_text('{"diagnostics": []}', 'utf-8')
    lease.finish()
    assert not dialog.show_files([{'path': str(path)}], lease, dialog.preview_generation)
    assert '没有生成' in dialog.status.text()
    assert not dialog.export_button.isEnabled() and not path.exists()
