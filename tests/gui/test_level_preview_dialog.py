from arknights_unpacker.ui.level_preview_dialog import LevelPreviewDialog


def test_missing_animation_has_explicit_feedback(qtbot, tmp_path):
    dialog = LevelPreviewDialog(tmp_path / 'missing.mp4', '7-18 · 爱国者之死')
    qtbot.addWidget(dialog)
    assert '7-18' in dialog.windowTitle()
    assert '文件不存在' in dialog.viewer.preview.toPlainText()
    assert dialog.viewer.player.source().isEmpty()
    assert not dialog.viewer.play_button.isEnabled()


def test_invalid_animation_is_rejected_before_opening_decoder(qtbot, tmp_path):
    source = tmp_path / 'invalid.mp4'
    source.write_bytes(b'not-an-mp4')
    dialog = LevelPreviewDialog(source, 'CA-5')
    qtbot.addWidget(dialog)
    dialog.open()
    assert '有效的 MP4' in dialog.viewer.preview.toPlainText()
    assert not dialog.viewer.play_button.isEnabled()

    dialog.reject()
    assert dialog.viewer.player.source().isEmpty()
    assert not dialog.isVisible()
    source.unlink()
