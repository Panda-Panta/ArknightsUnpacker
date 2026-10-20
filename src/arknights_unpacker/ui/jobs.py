from __future__ import annotations

from dataclasses import dataclass, field
import re
import traceback
import time
import uuid
from PySide6.QtCore import QObject, QThread, Signal, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem, QPlainTextEdit, QProgressBar, QLabel
from arknights_unpacker.contracts import CancelToken, CancelledError, GameDataSnapshot, as_jsonable
from .job_history import INTERRUPTED, JobHistory, valid_request, report_artifact_event, retained_file


SUCCESS_HISTORY_LIMIT = 20


@dataclass
class Job:
    title: str
    call: object
    done: object = None
    status: str = '排队中'
    output: str = ''
    token: CancelToken = field(default_factory=CancelToken)
    retry_call: object = None
    artifacts: list = field(default_factory=list)
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    request: dict | None = None
    last_error: str = ''
    result: dict = field(default_factory=dict)
    ancestors: list = field(default_factory=list)
    receipt_root: str = ''


class Worker(QThread):
    progress = Signal(object)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, job, parent=None):
        super().__init__(parent)
        self.job = job

    def run(self):
        last = [0.0]
        latest = [None]
        def emit(event):
            # Scanners can report every file or MiB. Bound UI signal pressure.
            latest[0] = event
            now = time.monotonic()
            checkpoint = isinstance(event, dict) and (event.get('stage') == 'extraction_task' or
                         report_artifact_event(event) or
                         event.get('kind', event.get('type')) in ('object_complete', 'source_complete', 'extraction_task') or
                         all(key in event for key in ('source', 'object_id', 'path')))
            if checkpoint or now - last[0] >= .1:
                self.progress.emit(event)
                last[0] = now
        try:
            result = self.job.call(emit=emit, cancel=self.job.token)
            if latest[0] is not None:
                self.progress.emit(latest[0])
            self.job.token.check()
            self.succeeded.emit(result)
        except CancelledError:
            self.failed.emit('任务已取消；已完成的产物保留。')
        except Exception:
            self.failed.emit(traceback.format_exc())


class JobQueue(QObject):
    changed = Signal()
    message = Signal(str)
    progress = Signal(object)
    settled = Signal(object)

    def __init__(self, parent=None, *, history_root=None, resume_handler=None):
        super().__init__(parent)
        self.jobs = []
        self.worker = None
        self.active = None
        self.closing = False
        self.paused = False
        self.resume_handler = resume_handler
        self.history = JobHistory(history_root) if history_root else None
        if self.history:
            for record in self.history.load():
                job = Job(record.get('title', '历史任务'), None,
                          status=record.get('status', '历史状态未知'), output=record.get('output', ''),
                          artifacts=record.get('artifacts', []), job_id=record['job_id'],
                          created_at=record.get('created_at', 0), started_at=record.get('started_at', 0),
                          request=record.get('request'), last_error=record.get('last_error', ''),
                          result=record.get('result', {}), ancestors=record.get('ancestors', []), receipt_root=record.get('receipt_root', ''))
                self.jobs.append(job)
                self._persist(job)
        self._prune_successful()

    def forget_finished(self, job_ids):
        """Forget exact settled tasks while preserving any retained recovery chain."""
        requested = {job_id for job_id in job_ids if isinstance(job_id, str) and re.fullmatch(r'[a-f0-9]{32}', job_id)}
        candidates = {job.job_id for job in self.jobs if job.job_id in requested
                      and job is not self.active and job.status not in INTERRUPTED}
        ancestors = {job.job_id: {item for item in job.ancestors if isinstance(item, str)}
                     for job in self.jobs if isinstance(job.ancestors, (list, tuple))}
        removed = []
        # Remove leaves first; an occupied child record must keep its checkpoints.
        while candidates:
            referenced = {ancestor for job_id, values in ancestors.items() if job_id not in removed for ancestor in values}
            ready_ids = candidates - referenced
            ready = [job for job in self.jobs if job.job_id in ready_ids]
            if not ready:
                break
            for job in ready:
                candidates.remove(job.job_id)
                try:
                    if self.history:
                        self.history.remove(job.job_id)
                except (OSError, ValueError) as error:
                    warning = '任务记录无法清理：' + str(error)
                    self.history.warnings.append(warning)
                    self.message.emit(warning)
                    continue
                removed.append(job.job_id)
        if removed:
            self.jobs[:] = [job for job in self.jobs if job.job_id not in removed]
            self.changed.emit()
        return removed

    def _prune_successful(self):
        successful = sorted((job for job in self.jobs if job.status == '成功'), key=lambda job: job.created_at)
        removed = self.forget_finished(job.job_id for job in successful[:-SUCCESS_HISTORY_LIMIT])
        if removed:
            self.message.emit(f'已自动清理 {len(removed)} 条旧成功任务记录；正式导出文件保留。')

    def clear_successful(self):
        removed = self.forget_finished(job.job_id for job in self.jobs if job.status == '成功')
        self.message.emit(f'已清理 {len(removed)} 条成功任务记录；正式导出文件保留。')
        return len(removed)

    def _persist(self, job):
        if self.history:
            try:
                self.history.save(job)
            except (OSError, ValueError, TypeError) as error:
                self.message.emit('任务历史无法保存：' + str(error))

    @property
    def busy(self):
        return self.worker is not None

    def submit(self, title, call, done=None, output='', *, request=None, ancestors=None):
        job = Job(title, call, done, output=output, request=valid_request(request), ancestors=ancestors or [])
        self.jobs.append(job)
        self._persist(job)
        self.changed.emit()
        self._next()
        return job

    def _next(self):
        if self.worker is not None or self.closing or self.paused:
            return
        self.active = next((j for j in self.jobs if j.status == '排队中'), None)
        if self.active is None:
            return
        self.active.status = '运行中'
        self.active.started_at = time.time()
        self._persist(self.active)
        worker = Worker(self.active, self)
        self.worker = worker
        worker.progress.connect(self._progress)
        worker.succeeded.connect(self._success)
        worker.failed.connect(self._failure)
        worker.finished.connect(self._finished)
        self.message.emit(f'开始：{self.active.title}')
        self.changed.emit()
        worker.start()

    def _progress(self, event):
        if isinstance(event, dict) and (event.get('stage') == 'extraction_task' or event.get('kind', event.get('type')) == 'extraction_task') and self.active:
            self.active.receipt_root = str(event.get('output_root', ''))
            self._persist(self.active)
        if self.active and report_artifact_event(event):
            from pathlib import Path
            path = Path(event['path'])
            # Register the exact batch manifest; never inspect a shared output root.
            task_root = path.parent.parent if path.parent.name == 'reports' else path.parent
            manifests = self.active.result.setdefault('report_manifests', [])
            manifest = str(task_root / 'manifest.json')
            if manifest not in manifests:
                manifests.append(manifest)
            artifact = {'path': str(path), 'format': event.get('format', path.suffix.lstrip('.')),
                        'title': str(event.get('message', path.name)), 'status': 'succeeded'}
            if retained_file(artifact):
                artifact['size'] = path.stat().st_size
                event = {**event, 'size': artifact['size']}
                by_path = {str(item.get('path') if isinstance(item, dict) else item.path): item for item in self.active.artifacts}
                by_path[str(path)] = artifact
                self.active.artifacts = list(by_path.values())
            self._persist(self.active)
        if self.history and self.active:
            try:
                self.history.append_event(self.active, event)
            except (OSError, ValueError) as error:
                self.message.emit('任务检查点无法保存：' + str(error))
        self.progress.emit(event)
        self.message.emit(str(event.get('message', event)) if isinstance(event, dict) else str(event))

    def _success(self, result):
        self.active.status = '成功'
        if hasattr(result, 'outputs'):
            self.active.result = as_jsonable(result)
            self.active.receipt_root = str(getattr(result, 'output_root', '') or self.active.receipt_root)
            from pathlib import Path
            self.active.artifacts = [{'path': item['path'], 'format': Path(item['path']).suffix.lstrip('.').lower(),
                                      'title': Path(item['path']).name, 'status': 'succeeded'}
                                     for item in result.outputs if item.get('path')]
        errors = getattr(result, 'errors', [])
        if errors:
            self.active.status = f'部分失败（{len(errors)}）'
            self.message.emit(str(errors))
        if hasattr(result, 'outputs'):
            skipped = getattr(result, 'skipped', [])
            self.message.emit(f'产物 {len(result.outputs)} 项；失败 {len(errors)} 项；跳过 {len(skipped)} 项。')
            if skipped:
                self.message.emit('跳过详情：' + str(skipped))
            status = getattr(result, 'status', 'succeeded')
            if status in ('partial', 'failed', 'cancelled'):
                self.active.status = {'partial': '部分完成（查看诊断）', 'failed': '失败', 'cancelled': '已取消'}[status]
        if isinstance(result, dict) and 'snapshot' in result and not getattr(result['snapshot'], 'complete', True):
            self.active.status = '部分扫描（未推进基线）'
        if isinstance(result, GameDataSnapshot) and not result.complete:
            self.active.status = '部分解析（查看诊断）'
            self.active.last_error = '\n'.join(map(str, result.diagnostics)) or '核心数据未完整解析。'
            self.message.emit(self.active.last_error)
        if isinstance(result, list):
            if result and all(hasattr(item, 'format') or isinstance(item, dict) and 'format' in item for item in result):
                self.active.artifacts = result
            failed = [item for item in result if getattr(item, 'status', 'succeeded') != 'succeeded']
            if failed:
                self.active.status = f'部分失败（{len(failed)}）'
        try:
            if self.active.done:
                self.active.done(result)
        except Exception:
            self.active.status = '结果处理失败'
            self.message.emit(traceback.format_exc())
        self.message.emit(f'{self.active.title}：{self.active.status}')
        self._persist(self.active)
        self.changed.emit()

    def _failure(self, error):
        self.active.status = '已取消' if self.active.token.cancelled else '失败'
        self.active.last_error = error
        self._persist(self.active)
        self.message.emit(error)
        self.changed.emit()

    def _finished(self):
        old = self.worker
        job = self.active
        self.worker = None
        self.active = None
        old.deleteLater()
        self.settled.emit(job)
        self._prune_successful()
        self.changed.emit()
        self._next()

    def cancel(self):
        if self.active:
            self.active.token.cancel()
            self.active.status = '正在取消'
            self._persist(self.active)
            self.message.emit('已请求取消，正在等待工作进程释放资源。')
            self.changed.emit()

    def retry(self, index):
        if 0 <= index < len(self.jobs):
            old = self.jobs[index]
            if old.status in ('运行中', '正在取消', '排队中', '成功'):
                return
            if old.request and self.resume_handler:
                try:
                    call, done = self.resume_handler(old)
                except (ValueError, OSError, TypeError) as error:
                    self.message.emit(str(error))
                    return
            else:
                call, done = old.retry_call or old.call, old.done
            if call is None:
                self.message.emit('此历史任务没有可恢复请求。请从对应页面重新操作；已保存产物仍可打开。')
                return
            self.submit(old.title + '（重试）', call, done, old.output, request=old.request,
                        ancestors=[*old.ancestors, old.job_id])

    def toggle_pause(self):
        self.paused = not self.paused
        self.message.emit('队列已暂停；当前任务继续到结束。' if self.paused else '队列已继续。')
        self.changed.emit()
        if not self.paused:
            self._next()

    def shutdown(self):
        self.closing = True
        for job in list(self.jobs):
            if job.status == '排队中':
                job.status = '已取消'
                self._persist(job)
                self.settled.emit(job)
        self.cancel()


class JobsView(QWidget):
    artifacts_requested = Signal(object)
    def __init__(self, queue, parent=None):
        super().__init__(parent)
        self.queue = queue
        layout = QVBoxLayout(self)
        retention = QLabel(f'成功任务自动保留最近 {SUCCESS_HISTORY_LIMIT} 条，其他状态及恢复依据保留；'
                           '中断任务需手动重试。清理任务不会删除正式导出文件。')
        retention.setWordWrap(True)
        layout.addWidget(retention)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['任务', '状态', '输出目录'])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 2)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        buttons = QHBoxLayout()
        self.pause = QPushButton('暂停队列')
        self.pause.clicked.connect(queue.toggle_pause)
        buttons.addWidget(self.pause)
        for text, action in [('取消当前任务', queue.cancel), ('重试选中任务', self.retry), ('预览任务产物', self.preview_artifacts),
                             ('打开输出目录', self.open_output), ('清理成功任务', queue.clear_successful)]:
            button = QPushButton(text)
            button.clicked.connect(action)
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(3000)
        layout.addWidget(self.log, 2)
        queue.changed.connect(self.refresh)
        queue.message.connect(self.log.appendPlainText)
        queue.progress.connect(self.update_progress)
        if queue.history:
            for warning in queue.history.warnings:
                self.log.appendPlainText(warning)
        self.refresh()

    def refresh(self):
        self.pause.setText('继续队列' if self.queue.paused else '暂停队列')
        self.table.setRowCount(len(self.queue.jobs))
        for i, job in enumerate(self.queue.jobs):
            for c, text in enumerate((job.title, job.status, job.receipt_root or job.output)):
                self.table.setItem(i, c, QTableWidgetItem(text))
            if job.last_error:
                self.table.item(i, 1).setToolTip(job.last_error)
        if self.queue.busy:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(100)

    def update_progress(self, event):
        if isinstance(event, dict):
            total = event.get('total', event.get('total_files', 0))
            done = event.get('current', event.get('completed', event.get('done', 0)))
            if isinstance(total, (int, float)) and total > 0 and isinstance(done, (int, float)):
                self.progress.setRange(0, int(total))
                self.progress.setValue(int(done))

    def retry(self):
        self.queue.retry(self.table.currentRow())

    def open_output(self):
        index = self.table.currentRow()
        if 0 <= index < len(self.queue.jobs) and self.queue.jobs[index].output:
            job = self.queue.jobs[index]
            QDesktopServices.openUrl(QUrl.fromLocalFile(job.receipt_root or job.output))

    def preview_artifacts(self):
        index = self.table.currentRow()
        if 0 <= index < len(self.queue.jobs):
            job = self.queue.jobs[index]
            if not job.artifacts and self.queue.history and (job.request or {}).get('operation') == 'extract':
                job.artifacts = self.queue.history.extraction_artifacts(job)
                self.queue._persist(job)
            if self.queue.history and (job.request or {}).get('operation') == 'report':
                # Keep historical file references even if a user later removes a
                # file; the preview explicitly reports that missing PNG.
                artifacts = {item['path']: item for item in as_jsonable(job.artifacts)}
                artifacts.update({item['path']: item for item in self.queue.history.report_artifacts(job)})
                job.artifacts = list(artifacts.values())
                self.queue._persist(job)
            if job.artifacts:
                self.artifacts_requested.emit(job.artifacts)
            else:
                self.queue.message.emit('该任务暂无可确认完整的产物。中断对象的临时文件不计为成功，可手动重试。')
