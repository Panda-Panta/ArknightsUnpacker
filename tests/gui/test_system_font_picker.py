"""Installed font faces remain stable selections across picker and service restart."""
import hashlib
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFileDialog, QPushButton, QVBoxLayout

from arknights_unpacker.application import AppServices
from arknights_unpacker.reports import font_catalog
from arknights_unpacker.ui.font_picker import ExportFontPicker
from arknights_unpacker.ui.settings import SettingsView


YAHEI = Path('C:/Windows/Fonts/msyh.ttc')
requires_yahei = pytest.mark.skipif(not YAHEI.is_file(), reason='需要本机Windows微软雅黑TTC样本')


def choose_face(qtbot, picker, path, index):
    combo = picker.system_combo
    target = next(i for i in range(combo.count())
                  if tuple(combo.itemData(i) or ()) == (str(path), index))
    picker.window().resize(1050, 750)
    picker.window().show()
    if isinstance(picker.window(), SettingsView):
        picker.window().scroll.ensureWidgetVisible(picker)
    picker.show()
    qtbot.wait(10)
    combo.showPopup()
    item = combo.model().index(target, 0)
    combo.view().scrollTo(item)
    qtbot.wait(10)
    qtbot.mouseClick(combo.view().viewport(), Qt.MouseButton.LeftButton,
                     pos=combo.view().visualRect(item).center())


@requires_yahei
def test_real_windows_catalog_contains_multiple_yahei_faces_and_preserves_original():
    before = hashlib.sha256(YAHEI.read_bytes()).hexdigest()
    faces = [face for face in font_catalog.system_font_faces() if Path(face.path) == YAHEI]
    assert {face.index for face in faces} == {0, 1}
    assert next(face.family for face in faces if face.index == 0) == '微软雅黑'
    assert next(face.family for face in faces if face.index == 1) == 'Microsoft YaHei UI'
    assert all(face.style for face in faces)
    assert hashlib.sha256(YAHEI.read_bytes()).hexdigest() == before


def test_redirected_localappdata_still_includes_the_actual_profile_fonts(monkeypatch, tmp_path):
    profile = tmp_path / 'profile'
    redirected = tmp_path / 'sandbox'
    monkeypatch.setenv('LOCALAPPDATA', str(redirected))
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: profile))
    directories = font_catalog.system_font_directories()
    assert profile / 'AppData' / 'Local' / 'Microsoft' / 'Windows' / 'Fonts' in directories
    assert redirected / 'Microsoft' / 'Windows' / 'Fonts' in directories


def test_catalog_only_reads_direct_font_files_and_caches_per_process(monkeypatch, tmp_path):
    font_root = tmp_path / 'Fonts'
    font_root.mkdir()
    for name in ('good.ttf', 'broken.otf', 'faces.ttc', 'ignore.txt'):
        (font_root / name).write_bytes(b'fixture')
    nested = font_root / 'unknown'
    nested.mkdir()
    (nested / 'outside.ttf').write_bytes(b'not visited')
    calls = []

    def read_faces(path):
        calls.append(path.name)
        if path.name == 'broken.otf':
            raise ValueError('malformed individual font')
        return (font_catalog.FontFace(str(path), 0, path.stem, 'Regular'),)

    font_catalog.system_font_faces.cache_clear()
    monkeypatch.setattr(font_catalog, 'system_font_directories', lambda: (font_root, tmp_path / 'absent'))
    monkeypatch.setattr(font_catalog, 'font_faces', read_faces)
    try:
        first = font_catalog.system_font_faces()
        assert font_catalog.system_font_faces() is first
        assert {face.family for face in first} == {'good', 'faces'}
        assert sorted(calls) == ['broken.otf', 'faces.ttc', 'good.ttf']
        assert (nested / 'outside.ttf').read_bytes() == b'not visited'
    finally:
        font_catalog.system_font_faces.cache_clear()


@requires_yahei
def test_picker_selects_actual_collection_face_and_emits_stable_path_index(qtbot):
    picker = ExportFontPicker()
    qtbot.addWidget(picker)
    changes = []
    picker.font_changed.connect(lambda path, index: changes.append((path, index)))
    choose_face(qtbot, picker, YAHEI, 1)
    assert (picker.font_path, picker.font_index) == (str(YAHEI), 1)
    assert changes == [(str(YAHEI), 1)]
    assert 'Microsoft YaHei UI' in picker.system_combo.currentText()


def test_search_text_is_not_committed_as_a_font_selection(qtbot):
    picker = ExportFontPicker()
    qtbot.addWidget(picker)
    picker.set_font(str(YAHEI), 1)
    changes = []
    picker.font_changed.connect(lambda *choice: changes.append(choice))
    picker.system_combo.lineEdit().setText('searching for another font')
    assert (picker.font_path, picker.font_index) == (str(YAHEI), 1)
    assert not changes


def test_set_font_is_silent_and_changing_file_path_resets_face(qtbot, tmp_path):
    picker = ExportFontPicker()
    qtbot.addWidget(picker)
    changes = []
    picker.font_changed.connect(lambda *choice: changes.append(choice))
    picker.set_font(str(YAHEI), 1)
    assert picker.path_edit.text() == str(YAHEI)
    assert not changes
    path = str(tmp_path / 'custom.otf')
    picker.path_edit.setText(path)
    assert (picker.font_path, picker.font_index) == (path, 0)
    assert changes == [(path, 0)]


def test_font_file_cancel_keeps_collection_face_and_ttc_filter_is_available(qtbot, monkeypatch):
    picker = ExportFontPicker()
    qtbot.addWidget(picker)
    picker.set_font(str(YAHEI), 1)
    calls = []

    def cancel(*args):
        calls.append(args)
        return '', ''

    monkeypatch.setattr(QFileDialog, 'getOpenFileName', cancel)
    qtbot.mouseClick(picker.choose_button, Qt.MouseButton.LeftButton)
    assert (picker.font_path, picker.font_index) == (str(YAHEI), 1)
    assert '*.ttc' in calls[0][3]
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *_: (str(YAHEI), ''))
    qtbot.mouseClick(picker.choose_button, Qt.MouseButton.LeftButton)
    assert (picker.font_path, picker.font_index) == (str(YAHEI), 0)


@requires_yahei
def test_settings_save_and_restart_restore_collection_face(qtbot, tmp_path):
    data_root, output_root = tmp_path / 'data', tmp_path / 'exports'
    services = AppServices(data_root, output_root)
    try:
        view = SettingsView(services.config, services.data_root)
        qtbot.addWidget(view)
        view.changed.connect(services.save_config)
        choose_face(qtbot, view.font_picker, YAHEI, 1)
        assert view.font_picker.font_index == 1
        qtbot.mouseClick(view.save_button, Qt.MouseButton.LeftButton)
        assert services.config['report_font_path'] == str(YAHEI)
        assert services.config['report_font_index'] == 1
        assert view.report_options().font_index == 1
    finally:
        services.shutdown()
    reopened = AppServices(data_root, output_root)
    try:
        restored = SettingsView(reopened.config, reopened.data_root)
        qtbot.addWidget(restored)
        assert (restored.report_options().font_path, restored.report_options().font_index) == (str(YAHEI), 1)
    finally:
        reopened.shutdown()


def test_reset_and_old_config_use_default_face(qtbot, tmp_path):
    old = SettingsView({'report_font_path': str(YAHEI)}, tmp_path)
    qtbot.addWidget(old)
    assert old.report_options().font_index == 0
    old.font_picker.set_font(str(YAHEI), 1)
    changes = []
    old.font_picker.font_changed.connect(lambda *choice: changes.append(choice))
    qtbot.mouseClick(old.font_picker.reset_button, Qt.MouseButton.LeftButton)
    old.commit()
    assert (old.report_options().font_path, old.report_options().font_index) == ('', 0)
    assert changes == [('', 0)]
    assert old.config['report_font_index'] == 0


def dialog_picker(qtbot, monkeypatch):
    dialog = QDialog()
    qtbot.addWidget(dialog)
    layout = QVBoxLayout(dialog)
    picker = ExportFontPicker(dialog)
    layout.addWidget(picker)
    other = QPushButton('导出')
    layout.addWidget(other)
    picker.choose_button.setDefault(True)
    file_dialogs, other_actions = [], []
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: file_dialogs.append(args) or ('', ''))
    other.clicked.connect(lambda: other_actions.append(True))
    dialog.show()
    qtbot.wait(10)
    return dialog, picker, file_dialogs, other_actions


@pytest.mark.parametrize('key', [Qt.Key.Key_Return, Qt.Key.Key_Enter])
@pytest.mark.parametrize('target', ['combo', 'combo_edit'])
def test_dialog_font_selection_enter_commits_match_without_opening_file_dialog(qtbot, monkeypatch, key, target):
    dialog, picker, file_dialogs, other_actions = dialog_picker(qtbot, monkeypatch)
    if picker.system_combo.count() < 2:
        pytest.skip('需要至少一份已安装字体')
    expected = tuple(picker.system_combo.itemData(1))
    picker.system_combo.setCurrentIndex(1)
    changes = []
    picker.font_changed.connect(lambda *choice: changes.append(choice))
    control = picker.system_combo if target == 'combo' else picker.system_combo.lineEdit()
    control.setFocus()
    qtbot.keyClick(control, key)
    assert not file_dialogs and not other_actions
    assert (picker.font_path, picker.font_index) == expected
    assert changes == [expected]
    assert dialog.isVisible()


@pytest.mark.parametrize('key', [Qt.Key.Key_Return, Qt.Key.Key_Enter])
@pytest.mark.parametrize('target', ['combo', 'combo_edit'])
def test_dialog_unknown_font_search_enter_is_consumed_without_committing(qtbot, monkeypatch, tmp_path, key, target):
    dialog, picker, file_dialogs, other_actions = dialog_picker(qtbot, monkeypatch)
    previous = str(tmp_path / 'previous.ttf')
    picker.set_font(previous)
    picker.system_combo.lineEdit().setText('not an installed font or complete suggestion')
    changes = []
    picker.font_changed.connect(lambda *choice: changes.append(choice))
    control = picker.system_combo if target == 'combo' else picker.system_combo.lineEdit()
    control.setFocus()
    qtbot.keyClick(control, key)
    assert not file_dialogs and not other_actions
    assert (picker.font_path, picker.font_index) == (previous, 0)
    assert not changes and dialog.isVisible()


@pytest.mark.parametrize('key', [Qt.Key.Key_Return, Qt.Key.Key_Enter])
def test_dialog_font_path_enter_keeps_edited_path_without_triggering_default_button(qtbot, monkeypatch, tmp_path, key):
    dialog, picker, file_dialogs, other_actions = dialog_picker(qtbot, monkeypatch)
    changes = []
    picker.font_changed.connect(lambda *choice: changes.append(choice))
    path = str(tmp_path / 'edited font.otf')
    picker.path_edit.setText(path)
    picker.path_edit.setFocus()
    qtbot.keyClick(picker.path_edit, key)
    assert not file_dialogs and not other_actions
    assert (picker.font_path, picker.font_index) == (path, 0)
    assert changes == [(path, 0)] and dialog.isVisible()
