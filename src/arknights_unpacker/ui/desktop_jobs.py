"""Desktop queue actions for the Vue workbench."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer

from arknights_unpacker.contracts import BuildSpec, ExportFormat, ExtractionResult, ReportOptions

from .job_history import remaining_extraction
from .models import value


class DesktopJobActions:
    """Use the platform queue, service and preview leases for extraction and recovery."""

    @staticmethod
    def _object_preview_kinds(dialog, object_ids):
        identifiers = {str(identifier) for ids in (object_ids or {}).values() for identifier in ids}
        rows = [row for row in dialog.model.rows if str(value(row, 'id')) in identifiers]
        if len(rows) == 1:
            row = rows[0]
            kind = {'Texture2D': 'image', 'Sprite': 'image', 'Image': 'image',
                    'AudioClip': 'audio', 'VideoClip': 'video', 'TextAsset': 'text'}.get(value(row, 'type'))
            if kind:
                if kind == 'text' and any(part in str(value(row, 'name', '')).lower()
                                          for part in ('.atlas', '.skel', '.spine')):
                    return ['text', 'spine']
                return [kind]
        return ['image', 'text', 'audio', 'spine', 'video']

    def extract(self, paths, object_ids=None, preview_dialog=None, *, kinds=None, mode=None, character_options=None):
        if preview_dialog and (self._closing or getattr(preview_dialog, '_workbench_closed', False)):
            return
        generation = getattr(preview_dialog, 'preview_generation', None)
        character_options = dict(character_options) if character_options is not None else None
        if preview_dialog and preview_dialog in self._object_preview_jobs:
            self._object_preview_pending[preview_dialog] = (generation, lambda: self.extract(
                list(paths), object_ids, preview_dialog, kinds=kinds, mode=mode, character_options=character_options))
            return
        output = self.output_root() if preview_dialog is None else None
        lease = None
        if preview_dialog:
            try:
                lease = self.preview_cache.allocate('objects')
            except (OSError, ValueError) as error:
                self.show_status('无法创建对象预览：' + str(error))
                preview_dialog.preview_failed(str(error), generation=generation)
                return
            preview_dialog.track_preview(lease)
            output = str(lease.path)
        if output is None:
            return
        if preview_dialog:
            kinds = list(kinds) if kinds is not None else self._object_preview_kinds(preview_dialog, object_ids)
            mode = 'auto'
        else:
            kinds = list(kinds) if kinds is not None else self.extraction_defaults()[0]
            mode = mode if mode is not None else self.extraction_defaults()[1]
        if not kinds:
            if lease:
                lease.release()
                lease.finish()
            self.show_status('请在设置中至少选择一种资源类型。')
            return
        character_arguments = {'character_options': character_options} if character_options is not None else {}
        self.show_status(f'加入解包队列：{len(paths)} 个文件 · {mode} · {output}')
        def done(result):
            errors = value(result, 'errors', [])
            if errors and self.queue.active and not preview_dialog:
                failed_paths = list(dict.fromkeys(str(e.get('source')) for e in errors if e.get('source')))
                failed_ids = {}
                for path in failed_paths:
                    failures = [e for e in errors if str(e.get('source')) == path]
                    if all(e.get('object_id') is not None for e in failures):
                        failed_ids[path] = [str(e['object_id']) for e in failures]
                if failed_paths:
                    self.queue.active.retry_call = lambda **kw: self.services.extract(failed_paths, output, kinds=kinds,
                                                                                     object_ids=failed_ids, mode=mode, **character_arguments, **kw)
            if preview_dialog:
                if self._closing or getattr(preview_dialog, '_workbench_closed', False):
                    lease.release()
                    return
                outputs = value(result, 'outputs', [])
                if preview_dialog.show_files(outputs, preview_lease=lease, generation=generation):
                    if self.queue.active:
                        self._displayed_preview_jobs.add(self.queue.active.job_id)
                else:
                    lease.release()
                    details = [str(value(item, 'error', value(item, 'reason', ''))) for item in
                               [*value(result, 'errors', []), *value(result, 'skipped', [])]]
                    preview_dialog.preview_failed('未生成可预览文件。' + ('\n'.join(details) or '请在任务页查看失败或跳过原因。'),
                                                  generation=generation)
        title = ('预览表情合成' if preview_dialog else '导出表情差分') if kinds == ['expression'] else (
            '预览对象' if preview_dialog else '导出包内原图' if kinds == ['image'] and mode == 'auto' else '解包所选')
        job = self.queue.submit(title + f' · {len(paths)} 个文件',
                          lambda **kw: self.services.extract(paths, output, kinds=kinds, object_ids=object_ids, mode=mode,
                                                            remember_output=not bool(preview_dialog), **character_arguments, **kw), done, output,
                          request={'operation': 'extract', 'root': str(value(self.services.installation, 'root') or self.game_root()), 'paths': list(paths),
                                   'output': output, 'kinds': kinds, 'object_ids': object_ids or {}, 'mode': mode, 'preview': bool(preview_dialog),
                                   'character_options': character_options})
        if lease:
            self._object_preview_jobs[preview_dialog] = (job.job_id, generation)
            self._bind_preview_job(job, lease, preview_dialog)

    def prepare_recovery(self, job):
        """Resolve declarative history only after the user explicitly presses retry."""
        request = job.request or {}
        if request.get('preview'):
            raise ValueError('预览是临时任务，请从原页面重新预览；正式导出文件不受影响。')
        operation = request.get('operation')
        if operation == 'scan':
            return (lambda **kw: self.services.scan(request['root'], hours=request.get('hours', 24),
                    strict=request.get('strict', False), **kw)), self.scanned
        if operation == 'load_data':
            if request.get('locale', 'unknown') != self.services.config.get('data_locale', 'unknown'):
                raise ValueError('历史解析任务的区服声明与当前设置不同。请确认设置后，从资料页重新解析。')
            return (lambda **kw: self.services.load_data(request['root'], **kw)), self.data_loaded
        if operation == 'extract':
            root = request.get('root', '')
            evidence = self.queue.history.evidence(job) if self.queue.history else [{'result': job.result}]
            scan_result = []
            def call(**kw):
                current = value(self.services.installation, 'root')
                if root and (not current or Path(current).resolve() != Path(root).resolve()):
                    kw['emit']({'message': '正在恢复任务原来的只读游戏目录…'})
                    scan_result.append(self.services.scan(root, **kw))
                paths, ids = remaining_extraction(request, evidence, self.services.objects, kw['emit'], kw['cancel'])
                if not paths:
                    return ExtractionResult(status='succeeded', skipped=[{'reason': '原请求已全部完成，保留已有产物。'}])
                kw['emit']({'message': f'恢复 {len(paths)} 个未完成来源；已完成对象不再导出。未知完整性的组按未完成组处理，已有产物保留。'})
                return self.services.extract(paths, request['output'], kinds=request.get('kinds'), object_ids=ids,
                                             mode=request.get('mode', 'auto'),
                                             **({'character_options': request['character_options']} if request.get('character_options') is not None else {}), **kw)
            def done(result):
                if scan_result:
                    self.scanned(scan_result[-1])
                self.show_status(f'恢复任务完成：{len(value(result, "outputs", []))} 个新产物；原有产物保留。')
            return call, done
        if operation == 'report':
            self.check_report_binding(request)
            spec = BuildSpec(**request.get('spec', {}))
            options = ReportOptions(**request.get('options', {}))
            formats = {ExportFormat(fmt) for fmt in request.get('formats', [])}
            def call(**kw):
                # Earlier queued tasks may have loaded another snapshot/installation.
                self.check_report_binding(request)
                return self.services.export(request.get('operators', []), request.get('modules', []), request['output'],
                                            formats, spec=spec, options=options, **kw)
            def done(artifacts):
                self.show_report_artifacts(artifacts)
            return call, done
        raise ValueError('此任务类型没有恢复入口，请从对应页面重新操作；历史产物仍保留。')

    def check_report_binding(self, request):
        if self.services.gamedata is None:
            raise ValueError('请先解析历史任务对应的核心数据，再手动重试报告。已生成的历史产物可直接预览。')
        if value(self.services.gamedata, 'snapshot_id') != request.get('snapshot_id'):
            raise ValueError('当前数据快照与历史报告任务不同。请从资料页重新选择导出，避免将当前资料冒充旧快照。')
        root = request.get('root')
        if root:
            current = value(self.services.installation, 'root')
            if not current or Path(current).resolve() != Path(root).resolve():
                raise ValueError('当前游戏安装与历史报告来源不同。请先解析原安装的核心数据，或从当前资料页重新导出。')

    def _bind_preview_job(self, job, lease, dialog=None):
        self._preview_jobs[job.job_id] = lease
        if dialog is not None:
            self._dialog_jobs[job.job_id] = dialog
        def cleaned():
            if job.status == '成功':
                self.queue.forget_finished([job.job_id])
            self._dialog_jobs.pop(job.job_id, None)
            self._discard_when_settled.discard(job.job_id)
        lease.on_cleaned(cleaned)

    def _job_settled(self, job):
        owner = self._dialog_jobs.get(job.job_id)
        report_current = self._report_preview_jobs.get(owner)
        report_pending = None
        if report_current and report_current[0] == job.job_id:
            self._report_preview_jobs.pop(owner, None)
            report_pending = self._report_preview_pending.pop(owner, None)
            if (not self._closing and not getattr(owner, '_workbench_closed', False)
                    and job.status != '成功'):
                owner.font_preview_failed(job.last_error or job.status, generation=report_current[1])
        current = self._object_preview_jobs.get(owner)
        pending = None
        if current and current[0] == job.job_id:
            self._object_preview_jobs.pop(owner, None)
            pending = self._object_preview_pending.pop(owner, None)
            if not self._closing and not getattr(owner, '_workbench_closed', False) and job.last_error:
                owner.preview_failed(job.last_error, generation=current[1])
        lease = self._preview_jobs.pop(job.job_id, None)
        if lease:
            if job.job_id not in self._displayed_preview_jobs or self._closing:
                lease.release()
            lease.finish()
        self._displayed_preview_jobs.discard(job.job_id)
        if job.job_id in self._discard_when_settled:
            if job.status == '成功':
                self.queue.forget_finished([job.job_id])
            self._dialog_jobs.pop(job.job_id, None)
            self._discard_when_settled.discard(job.job_id)
        self._report_preview_warnings()
        if report_pending is not None:
            generation, submit = report_pending
            def latest_report():
                if (not self._closing and not getattr(owner, '_workbench_closed', False)
                        and owner.preview_generation == generation):
                    submit()
            QTimer.singleShot(0, latest_report)
        if pending is not None:
            generation, submit = pending
            def latest():
                if (not self._closing and not getattr(owner, '_workbench_closed', False)
                        and getattr(owner, 'preview_generation', None) == generation):
                    submit()
            QTimer.singleShot(0, latest)

    def _report_preview_warnings(self):
        for warning in self.preview_cache.warnings[self._preview_warning_count:]:
            self.queue.message.emit(warning)
        self._preview_warning_count = len(self.preview_cache.warnings)
