"""Browse operator/module data and manage report jobs for Vue."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog

from arknights_unpacker.contracts import BuildSpec, ExportFormat, ReportOptions, ReportSelection, as_jsonable
from arknights_unpacker.reports import compose_report
from arknights_unpacker.reports.model import semantic_blocks

from ..models import value
from ..original_image import _copy_original_image


class WorkbenchEntities:
    def __init__(self, window, changed):
        self.window = window
        self.services = window.services
        self.changed = changed
        self.previews = {}
        window.queue.settled.connect(self._settled)

    def _rows(self, kind):
        if kind not in ('operators', 'modules'):
            raise ValueError('请选择干员或模组。')
        return self.services.operators() if kind == 'operators' else self.services.modules()

    @staticmethod
    def _spec(payload):
        choices = payload.get('spec') or {}
        limits = {'phase': (0, 2), 'level': (1, 90), 'potential': (1, 6),
                  'trust': (0, 200), 'module_level': (1, 3)}
        params = {}
        for key, (lower, upper) in limits.items():
            item = choices.get(key)
            if item is None:
                continue
            if type(item) is not int or not lower <= item <= upper:
                raise ValueError('培养条件超出允许范围。')
            params[key] = item
        module = choices.get('module_id')
        if module:
            params['module_id'] = str(module)
        return BuildSpec(**params)

    def _report_options(self, payload):
        config = self.services.config
        options = ReportOptions(
            width=int(config.get('report_width', 1200)), font_size=int(config.get('report_font_size', 28)),
            theme=config.get('report_theme', 'dark'), module_image_layout=config.get('report_module_image_layout', 'single'),
            font_path=config.get('report_font_path', ''), font_index=int(config.get('report_font_index', 0)),
        )
        overrides = payload.get('options') or {}
        if overrides.get('theme') in ('dark', 'light'):
            options = replace(options, theme=overrides['theme'])
        if 'font_path' in overrides:
            font_index = overrides.get('font_index', 0)
            if type(font_index) is not int or font_index < 0:
                raise ValueError('所选字体字形不可用。')
            options = replace(options, font_path=str(overrides['font_path']), font_index=font_index)
        return options

    def _list(self, payload):
        kind = payload['kind']
        if kind not in ('operators', 'modules'):
            return self._rows(kind)
        query = str(payload.get('query') or '').strip()
        rows = (self.services.operators(query) if kind == 'operators' else self.services.modules(query))
        status = payload.get('status')
        if status:
            rows = [row for row in rows if row['status'] == status]
        return {'rows': rows, 'baseline': bool(value(self.services.entity_changes, 'baseline_id')),
                'version': value(self.services.gamedata, 'version', '')}

    def _profile(self, payload):
        spec = self._spec(payload)
        identifier = payload['id']
        kind = payload['kind']
        if identifier not in {row['id'] for row in self._rows(kind)}:
            raise ValueError('资料已变化，请重新选择。')
        if kind == 'operators':
            profile = self.services.operator_profile(identifier, spec)
            selection = ReportSelection(operators=[profile])
            modules = [{'id': row['id'], 'name': row['name']} for row in self.services.modules()
                       if row['char_id'] == identifier]
        else:
            profile = self.services.module_profile(identifier, spec)
            selection = ReportSelection(modules=[profile])
            modules = []
        document = compose_report(selection)
        document.metadata['complete'] = value(self.services.gamedata, 'complete', False)
        return {'title': document.title, 'blocks': as_jsonable(semantic_blocks(document)), 'modules': modules}

    def _submit_report(self, payload):
        source = self.services.gamedata
        if source is None:
            raise ValueError('请先解析核心数据。')
        kind = payload['kind']
        rows = self._rows(kind)
        if payload.get('onlyNew'):
            if not value(self.services.entity_changes, 'baseline_id'):
                raise ValueError('需要历史基线才能确认新增。')
            ids = [row['id'] for row in rows if row['status'] == 'added']
        else:
            requested = payload.get('ids', [])
            if not isinstance(requested, list) or any(not isinstance(key, str) for key in requested):
                raise ValueError('请选择可用资料。')
            ids = list(dict.fromkeys(requested))
        if not ids or not set(ids).issubset({row['id'] for row in rows}):
            raise ValueError('请选择可用资料。')
        operator_ids, module_ids = (ids, []) if kind == 'operators' else ([], ids)
        spec = self._spec(payload)
        if len(ids) > 1:
            spec = replace(spec, module_id=None)
        options = self._report_options(payload)
        preview = payload.get('preview') is True
        formats = {ExportFormat(fmt) for fmt in self.services.config.get('formats', ['png', 'html'])}
        if preview:
            formats.update({ExportFormat.PNG, ExportFormat.HTML})
        if kind == 'modules' and payload.get('onlyNew'):
            options = replace(options, title='本次新增模组')
        lease = self.window.preview_cache.allocate('reports') if preview else None
        output = str(lease.path) if lease else self.window.output_root()
        if not output:
            return None
        token = uuid4().hex
        binding = {'root': self.window.root, 'snapshot_id': source.snapshot_id}
        record = {'lease': lease, 'job': None, 'files': [], 'error': '', 'external': False, 'closed': False}

        def call(**kwargs):
            self.window.check_report_binding(binding)
            return self.services.export(operator_ids, module_ids, output, formats, spec, options,
                                        remember_output=not preview, **kwargs)

        def done(artifacts):
            if not preview:
                self.window.show_report_artifacts(artifacts)
            elif not record['closed']:
                for item in artifacts:
                    path = Path(item.path).resolve()
                    if path.is_file() and path.is_relative_to(lease.path):
                        record['files'].append({
                            'format': item.format, 'name': path.name, 'path': str(path),
                            'url': QUrl.fromLocalFile(str(path)).toString(),
                        })
                self.changed()

        try:
            job = self.window.queue.submit(
                f'{"预览" if preview else "导出"}资料 · {len(ids)} 项', call, done, output,
                request={'operation': 'report', **binding, 'operators': operator_ids, 'modules': module_ids,
                         'output': output, 'formats': [fmt.value for fmt in formats], 'spec': as_jsonable(spec),
                         'options': as_jsonable(options), 'preview': preview})
        except Exception:
            if lease:
                lease.release()
                lease.finish()
            raise
        if lease:
            record['job'] = job
            self.previews[token] = record
            lease.on_cleaned(lambda: self.window.queue.forget_finished([job.job_id]) if job.status == '成功' else None)
            return {'token': token}
        return {'job': job.job_id}

    def _settled(self, job):
        for token, data in tuple(self.previews.items()):
            if job is not data['job']:
                continue
            data['job'] = None
            data['error'] = job.last_error or (job.status if job.status != '成功' else '')
            data['lease'].finish()
            if data['closed'] and not data['external']:
                self.previews.pop(token, None)
            self.changed()
            break

    def _preview_file(self, token, index, *, image=False):
        data = self.previews.get(token)
        if data is None or type(index) is not int or not 0 <= index < len(data['files']):
            raise ValueError('此资料预览已关闭。')
        item = data['files'][index]
        path = Path(item['path']).resolve(strict=True)
        if not path.is_file() or not path.is_relative_to(data['lease'].path) or image and item['format'] != 'png':
            raise ValueError('所选预览文件不可用。')
        return data, path

    def _save_image(self, token, index):
        _, path = self._preview_file(token, index, image=True)
        output = self.window.output_root() or str(Path.home() / 'Pictures')
        target, _ = QFileDialog.getSaveFileName(self.window, '保存资料原图', str(Path(output) / path.name),
                                               'PNG (*.png)', options=QFileDialog.Option.DontConfirmOverwrite)
        if target:
            _, path = self._preview_file(token, index, image=True)
            return str(_copy_original_image(path, target, (self.window.root,), self.window.preview_cache.roots))

    def close(self, token=None):
        for key, data in tuple(self.previews.items()):
            if token is not None and key != token:
                continue
            data['closed'] = True
            if token is None or not data['external']:
                data['lease'].release()
                if data['job'] is None:
                    self.previews.pop(key, None)

    def dispatch(self, action, payload):
        token = payload.get('token')
        if action == 'entitiesList':
            return self._list(payload)
        if action == 'entitiesProfile':
            return self._profile(payload)
        if action == 'entitiesReport':
            return self._submit_report(payload)
        if action == 'entitiesPreview':
            data = self.previews.get(token)
            if data is None or data['closed']:
                raise ValueError('此资料预览已关闭。')
            return {'loading': data['job'] is not None, 'files': data['files'], 'error': data['error']}
        if action == 'entitiesClosePreview':
            return self.close(token) if token else None
        if action == 'entitiesSaveImage':
            return self._save_image(token, payload.get('index'))
        if action == 'entitiesOpenArtifact':
            data, path = self._preview_file(token, payload.get('index'))
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                raise ValueError('无法打开预览文件。')
            data['external'] = True
            return None
        raise ValueError('未知资料操作。')
