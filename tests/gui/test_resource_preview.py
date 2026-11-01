"""The in-dialog viewer displays decoded resources without external apps."""
import hashlib
import json
from pathlib import Path
import wave

import pytest
from PIL import Image
from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QImage, QMovie
from PySide6.QtMultimedia import QMediaPlayer


@pytest.fixture
def viewer(qtbot):
    from arknights_unpacker.ui.resource_preview import ResourcePreviewWidget
    widget = ResourcePreviewWidget()
    qtbot.addWidget(widget)
    widget.resize(680, 620)
    widget.show()
    qtbot.waitUntil(widget.isVisible)
    yield widget
    widget.shutdown()


def png(path, width=1600, height=1000):
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.cyan)
    assert image.save(str(path))
    return path


def wav(path):
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b'\0\0' * 16000)
    return path


def test_new_images_fit_the_available_panel_and_keep_original_pixels(viewer, qtbot, tmp_path):
    source = png(tmp_path / 'large.png')
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    assert viewer.show_files([{'path': str(source), 'kind': 'image'}])
    qtbot.waitUntil(lambda: not viewer.picture.pixmap().isNull())
    qtbot.waitUntil(lambda: viewer.picture.pixmap().width() <= viewer.image_scroll.viewport().width()
                   and viewer.picture.pixmap().height() <= viewer.image_scroll.viewport().height())
    assert viewer.image_path == source.resolve()
    assert viewer.current_path == source.resolve()
    assert viewer.image_pixmap.size() == QImage(str(source)).size()
    assert viewer.image_tools.isVisible() and viewer.image_scroll.isVisible()
    assert viewer.image_scroll.height() > 320
    assert viewer.save_original_button.isEnabled()
    requested = []
    viewer.save_original_requested.connect(lambda: requested.append(True))
    viewer.save_original_button.click()
    assert requested == [True]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original


def test_manual_zoom_survives_resize_and_new_image_returns_to_fit(viewer, qtbot, tmp_path):
    viewer.show_file(png(tmp_path / 'first.png', 400, 200))
    viewer.image_zoom.setValue(250)
    assert viewer.picture.pixmap().width() == 1000
    viewer.resize(820, 680)
    qtbot.wait(20)
    assert viewer.image_zoom.value() == 250
    assert viewer.picture.pixmap().width() == 1000
    viewer.show_file(png(tmp_path / 'second.png', 1800, 1200))
    qtbot.waitUntil(lambda: viewer.picture.pixmap().width() <= viewer.image_scroll.viewport().width()
                   and viewer.picture.pixmap().height() <= viewer.image_scroll.viewport().height())
    assert viewer.image_zoom.value() < 100


def test_decoded_json_is_preferred_to_raw_bytes_and_outputs_are_switchable(viewer, tmp_path):
    raw = tmp_path / 'table.bytes'
    raw.write_bytes(bytes(range(256)))
    decoded = tmp_path / 'table.json'
    decoded.write_text(json.dumps({'名称': '中文资料', '参数': [1, 2]}, ensure_ascii=False), 'utf-8')
    assert viewer.show_files([{'path': str(raw), 'kind': 'text'}, {'path': str(decoded), 'kind': 'text'}])
    assert viewer.current_path == decoded.resolve()
    assert viewer.file_choice.count() == 2
    assert '中文资料' in viewer.preview.toPlainText()
    assert '\n  "名称"' in viewer.preview.toPlainText()
    viewer.file_choice.setCurrentIndex(viewer.file_choice.findData(str(raw.resolve())))
    assert viewer.current_path == raw.resolve()
    assert '00000000' in viewer.preview.toPlainText()


def test_html_is_plain_text_and_large_binary_has_bounded_readable_hex(viewer, tmp_path):
    html = tmp_path / 'sample.html'
    markup = '<h1>原始内容</h1><script>alert(1)</script>'
    html.write_text(markup, 'utf-8')
    viewer.show_file(html)
    assert viewer.preview.toPlainText() == markup
    binary = tmp_path / 'unknown.bin'
    binary.write_bytes(bytes(range(256)) * 4096)
    viewer.show_file(binary)
    text = viewer.preview.toPlainText()
    assert '十六进制' in text and '00000000' in text
    assert '00 01 02 03 04 05 06 07' in text
    assert '限长' in text and '\ufffd' not in text and len(text) < 100000
    assert viewer.image_path is None and not viewer.save_original_button.isEnabled()


def test_text_read_is_bounded_and_does_not_keep_previous_image(viewer, tmp_path):
    viewer.show_file(png(tmp_path / 'image.png', 30, 20))
    text = tmp_path / 'large.txt'
    text.write_text('中文内容\n' * 100000, 'utf-8')
    viewer.show_file(text)
    assert '中文内容' in viewer.preview.toPlainText()
    assert '限长' in viewer.preview.toPlainText()
    assert len(viewer.preview.toPlainText()) < 270000
    assert viewer.image_path is None and viewer.image_pixmap.isNull()
    assert viewer.picture.pixmap().isNull()


def test_audio_uses_qt_player_without_autoplay_and_clear_releases_source(viewer, qtbot, tmp_path):
    source = wav(tmp_path / 'silence.wav')
    viewer.audio_output.setMuted(True)
    assert viewer.show_file(source)
    assert viewer.player.source() == QUrl.fromLocalFile(str(source.resolve()))
    assert viewer.player.playbackState() == QMediaPlayer.PlaybackState.StoppedState
    qtbot.waitUntil(lambda: viewer.player.duration() > 0, timeout=10000)
    assert viewer.position_slider.maximum() == viewer.player.duration()
    assert viewer.play_button.isEnabled()
    viewer.volume_slider.setValue(35)
    assert viewer.audio_output.volume() == pytest.approx(.35, abs=.001)
    viewer.play_button.click()
    qtbot.waitUntil(lambda: viewer.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState, timeout=3000)
    viewer.play_button.click()
    assert viewer.player.playbackState() == QMediaPlayer.PlaybackState.PausedState
    viewer.position_slider.setValue(500)
    viewer.position_slider.sliderReleased.emit()
    assert viewer.player.position() == 500
    viewer.clear()
    assert viewer.player.source().isEmpty()
    assert viewer.player.playbackState() == QMediaPlayer.PlaybackState.StoppedState
    assert viewer.current_path is None
    source.unlink()
    assert not source.exists()


def test_video_is_preferred_to_unplayable_raw_outputs_and_errors_are_readable(viewer, qtbot, tmp_path):
    raw = tmp_path / 'stream.bytes'
    raw.write_bytes(b'\x00\x01unreadable')
    video = tmp_path / 'clip.mp4'
    video.write_bytes(b'not-a-real-video')
    assert viewer.show_files([str(raw), {'path': str(video), 'kind': 'video'}])
    assert viewer.current_path == video.resolve()
    assert viewer.player.source() == QUrl.fromLocalFile(str(video.resolve()))
    assert viewer.video_widget.isVisible()
    assert viewer.player.playbackState() == QMediaPlayer.PlaybackState.StoppedState
    qtbot.waitUntil(lambda: '无法播放' in viewer.media_status.text(), timeout=10000)
    assert viewer.preview.toPlainText() != 'not-a-real-video'
    viewer.show_file(raw)
    assert viewer.player.source().isEmpty()
    assert '十六进制' in viewer.preview.toPlainText()


def test_container_and_stream_outputs_rank_before_media_metadata(viewer, tmp_path):
    stream = tmp_path / 'video.ivf'
    stream.write_bytes(b'DKIF-invalid-fixture')
    metadata = tmp_path / 'video.media.json'
    metadata.write_text('{"format":"USM"}', 'utf-8')
    assert viewer.show_files([{'path': str(metadata), 'kind': 'video_metadata'},
                              {'path': str(stream), 'kind': 'video_stream'}])
    assert viewer.current_path == stream.resolve()
    container = tmp_path / 'video.mkv'
    container.write_bytes(b'invalid-container-fixture')
    assert viewer.show_files([str(metadata), str(stream), {'path': str(container), 'kind': 'video_playable'}])
    assert viewer.current_path == container.resolve()


def test_gif_frames_support_animation_and_shutdown_closes_file(viewer, qtbot, tmp_path):
    path = tmp_path / 'animated.gif'
    Image.new('RGB', (80, 50), 'red').save(path, save_all=True,
        append_images=[Image.new('RGB', (80, 50), 'blue')], duration=150, loop=0)
    assert viewer.show_file(path)
    assert viewer.movie is not None and viewer.movie.isValid()
    assert viewer.image_path == path.resolve()
    assert viewer.animation_button.isVisible()
    viewer.animation_button.click()
    qtbot.waitUntil(lambda: viewer.movie.currentFrameNumber() == 1, timeout=3000)
    viewer.shutdown()
    assert viewer.movie is None and viewer.image_pixmap.isNull()
    path.unlink()
    assert not path.exists()


def test_missing_outputs_clear_previous_content_and_report_a_readable_failure(viewer, tmp_path):
    viewer.show_file(png(tmp_path / 'image.png', 30, 20))
    assert not viewer.show_files([{'path': str(tmp_path / 'missing.png'), 'kind': 'image'}])
    assert viewer.image_path is None and viewer.current_path is None
    assert not viewer.save_original_button.isEnabled()
    assert '没有可预览' in viewer.preview.toPlainText()
