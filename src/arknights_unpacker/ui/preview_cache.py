"""Application-owned previews with producer/viewer lifetimes and bounded recovery.

Only the two reserved preview roots are inspected. An old, unmarked directory
requires both its exact preview request and a complete list of generated files.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import time
import uuid

from PySide6.QtCore import QLockFile


_ID = re.compile(r'[a-f0-9]{32}')
_ROOTS = {'objects': 'preview', 'reports': 'previews'}
_MARKER = '.preview-cache.json'
_LOCK = '.preview.lock'


def _linked(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) &
                                            getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400))


def _cache_path(data_root, value, kind):
    if not isinstance(value, (str, Path)) or not str(value).strip():
        return None
    path = Path(value).expanduser().absolute()
    root = data_root / _ROOTS[kind]
    if path.parent != root or not _ID.fullmatch(path.name) or path.resolve() != path:
        return None
    if root.exists() and (_linked(root) or not root.is_dir()):
        return None
    return path


def _legacy_records(data_root, history_root):
    history = Path(history_root).expanduser().absolute()
    try:
        if not history.exists() or history.resolve() != history or _linked(history):
            return []
        sources = list(history.glob('*.json'))
    except OSError:
        return []
    records = []
    for source in sources:
        try:
            if not _ID.fullmatch(source.stem) or _linked(source) or not source.is_file():
                continue
            record = json.loads(source.read_text(encoding='utf-8'))
            if not isinstance(record, dict) or record.get('schema') != 1 or record.get('job_id') != source.stem:
                continue
            request = record.get('request') or {}
            operation = request.get('operation')
            kind = 'reports' if operation == 'report' and request.get('preview') is True else None
            if operation == 'extract' and (request.get('preview') is True or
                    str(record.get('title', '')).startswith('预览对象 · ')):
                kind = 'objects'
            if kind is None:
                continue
            path = _cache_path(data_root, request.get('output'), kind)
            if path is not None and _cache_path(data_root, record.get('output'), kind) == path:
                records.append((path, record, source))
        except (OSError, ValueError, TypeError, AttributeError):
            continue  # Unreadable metadata is never a deletion authority.
    return records


def legacy_preview_paths(data_root, history_root):
    """Return exact preview outputs proven by old queue requests; never delete."""
    root = Path(data_root).expanduser().resolve()
    return {path for path, _, _ in _legacy_records(root, history_root)}


class PreviewLease:
    def __init__(self, cache, path, lock):
        self.cache = cache
        self.path = path
        self._lock = lock
        self._finished = False
        self._released = False
        self._deferred = False
        self.cleaned = False
        self._callbacks = []

    def finish(self):
        self._finished = True
        self.cache._try_cleanup(self)

    def release(self):
        self._released = True
        self.cache._try_cleanup(self)

    def defer_until_exit(self):
        self._deferred = True

    def on_cleaned(self, callback):
        if self.cleaned:
            callback()
        else:
            self._callbacks.append(callback)


class PreviewCache:
    def __init__(self, data_root, protected_roots=()):
        self.data_root = Path(data_root).expanduser().resolve()
        self.roots = tuple(self.data_root / name for name in _ROOTS.values())
        self.protected_roots = tuple(Path(root).expanduser().resolve() for root in protected_roots if str(root).strip())
        self.session_id = uuid.uuid4().hex
        self.warnings = []
        self.last_cleanup = {'removed': [], 'retained': [], 'warnings': []}
        self._leases = []
        self._shutting_down = False

    def _warn(self, path, reason):
        message = f'预览缓存保留待清理：{path}：{reason}'
        if message not in self.warnings:
            self.warnings.append(message)
        return message

    def _protected(self, path):
        return any(path == root or path.is_relative_to(root) or root.is_relative_to(path)
                   for root in self.protected_roots)

    def _files(self, path):
        if path.parent not in self.roots or not _ID.fullmatch(path.name) or path.resolve() != path:
            raise ValueError('路径不属于本程序的预览缓存')
        if self._protected(path):
            raise ValueError('与正式输出目录相交')
        if _linked(path.parent) or _linked(path) or not path.is_dir():
            raise ValueError('缓存目录包含链接或重解析点')
        files, pending = [], [path]
        while pending:
            for item in pending.pop().iterdir():
                if _linked(item):
                    raise ValueError('缓存中包含链接或重解析点')
                if item.is_dir():
                    pending.append(item)
                elif item.is_file():
                    files.append(item)
                else:
                    raise ValueError('缓存包含无法确认的文件类型')
        return files

    def allocate(self, kind):
        if kind not in _ROOTS:
            raise ValueError('未知预览缓存种类')
        root = self.data_root / _ROOTS[kind]
        if root.exists() and (_linked(root) or not root.is_dir()):
            raise ValueError('预览缓存根目录不能是链接或文件')
        if root.resolve() != root:
            raise ValueError('预览缓存根目录越界')
        path = root / uuid.uuid4().hex
        if self._protected(path):
            raise ValueError('预览缓存与正式输出目录相交，请先选择独立输出目录。')
        path.mkdir(parents=True, exist_ok=False)
        lock = QLockFile(str(path / _LOCK))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            raise OSError('预览缓存无法锁定')
        (path / _MARKER).write_text(json.dumps({'application': 'ArknightsUnpacker', 'schema': 1,
            'session_id': self.session_id, 'kind': kind, 'created_at': time.time()}), encoding='utf-8')
        lease = PreviewLease(self, path, lock)
        self._leases.append(lease)
        return lease

    def _try_cleanup(self, lease):
        if lease.cleaned or not (lease._finished and lease._released):
            return
        if lease._deferred and not self._shutting_down:
            return
        try:
            if lease.path.exists():
                self._files(lease.path)
                lease._lock.unlock()
                shutil.rmtree(lease.path)
            else:
                lease._lock.unlock()
        except (OSError, ValueError) as error:
            self._warn(lease.path, str(error))
            return
        lease.cleaned = True
        for callback in lease._callbacks:
            try:
                callback()
            except Exception as error:
                self._warn(lease.path, '任务记录清理失败：' + str(error))
        lease._callbacks.clear()
        self._leases.remove(lease)

    def shutdown(self):
        self._shutting_down = True
        for lease in tuple(self._leases):
            lease.release()

    def _known_legacy_files(self, path, records):
        known = {}

        def add(filename, size=None, digest=None):
            if not filename:
                return
            target = Path(filename).expanduser().absolute()
            if target.is_relative_to(path) and target.resolve() == target:
                known[target] = (size, digest)

        def outputs(items):
            for item in items or []:
                if isinstance(item, dict):
                    add(item.get('path'), item.get('size'), item.get('sha256'))

        for record, source in records:
            result = record.get('result') or {}
            outputs(record.get('artifacts'))
            outputs(result.get('outputs'))
            receipt = record.get('receipt_root') or result.get('output_root')
            if receipt:
                receipt = Path(receipt) / 'extraction-result.json'
                if receipt.is_relative_to(path) and receipt.is_file() and receipt.resolve() == receipt and not _linked(receipt):
                    payload = json.loads(receipt.read_text(encoding='utf-8'))
                    add(receipt)
                    outputs(payload.get('outputs'))
            event_file = source.with_suffix('.events.jsonl')
            if event_file.is_file() and not _linked(event_file):
                for line in event_file.read_text(encoding='utf-8').splitlines():
                    try:
                        event = json.loads(line)
                        if isinstance(event, dict):
                            outputs([event])
                    except ValueError:
                        continue
            manifests = set(result.get('report_manifests') or [])
            for item in record.get('artifacts') or []:
                if isinstance(item, dict) and item.get('path'):
                    artifact = Path(item['path'])
                    if artifact.parent.name == 'reports':
                        manifests.add(str(artifact.parent.parent / 'manifest.json'))
            for filename in manifests:
                manifest = Path(filename).absolute()
                if manifest.is_relative_to(path) and manifest.is_file() and manifest.resolve() == manifest and not _linked(manifest):
                    payload = json.loads(manifest.read_text(encoding='utf-8'))
                    add(manifest)
                    for item in payload.get('artifacts') or []:
                        add(manifest.parent / item.get('path', ''), item.get('size'), item.get('sha256'))
        return known

    def cleanup_stale(self, history_root):
        result = {'removed': [], 'retained': [], 'warnings': []}
        records = {}
        for path, record, source in _legacy_records(self.data_root, history_root):
            records.setdefault(path, []).append((record, source))
        for root in self.roots:
            try:
                if not root.exists():
                    continue
                if root.resolve() != root or _linked(root) or not root.is_dir():
                    raise ValueError('缓存根目录不是普通目录')
                candidates = list(root.iterdir())
            except (OSError, ValueError) as error:
                result['warnings'].append(self._warn(root, str(error)))
                continue
            for path in candidates:
                if not _ID.fullmatch(path.name):
                    result['retained'].append(str(path))
                    result['warnings'].append(self._warn(path, '不是本程序生成的预览目录名'))
                    continue
                lock = None
                try:
                    files = self._files(path)
                    marker = path / _MARKER
                    if marker in files:
                        metadata = json.loads(marker.read_text(encoding='utf-8'))
                        kind = metadata.get('kind')
                        if metadata.get('application') != 'ArknightsUnpacker' or metadata.get('schema') != 1 or \
                                kind not in _ROOTS or root.name != _ROOTS[kind] or \
                                not _ID.fullmatch(str(metadata.get('session_id', ''))):
                            raise ValueError('无法确认缓存标记归属')
                    elif path in records:
                        if any(item.get('status') in ('排队中', '运行中', '正在取消') for item, _ in records[path]):
                            raise ValueError('旧版本任务仍标记为进行中，无法确认是否在用')
                        known = self._known_legacy_files(path, records[path])
                        for file in files:
                            if file.name == _LOCK:
                                continue
                            if file not in known:
                                raise ValueError('旧缓存包含未登记文件，可能是已保存的副本')
                            size, digest = known[file]
                            if size is not None and file.stat().st_size != int(size):
                                raise ValueError('旧预览文件已修改')
                            if digest and hashlib.sha256(file.read_bytes()).hexdigest() != digest:
                                raise ValueError('旧预览文件内容已修改')
                    else:
                        raise ValueError('没有可证明归属的缓存标记或预览任务')
                    lock = QLockFile(str(path / _LOCK))
                    lock.setStaleLockTime(0)
                    if not lock.tryLock(0):
                        result['retained'].append(str(path))
                        continue
                    self._files(path)
                    lock.unlock()
                    shutil.rmtree(path)
                    result['removed'].append(str(path))
                except (OSError, ValueError, TypeError, AttributeError) as error:
                    result['retained'].append(str(path))
                    result['warnings'].append(self._warn(path, str(error)))
                finally:
                    if lock is not None:
                        lock.unlock()
        self.last_cleanup = result
        return result
