from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
from uuid import uuid4

from ..contracts import ExportFormat, ReportArtifact, ReportDocument, as_jsonable, CancelToken, CancelledError, null_progress
from .compose import validate_options, restrict_changes
from .html_render import render_html, render_index
from .model import plain, text_report


def safe_filename(value: str, maximum: int = 96) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(value)).strip(' .')
    value = value[:maximum].rstrip(' .') or 'report'
    if value.split('.')[0].upper() in {'CON','PRN','AUX','NUL', *(f'COM{i}' for i in range(1,10)), *(f'LPT{i}' for i in range(1,10))}:
        value = '_' + value
    return value


def _write(path: Path, content: str):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(content, encoding='utf-8')
    temporary.replace(path)


def _check_source_paths(document: ReportDocument, target: Path):
    """Reject writes inside known source directories, resolving junctions as well."""
    root_keys = {'source_root','input_root','game_root','installation_root','source_roots','input_roots'}
    def walk(value, key=''):
        if isinstance(value, dict):
            for k, v in value.items():
                yield from walk(v, key if key in root_keys else str(k))
        elif isinstance(value, (list, tuple)):
            for v in value:
                yield from walk(v, key)
        elif isinstance(value, (str, Path)) and key in root_keys:
            if str(value).strip():
                yield Path(value)
    for root in walk(as_jsonable(document)):
        if root.exists():
            source = root.resolve()
            if target == source or target.is_relative_to(source):
                raise ValueError(f'输出目录不能位于游戏输入目录内：{source}')


def export_report(document: ReportDocument, target: Path, formats: set[ExportFormat], *,
                  cancel: CancelToken | None = None, emit=null_progress) -> list[ReportArtifact]:
    """Export a new task folder, returning only the requested report artifacts.

    The caller must additionally validate its selected installation root when the
    input models do not carry source_root metadata. No existing output is reused.
    """
    requested = {ExportFormat(value) for value in formats}
    if not requested:
        return []
    validate_options(document.options)
    cancel = cancel or CancelToken()
    cancel.check()
    target = Path(target).expanduser().resolve()
    _check_source_paths(document, target)
    # Bounded filenames keep ordinary Windows paths under MAX_PATH without
    # requiring a machine-wide long-path setting.
    if len(str(target)) > 160:
        raise ValueError('输出目录路径过长，请选择更短的目录（不超过160个字符）')
    task = target / ('report-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:10])
    directory = task / 'reports'
    name_budget = min(88, 240 - len(str(directory)) - 10)
    if name_budget < 24:
        raise ValueError('输出目录路径过长，请选择更短的目录')
    directory.mkdir(parents=True, exist_ok=False)
    artifacts: list[ReportArtifact] = []
    failures = []
    status = 'succeeded'
    def record(artifact: ReportArtifact):
        artifacts.append(artifact)
        emit({'kind':'progress','stage':'report_export','format':artifact.format,'status':'succeeded',
              'path':artifact.path,'message':artifact.title})
    stem = safe_filename(document.title, min(48, name_budget))
    payload = as_jsonable(document)
    documents = []
    for index, operator in enumerate(document.operators, 1):
        single = deepcopy(document)
        single.title, single.operators, single.modules = operator.name, [deepcopy(operator)], []
        restrict_changes(single)
        identity = sha256(operator.char_id.encode('utf-8')).hexdigest()[:8]
        prefix = f'{index:03d}_{safe_filename(operator.char_id, 20)}_{identity}'
        name = safe_filename(prefix + '_' + operator.name + '_' + str(operator.metadata.get('version', 'unknown')), name_budget)
        documents.append((single, name, operator.summary.get('profession', ''), operator.metadata.get('version', 'unknown'), operator.char_id))
    if document.modules or not document.operators:
        single = deepcopy(document)
        single.title = '模组资料合集' if document.modules and document.operators else document.title
        single.operators = []
        restrict_changes(single)
        documents.append((single, 'modules' if document.modules else 'report', '', '', ''))
    try:
        if ExportFormat.JSON in requested:
            cancel.check()
            path = directory / f'{stem}.json'
            _write(path, json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
            record(ReportArtifact(str(path), 'json', document.title))
        if ExportFormat.TXT in requested:
            cancel.check()
            path = directory / f'{stem}.txt'
            _write(path, text_report(document))
            record(ReportArtifact(str(path), 'txt', document.title))
        if ExportFormat.HTML in requested:
            entries = []
            for single, name, profession, version, identifier in documents:
                cancel.check()
                path = directory / f'{name}.html'
                _write(path, render_html(single))
                record(ReportArtifact(str(path), 'html', single.title))
                entry_status = '当前快照'
                changes = document.metadata.get('changes') or {}
                for change in changes.get('operators', []):
                    if change.get('id', change.get('char_id')) == identifier:
                        entry_status = plain(change.get('kind', change.get('status', '变化')))
                entries.append({'path':path.name, 'title':single.title, 'profession':plain(profession), 'version':plain(version), 'status':entry_status})
            if len(documents) > 1:
                cancel.check()
                path = directory / 'index.html'
                _write(path, render_index(entries, document.title))
                record(ReportArtifact(str(path), 'html', document.title + ' · 目录'))
        if ExportFormat.PNG in requested:
            from .render import render_png
            for single, name, _, _, _ in documents:
                cancel.check()
                render_png(single, directory, name, cancel=cancel, emit=emit,
                    on_page=lambda path,pages:record(ReportArtifact(str(path),'png',single.title,pages)))
        cancel.check()
    except Exception as error:
        status = 'cancelled' if isinstance(error,CancelledError) else 'failed'
        failures.append({'type': type(error).__name__, 'message':str(error)})
        raise
    finally:
        manifest = {'task_id':task.name, 'template_version':document.metadata.get('template_version'),
            'status':status,'complete':status == 'succeeded',
            'requested_formats':sorted(item.value for item in requested), 'artifacts':[
                {**as_jsonable(artifact), 'path':str(Path(artifact.path).relative_to(task)),
                 'sha256':sha256(Path(artifact.path).read_bytes()).hexdigest()} for artifact in artifacts],
            'errors':failures}
        _write(task / 'manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return artifacts
