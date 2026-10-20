"""Ordered format adapters. Renderers are imported only by a selected adapter."""
from collections.abc import Callable
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from ..contracts import (CancelToken, ExportFormat, ProgressSink, ReportArtifact,
    ReportDocument, as_jsonable)


@dataclass
class ExportContext:
    document: ReportDocument
    directory: Path
    stem: str
    documents: list[tuple[ReportDocument, str, Any, Any, str]]
    cancel: CancelToken
    emit: ProgressSink
    record: Callable[[ReportArtifact], None]
    write: Callable[[Path, str], None]


def _export_json(context: ExportContext) -> None:
    path = context.directory / f'{context.stem}.json'
    context.write(path, json.dumps(as_jsonable(context.document), ensure_ascii=False, indent=2) + '\n')
    context.record(ReportArtifact(str(path), 'json', context.document.title))


def _export_text(context: ExportContext) -> None:
    from .model import text_report

    path = context.directory / f'{context.stem}.txt'
    context.write(path, text_report(context.document))
    context.record(ReportArtifact(str(path), 'txt', context.document.title))


def _export_html(context: ExportContext) -> None:
    from .html_render import render_html, render_index
    from .model import plain

    entries = []
    for single, name, profession, version, identifier in context.documents:
        context.cancel.check()
        path = context.directory / f'{name}.html'
        context.write(path, render_html(single))
        context.record(ReportArtifact(str(path), 'html', single.title))
        entry_status = '当前快照'
        changes = context.document.metadata.get('changes') or {}
        for change in changes.get('operators', []):
            if change.get('id', change.get('char_id')) == identifier:
                entry_status = plain(change.get('kind', change.get('status', '变化')))
        entries.append({'path': path.name, 'title': single.title, 'profession': plain(profession),
                        'version': plain(version), 'status': entry_status})
    if len(context.documents) > 1:
        context.cancel.check()
        path = context.directory / 'index.html'
        context.write(path, render_index(entries, context.document.title, theme=context.document.options.theme))
        context.record(ReportArtifact(str(path), 'html', context.document.title + ' · 目录'))


def _export_png(context: ExportContext) -> None:
    from .render import render_png

    for single, name, _, _, _ in context.documents:
        context.cancel.check()
        render_png(single, context.directory, name, cancel=context.cancel, emit=context.emit,
            on_page=lambda path, pages: context.record(ReportArtifact(str(path), 'png', single.title, pages)))


# This order is part of the batch behavior: completed sidecars remain available
# when a later renderer fails or the caller cancels the remaining formats.
_EXPORTERS: dict[ExportFormat, Callable[[ExportContext], None]] = {
    ExportFormat.JSON: _export_json,
    ExportFormat.TXT: _export_text,
    ExportFormat.HTML: _export_html,
    ExportFormat.PNG: _export_png,
}


def dispatch_exports(context: ExportContext, requested: set[ExportFormat]) -> None:
    missing = requested - _EXPORTERS.keys()
    if missing:
        raise ValueError('不支持的报告导出格式：' + ', '.join(sorted(item.value for item in missing)))
    for format, exporter in _EXPORTERS.items():
        if format in requested:
            context.cancel.check()
            exporter(context)
