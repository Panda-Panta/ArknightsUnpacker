"""Local resource changes and task history for the Vue workbench."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from arknights_unpacker.contracts import as_jsonable
from arknights_unpacker.library.classifications import category_labels
from arknights_unpacker.library.preview_types import source_preview_type
from .resources import _SOURCES, _STATUS, _bounded_int, _relative, _timestamp, _value


_IMAGE_EXCLUSIONS = {'.usm', '.idx', '.acb', '.awb'}
_UNRETRYABLE = {'运行中', '正在取消', '排队中', '成功'}
_SORTS = {'path', 'category', 'source', 'status', 'size', 'modified', 'observed', 'evidence'}


def _file_info(path):
    mime = source_preview_type(path)
    kind = mime[1] if mime and mime[1] in {'image', 'audio', 'video'} else ''
    return kind


class WorkbenchRecords:
    def __init__(self, window, resources):
        self.window = window
        self.resources = resources
        self._observation = None
        self._changes = None
        self._files = {}
        self._diff = {}
        self._categories = list(category_labels())
        self._progress = None
        self.window.queue.progress.connect(self._on_progress)

    def _on_progress(self, event):
        job = self.window.queue.active
        if job is not None and job.show_in_tasks and isinstance(event, dict):
            current = event.get('current', event.get('completed', event.get('done')))
            total = event.get('total', event.get('total_files'))
            self._progress = {
                'id': job.job_id, 'message': str(event.get('message', '')),
                'current': current if isinstance(current, (int, float)) else None,
                'total': total if isinstance(total, (int, float)) else None,
            }

    def _sync(self):
        services = self.window.services
        snapshot = services.scan_snapshot
        if not self.window.root or snapshot is None or Path(_value(snapshot, 'root')).resolve() != Path(self.window.root).resolve():
            snapshot = None
        changes = services.file_changes if snapshot is not None else None
        if snapshot is self._observation and changes is self._changes:
            return
        self._observation, self._changes = snapshot, changes
        self._files = {_relative(_value(item, 'path')): item for item in _value(snapshot, 'files', [])}
        self._files.pop('', None)
        self._diff = {_relative(_value(item, 'path')): item for item in _value(changes, 'changes', [])}
        self._diff.pop('', None)
        sources = list(self._files.values())
        for change in self._diff.values():
            sources.extend(record for record in (_value(change, 'before'), _value(change, 'after')) if record)
        self._categories = sorted({*category_labels(), *(_value(item, 'category') or '未知用途' for item in sources)})

    def _updates(self, payload, *, selection=False):
        self._sync()
        hours = float(self.window.services.config.get('hours', 24))
        end = _value(self._observation, 'started_at', 0)
        lower = (end - hours * 3600) * 1_000_000_000
        upper = end * 1_000_000_000
        baseline = bool(_value(self._changes, 'baseline_id'))
        recent = {path for path, item in self._files.items() if lower <= (_value(item, 'mtime_ns') or 0) <= upper}
        changes = self._diff.keys() if baseline else set()
        scope = payload.get('scope')
        if scope == 'recent':
            paths = recent
        elif scope == 'changes':
            paths = changes
        elif scope == 'both':
            paths = recent & changes
        else:
            paths = recent | changes
        query = str(payload.get('query') or '').strip().casefold()
        category = payload.get('category')
        source = payload.get('source')
        sort = payload.get('sort')
        sort = sort if isinstance(sort, str) and sort in _SORTS else 'path'
        known, unknown = [], []
        for path in sorted(paths):
            change = self._diff.get(path)
            record = self._files.get(path) or _value(change, 'before')
            kind = _value(change, 'kind', 'unchanged') if baseline else 'first_seen'
            if record is None or kind == 'removed' and payload.get('excludeDeleted', True):
                continue
            record_category = _value(record, 'category') or '未知用途'
            layer = _SOURCES.get(_value(record, 'layer'), '')
            status = _STATUS.get(kind, kind)
            extension = Path(path).suffix.casefold()
            if (category and category != record_category or source and source != layer
                    or payload.get('abOnly') and extension != '.ab'
                    or query not in f'{path} {record_category} {status} {layer}'.casefold()):
                continue
            raw = self.resources.raw_row(path) if path in self._files else None
            usable = bool(raw and raw['extractable'])
            row = {
                'id': raw['id'] if raw else 'history:' + path, 'kind': 'file',
                'name': path.rsplit('/', 1)[-1], 'path': path, 'category': record_category,
                'status': status, 'source': layer, 'size': _value(record, 'size'),
                'modified': _timestamp(_value(record, 'mtime_ns')),
                'observed': _value(record, 'first_seen_at'),
                'evidence': '；'.join(label for active, label in (
                    (path in recent, '本机修改时间'), (path in changes, '两次完整观测比较')) if active),
                'extractable': usable, 'images': usable and extension not in _IMAGE_EXCLUSIONS,
                'previewable': usable and raw['previewable'],
            }
            if selection:
                if usable:
                    known.append((row['id'], row['images']))
                continue
            sort_value = (_value(record, 'mtime_ns') or None) if sort == 'modified' else row[sort]
            if sort_value is None:
                unknown.append(row)
            else:
                known.append((sort_value.casefold() if isinstance(sort_value, str) else sort_value, row))
        if selection:
            return {'ids': [item[0] for item in known], 'imageIds': [item[0] for item in known if item[1]]}
        known.sort(key=lambda item: item[0], reverse=payload.get('descending') is True)
        matched = [item[1] for item in known] + unknown
        page = _bounded_int(payload.get('page'), 1, 1)
        size = _bounded_int(payload.get('pageSize'), 100, 1, 500)
        start = (page - 1) * size
        return {
            'rows': matched[start:start + size], 'total': len(matched), 'categories': self._categories,
            'sources': list(_SOURCES.values()), 'hours': hours, 'hasBaseline': baseline,
            'scanTime': _value(self._observation, 'finished_at'),
            'diagnostics': (_value(self._observation, 'errors', []) + _value(self._changes, 'diagnostics', []))[:6],
        }

    def _jobs(self):
        queue = self.window.queue
        active = queue.active
        visible = active is not None and active.show_in_tasks
        return {
            'paused': bool(queue.paused), 'active': active.job_id if visible else '',
            'progress': self._progress if visible and self._progress and self._progress['id'] == active.job_id else None,
            'rows': [{
                'id': job.job_id, 'title': job.title, 'status': job.status, 'created': job.created_at,
                'started': job.started_at or None, 'output': job.receipt_root or job.output,
                'retryable': job.status not in _UNRETRYABLE and (bool(job.request) or job.call is not None),
            } for job in reversed(queue.visible_jobs)],
        }

    def _job(self, identifier):
        return next((job for job in self.window.queue.visible_jobs if job.job_id == identifier), None)

    def _artifacts(self, job, *, recover=False):
        queue = self.window.queue
        operation = (job.request or {}).get('operation')
        artifacts = as_jsonable(job.artifacts)
        if recover and queue.history and (operation == 'report' or operation == 'extract' and not artifacts):
            recovered = (queue.history.report_artifacts(job) if operation == 'report'
                         else queue.history.extraction_artifacts(job))
            if recovered:
                dated = {item['path']: item for item in artifacts}
                dated.update({item['path']: item for item in recovered})
                artifacts = job.artifacts = list(dated.values())
                queue._persist(job)
        result = []
        for item in artifacts:
            filename = item.get('path')
            if not filename:
                continue
            path = Path(filename)
            exists = path.is_file()
            kind = _file_info(path) if exists else ''
            result.append({
                'path': str(path), 'name': item.get('title') or path.name,
                'format': item.get('format') or path.suffix.lstrip('.'), 'kind': kind,
                'url': QUrl.fromLocalFile(str(path)).toString() if kind else '', 'exists': exists,
            })
        return result

    def _job_details(self, job):
        result = job.result or {}
        return {
            'error': job.last_error, 'artifacts': self._artifacts(job, recover=True),
            'errors': result.get('errors', []), 'skipped': result.get('skipped', []),
        }

    @staticmethod
    def _open_path(path):
        if not path or not Path(path).exists() or not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
            raise ValueError('文件或目录已不可用。')

    def _job_action(self, payload):
        queue = self.window.queue
        operation = payload.get('operation')
        if operation == 'pause':
            return queue.toggle_pause()
        if operation == 'clear':
            return queue.clear_successful()
        if operation == 'cancel':
            if queue.active and queue.active.show_in_tasks:
                return queue.cancel()
            raise ValueError('当前没有可取消的任务。')
        job = self._job(payload.get('id'))
        if job is None:
            raise ValueError('任务记录已不可用。')
        if operation == 'retry':
            return queue.retry(next(index for index, item in enumerate(queue.jobs) if item is job))
        if operation == 'output':
            return self._open_path(job.receipt_root or job.output)
        if operation == 'artifact':
            path = payload.get('path')
            if any(item['path'] == path and item['exists'] for item in self._artifacts(job)):
                return self._open_path(path)
            raise ValueError('任务产物已不可用。')
        raise ValueError('未知任务操作。')

    def dispatch(self, action, payload):
        if action == 'recordsUpdates':
            return self._updates(payload)
        if action == 'recordsUpdateSelection':
            return self._updates(payload, selection=True)
        if action == 'recordsExtract':
            ids = payload.get('ids')
            paths = self.resources.paths(ids, extraction=True)
            if payload.get('images'):
                paths = [path for path in paths if Path(path).suffix.casefold() not in _IMAGE_EXCLUSIONS]
                if not paths:
                    raise ValueError('所选资源中没有可导出图片的文件。')
                return self.window.extract(paths, kinds=['image'], mode='auto')
            return self.window.extract(paths)
        if action == 'recordsOpen':
            identifier = payload.get('id')
            self.resources.paths([identifier])
            return self.resources.resource_row(identifier)
        if action == 'recordsJobs':
            return self._jobs()
        if action == 'recordsJobDetails':
            job = self._job(payload.get('id'))
            if job is not None:
                return self._job_details(job)
            raise ValueError('任务记录已不可用。')
        if action == 'recordsJobAction':
            return self._job_action(payload)
        raise ValueError('未知的记录操作。')
