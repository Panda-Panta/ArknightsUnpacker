"""Isolated native decoders with a small, structured disk/JSONL protocol."""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback
import uuid

from .contracts import CancelToken, CancelledError, ExtractionRequest, as_jsonable, null_progress
from .paths import atomic_json


class FileCancelToken(CancelToken):
    def __init__(self, marker: Path):
        super().__init__()
        self.marker = marker

    @property
    def cancelled(self):
        return super().cancelled or self.marker.exists()


def worker_entry(request_file: str) -> int:
    request = json.loads(Path(request_file).read_text(encoding="utf-8"))
    result_path = Path(request["result_file"])
    cancel = FileCancelToken(Path(request.get("cancel_file", str(result_path) + ".cancel")))
    event_file = Path(request_file).parent / "events.jsonl"
    event_lock = threading.Lock()
    fallback_log = None
    previous_stderr = sys.stderr
    if sys.stderr is None:
        fallback_log = (Path(request_file).parent / "diagnostics.log").open("a", encoding="utf-8")
        sys.stderr = fallback_log

    def emit(event):
        # The windowed PyInstaller bootloader intentionally has no stdout.
        # A task-local JSONL stream works in both source and frozen builds.
        with event_lock:
            with event_file.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(as_jsonable(event), ensure_ascii=False) + "\n")

    try:
        operation = request.get("operation")
        args = request.get("args", {})
        cancel.check()
        with contextlib.redirect_stdout(sys.stderr):
            if operation == "tables":
                from .extraction.tables import load_local_tables
                value = load_local_tables(Path(args["root"]), Path(args["cache_dir"]), emit=emit, cancel=cancel)
            elif operation == "extract":
                from .extraction.engine import run_extraction
                value = run_extraction(ExtractionRequest(**args), emit, cancel)
            elif operation == "objects":
                from .extraction.engine import list_bundle_objects
                value = list_bundle_objects(args["path"])
            elif operation == "character_catalog":
                from .extraction.unity import load_bundle
                from .extraction.characters import character_catalog
                value = character_catalog(load_bundle(args['path']), check=cancel.check)
            elif operation in {"gameplay", "gameplay_level"}:
                from .extraction.gameplay import load_autochess, load_gameplay_level
                load = load_autochess if operation == "gameplay" else load_gameplay_level
                value = load(**args, emit=emit, cancel=cancel)
            elif operation == "level_metadata":
                from .extraction.level_metadata import load_level_metadata
                value = load_level_metadata(**args, emit=emit, cancel=cancel)
            elif operation == "level_map_image":
                from .extraction.level_map_image import load_level_map_image
                value = load_level_map_image(**args, emit=emit, cancel=cancel)
            elif operation == "level_preview_info":
                from .extraction.gameplay import load_level_preview_info
                value = load_level_preview_info(**args, emit=emit, cancel=cancel)
            elif operation == "level_replay":
                from .extraction.level_replay_assets import prepare_level_playback
                value = prepare_level_playback(**args, emit=emit, cancel=cancel)
            elif operation == "level_tag_options":
                from .extraction.gameplay import load_level_data
                from .extraction.level_tags import load_level_tags
                crisis_info_path = args.pop("crisis_info_path", None)
                value = load_level_tags(**args, emit=emit, cancel=cancel, crisis_info_path=crisis_info_path)
                if value["tags"]:
                    level_source, level = load_level_data(**args, emit=emit, cancel=cancel)
                    value["level"] = level
                    value["diagnostics"].extend(level_source.diagnostics)
            else:
                raise ValueError(f"未知工作进程操作: {operation}")
        cancel.check()
        atomic_json(result_path, {"status": "succeeded", "value": as_jsonable(value)})
        emit({"type": "worker_done"})
        return 0
    except BaseException as exc:
        atomic_json(result_path, {"status": "cancelled" if isinstance(exc, CancelledError) else "failed",
                                  "error": str(exc), "error_type": type(exc).__name__, "traceback": traceback.format_exc()})
        return 2
    finally:
        if fallback_log is not None:
            fallback_log.close()
            sys.stderr = previous_stderr


def worker_server_entry(server_directory: str) -> int:
    """Reuse decoder imports for interactive requests, with task-local IPC.

    A process crash still belongs to this worker, never to the GUI. No loaded
    bundles or decoded outputs are cached between requests: every selection
    reads its current source again. Idle exit also bounds retained imports.
    """
    root = Path(server_directory)
    settings = json.loads((root / "server.json").read_text(encoding="utf-8"))
    idle_timeout = float(settings.get("idle_timeout", 60))
    command_file = root / "command.json"
    last_request = time.monotonic()
    while True:
        if command_file.exists():
            command = json.loads(command_file.read_text(encoding="utf-8"))
            command_file.unlink()
            request_file = Path(command["request_file"])
            # The parent can distinguish a completed idle exit from a crash
            # after extraction has started, and must never replay the latter.
            (request_file.parent / "started").touch()
            worker_entry(str(request_file))
            last_request = time.monotonic()
        elif time.monotonic() - last_request >= idle_timeout:
            return 0
        else:
            time.sleep(0.025)


class WorkerRunner:
    def __init__(self, work_root: Path):
        self.work_root = Path(work_root).expanduser().resolve()
        self._active = set()
        self._lock = threading.Lock()
        self._reusable_lock = threading.Lock()
        self._preview_server = None
        self._preview_idle_timeout = 60.0
        self._closed = False

    def run(self, operation: str, args: dict, emit=null_progress, cancel: CancelToken | None = None, *, reusable=False):
        cancel = cancel or CancelToken()
        cancel.check()
        if reusable:
            if operation not in {"objects", "extract", "character_catalog"}:
                raise ValueError("仅交互资源浏览可复用工作进程")
            return self._run_reusable(operation, args, emit, cancel)
        if self._closed:
            raise RuntimeError("工作进程管理器已关闭")
        task = self.work_root / uuid.uuid4().hex
        task.mkdir(parents=True, exist_ok=False)
        result = task / "result.json"
        marker = task / "cancel"
        req = task / "request.json"
        atomic_json(req, {"operation": operation, "args": args, "result_file": str(result), "cancel_file": str(marker)})
        cmd = [sys.executable]
        if not getattr(sys, "frozen", False):
            cmd += ["-X", "utf8", "-m", "arknights_unpacker"]
        cmd += ["--worker", str(req)]
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        if not getattr(sys, "frozen", False):
            src = str(Path(__file__).resolve().parents[1])
            env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
        cancelled_at = None
        event_file = task / "events.jsonl"
        event_offset = 0

        def drain_events():
            nonlocal event_offset
            if not event_file.exists():
                return
            with event_file.open("r", encoding="utf-8") as stream:
                stream.seek(event_offset)
                while True:
                    start = stream.tell()
                    line = stream.readline()
                    if not line or not line.endswith("\n"):
                        event_offset = start
                        break
                    event_offset = stream.tell()
                    try:
                        emit(json.loads(line))
                    except (ValueError, TypeError):
                        emit({"type": "log", "message": line.strip()})

        with (task / "worker.log").open("w", encoding="utf-8") as log:
            with self._lock:
                if self._closed:
                    raise RuntimeError("工作进程管理器已关闭")
                proc = subprocess.Popen(cmd, cwd=task, stdout=log, stderr=log,
                                        text=True, encoding="utf-8", errors="replace", env=env,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self._active.add(proc)

            try:
                while proc.poll() is None:
                    drain_events()
                    time.sleep(0.1)
                    if cancel.cancelled:
                        if cancelled_at is None:
                            marker.touch()
                            cancelled_at = time.monotonic()
                        elif time.monotonic() - cancelled_at > 2.0:
                            proc.terminate()
                            try:
                                proc.wait(timeout=3)
                            except subprocess.TimeoutExpired:
                                proc.kill()
                drain_events()
                cancel.check()
                payload = json.loads(result.read_text(encoding="utf-8")) if result.exists() else {}
                if proc.returncode != 0 or payload.get("status") != "succeeded":
                    detail = payload.get("error", "工作进程未返回有效结果")
                    raise RuntimeError(f"{detail}\n诊断日志：{task / 'worker.log'}")
                return payload["value"]
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=5)
                with self._lock:
                    self._active.discard(proc)

    def shutdown(self):
        with self._lock:
            self._closed = True
            processes = list(self._active)
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()
        for proc in processes:
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
        with self._lock:
            self._active.difference_update(processes)

    def _start_preview_server(self):
        previous = self._preview_server
        if previous is not None:
            with self._lock:
                self._active.discard(previous[0])
        root = self.work_root / ("interactive-" + uuid.uuid4().hex)
        root.mkdir(parents=True, exist_ok=False)
        atomic_json(root / "server.json", {"idle_timeout": self._preview_idle_timeout})
        cmd = [sys.executable]
        if not getattr(sys, "frozen", False):
            cmd += ["-X", "utf8", "-m", "arknights_unpacker"]
        cmd += ["--worker-server", str(root)]
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        if not getattr(sys, "frozen", False):
            src = str(Path(__file__).resolve().parents[1])
            env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
        with (root / "worker.log").open("w", encoding="utf-8") as log:
            # Registration and shutdown share the same lock, so closing the
            # service cannot miss a process that is being launched here.
            with self._lock:
                if self._closed:
                    raise RuntimeError("工作进程管理器已关闭")
                proc = subprocess.Popen(cmd, cwd=root, stdout=log, stderr=log,
                                        text=True, encoding="utf-8", errors="replace", env=env,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self._active.add(proc)
        self._preview_server = proc, root
        return proc, root

    def _run_reusable(self, operation, args, emit, cancel):
        # Usually the GUI queue already serializes these calls; also handle
        # independent service callers without making lock waits uncancellable.
        while not self._reusable_lock.acquire(timeout=0.05):
            cancel.check()
            if self._closed:
                raise RuntimeError("工作进程管理器已关闭")
        try:
            cancel.check()
            if self._closed:
                raise RuntimeError("工作进程管理器已关闭")
            task = self.work_root / uuid.uuid4().hex
            task.mkdir(parents=True, exist_ok=False)
            result = task / "result.json"
            marker = task / "cancel"
            req = task / "request.json"
            atomic_json(req, {"operation": operation, "args": args,
                              "result_file": str(result), "cancel_file": str(marker)})
            server = self._preview_server
            proc, root = server if server is not None and server[0].poll() is None else self._start_preview_server()
            atomic_json(root / "command.json", {"request_file": str(req)})
            event_file = task / "events.jsonl"
            event_offset = 0
            cancelled_at = None
            idle_retry = False

            def drain_events():
                nonlocal event_offset
                if not event_file.exists():
                    return
                with event_file.open("r", encoding="utf-8") as stream:
                    stream.seek(event_offset)
                    while True:
                        start = stream.tell()
                        line = stream.readline()
                        if not line or not line.endswith("\n"):
                            event_offset = start
                            break
                        event_offset = stream.tell()
                        try:
                            emit(json.loads(line))
                        except (ValueError, TypeError):
                            emit({"type": "log", "message": line.strip()})

            try:
                while not result.exists():
                    drain_events()
                    if cancel.cancelled:
                        if cancelled_at is None:
                            marker.touch()
                            cancelled_at = time.monotonic()
                        elif time.monotonic() - cancelled_at > 2.0 and proc.poll() is None:
                            proc.terminate()
                            try:
                                proc.wait(timeout=3)
                            except subprocess.TimeoutExpired:
                                proc.kill()
                                proc.wait(timeout=3)
                    if proc.poll() is not None:
                        # Idle timeout can race command publication. Retry only
                        # if the process never began this task; never replay an
                        # extraction whose worker crashed after touching files.
                        if (not idle_retry and proc.returncode == 0 and
                                not (task / "started").exists() and not cancel.cancelled and not self._closed):
                            proc, root = self._start_preview_server()
                            atomic_json(root / "command.json", {"request_file": str(req)})
                            idle_retry = True
                            continue
                        break
                    time.sleep(0.025)
                drain_events()
                cancel.check()
                payload = json.loads(result.read_text(encoding="utf-8")) if result.exists() else {}
                if payload.get("status") != "succeeded":
                    detail = payload.get("error", "工作进程未返回有效结果")
                    raise RuntimeError(f"{detail}\n诊断日志：{root / 'worker.log'}")
                return payload["value"]
            except BaseException:
                # Exceptions from progress consumers must not leave an old task
                # running when the next caller posts a new command.
                if not result.exists() and proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=3)
                raise
            finally:
                if proc.poll() is not None:
                    with self._lock:
                        self._active.discard(proc)
        finally:
            self._reusable_lock.release()

