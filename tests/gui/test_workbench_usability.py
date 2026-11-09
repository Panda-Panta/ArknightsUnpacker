"""Workbench controls remain reachable in the supported compact window."""
from PySide6.QtCore import QPoint, Qt

from arknights_unpacker.application import AppServices
from arknights_unpacker.ui.main_window import MainWindow
from test_explorer import MockServices


def test_scan_options_collapse_preserves_values_and_history_is_available(qtbot, tmp_path):
    window = MainWindow(MockServices(tmp_path))
    qtbot.addWidget(window)
    window.show()
    assert not window.scan_options.isVisible()
    assert not window.baseline_panel.isVisible()
    qtbot.mouseClick(window.scan_options_button, Qt.MouseButton.LeftButton)
    assert window.hours.isVisible()
    window.hours.setValue(48)
    window.strict.setChecked(True)
    qtbot.mouseClick(window.scan_options_button, Qt.MouseButton.LeftButton)
    assert not window.hours.isVisible()
    assert window.hours.value() == 48
    assert window.strict.isChecked()
    qtbot.mouseClick(window.history_button, Qt.MouseButton.LeftButton)
    assert window.history.isVisible()
    assert not window.compare_button.isEnabled()
    assert not window.export_snapshot_button.isEnabled()


def test_settings_save_stays_visible_at_top_and_bottom_and_persists(qtbot, tmp_path):
    services = AppServices(tmp_path / 'data', tmp_path / 'exports')
    window = MainWindow(services)
    qtbot.addWidget(window)
    window.resize(1050, 700)
    window.show()
    window.pages.select('settings')
    qtbot.wait(30)
    view = window.settings
    assert window.page_title.text() == '工作台设置'
    assert view.scroll.verticalScrollBar().maximum() > 0
    for position in (0, view.scroll.verticalScrollBar().maximum()):
        view.scroll.verticalScrollBar().setValue(position)
        qtbot.wait(10)
        assert view.save_button.isVisible()
        point = view.save_button.mapTo(window, QPoint(0, 0))
        assert window.rect().contains(point)
        assert point.y() + view.save_button.height() <= window.height()
    view.width.setValue(1440)
    assert '已更改' in view.save_status.text()
    qtbot.mouseClick(view.save_button, Qt.MouseButton.LeftButton)
    assert '已保存' in view.save_status.text()
    import json
    config = json.loads(services.config_file.read_text(encoding='utf-8'))
    assert config['report_width'] == 1440
    window.close()
    services.shutdown()


def test_long_output_path_does_not_force_window_wider(qtbot, tmp_path):
    services = MockServices(tmp_path)
    services.config['output_root'] = 'D:/' + '很长的输出目录/' * 30
    window = MainWindow(services)
    qtbot.addWidget(window)
    window.resize(1050, 700)
    window.show()
    qtbot.wait(30)
    assert window.width() == 1050
    assert window.output_label.toolTip() == '输出：' + services.config['output_root']
    assert '…' in window.output_label.text()
    assert window.cancel_button.mapTo(window, QPoint(window.cancel_button.width(), 0)).x() <= window.width()


def test_empty_queue_does_not_look_like_a_completed_job(qtbot, tmp_path):
    window = MainWindow(MockServices(tmp_path))
    qtbot.addWidget(window)
    window.show()
    window.show_task_history()
    assert window.jobs.empty_hint.isVisible()
    assert window.jobs.progress.value() == 0
    assert window.jobs.progress.format() == '等待任务'
