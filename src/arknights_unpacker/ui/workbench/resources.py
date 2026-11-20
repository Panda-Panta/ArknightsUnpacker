"""Directory, filter and selection state for the Vue resource workbench."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import uuid4

from arknights_unpacker.library.classifications import category_labels
from arknights_unpacker.library.discover import safe_path
from arknights_unpacker.library.preview_types import DIRECT_SOURCE_TYPES


_RESOURCE_SUFFIXES = {'.ab', '.bin', '.usm', '.idx', '.bytes', '.acb', '.awb'}
_SOURCES = {'base': '初始包', 'hot': '热更新', 'other': '其他游戏文件'}
_STATUS = {
    'added': '新增', 'modified': '已修改', 'removed': '已删除',
    'metadata_only': '仅元数据变化', 'unchanged': '元数据未变',
    'first_seen': '首次发现，历史未知', 'current': '当前候选（未核实内容）',
    'unverified': '未验证', 'available': '可用', 'verified': '已验证',
    'missing': '未安装', 'not_installed_optional': '未安装的可选资源',
    'stale': '仅有旧版', 'incomplete': '资源不完整',
    'error': '读取失败', 'unstable': '读取期间变化',
}
_UNAVAILABLE = {'removed', 'missing', 'not_installed_optional', 'stale', 'incomplete', 'error', 'unstable'}
_SORTS = {'name', 'category', 'extension', 'size', 'modified', 'created', 'observed', 'source'}


def _value(record, key, default=None):
    return record.get(key, default) if isinstance(record, dict) else getattr(record, key, default)


def _relative(path):
    """Validate relative syntax without filesystem access."""
    normalized = str(path or '').replace('\\', '/')
    if not normalized or any(part in ('', '.', '..') or ':' in part or '\x00' in part
                             for part in normalized.split('/')):
        return ''
    return normalized


def _within_root(root, path):
    if not path:
        return ''
    try:
        return _relative(Path(path).relative_to(root).as_posix())
    except ValueError:
        return ''


def _same_root(root, path):
    return bool(path) and Path(path).absolute() == root


def _timestamp(ns):
    return ns / 1_000_000_000 if ns else None


@dataclass(frozen=True, slots=True)
class _File:
    row: dict
    physical: str
    search: str
    modified_ns: int | None
    created_ns: int | None

    def sort_value(self, sort):
        if sort == 'modified':
            return self.modified_ns or None
        if sort == 'created':
            return self.created_ns or None
        if sort == 'source':
            source = self.row['source']
            return (source, self.row['status']) if source else None
        value = self.row[sort]
        return value.casefold() if isinstance(value, str) else value


@dataclass(slots=True)
class _Layer:
    files: list[_File]
    files_by_folder: dict[str, list[_File]]
    subdirectories: dict[str, list[dict]]

    def folder(self, relative):
        # When changing source layers, keep the closest directory that exists.
        while relative and relative not in self.subdirectories:
            relative = relative.rpartition('/')[0]
        return relative


def _directory_row(path, name):
    return {
        'id': 'directory:' + path, 'path': path, 'name': name, 'kind': 'directory',
        'category': '', 'extension': '', 'size': None,
        'modified': None, 'created': None, 'observed': None,
        'source': '', 'status': '', 'extractable': False, 'previewable': False,
    }


def _prepare_layer(files):
    files_by_folder = defaultdict(list)
    subdirectories = {'': []}
    known_folders = {''}
    for entry in files:
        folder = entry.row['path'].rpartition('/')[0]
        files_by_folder[folder].append(entry)
        while folder not in known_folders:
            known_folders.add(folder)
            subdirectories.setdefault(folder, [])
            parent, _, name = folder.rpartition('/')
            subdirectories.setdefault(parent, []).append(_directory_row(folder, name))
            folder = parent
    return _Layer(files, files_by_folder, subdirectories)


def _file_entry(file_id, path, physical, source, status, category, size, observation, logical=''):
    name = path.rsplit('/', 1)[-1]
    extension = PurePosixPath(name).suffix.casefold()
    supported = source in ('base', 'hot') or extension in _RESOURCE_SUFFIXES or extension in DIRECT_SOURCE_TYPES
    actionable = bool(physical and supported and status not in _UNAVAILABLE)
    modified_ns = _value(observation, 'mtime_ns')
    created_ns = _value(observation, 'created_ns')
    category = category or '未知用途'
    row = {
        'id': file_id, 'path': path, 'name': name, 'kind': 'file',
        'category': category, 'extension': extension, 'size': size,
        'modified': _timestamp(modified_ns), 'created': _timestamp(created_ns),
        'observed': _value(observation, 'first_seen_at'),
        'source': _SOURCES.get(source, ''), 'status': _STATUS.get(status, '历史未知'),
        'extractable': actionable, 'previewable': actionable,
    }
    return _File(row, physical, f'{path} {logical} {category}'.casefold(), modified_ns, created_ns)


def _bounded_int(value, default, minimum, maximum=None):
    if not isinstance(value, int) or isinstance(value, bool):
        return default
    return max(minimum, value) if maximum is None else max(minimum, min(maximum, value))


class WorkbenchResources:
    """Index only the current installation's saved and resolved observations."""

    def __init__(self):
        self._root = None
        self._inputs = None
        self._layers = {'raw': _prepare_layer([]), 'effective': _prepare_layer([])}
        self._files = {}
        self._raw_by_path = {}
        self._categories = list(category_labels())
        self._query_key = None
        self._matches = None

    def refresh(self, root, snapshot, changes, catalog):
        root = Path(root).absolute() if root else None
        if (self._inputs is not None and root == self._root
                and all(previous is current for previous, current in zip(self._inputs, (snapshot, changes, catalog)))):
            return
        generation = uuid4().hex
        raw, effective = [], []
        observed = {}
        categories = set(category_labels())
        if root and _same_root(root, _value(snapshot, 'root')):
            differ = {_relative(_value(change, 'path')).casefold(): _value(change, 'kind')
                      for change in _value(changes, 'changes', [])}
            fallback_status = 'unchanged' if _value(changes, 'baseline_id') else 'first_seen'
            for record in _value(snapshot, 'files', []):
                path = _relative(_value(record, 'path'))
                if not path:
                    continue
                key = path.casefold()
                observed[key] = record
                status = differ.get(key, fallback_status)
                if _value(record, 'error'):
                    status = 'error'
                raw.append(_file_entry(f'{generation}:raw:{len(raw)}', path, path, _value(record, 'layer'), status,
                                       _value(record, 'category'), _value(record, 'size'), record))
        if root and _same_root(root, _value(_value(catalog, 'installation'), 'root')):
            for key, record in _value(catalog, 'resources', {}).items():
                logical = _relative(_value(record, 'logical_key') or key)
                physical = _within_root(root, _value(record, 'path'))
                path = physical or logical
                if not path:
                    continue
                observation = observed.get(physical.casefold())
                effective.append(_file_entry(
                    f'{generation}:effective:{len(effective)}', path, physical, _value(record, 'layer'),
                    _value(record, 'status'), _value(record, 'category'), _value(record, 'size') if physical else None,
                    observation, logical))
        self._root = root
        self._inputs = (snapshot, changes, catalog)
        self._layers = {'raw': _prepare_layer(raw), 'effective': _prepare_layer(effective)}
        self._files = {item.row['id']: item for layer in (raw, effective) for item in layer}
        self._raw_by_path = {item.physical: item.row for item in raw}
        categories.update(item.row['category'] for item in self._files.values())
        self._categories = sorted(categories)
        self._query_key = None
        self._matches = None

    def raw_row(self, path):
        return self._raw_by_path.get(_relative(path))

    def resource_row(self, file_id):
        entry = self._files.get(file_id)
        return entry.row if entry else None

    def query(self, payload):
        source = 'effective' if payload.get('layer') == 'effective' else 'raw'
        layer = self._layers[source]
        folder = layer.folder(_relative(payload.get('folder')))
        query = str(payload.get('query') or '').strip().casefold()
        category = str(payload.get('category') or '')
        recursive = payload.get('recursive') is True
        ab_only = payload.get('abOnly') is True
        sort = str(payload.get('sort') or 'name')
        if sort not in _SORTS:
            sort = 'name'
        descending = payload.get('descending') is True
        key = (source, folder, query, category, recursive, ab_only, sort, descending)
        if key != self._query_key:
            self._matches = self._query(layer, folder, query, category, recursive, ab_only, sort, descending)
            self._query_key = key
        rows, directory_count = self._matches
        page = _bounded_int(payload.get('page'), 1, 1)
        page_size = _bounded_int(payload.get('pageSize'), 100, 1, 500)
        start = (page - 1) * page_size
        return {
            'folder': folder, 'rows': rows[start:start + page_size], 'categories': self._categories,
            'total': len(rows), 'directoryCount': directory_count, 'fileCount': len(rows) - directory_count,
        }

    @staticmethod
    def _query(layer, folder, query, category, recursive, ab_only, sort, descending):
        if category:
            directories = []
            candidates = layer.files
        else:
            directories = [row for row in layer.subdirectories.get(folder, [])
                           if query in row['path'].casefold()]
            directories.sort(key=lambda row: row['name'].casefold(), reverse=sort == 'name' and descending)
            if recursive and folder:
                prefix = folder + '/'
                candidates = (item for item in layer.files if item.row['path'].startswith(prefix))
            elif recursive:
                candidates = layer.files
            else:
                candidates = layer.files_by_folder.get(folder, [])
        known, unknown = [], []
        for entry in candidates:
            row = entry.row
            if (category and row['category'] != category or ab_only and row['extension'] != '.ab'
                    or query not in entry.search):
                continue
            value = entry.sort_value(sort)
            if value is None:
                unknown.append(row)
            else:
                known.append((value, row))
        known.sort(key=lambda pair: pair[0], reverse=descending)
        return directories + [row for _, row in known] + unknown, len(directories)

    def matching_ids(self, payload):
        self.query(payload)
        rows, _ = self._matches
        return [row['id'] for row in rows if row['extractable']]

    def paths(self, ids, *, extraction=False):
        if not isinstance(ids, (list, tuple)) or not ids:
            raise ValueError('请选择文件。')
        if any(not isinstance(file_id, str) for file_id in ids):
            raise ValueError('所选资源标识无效。')
        result = []
        for file_id in dict.fromkeys(ids):
            entry = self._files.get(file_id)
            capability = 'extractable' if extraction else 'previewable'
            if not entry or not entry.row[capability]:
                raise ValueError('所选资源不可用。请刷新列表后重新选择。')
            path = safe_path(self._root, entry.physical)
            if not path.is_file() or not path.resolve().is_relative_to(self._root):
                raise ValueError('所选文件已不可用。请重新扫描后选择。')
            result.append(str(path))
        return list(dict.fromkeys(result))

    def directory_paths(self, folder, layer):
        relative = _relative(folder)
        entries = self._layers['effective' if layer == 'effective' else 'raw']
        if (folder and not relative) or (relative and relative not in entries.subdirectories):
            raise ValueError('所选目录已不可用。请刷新列表后重新选择。')
        prefix = relative + '/' if relative else ''
        ids = [entry.row['id'] for entry in entries.files
               if entry.row['extractable'] and entry.row['path'].startswith(prefix)]
        return self.paths(ids, extraction=True)
