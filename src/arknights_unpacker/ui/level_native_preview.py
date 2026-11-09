"""Prepare the selected native replay independently of the foreground queue."""
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QPushButton


@dataclass(frozen=True)
class NativeReplayRequest:
    root: str
    version: str
    path: str
    tags: tuple | None
    archive: str | Path | None
    caption: str = field(compare=False)

    def options(self):
        return {'caption': self.caption, 'tag_ids': self.tags, 'crisis_info_path': self.archive}


@dataclass
class _Preparation:
    request: NativeReplayRequest
    lease: object
    prewarm: bool
    job: object = None
    result: dict | None = None


@dataclass
class _Preview:
    request: NativeReplayRequest
    dialog: object
    button: QPushButton
    info_job: object
    waiting: bool = False
    player: object = None


class NativeReplayPreloader:
    def __init__(self, window, catalog_view, lookup, project):
        self.window = window
        self.view = catalog_view
        self.lookup = lookup
        self.project = project
        self.queue = window.native_replay_queue
        self.active = None
        self.pending = None
        self.preview = None
        self.selection = None
        self.failure = None
        self.timer = QTimer(catalog_view)
        self.timer.setSingleShot(True)
        self.timer.setInterval(650)
        self.timer.timeout.connect(self._selected)
        self.view.replay_selection_changed.connect(self._selection_changed)
        window.tabs.currentChanged.connect(lambda *_: self.timer.start())
        self.queue.progress.connect(self._progress)
        self.queue.settled.connect(self._settled)

    def _selection_changed(self, path):
        self.selection = path
        self.timer.start()

    def _selected(self):
        if self.preview is not None or self.window._closing:
            return
        request = self.lookup(self.selection) if self.selection and self.view.isVisible() else None
        if request is None:
            self.cancel()
        else:
            self.prepare(request)

    def cancel(self):
        self.timer.stop()
        self.pending = None
        if self.active is not None:
            self.active.job.token.cancel()

    def attach(self, request, dialog, info_job):
        self.timer.stop()
        button = dialog.replay_button
        button.setToolTip('使用游戏原版场景和角色，在原生窗口播放出怪。')
        self.preview = preview = _Preview(request, dialog, button, info_job)
        dialog.finished.connect(lambda *_: self._close_preview(preview))
        button.clicked.connect(lambda: self._play(preview))
        button.show()
        self.prepare(request)

    def _close_preview(self, preview):
        self.preview = None
        if preview.player is not None:
            preview.player.close()
        self.timer.start()

    def _play(self, preview):
        preview.waiting = True
        preview.button.setEnabled(False)
        if preview.info_job is not None and preview.info_job.status in ('排队中', '运行中'):
            preview.info_job.token.cancel()
        self.prepare(preview.request, prewarm=False)

    def _current(self, request):
        preview = self.preview
        return preview if preview and preview.request == request else None

    def _status(self, request, message):
        if (preview := self._current(request)) is not None:
            if preview.waiting:
                message = f'{message} · 完成后自动播放'
            preview.dialog.show_replay_status(message)

    def prepare(self, request, *, prewarm=True):
        if self.window._closing:
            return
        if self.active is not None:
            if self.active.request == request and not self.active.job.token.cancelled:
                self._status(request, '正在准备原版关卡和角色动画…')
                return
            self.active.job.token.cancel()
        self.pending = None
        if prewarm and self.failure is not None and self.failure[0] == request:
            self._status(request, self.failure[1])
            return
        services = self.window.services
        try:
            cached = services.cached_native_level_replay(
                request.root, request.path, request.version, **request.options())
            if cached is not None:
                self._ready(request, cached)
                return
            if self.active is not None:
                self.pending = (request, prewarm)
                self._status(request, '等待上一项原生回放准备退出…')
                return
            lease = self.window.preview_cache.allocate('objects')
        except (OSError, ValueError, RuntimeError) as error:
            self._failed(request, str(error))
            return

        self.active = preparation = _Preparation(request, lease, prewarm)

        def complete(result):
            preparation.result = result

        self._status(request, '正在后台准备原版关卡和角色动画…')
        preparation.job = self.queue.submit('准备原生关卡回放', lambda **kw: services.load_level_replay(
            request.root, request.path, request.version, lease.path, native=True, prewarm=prewarm,
            **request.options(), **kw), complete, show_in_tasks=False)

    def _progress(self, event):
        if self.active is not None and not self.active.job.token.cancelled and isinstance(event, dict):
            if message := event.get('message'):
                self._status(self.active.request, message)

    def _settled(self, job):
        preparation = self.active
        if preparation is None or preparation.job is not job:
            return
        self.active = None
        preparation.lease.finish()
        preparation.lease.release()
        self.queue.forget_finished([job.job_id])
        request = preparation.request
        if not self.window._closing and not job.token.cancelled:
            if preparation.result is not None:
                self._ready(request, preparation.result)
            else:
                lines = [line for line in job.last_error.strip().splitlines()
                         if line and not line.startswith('诊断日志：')]
                reason = lines[-1] if lines else '原生回放暂不可用。'
                reason = reason.removeprefix('RuntimeError: ').removeprefix('ValueError: ')
                preview = self._current(request)
                if preparation.prewarm and preview is not None and preview.waiting:
                    from ..level_native_cache import NativeReplayPrewarmBudgetError

                    if reason == str(NativeReplayPrewarmBudgetError()):
                        self.prepare(request, prewarm=False)
                        return
                self._failed(request, reason)
        if self.pending is not None:
            pending, prewarm = self.pending
            self.pending = None
            self.prepare(pending, prewarm=prewarm)

    def _failed(self, request, reason):
        self.failure = (request, reason)
        if (preview := self._current(request)) is not None:
            preview.waiting = False
            preview.button.setEnabled(True)
            preview.dialog.show_replay_status(reason)

    def _ready(self, request, result):
        if result['level_id'] != request.path or result['resource_version'] != request.version:
            self._failed(request, '回放来源与当前关卡不匹配。')
            return
        self.failure = None
        preview = self._current(request)
        if preview is None:
            return
        if preview.waiting:
            preview.waiting = False
            try:
                self._open_player(preview, result)
            except (OSError, ValueError, RuntimeError) as error:
                self._failed(request, str(error))
                return
        preview.button.setEnabled(True)
        preview.dialog.show_replay_status(
            f"原生回放已准备 · {result['spawns']} 次出怪 · {result['duration']:.1f} 秒")
        details = list(result.get('diagnostics') or ())
        if 'seed' in result:
            details.insert(0, f"本次回放的随机种子为 {result['seed']}")
        preview.dialog.replay_status.setToolTip('\n'.join(details))

    def _open_player(self, preview, result):
        from PySide6.QtCore import Qt
        from .level_native_dialog import NativeLevelReplayDialog

        lease = self.window.preview_cache.allocate('objects')
        lease.finish()
        try:
            player = NativeLevelReplayDialog(preview.dialog, preview.request.caption,
                                             engine=self.project / 'Godot.exe', project=self.project,
                                             assets=result['native_assets'], log_dir=lease.path)
            player.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            self.window._track_dialog(player)

            def closed(*_):
                preview.player = None
                lease.release()

            player.finished.connect(closed)
            preview.player = player
            player.open()
        except Exception:
            lease.release()
            raise
