"""Versioned JSON task metadata and explicit, whitelisted restart recovery.

No executable Python is persisted. An interrupted task never runs on load.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import stat
import uuid
from arknights_unpacker.contracts import as_jsonable

OPERATIONS = {'scan', 'load_data', 'extract', 'report'}
INTERRUPTED = {'排队中', '运行中', '正在取消'}


def show_in_tasks(record):
    value = record.get('show_in_tasks')
    if isinstance(value, bool):
        return value
    title = record.get('title', '')
    # Only these old application-owned read titles predate the explicit flag.
    return not (isinstance(title, str) and (title.startswith('查看资料 · ')
                or title.startswith('读取内部对象 · ') or title == '读取上次扫描与解析结果'))


def retained_file(item):
    try:
        path = Path(item.get('path', ''))
        if not path.is_file():
            return False
        expected = item.get('size')
        return expected is None or path.stat().st_size == int(expected)
    except (OSError, ValueError, TypeError, OverflowError):
        return False


def report_artifact_event(event):
    return isinstance(event, dict) and event.get('stage') == 'report_export' and event.get('status') == 'succeeded' and bool(event.get('path'))


def valid_request(request):
    if not isinstance(request, dict) or request.get('operation') not in OPERATIONS:
        return None
    # JSON round trip rejects functions and keeps recovery declarative.
    return json.loads(json.dumps(request, ensure_ascii=False, allow_nan=False))


class JobHistory:
    def __init__(self, root):
        self.root = Path(root).absolute()
        self.root.mkdir(parents=True, exist_ok=True)
        self.warnings = []

    def remove(self, job_id):
        """Remove only this task's metadata, never any registered output path."""
        if not isinstance(job_id, str) or not re.fullmatch(r'[a-f0-9]{32}', job_id):
            raise ValueError('无效任务ID，已保留任务记录。')
        for folder in (self.root, *self.root.parents):
            info = folder.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError('任务历史路径含重解析点，已保留任务记录。')
        targets = [self.root / (job_id + suffix) for suffix in ('.events.jsonl', '.json')]
        for path in targets:
            try:
                info = path.lstat()
            except FileNotFoundError:
                continue
            if (not stat.S_ISREG(info.st_mode) or
                    getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                raise ValueError('任务历史文件类型异常，已保留任务记录。')
        for path in targets:
            path.unlink(missing_ok=True)

    def save(self, job):
        payload = {key: getattr(job, key) for key in ('job_id', 'title', 'status', 'output', 'created_at',
                   'started_at', 'request', 'last_error', 'result', 'ancestors', 'receipt_root', 'show_in_tasks')}
        payload.update(schema=1, artifacts=as_jsonable(job.artifacts))
        target = self.root / (job.job_id + '.json')
        temporary = target.with_name(target.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            temporary.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def load(self):
        jobs = []
        for path in self.root.glob('*.json'):
            if not re.fullmatch(r'[a-f0-9]{32}', path.stem):
                continue
            try:
                payload = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(payload, dict):
                    raise ValueError('任务历史必须是JSON对象')
                if payload.get('schema') != 1 or payload.get('job_id') != path.stem:
                    raise ValueError('不支持的任务历史格式')
                payload['show_in_tasks'] = show_in_tasks(payload)
                payload['request'] = valid_request(payload.get('request'))
                if payload.get('status') in INTERRUPTED:
                    payload['status'] = '已中断（等待手动重试）'
                jobs.append(payload)
            except (ValueError, OSError, TypeError) as error:
                self.warnings.append(f'任务历史无法读取：{path.name}：{error}')
        return sorted(jobs, key=lambda item: item.get('created_at', 0))

    def append_event(self, job, event):
        if not isinstance(event, dict):
            return
        complete = event.get('kind') in ('object_complete', 'source_complete')
        output = all(key in event for key in ('source', 'object_id', 'path'))
        if not (complete or output or report_artifact_event(event)):
            return
        with (self.root / (job.job_id + '.events.jsonl')).open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + '\n')

    def evidence(self, job):
        records = []
        for job_id in [*job.ancestors, job.job_id]:
            if not re.fullmatch(r'[a-f0-9]{32}', job_id):
                continue
            try:
                record = json.loads((self.root / (job_id + '.json')).read_text(encoding='utf-8'))
            except (ValueError, OSError):
                continue
            events = []
            event_file = self.root / (job_id + '.events.jsonl')
            if event_file.exists():
                with event_file.open(encoding='utf-8') as stream:
                    for line in stream:
                        try:
                            event = json.loads(line)
                            if isinstance(event, dict):
                                events.append(event)
                        except ValueError:
                            continue  # A process crash may leave one incomplete last line.
            record['events'] = events
            records.append(record)
            # Read only this task's explicit receipt directory, never another task's
            # top-level result in a shared user output directory.
            receipt = record.get('receipt_root') or (record.get('result') or {}).get('output_root')
            if receipt:
                result_file = Path(receipt) / 'extraction-result.json'
                try:
                    if record.get('started_at') and result_file.stat().st_mtime >= record['started_at']:
                        records.append({'result': json.loads(result_file.read_text(encoding='utf-8')), 'events': []})
                except (ValueError, OSError):
                    pass
        return records

    def extraction_artifacts(self, job):
        records = self.evidence(job)
        sources, objects = extraction_completion(records)
        artifacts = {}
        for record in records:
            for item in [*(record.get('result') or {}).get('outputs', []), *record.get('events', [])]:
                path = item.get('path')
                source = str(item.get('source', ''))
                obj_id = str(item.get('object_id', ''))
                if path and retained_file(item) and (source in sources or obj_id in objects.get(source, set())):
                    artifacts[path] = {'path': path, 'format': Path(path).suffix.lstrip('.').lower(),
                                       'title': Path(path).name, 'status': 'succeeded'}
        return list(artifacts.values())

    def report_artifacts(self, job):
        """Recover partial reports only from this task's events/registered manifests."""
        artifacts, manifests, known_sizes = {}, set(), {}
        for record in self.evidence(job):
            for item in [*record.get('artifacts', []), *record.get('events', [])]:
                if not isinstance(item, dict):
                    continue
                if not (item.get('format') and item.get('path')):
                    continue
                if item.get('stage') and not report_artifact_event(item):
                    continue
                if item.get('size') is not None:
                    known_sizes[item['path']] = item['size']
                if retained_file(item):
                    artifacts[item['path']] = {**item, 'title': item.get('title', item.get('message', Path(item['path']).name))}
            manifests.update((record.get('result') or {}).get('report_manifests', []))
        for filename in manifests:
            manifest = Path(filename)
            try:
                payload = json.loads(manifest.read_text(encoding='utf-8'))
                if not isinstance(payload, dict):
                    continue
                for item in payload.get('artifacts', []):
                    path = (manifest.parent / item.get('path', '')).resolve()
                    if not path.is_relative_to(manifest.parent.resolve()):
                        continue
                    artifact = {**item, 'path': str(path), 'status': 'succeeded'}
                    if str(path) in known_sizes:
                        artifact['size'] = known_sizes[str(path)]
                    if retained_file(artifact):
                        artifacts[str(path)] = artifact
            except (OSError, ValueError, TypeError):
                continue
        return list(artifacts.values())


def extraction_completion(records):
    """Only complete objects/groups with retained files are eligible to skip."""
    sources, objects = set(), {}
    for record in records:
        outputs = []
        for event in record.get('events', []):
            if all(key in event for key in ('source', 'object_id', 'path')):
                outputs.append(event)
            kind = event.get('kind')
            if kind not in ('object_complete', 'source_complete'):
                continue
            source = str(event.get('source', ''))
            ids = {str(item) for item in event.get('object_ids', [])}
            if event.get('object_id') is not None:
                ids.add(str(event['object_id']))
            if event.get('group_id') is not None:
                ids.add(str(event['group_id']))
            saved = [item for item in outputs if str(item.get('source')) == source and
                     (kind == 'source_complete' or str(item.get('object_id')) in ids)]
            if not saved or not all(retained_file(item) for item in saved):
                continue
            if kind == 'source_complete':
                sources.add(source)
            else:
                objects.setdefault(source, set()).update(ids)
        result = record.get('result') or {}
        if result.get('status') not in ('succeeded', 'partial', 'failed'):
            continue  # A last object's raw file alone does not establish completion.
        saved = result.get('outputs', [])
        errors, skipped = result.get('errors', []), result.get('skipped', [])
        for source in {str(item.get('source')) for item in saved}:
            source_outputs = [item for item in saved if str(item.get('source')) == source]
            source_errors = [item for item in errors if str(item.get('source')) == source]
            source_skipped = [item for item in skipped if str(item.get('source')) == source]
            if source_outputs and all(retained_file(item) for item in source_outputs) and not source_errors and not source_skipped:
                sources.add(source)
            for obj_id in {str(item.get('object_id', '')) for item in source_outputs}:
                object_outputs = [item for item in source_outputs if str(item.get('object_id', '')) == obj_id]
                # Legacy receipts cannot prove a Spine group's full dependency IDs.
                # Those groups are retried conservatively unless a complete event exists.
                legacy_spine = any(str(item.get('kind', '')).startswith('spine') for item in object_outputs)
                if obj_id and not legacy_spine and all(retained_file(item) for item in object_outputs) and not any(
                    error.get('object_id') is None or str(error.get('object_id')) == obj_id for error in source_errors):
                    objects.setdefault(source, set()).add(obj_id)
    return sources, objects


def remaining_extraction(request, records, enumerate_objects, emit, cancel):
    sources, completed = extraction_completion(records)
    path_key = lambda path: os.path.normcase(str(Path(path).absolute()))
    complete_sources = {path_key(source) for source in sources}
    complete_objects = {}
    for source, ids in completed.items():
        complete_objects.setdefault(path_key(source), set()).update(ids)
    paths, object_ids = [], {}
    original_ids = request.get('object_ids') or {}
    for source in request.get('paths', []):
        cancel.check()
        if path_key(source) in complete_sources:
            emit({'message': '保留已完成来源：' + source})
            continue
        if 'expression' in request.get('kinds', []):
            # Composition outputs represent a complete configuration group, not
            # individual Unity objects. Retry incomplete sources conservatively.
            paths.append(source)
            continue
        done = complete_objects.get(path_key(source), set())
        if source in original_ids:
            pending = [str(item) for item in original_ids[source] if str(item) not in done]
        elif done:
            # Object enumeration is also a worker operation, never a UI-thread loop.
            available = enumerate_objects(source, emit=emit, cancel=cancel)
            pending = [str(item['id']) for item in available if str(item['id']) not in done]
        else:
            paths.append(source)
            continue
        if pending:
            paths.append(source)
            object_ids[source] = pending
    return paths, object_ids
