"""Run AVG compositions for the Vue workbench using the desktop queue."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QImageReader

from ..models import value
from .objects import _BundlePreview, _owned_file


class _CharacterPreview(_BundlePreview):
    def __init__(self, path, window, changed):
        super().__init__(path, window, changed)
        self.catalog = {}
        self.requested_options = None
        self.composition = None

    def clear_preview(self):
        self.composition = None
        super().clear_preview()

    def show_files(self, outputs, preview_lease=None, generation=None):
        if self._workbench_closed or generation != self.preview_generation or preview_lease is None:
            return False
        for item in outputs:
            path = _owned_file(preview_lease.path, value(item, 'path', item))
            if path is None or path.suffix.lower() != '.png':
                continue
            size = QImageReader(str(path)).size()
            if not size.isValid():
                continue
            self.current_lease = preview_lease
            self.composition = {'url': QUrl.fromLocalFile(str(path)).toString(), 'width': size.width(),
                                'height': size.height(), 'options': dict(self.requested_options)}
            self.preview_loading = False
            self.preview_error = ''
            self.changed()
            return True
        return False


def _composition_options(catalog, options):
    if not isinstance(options, dict):
        raise ValueError('表情合成选项无效。')
    group_id = options.get('group_id')
    group = next((item for item in catalog.get('groups', []) if item['id'] == group_id), None)
    if group is None:
        raise ValueError('所选姿态组不可用。')
    roles = {entry['id']: entry['role'] for entry in group.get('entries', [])}
    base_id, face_id = options.get('base_id'), options.get('face_id', '')
    if not isinstance(base_id, str) or roles.get(base_id) not in ('base', 'whole'):
        raise ValueError('请选择当前姿态组中的完整底图。')
    if not isinstance(face_id, str) or (face_id and roles.get(face_id) not in ('face', 'whole')):
        raise ValueError('所选表情不属于当前姿态组。')
    result = {'group_id': group_id, 'base_id': base_id, 'face_id': face_id}
    for key, label, minimum, maximum in (('x', '横向位置', -32768, 32768), ('y', '纵向位置', -32768, 32768),
                                          ('width', '表情宽度', 1, 16384), ('height', '表情高度', 1, 16384)):
        number = options.get(key)
        if type(number) is not int or not minimum <= number <= maximum:
            raise ValueError(f'{label}必须是 {minimum} 至 {maximum} 之间的整数。')
        result[key] = number
    return result


class WorkbenchCharacters:
    """Own one editable character composition while exports stay in the task queue."""

    def __init__(self, window, changed):
        self._window = window
        self._changed = changed
        self._context = None
        window.queue.settled.connect(self._list_settled)

    def open(self, paths):
        sources = list(dict.fromkeys(Path(path).resolve(strict=True) for path in paths))
        if not sources or any(not path.is_file() for path in sources):
            raise ValueError('角色资源不存在，请重新扫描。')
        self.close()
        if len(sources) > 1:
            self._window.extract([str(path) for path in sources], kinds=['expression'], mode='auto')
            return {'token': None}
        source = sources[0]
        context = self._context = _CharacterPreview(source, self._window, self._changed)

        def loaded(catalog):
            if self._context is context:
                context.catalog = catalog

        context.list_job = self._window.queue.submit('读取角色表情配置 · ' + source.name,
            lambda **kwargs: self._window.services.character_catalog(context.path, **kwargs), loaded, show_in_tasks=False)
        return {'token': context.token}

    def _list_settled(self, job):
        context = self._context
        if context is not None and context.list_job is job:
            context.loading = False
            context.error = '' if job.status == '成功' else (job.last_error or job.status)
            context.list_job = None
            self._changed()

    def _current(self, token):
        if self._context is None or self._context.token != token:
            raise ValueError('表情差分工作台已关闭，请重新打开。')
        return self._context

    def state(self, token):
        context = self._current(token)
        return {'name': Path(context.path).name, 'loading': context.loading, 'error': context.error,
                'groups': context.catalog.get('groups', []), 'diagnostics': context.catalog.get('diagnostics', []),
                'previewLoading': context.preview_loading, 'previewError': context.preview_error,
                'preview': context.composition}

    def preview(self, token, options):
        context = self._current(token)
        wanted = _composition_options(context.catalog, options)
        if wanted == context.requested_options and (context.preview_loading or context.composition is not None):
            return
        context.preview_generation += 1
        context.clear_preview()
        context.requested_options = wanted
        context.preview_loading = True
        context.preview_error = ''
        self._window.extract([context.path], preview_dialog=context,
                             kinds=['expression'], mode='auto', character_options=wanted)
        self._changed()

    def export(self, token, options):
        context = self._current(token)
        wanted = _composition_options(context.catalog, options)
        if context.composition is None or context.composition['options'] != wanted:
            raise ValueError('请等待当前合成预览完成后再导出。')
        self._window.extract([context.path], kinds=['expression'], mode='auto', character_options=wanted)

    def batch(self, token):
        context = self._current(token)
        if not context.catalog.get('groups'):
            raise ValueError('此资源没有可批量导出的角色表情配置。')
        self._window.extract([context.path], kinds=['expression'], mode='auto')

    def close(self, token=None):
        context = self._context
        if context is None or (token is not None and token != context.token):
            return
        self._context = None
        context._workbench_closed = True
        self._window._object_preview_pending.pop(context, None)
        context.clear_preview()
        for lease in tuple(context.leases):
            lease.release()
        pending = self._window._object_preview_jobs.get(context)
        queue = self._window.queue
        for job in list(queue.jobs):
            if job is not context.list_job and (pending is None or pending[0] != job.job_id):
                continue
            if queue.active is job and job.status == '运行中':
                queue.cancel()
            elif job.status == '排队中':
                job.token.cancel()
                job.status = '已取消'
                queue._persist(job)
                queue.settled.emit(job)
                queue.changed.emit()
        self._changed()
