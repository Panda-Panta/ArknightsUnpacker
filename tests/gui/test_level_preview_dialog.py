from PySide6.QtWidgets import QWidget

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


def test_replay_fullscreen_fills_dialog_and_restores_controls(qtbot):
    class Replay(QWidget):
        def set_fullscreen_presentation(self, enabled):
            self.fullscreen_presentation = enabled

        def shutdown(self):
            pass

    dialog = LevelPreviewDialog(None, '关卡')
    qtbot.addWidget(dialog)
    view = Replay(dialog.content)
    dialog.replay_view = view
    dialog.content.addWidget(view)
    dialog.content.setCurrentWidget(view)
    dialog.show_detail('详情')
    dialog.show_replay_status('回放就绪')
    dialog.fullscreen_button.show()
    dialog.show()

    dialog.fullscreen_button.click()
    qtbot.waitUntil(lambda: dialog.content.geometry() == dialog.rect())

    assert dialog.isFullScreen() and view.fullscreen_presentation
    assert dialog._fullscreen_exit.isVisible() and not dialog.buttons.isVisible()
    assert not dialog.heading.isVisible() and not dialog.detail.isVisible()
    dialog.show_replay_status('新状态')
    assert not dialog.replay_status.isVisible()

    dialog._fullscreen_exit.click()
    qtbot.waitUntil(lambda: not dialog.isFullScreen())
    assert not view.fullscreen_presentation and not dialog._fullscreen_exit.isVisible()
    assert dialog.heading.isVisible() and dialog.detail.isVisible() and dialog.buttons.isVisible()
    assert dialog.replay_status.isVisible() and dialog.replay_status.text() == '新状态'
