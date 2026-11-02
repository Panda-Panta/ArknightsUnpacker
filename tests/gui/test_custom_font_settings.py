"""Custom report fonts follow the existing choose, save, and restart flow."""
import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QPushButton

from arknights_unpacker.application import AppServices
from arknights_unpacker.ui.settings import SettingsView


def button(view, name):
    found = view.findChild(QPushButton, name)
    assert found is not None
    return found


def test_font_file_picker_updates_export_options_without_changing_workbench_font(qtbot, monkeypatch, tmp_path):
    view = SettingsView({}, tmp_path)
    qtbot.addWidget(view)
    path = str(tmp_path / '中文字体.ttf')
    calls = []

    def choose(parent, caption, current, file_filter):
        calls.append((parent, caption, current, file_filter))
        return path, '字体文件 (*.ttf *.otf)'

    monkeypatch.setattr(QFileDialog, 'getOpenFileName', choose)
    workbench_font = QApplication.instance().font().toString()
    qtbot.mouseClick(button(view, 'chooseReportFont'), Qt.MouseButton.LeftButton)
    assert view.font_path.text() == path
    assert view.report_options().font_path == path
    assert view.config.get('report_font_path', '') == ''
    assert '已更改' in view.save_status.text()
    assert len(calls) == 1 and calls[0][0] is view.font_picker
    assert '*.ttf' in calls[0][3] and '*.otf' in calls[0][3]
    assert QApplication.instance().font().toString() == workbench_font


def test_cancel_font_picker_preserves_existing_selection(qtbot, monkeypatch, tmp_path):
    path = str(tmp_path / 'existing.otf')
    view = SettingsView({'report_font_path': path}, tmp_path)
    qtbot.addWidget(view)
    status = view.save_status.text()
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *_: ('', ''))
    qtbot.mouseClick(button(view, 'chooseReportFont'), Qt.MouseButton.LeftButton)
    assert view.font_path.text() == path
    assert view.report_options().font_path == path
    assert view.save_status.text() == status


def test_selected_font_is_saved_and_restored_by_real_app_services(qtbot, monkeypatch, tmp_path):
    data_root, output_root = tmp_path / 'data', tmp_path / 'exports'
    path = str(tmp_path / '中文字体.otf')
    services = AppServices(data_root, output_root)
    try:
        view = SettingsView(services.config, services.data_root)
        qtbot.addWidget(view)
        view.changed.connect(services.save_config)
        monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *_: (path, ''))
        qtbot.mouseClick(button(view, 'chooseReportFont'), Qt.MouseButton.LeftButton)
        qtbot.mouseClick(view.save_button, Qt.MouseButton.LeftButton)
        assert services.config['report_font_path'] == path
        assert json.loads(services.config_file.read_text('utf-8'))['report_font_path'] == path
    finally:
        services.shutdown()
    restored_services = AppServices(data_root, output_root)
    try:
        restored = SettingsView(restored_services.config, restored_services.data_root)
        qtbot.addWidget(restored)
        assert restored.font_path.text() == path
        assert restored.report_options().font_path == path
    finally:
        restored_services.shutdown()


def test_restoring_default_font_is_saved_as_empty_path(qtbot, tmp_path):
    data_root, output_root = tmp_path / 'data', tmp_path / 'exports'
    services = AppServices(data_root, output_root)
    try:
        services.config['report_font_path'] = str(tmp_path / 'custom.ttf')
        view = SettingsView(services.config, services.data_root)
        qtbot.addWidget(view)
        view.changed.connect(services.save_config)
        qtbot.mouseClick(button(view, 'resetReportFont'), Qt.MouseButton.LeftButton)
        assert view.font_path.text() == '' and view.report_options().font_path == ''
        qtbot.mouseClick(view.save_button, Qt.MouseButton.LeftButton)
        assert services.config['report_font_path'] == ''
    finally:
        services.shutdown()
    reopened = AppServices(data_root, output_root)
    try:
        restored = SettingsView(reopened.config, reopened.data_root)
        qtbot.addWidget(restored)
        assert restored.report_options().font_path == ''
    finally:
        reopened.shutdown()


def test_old_settings_keep_default_font_and_other_report_choices(qtbot, tmp_path):
    view = SettingsView({'report_width': 1440, 'report_font_size': 30, 'report_theme': 'light'}, tmp_path)
    qtbot.addWidget(view)
    options = view.report_options()
    assert options.font_path == ''
    assert (options.width, options.font_size, options.theme) == (1440, 30, 'light')
