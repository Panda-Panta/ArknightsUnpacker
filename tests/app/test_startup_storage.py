from arknights_unpacker import bootstrap


def test_windowed_startup_displays_storage_error_in_a_dialog(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    def fail(*args, **kwargs):
        raise PermissionError('无法保存到 example/data；请使用 --data-dir。')
    messages = []
    monkeypatch.setattr('arknights_unpacker.application.AppServices', fail)
    monkeypatch.setattr(QMessageBox, 'critical', lambda parent, title, text: messages.append((title, text)))
    monkeypatch.setattr('sys.argv', ['ArknightsUnpacker'])
    assert bootstrap.main() == 1
    assert len(messages) == 1
    assert 'example/data' in messages[0][1] and '--data-dir' in messages[0][1]
