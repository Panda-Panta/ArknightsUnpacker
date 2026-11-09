from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QDialog, QFileDialog, QLineEdit, QMessageBox

from arknights_unpacker.contracts import ReportArtifact
from arknights_unpacker.ui.object_preview import ObjectsDialog
from arknights_unpacker.ui.report_preview import ReportArtifactsDialog


def original_png(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    image = QImage(173, 89, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    image.setPixelColor(19, 27, Qt.GlobalColor.cyan)
    image.setText('source-note', 'Preserve PNG metadata and original encoded bytes.')
    assert image.save(str(path))
    return path


def test_object_save_copies_original_bytes_after_preview_zoom(qtbot, tmp_path, monkeypatch):
    game = tmp_path / 'game'
    game.mkdir()
    source = original_png(tmp_path / 'cache' / 'original.png')
    target = tmp_path / 'exports' / 'original.png'
    dialog = ObjectsDialog(str(game / 'portrait.ab'), auto_preview=False)
    qtbot.addWidget(dialog)
    dialog.show_file(source)
    dialog.image_zoom.setValue(250)
    assert dialog.picture.pixmap().width() != 173
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(target), ''))
    qtbot.mouseClick(dialog.save_original_button, Qt.MouseButton.LeftButton)
    assert target.read_bytes() == source.read_bytes()
    saved = QImage(str(target))
    assert (saved.width(), saved.height()) == (173, 89)


def test_original_save_does_not_overwrite_or_write_in_game(qtbot, tmp_path, monkeypatch):
    game = tmp_path / 'game'
    game.mkdir()
    source = original_png(tmp_path / 'cache' / 'original.png')
    dialog = ObjectsDialog(str(game / 'portrait.ab'), auto_preview=False)
    qtbot.addWidget(dialog)
    dialog.show_file(source)
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a: warnings.append(str(a[-1])))
    target = tmp_path / 'existing.png'
    target.write_bytes(b'keep-existing-user-file')
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(target), ''))
    dialog.save_original()
    assert target.read_bytes() == b'keep-existing-user-file'
    assert warnings and '已存在' in warnings[-1]
    target = game / 'forbidden' / 'original.png'
    dialog.save_original()
    assert not target.parent.exists()
    assert '游戏' in warnings[-1]


def test_report_save_uses_current_original_page_after_zoom(qtbot, tmp_path, monkeypatch):
    first = original_png(tmp_path / 'cache' / 'page-1.png')
    second = original_png(tmp_path / 'cache' / 'page-2.png')
    image = QImage(str(second))
    image.setText('page', 'second page')
    assert image.save(str(second))
    dialog = ReportArtifactsDialog([ReportArtifact(str(first), 'png'), ReportArtifact(str(second), 'png')])
    qtbot.addWidget(dialog)
    dialog.pages.setCurrentIndex(1)
    dialog.zoom.setValue(25)
    target = tmp_path / 'exports' / 'saved-page.png'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(target), ''))
    dialog.save_original()
    assert target.read_bytes() == second.read_bytes()
    assert QImage(str(target)).size() == QImage(str(second)).size()


def test_text_preview_disables_original_image_save(qtbot, tmp_path):
    source = original_png(tmp_path / 'cache' / 'original.png')
    dialog = ObjectsDialog(str(tmp_path / 'game' / 'portrait.ab'), auto_preview=False)
    qtbot.addWidget(dialog)
    dialog.show_file(source)
    assert dialog.save_original_button.isEnabled()
    text = tmp_path / 'text.txt'
    text.write_text('text object', encoding='utf-8')
    dialog.show_file(text)
    assert not dialog.save_original_button.isEnabled()
    assert dialog.picture.pixmap().isNull()


def test_report_preview_keeps_original_installation_write_guard(qtbot, tmp_path, monkeypatch):
    original_game = tmp_path / 'original-game'
    original_game.mkdir()
    parent = QDialog()
    qtbot.addWidget(parent)
    parent.services = SimpleNamespace(installation=SimpleNamespace(root=original_game))
    parent.root_edit = QLineEdit(str(original_game), parent)
    source = original_png(tmp_path / 'cache' / 'page.png')
    dialog = ReportArtifactsDialog([ReportArtifact(str(source), 'png')], parent)
    qtbot.addWidget(dialog)
    # Changing the workbench selection cannot release a still-open preview's guard.
    parent.root_edit.setText(str(tmp_path / 'different-game'))
    parent.services.installation = None
    target = original_game / 'do-not-create' / 'saved.png'
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a: warnings.append(str(a[-1])))
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(target), ''))
    dialog.save_original()
    assert not target.parent.exists()
    assert warnings and '游戏' in warnings[-1]
