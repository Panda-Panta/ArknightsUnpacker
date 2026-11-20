"""Bundle selection and temporary object previews for the Vue workspace."""
from __future__ import annotations

import codecs
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog

from ..models import value
from ..object_preview import ObjectsDialog
from ..original_image import _copy_original_image, input_roots


def _text_artifact(path):
    from ..resource_preview import HEX_PREVIEW_BYTES, TEXT_PREVIEW_BYTES

    with path.open('rb') as stream:
        data = stream.read(TEXT_PREVIEW_BYTES + 1)
    truncated = len(data) > TEXT_PREVIEW_BYTES
    data = data[:TEXT_PREVIEW_BYTES]
    encoding = 'utf-8-sig'
    for bom, candidate in ((codecs.BOM_UTF32_LE, 'utf-32'), (codecs.BOM_UTF32_BE, 'utf-32'),
                           (codecs.BOM_UTF16_LE, 'utf-16'), (codecs.BOM_UTF16_BE, 'utf-16')):
        if data.startswith(bom):
            encoding = candidate
            break
    try:
        text = codecs.getincrementaldecoder(encoding)().decode(data, final=not truncated)
    except UnicodeDecodeError:
        text = None
    if text is None or any(ord(character) < 32 and character not in '\n\r\t\f' for character in text):
        chunk = data[:HEX_PREVIEW_BYTES]
        lines = [f'{offset:08x}  {chunk[offset:offset + 16].hex(" ")}'
                 for offset in range(0, len(chunk), 16)]
        if truncated or len(data) > HEX_PREVIEW_BYTES:
            lines.append('… 预览已限长。')
        return 'binary', '\n'.join(lines)
    if truncated:
        text += '\n\n… 预览已限长。'
    elif path.suffix.casefold() == '.json':
        try:
            text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        except (ValueError, RecursionError):
            pass
    return 'text', text


def _owned_file(root, filename):
    try:
        path = Path(filename).resolve(strict=True)
        if path.is_relative_to(root) and path.is_file():
            return path
    except (OSError, RuntimeError, ValueError, TypeError):
        pass
    return None


class _BundlePreview:
    """View adapter for the same producer lifecycle used by ObjectsDialog."""

    def __init__(self, path, window, changed):
        self.path = str(path)
        self.token = uuid4().hex
        self.input_roots = input_roots(window, path)
        self.changed = changed
        self.loading = True
        self.error = ''
        self.list_job = None
        self.model = SimpleNamespace(rows=[])
        self.rows_by_id = {}
        self.selected = ''
        self.preview_generation = 0
        self.preview_loading = False
        self.preview_error = ''
        self.artifacts = []
        self.artifact_paths = []
        self.current_lease = None
        self.leases = set()
        self._workbench_closed = False

    def clear_preview(self):
        self.artifacts = []
        self.artifact_paths = []
        lease, self.current_lease = self.current_lease, None
        if lease is not None:
            lease.release()

    def track_preview(self, lease):
        self.leases.add(lease)
        lease.on_cleaned(lambda: self.leases.discard(lease))

    def show_files(self, outputs, preview_lease=None, generation=None):
        if self._workbench_closed or generation != self.preview_generation:
            return False
        from ..resource_preview import _kind, _priority

        self.clear_preview()
        if preview_lease is None:
            return False
        owned = {}
        for item in outputs:
            path = _owned_file(preview_lease.path, value(item, 'path', item))
            if path is not None and path not in owned:
                owned[path] = {'path': path, 'kind': str(value(item, 'kind', ''))}
        for item in sorted(owned.values(), key=_priority):
            path = item['path']
            kind = _kind(path, item['kind'])
            artifact = {'name': path.name, 'kind': kind, 'url': ''}
            if kind == 'text':
                try:
                    artifact['kind'], artifact['text'] = _text_artifact(path)
                except OSError:
                    continue
            else:
                artifact['url'] = QUrl.fromLocalFile(str(path)).toString()
            self.artifacts.append(artifact)
            self.artifact_paths.append(path)
        if not self.artifacts:
            return False
        self.current_lease = preview_lease
        self.preview_loading = False
        self.preview_error = ''
        self.changed()
        return True

    def preview_failed(self, message, generation=None):
        if self._workbench_closed or generation != self.preview_generation:
            return False
        self.clear_preview()
        self.preview_loading = False
        self.preview_error = str(message)
        self.changed()
        return True


class WorkbenchObjects:
    """Expose one open bundle while keeping paths and object selection in Python."""

    def __init__(self, window, changed):
        self._window = window
        self._changed = changed
        self._bundle = None
        self._window.queue.settled.connect(self._list_settled)

    def open(self, path):
        source = Path(path).resolve(strict=True)
        if not source.is_file():
            raise ValueError('资源文件不存在，请重新扫描。')
        self.close()
        bundle = self._bundle = _BundlePreview(source, self._window, self._changed)

        def loaded(objects):
            if self._bundle is bundle:
                bundle.model.rows = [
                    {'id': str(value(row, 'id')), 'name': value(row, 'name', ''), 'type': value(row, 'type', ''),
                     'size': value(row, 'size'), 'previewable': ObjectsDialog._previewable(row)}
                    for row in objects]
                bundle.rows_by_id = {row['id']: row for row in bundle.model.rows}

        bundle.list_job = self._window.queue.submit('读取内部对象 · ' + source.name,
            lambda **kwargs: self._window.services.objects(bundle.path, **kwargs), loaded, show_in_tasks=False)
        return {'token': bundle.token}

    def _list_settled(self, job):
        bundle = self._bundle
        if bundle is not None and bundle.list_job is job:
            bundle.loading = False
            bundle.error = '' if job.status == '成功' else (job.last_error or job.status)
            bundle.list_job = None
            self._changed()

    def _current(self, token):
        if self._bundle is None or self._bundle.token != token:
            raise ValueError('包内对象视图已关闭，请重新打开资源包。')
        return self._bundle

    def state(self, token):
        bundle = self._current(token)
        return {'loading': bundle.loading, 'error': bundle.error, 'rows': bundle.model.rows}

    def select(self, token, identifier):
        bundle = self._current(token)
        row = bundle.rows_by_id.get(identifier) if isinstance(identifier, str) else None
        if row is None:
            raise ValueError('找不到所选对象，请重新打开资源包。')
        if bundle.selected == identifier and (bundle.preview_loading or bundle.artifacts):
            return
        bundle.selected = identifier
        bundle.preview_generation += 1
        bundle.clear_preview()
        bundle.preview_loading = row['previewable']
        bundle.preview_error = '' if bundle.preview_loading else '此对象暂不支持预览，可选择解包查看诊断。'
        if bundle.preview_loading:
            self._window.extract([bundle.path], {bundle.path: [identifier]}, bundle)
        self._changed()

    def preview(self, token):
        bundle = self._current(token)
        return {'id': bundle.selected, 'loading': bundle.preview_loading,
                'error': bundle.preview_error, 'artifacts': bundle.artifacts}

    def extract(self, token, identifiers):
        bundle = self._current(token)
        if not isinstance(identifiers, list) or not identifiers or not all(isinstance(key, str) for key in identifiers):
            raise ValueError('请选择要解包的对象。')
        if any(key not in bundle.rows_by_id for key in identifiers):
            raise ValueError('所选对象已变化，请重新选择。')
        self._window.extract([bundle.path], {bundle.path: list(dict.fromkeys(identifiers))})

    def save(self, token, index):
        bundle = self._current(token)
        if type(index) is not int or not 0 <= index < len(bundle.artifacts) or bundle.artifacts[index]['kind'] != 'image':
            raise ValueError('请选择可保存的预览图片。')
        source = bundle.artifact_paths[index]
        lease = bundle.current_lease
        destination = self._window.services.config.get('output_root') or Path.home() / 'Pictures'
        filename, _ = QFileDialog.getSaveFileName(self._window, '保存原图（保留原始像素）',
            str(Path(destination) / source.name), f'原始图片 (*{source.suffix.lower()})',
            options=QFileDialog.Option.DontConfirmOverwrite)
        if not filename:
            return None
        if self._current(token).current_lease is not lease or _owned_file(lease.path, source) != source:
            raise ValueError('原始图片已变化，请重新预览后保存。')
        target = _copy_original_image(source, filename, bundle.input_roots, lease.cache.roots)
        return str(target)

    def open_media(self, token, index):
        bundle = self._current(token)
        if type(index) is not int or not 0 <= index < len(bundle.artifacts):
            raise ValueError('请先选中要打开的预览产物。')
        if bundle.artifacts[index]['kind'] not in ('image', 'audio', 'video'):
            raise ValueError('当前产物适合在工作台内查看。')
        path = _owned_file(bundle.current_lease.path, bundle.artifact_paths[index])
        if path is None or not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            raise ValueError('无法使用系统播放器打开此文件。')

    def _cancel(self, job):
        queue = self._window.queue
        if job is None:
            return
        if queue.active is job and job.status == '运行中':
            queue.cancel()
        elif job.status == '排队中':
            job.token.cancel()
            job.status = '已取消'
            queue._persist(job)
            queue.settled.emit(job)
            queue.changed.emit()

    def close(self, token=None):
        bundle = self._bundle
        if bundle is None or (token is not None and token != bundle.token):
            return
        self._bundle = None
        bundle._workbench_closed = True
        self._window._object_preview_pending.pop(bundle, None)
        bundle.clear_preview()
        for lease in tuple(bundle.leases):
            lease.release()
        self._cancel(bundle.list_job)
        preview = self._window._object_preview_jobs.get(bundle)
        if preview is not None:
            job = next((job for job in self._window.queue.jobs if job.job_id == preview[0]), None)
            self._cancel(job)
        self._changed()
