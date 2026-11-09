import json
import sys

import pytest
from PySide6.QtCore import QByteArray
from PySide6.QtWidgets import QComboBox, QDialogButtonBox, QLabel, QPushButton, QSlider

if sys.platform != 'win32':
    pytest.skip('The native replay window uses Win32.', allow_module_level=True)

from arknights_unpacker.ui import level_native_dialog


def test_native_playback_controls_follow_player_state(qtbot, tmp_path, monkeypatch):
    engine = tmp_path / 'Godot.exe'
    engine.touch()
    (tmp_path / 'project.godot').touch()
    (tmp_path / 'native-actors').mkdir()
    (tmp_path / 'native-actors' / 'index.json').touch()
    log_dir = tmp_path / 'logs'
    dialog = level_native_dialog.NativeLevelReplayDialog(
        None, '1-7', engine=engine, project=tmp_path, assets=tmp_path, log_dir=log_dir)
    qtbot.addWidget(dialog)
    launch, output, key_messages = [], [], []
    monkeypatch.setattr(dialog._process, 'start', lambda *args: launch.append(args))
    monkeypatch.setattr(dialog._process, 'processId', lambda: 42)
    monkeypatch.setattr(dialog._process, 'readAllStandardOutput',
                        lambda: QByteArray(output.pop(0) if output else b''))
    monkeypatch.setattr(dialog, '_surface_rect',
                        lambda: level_native_dialog.wintypes.RECT(0, 0, 800, 600))
    monkeypatch.setattr(level_native_dialog, '_owned_window', lambda *_: 100)
    monkeypatch.setattr(level_native_dialog, '_set_window_pos', lambda *_: True)
    monkeypatch.setattr(level_native_dialog, '_set_foreground', lambda *_: True)
    monkeypatch.setattr(level_native_dialog, '_post_message', lambda *args: key_messages.append(args))

    def report(kind, battle, speed, playing):
        state = {'battle': battle, 'duration': 65.5004, 'speed': speed, 'playing': playing}
        output.append(f'{kind} {json.dumps(state)}\n'.encode())
        dialog._read_output()

    def commands():
        return json.loads((log_dir / 'controls.json').read_text(encoding='utf-8'))

    speed = dialog.findChild(QComboBox, 'nativeReplaySpeed')
    seek = dialog.findChild(QSlider, 'nativeReplaySeek')
    pause = dialog.findChild(QPushButton, 'nativeReplayPause')
    time = dialog.findChild(QLabel, 'nativeReplayTime')
    dialog.open()
    qtbot.waitUntil(lambda: bool(launch))
    dialog._find_player()
    assert launch[0][0] == str(engine)
    assert f'--controls={log_dir / "controls.json"}' in launch[0][1]
    assert commands() == {'speed': 2, 'seek_serial': 0, 'seek_seconds': 0.0}
    assert speed.currentData() == 2
    assert not any(widget.isEnabled() for widget in (speed, seek, pause))

    report('PROBE_READY', 0, 2, True)
    assert all(widget.isEnabled() for widget in (speed, seek, pause))
    assert pause.text() == '暂停'
    assert seek.maximum() == 65500
    assert time.text() == '00:00 / 01:05'

    seek.setSliderDown(True)
    seek.setSliderPosition(42000)
    report('PROBE_TICK', 5.25, 2, True)
    assert seek.sliderPosition() == 42000
    assert time.text() == '00:42 / 01:05'
    assert commands()['seek_serial'] == 0
    seek.setSliderDown(False)
    assert commands() == {'speed': 2, 'seek_serial': 1, 'seek_seconds': 42.0}

    speed.setCurrentIndex(speed.findData(1))
    assert commands() == {'speed': 1, 'seek_serial': 1, 'seek_seconds': 42.0}
    pause.click()
    assert [message[:3] for message in key_messages] == [(100, 0x100, 0x20), (100, 0x101, 0x20)]
    report('PROBE_TICK', 42.25, 1, False)
    assert pause.text() == '继续'
    assert seek.value() == 42250
    assert commands()['seek_serial'] == 1

    seek.setSliderDown(True)
    seek.setSliderPosition(seek.maximum())
    seek.setSliderDown(False)
    assert commands()['seek_seconds'] == 65.5004

    dialog._enter_fullscreen()
    assert not any(widget.isVisible() for widget in (speed, seek, pause, time))
    dialog._leave_fullscreen()
    assert all(widget.isVisible() for widget in (speed, seek, pause, time))
    dialog._player_finished(1, None)
    assert not any(widget.isEnabled() for widget in (speed, seek, pause))
    close = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Close)
    assert close.text() == '返回地图预览'
