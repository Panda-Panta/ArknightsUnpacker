"""Host the Windows native level player in a Qt preview dialog."""

import ctypes
from ctypes import wintypes
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QEvent, QProcess, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPushButton, QVBoxLayout, QWidget


_user32 = ctypes.WinDLL('user32')
_enum_window_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _win32(name, result, *args):
    function = getattr(_user32, name)
    function.restype = result
    function.argtypes = args
    return function


_enum_windows = _win32('EnumWindows', wintypes.BOOL, _enum_window_proc, wintypes.LPARAM)
_get_window = _win32('GetWindow', wintypes.HWND, wintypes.HWND, wintypes.UINT)
_get_window_process = _win32('GetWindowThreadProcessId', wintypes.DWORD, wintypes.HWND,
                             ctypes.POINTER(wintypes.DWORD))
_get_window_rect = _win32('GetWindowRect', wintypes.BOOL, wintypes.HWND, ctypes.POINTER(wintypes.RECT))
_screen_metric = _win32('GetSystemMetrics', ctypes.c_int, ctypes.c_int)
_set_window_pos = _win32('SetWindowPos', wintypes.BOOL, wintypes.HWND, wintypes.HWND,
                         ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT)
_set_foreground = _win32('SetForegroundWindow', wintypes.BOOL, wintypes.HWND)
_post_message = _win32('PostMessageW', wintypes.BOOL, wintypes.HWND, wintypes.UINT,
                       wintypes.WPARAM, wintypes.LPARAM)

_GW_OWNER = 4
_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_SWP_ASYNCWINDOWPOS = 0x4000
_WM_CLOSE = 0x0010
_WM_KEYDOWN = 0x0100
_WM_KEYUP = 0x0101
_VK_SPACE = 0x20


def _owned_window(owner, pid):
    matches = []

    @_enum_window_proc
    def visit(hwnd, _):
        process = wintypes.DWORD()
        _get_window_process(hwnd, ctypes.byref(process))
        if process.value == pid and _get_window(hwnd, _GW_OWNER) == owner:
            matches.append(hwnd)
            return False
        return True

    _enum_windows(visit, 0)
    return matches[0] if matches else None


class _NativeSurface(QWidget):
    geometry_changed = Signal()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.geometry_changed.emit()

    def moveEvent(self, event):
        super().moveEvent(event)
        self.geometry_changed.emit()


class NativeLevelReplayDialog(QDialog):
    def __init__(self, parent, caption, *, engine, project, assets, log_dir):
        super().__init__(parent)
        self._engine = Path(engine).resolve()
        self._project = Path(project).resolve()
        self._assets = Path(assets).resolve()
        self._log_dir = Path(log_dir).resolve()
        self._player_hwnd = None
        self._windowed_state = None
        self._closing = False
        self._output_tail = b''
        self._last_error = ''
        self.setWindowTitle(f'{caption} · 原生出怪回放')
        self.resize(1020, 660)

        layout = QVBoxLayout(self)
        self._windowed_margins = layout.contentsMargins()
        self._status = QLabel('正在载入原生回放…')
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._surface = _NativeSurface(self)
        self._surface.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self._surface.setStyleSheet('background-color: #141822')
        self._surface.geometry_changed.connect(self._fit_player)
        layout.addWidget(self._surface, 1)

        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self._buttons.button(QDialogButtonBox.StandardButton.Close).setText('关闭')
        self._buttons.rejected.connect(self.close)
        self._fullscreen = QPushButton('全屏播放')
        self._fullscreen.setToolTip('空格播放或暂停，Esc 恢复窗口')
        self._fullscreen.setEnabled(False)
        self._fullscreen.clicked.connect(self._enter_fullscreen)
        self._buttons.addButton(self._fullscreen, QDialogButtonBox.ButtonRole.ActionRole)
        layout.addWidget(self._buttons)

        self._escape_key = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._escape_key.setEnabled(False)
        self._escape_key.activated.connect(self._leave_fullscreen)
        self._space_key = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        self._space_key.setAutoRepeat(False)
        self._space_key.setEnabled(False)
        self._space_key.activated.connect(self._toggle_playback)

        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._process.readyReadStandardOutput.connect(self._read_output)
        self._process.finished.connect(self._player_finished)
        self._process.errorOccurred.connect(self._process_error)
        self._attach = QTimer(self)
        self._attach.setInterval(25)
        self._attach.timeout.connect(self._find_player)
        self._startup = QTimer(self)
        self._startup.setSingleShot(True)
        self._startup.timeout.connect(self._start_player)

        self._parent_window = parent.window() if parent is not None else None
        if self._parent_window is not None:
            self._parent_window.installEventFilter(self)
            parent.destroyed.connect(self._stop_player)

    def open(self):
        super().open()
        self._startup.start(0)

    def _start_player(self):
        if self._closing or self._process.state() != QProcess.ProcessState.NotRunning:
            return
        actors = self._assets / 'native-actors'
        if not self._engine.is_file() or not (self._project / 'project.godot').is_file():
            self._status.setText('原生播放器或项目文件缺失。')
            return
        if not (actors / 'index.json').is_file():
            self._status.setText('原生回放的角色资源未准备完成。')
            return

        self._owner_hwnd = int(self.winId())
        area = self._surface_rect()
        x = area.left - _screen_metric(_SM_XVIRTUALSCREEN)
        y = area.top - _screen_metric(_SM_YVIRTUALSCREEN)
        size = f'{area.right - area.left}x{area.bottom - area.top}'
        # Godot uses an owned Win32 popup for --wid. Keep its screen coordinates
        # aligned with the surface instead of replacing its native window.
        args = ['--path', str(self._project), '--rendering-driver', 'd3d12', '--windowed',
                '--wid', str(self._owner_hwnd), '--position', f'{x},{y}', '--resolution', size,
                '--log-file', str(self._log_dir / 'native-player.log'), '--', '--embedded',
                '--start=0', f'--assets={self._assets}', f'--actors={actors}']
        self._deadline = monotonic() + 30
        self._attach.start()
        self._process.start(str(self._engine), args)

    def _surface_rect(self):
        area = wintypes.RECT()
        _get_window_rect(int(self._surface.winId()), ctypes.byref(area))
        return area

    def _find_player(self):
        pid = self._process.processId()
        hwnd = _owned_window(self._owner_hwnd, pid) if pid else None
        if hwnd:
            self._attach.stop()
            self._player_hwnd = hwnd
            self._fit_player()
            self._fullscreen.setEnabled(True)
            self._space_key.setEnabled(True)
        elif monotonic() >= self._deadline:
            self._stop_player()
            self._status.setText('原生播放器未能嵌入预览窗口。')

    def _fit_player(self):
        if self._player_hwnd:
            area = self._surface_rect()
            if area.right > area.left and area.bottom > area.top:
                _set_window_pos(self._player_hwnd, None, area.left, area.top,
                                area.right - area.left, area.bottom - area.top,
                                _SWP_NOZORDER | _SWP_NOACTIVATE | _SWP_ASYNCWINDOWPOS)

    def moveEvent(self, event):
        super().moveEvent(event)
        self._fit_player()

    def _read_output(self):
        data = self._output_tail + self._process.readAllStandardOutput().data()
        if self._closing:
            return
        complete, _, tail = data.rpartition(b'\n')
        self._output_tail = tail[-4096:]
        for line in complete.decode('utf-8', errors='replace').splitlines():
            if line == 'PROBE_ESCAPE':
                self._leave_fullscreen()
            elif line.startswith('PROBE_READY '):
                self._status.setText('原生回放 · 1080p · 2×')
            elif line.startswith(('PROBE_ERROR ', 'ERROR:', 'SCRIPT ERROR:')):
                self._last_error = line[:300]

    def _toggle_playback(self):
        if self._player_hwnd:
            _post_message(self._player_hwnd, _WM_KEYDOWN, _VK_SPACE, 0x00390001)
            _post_message(self._player_hwnd, _WM_KEYUP, _VK_SPACE, 0xC0390001)

    def _enter_fullscreen(self):
        if self._windowed_state is not None or not self._player_hwnd:
            return
        window = self.windowHandle()
        self._windowed_state = self.windowState(), window.flags()
        window.setFlag(Qt.WindowType.FramelessWindowHint)
        self.layout().setContentsMargins(0, 0, 0, 0)
        self._status.hide()
        self._buttons.hide()
        self.showFullScreen()
        self._fit_player()
        _set_foreground(self._player_hwnd)
        self._escape_key.setEnabled(True)

    def _leave_fullscreen(self):
        if self._windowed_state is None:
            return
        state, flags = self._windowed_state
        self._windowed_state = None
        self.setWindowState(state)
        self.windowHandle().setFlags(flags)
        self.layout().setContentsMargins(self._windowed_margins)
        self._status.show()
        self._buttons.show()
        self._fit_player()
        self._escape_key.setEnabled(False)

    def _player_finished(self, code, _):
        self._read_output()
        self._attach.stop()
        self._player_hwnd = None
        if not self._closing:
            self._leave_fullscreen()
            self._fullscreen.setEnabled(False)
            self._space_key.setEnabled(False)
            self._status.setText(self._last_error or f'原生播放器已退出（{code}）。')

    def _process_error(self, _):
        if not self._closing:
            self._attach.stop()
            self._status.setText(f'原生播放器错误：{self._process.errorString()}')

    def _stop_player(self):
        if self._closing:
            return
        self._closing = True
        self._startup.stop()
        self._attach.stop()
        if self._process.state() == QProcess.ProcessState.NotRunning:
            return
        pid = self._process.processId()
        hwnd = _owned_window(self._owner_hwnd, pid) if pid else None
        if hwnd:
            _post_message(hwnd, _WM_CLOSE, 0, 0)
            if self._process.waitForFinished(750):
                return
        self._process.kill()
        self._process.waitForFinished(1500)

    def eventFilter(self, watched, event):
        if watched is self._parent_window and event.type() == QEvent.Type.Close:
            self.close()
        return super().eventFilter(watched, event)

    def done(self, result):
        self._stop_player()
        super().done(result)
