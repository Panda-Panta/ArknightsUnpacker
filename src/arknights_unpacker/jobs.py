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


class WorkerRunner:
    def __init__(self, work_root: Path):
        self.work_root = Path(work_root).expanduser().resolve()
        self._active = set()
        self._lock = threading.Lock()

    def run(self, operation: str, args: dict, emit=null_progress, cancel: CancelToken | None = None):
        cancel = cancel or CancelToken()
        cancel.check()
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
            proc = subprocess.Popen(cmd, cwd=task, stdout=log, stderr=log,
                                    text=True, encoding="utf-8", errors="replace", env=env,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            with self._lock:
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
            processes = list(self._active)
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()

