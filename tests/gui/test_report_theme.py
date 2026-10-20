"""A chosen report theme survives service restart and supplies export options."""
import pytest

from arknights_unpacker.application import AppServices
from arknights_unpacker.ui.settings import SettingsView


@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_report_theme_selection_is_persisted_and_restored(qtbot, tmp_path, theme):
    data_root, output_root = tmp_path / 'data', tmp_path / 'exports'
    services = AppServices(data_root, output_root=output_root)
    try:
        services.config['report_theme'] = 'dark' if theme == 'light' else 'light'
        view = SettingsView(services.config, services.data_root)
        qtbot.addWidget(view)
        assert {view.theme.itemData(i) for i in range(view.theme.count())} == {'dark', 'light'}
        view.changed.connect(services.save_config)
        view.theme.setCurrentIndex(view.theme.findData(theme))
        view.commit()
        assert view.report_options().theme == theme
        assert services.config['report_theme'] == theme
    finally:
        services.shutdown()
    restored_services = AppServices(data_root, output_root=output_root)
    try:
        restored = SettingsView(restored_services.config, restored_services.data_root)
        qtbot.addWidget(restored)
        assert restored.theme.currentData() == theme
        assert restored.report_options().theme == theme
    finally:
        restored_services.shutdown()
