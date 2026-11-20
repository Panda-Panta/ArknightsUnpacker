"""Host the offline Vue resource workbench and reuse the desktop job queue."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox

from arknights_unpacker.paths import default_output_root, resource_root, validate_output

from ..desktop_jobs import DesktopJobActions
from ..jobs import JobQueue
from ..models import value
from ..preview_cache import PreviewCache, legacy_preview_paths
from .characters import WorkbenchCharacters
from .entities import WorkbenchEntities
from .gameplay import WorkbenchGameplay
from .objects import WorkbenchObjects
from .records import WorkbenchRecords
from .resources import WorkbenchResources
from .settings import WorkbenchSettings

logger = logging.getLogger(__name__)


def workbench_index() -> Path:
    return resource_root() / 'resources/workbench/index.html'


class WorkbenchPage(QWebEnginePage):
    def __init__(self, profile, index_url, parent):
        super().__init__(profile, parent)
        self._index_url = index_url

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        return url == self._index_url

    def javaScriptConsoleMessage(self, level, message, line, source):
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            logger.error('Vue 工作台 %s:%s %s', source, line, message)


class WorkbenchBridge(QObject):
    changed = Signal()

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.resources = WorkbenchResources()
        self.objects = WorkbenchObjects(window, self.schedule_changed)
        self.characters = WorkbenchCharacters(window, self.schedule_changed)
        self.sections = {
            'entities': WorkbenchEntities(window, self.schedule_changed),
            'gameplay': WorkbenchGameplay(window, self.schedule_changed),
            'records': WorkbenchRecords(window, self.resources),
            'settings': WorkbenchSettings(window, self.schedule_changed),
        }
        self._binding = None
        self._revision = 0
        self._notify = QTimer(self)
        self._notify.setSingleShot(True)
        self._notify.setInterval(40)
        self._notify.timeout.connect(self.changed)
        window.queue.changed.connect(self.schedule_changed)
        window.state_changed.connect(self.schedule_changed)

    def schedule_changed(self, *_):
        if not self._notify.isActive():
            self._notify.start()

    def _sync_resources(self):
        services = self.window.services
        selected = self.window.root
        root = str(Path(selected).resolve()) if selected else ''
        snapshot, changes, catalog = None, None, None
        if root and services.scan_snapshot is not None:
            observation_root = value(services.scan_snapshot, 'root')
            if observation_root and Path(observation_root).resolve() == Path(root):
                snapshot, changes = services.scan_snapshot, services.file_changes
        installed_root = value(services.installation, 'root')
        if root and installed_root and Path(installed_root).resolve() == Path(root):
            catalog = services.catalog
        binding = (root, id(snapshot), id(changes), id(catalog))
        if binding != self._binding:
            if self._binding is not None:
                self.objects.close()
                self.characters.close()
            self.resources.refresh(root, snapshot, changes, catalog)
            self._binding = binding
            self._revision += 1
        return root

    def _state(self):
        window = self.window
        root = self._sync_resources()
        snapshot_id = value(window.services.gamedata, 'snapshot_id', '')
        return {
            'root': root,
            'busy': bool(window.queue.busy),
            'scanning': window._scan_pending,
            'restoring': window._restore_pending,
            'status': window.status,
            'taskCount': sum(job.status in ('排队中', '运行中', '正在取消') and job.show_in_tasks
                             for job in window.queue.jobs),
            'revision': self._revision,
            'dataRevision': f'{snapshot_id}:{id(window.services.entity_changes)}' if snapshot_id else '',
        }

    def _scan(self):
        if self.window.root:
            self.window.scan()
        else:
            self._choose_root()

    def _choose_root(self):
        if self.window.queue.busy:
            raise ValueError('请等待当前任务完成，再切换游戏目录。')
        self.window.choose_root()

    def _open_output(self):
        output = self.window.output_root()
        if not output or not QDesktopServices.openUrl(QUrl.fromLocalFile(output)):
            raise ValueError('无法打开输出目录，请检查设置。')

    def _dispatch(self, action, payload):
        if action == 'state':
            return self._state()
        if action == 'list':
            self._sync_resources()
            return self.resources.query(payload)
        if action == 'matchingResources':
            self._sync_resources()
            return self.resources.matching_ids(payload)
        window = self.window
        standalone = {
            'chooseRoot': self._choose_root, 'scan': self._scan, 'loadData': window.load_data,
            'cancel': window.queue.cancel, 'openOutput': self._open_output,
        }
        if action in standalone:
            standalone[action]()
            return None
        self._sync_resources()
        for prefix, section in self.sections.items():
            if action.startswith(prefix):
                return section.dispatch(action, payload)
        if action == 'extractDirectory':
            files = self.resources.directory_paths(payload['folder'], payload['layer'])
            window.extract(files)
            return None
        if action in ('extract', 'extractImages', 'expressions'):
            files = self.resources.paths(payload['ids'], extraction=True)
            if action == 'expressions':
                return self.characters.open(files)
            elif action == 'extractImages':
                window.extract(files, kinds=['image'], mode='auto')
            else:
                window.extract(files)
            return None
        if action == 'objects':
            path, = self.resources.paths([payload['id']])
            return self.objects.open(path)
        token = payload.get('token')
        if action == 'objectState':
            return self.objects.state(token)
        if action == 'previewObject':
            return self.objects.select(token, payload['id'])
        if action == 'objectPreview':
            return self.objects.preview(token)
        if action == 'extractObjects':
            return self.objects.extract(token, payload['ids'])
        if action == 'saveArtifact':
            return self.objects.save(token, payload['index'])
        if action == 'openMedia':
            return self.objects.open_media(token, payload['index'])
        if action == 'closeObjects':
            return self.objects.close(token)
        if action == 'characterState':
            return self.characters.state(token)
        if action == 'characterPreview':
            return self.characters.preview(token, payload['options'])
        if action == 'characterExport':
            return self.characters.export(token, payload['options'])
        if action == 'characterBatch':
            return self.characters.batch(token)
        if action == 'characterClose':
            return self.characters.close(token)
        raise ValueError('未知的工作台操作。')

    @Slot(str, str, result=str)
    def invoke(self, action, serialized):
        try:
            payload = json.loads(serialized)
            if not isinstance(payload, dict):
                raise ValueError('工作台参数格式无效。')
            result = {'ok': True, 'data': self._dispatch(action, payload)}
            return json.dumps(result, ensure_ascii=False, allow_nan=False)
        except (ValueError, OSError) as error:
            result = {'ok': False, 'error': str(error)}
        except Exception:
            logger.exception('Vue 工作台操作失败: %s', action)
            result = {'ok': False, 'error': '工作台操作失败，请查看应用日志。'}
        return json.dumps(result, ensure_ascii=False, allow_nan=False)


class VueWorkbenchWindow(DesktopJobActions, QMainWindow):
    state_changed = Signal()

    def __init__(self, services, initial_root=''):
        super().__init__()
        self.services = services
        self.root = initial_root or str(services.config.get('game_root', ''))
        self.status = '正在读取上次保存的结果…' if self.root else '选择游戏目录以开始浏览资源。'
        self._closing = False
        self._restore_pending = bool(self.root)
        self._restore_job = None
        self._scan_pending = False
        self._scan_job = None
        self._scan_after_load = False
        self._load_job = None
        self._monitor_stamp = None
        self._preview_warning_count = 0
        self._dialog_jobs = {}
        self._preview_jobs = {}
        self._object_preview_jobs = {}
        self._object_preview_pending = {}
        self._report_preview_jobs = {}
        self._report_preview_pending = {}
        self._displayed_preview_jobs = set()
        self._discard_when_settled = set()
        history = services.data_root / 'queue'
        output = services.config.get('output_root')
        if output and Path(output).resolve() in legacy_preview_paths(services.data_root, history):
            services.config['output_root'] = str(default_output_root())
            services.save_config()
        self.preview_cache = PreviewCache(services.data_root, protected_roots=[services.config['output_root']])
        self.preview_cache.cleanup_stale(history)
        self.queue = JobQueue(self, history_root=history, resume_handler=self.prepare_recovery)
        self.queue.changed.connect(self._finish_closing)
        self.queue.message.connect(self.show_status)
        self.queue.settled.connect(self._job_settled)
        self.queue.settled.connect(self._settled)
        self.setWindowTitle('ArknightsUnpacker')
        self.resize(1500, 900)
        self.setMinimumSize(1030, 650)
        self.web = QWebEngineView(self)
        self.setCentralWidget(self.web)
        self.bridge = WorkbenchBridge(self)
        self.channel = QWebChannel(self.web)
        self.channel.registerObject('workbench', self.bridge)

        profile = QWebEngineProfile('resource-workbench', QApplication.instance())
        profile.setPersistentStoragePath(str(services.data_root / 'workbench-web'))
        profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        index_url = QUrl.fromLocalFile(str(workbench_index()))
        self.web.setPage(WorkbenchPage(profile, index_url, self.web))
        self.web.page().setWebChannel(self.channel)
        self.web.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        self.web.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        self.web.loadFinished.connect(self._loaded)
        self.web.load(index_url)
        self.monitor_timer = QTimer(self)
        self.monitor_timer.setInterval(15000)
        self.monitor_timer.timeout.connect(self._check_manifests)
        self.monitor_timer.start()
        if self._restore_pending:
            QTimer.singleShot(0, self._restore)

    def game_root(self):
        return self.root

    def extraction_defaults(self):
        config = self.services.config
        kinds = [kind for kind in config['extraction_kinds'] if kind != 'video']
        if config.get('extraction_video', True):
            kinds.append('video')
        return kinds, config['extraction_mode']

    def output_root(self):
        path = self.services.config.get('output_root')
        if not path:
            self.show_status('请先在设置中选择独立输出目录。')
            return None
        try:
            path = validate_output(Path(path).expanduser().resolve(), self.root)
            if any(path.is_relative_to(root) for root in self.preview_cache.roots):
                raise ValueError('请选择临时预览目录之外的输出目录。')
            return str(path)
        except (ValueError, OSError) as error:
            self.show_status(str(error))
            return None

    def show_status(self, message):
        self.status = str(message)[-450:]
        self.state_changed.emit()

    def _restore(self):
        if self._closing:
            return
        root = self.root
        self._restore_job = self.queue.submit('读取上次扫描与解析结果',
                                              lambda **kw: self.services.restore(root, **kw),
                                              self._restored, show_in_tasks=False)

    def _restored(self, result):
        self._normalized_root()
        self.show_status('已恢复保存的结果。' if result.get('snapshot') or result.get('gamedata')
                         else '当前目录没有保存结果，可以开始扫描。')

    def _normalized_root(self):
        root = value(self.services.installation, 'root')
        if root:
            self.root = str(root)
        self._monitor_stamp = self._manifest_stamp()

    def choose_root(self):
        root = QFileDialog.getExistingDirectory(self, '选择游戏目录', self.root)
        if root:
            self.root = root
            self.state_changed.emit()
            self.scan()

    def scan(self):
        if self._restore_pending or self._scan_pending or self._load_job is not None:
            self.show_status('扫描或资料检查已在队列中。')
            return
        if not self.root or not Path(self.root).is_dir():
            self.show_status('请先选择可访问的游戏目录。')
            return
        priority = self.services.config.get('scan_priority', 'data_first')
        self._scan_pending = True
        if priority == 'files_only':
            self._submit_inventory()
        else:
            self._scan_after_load = priority != 'data_only'
            self._submit_data()
            self._scan_job = self._load_job

    def _submit_inventory(self):
        root = self.root
        hours = self.services.config.get('hours', 24)
        strict = bool(self.services.config.get('strict_scan', False))
        self._scan_job = self.queue.submit('扫描游戏目录',
            lambda **kw: self.services.scan(root, hours, strict, **kw), self.scanned,
            request={'operation': 'scan', 'root': root, 'hours': hours, 'strict': strict})

    def scanned(self, result):
        self._normalized_root()
        snapshot = result.get('snapshot')
        self.show_status(f'扫描结果 · {len(value(snapshot, "files", [])):,} 个文件。')

    def load_data(self):
        if not self.root or self._scan_pending or self._restore_pending or self._load_job is not None:
            self.show_status('请选择游戏目录，或等待当前检查完成。')
            return
        self._submit_data()

    def _submit_data(self):
        root = self.root
        self._load_job = self.queue.submit('解析核心数据', lambda **kw: self.services.load_data(root, **kw),
            self.data_loaded, request={'operation': 'load_data', 'root': root,
                                       'locale': self.services.config.get('data_locale', 'unknown')})

    def data_loaded(self, snapshot):
        if value(snapshot, 'complete'):
            self._normalized_root()
            self.show_status('核心资料已更新。')

    def _settled(self, job):
        if job is self._restore_job:
            self._restore_job = None
            self._restore_pending = False
        if job is self._load_job:
            self._load_job = None
        if job is self._scan_job:
            self._scan_job = None
            if self._scan_after_load and not job.token.cancelled and not self._closing:
                self._scan_after_load = False
                self._submit_inventory()
            else:
                self._scan_after_load = False
                self._scan_pending = False
        self.state_changed.emit()

    def show_report_artifacts(self, artifacts):
        self.show_status(f'资料导出完成 · {len(artifacts)} 项，可在任务记录中查看。')

    def _manifest_stamp(self):
        stamp = []
        for root in value(self.services.installation, 'source_roots', {}).values():
            for name in ('hot_update_list.json', 'persistent_res_list.json', 'resource_manifest.json'):
                path = Path(root) / name
                try:
                    info = path.stat()
                    stamp.append((path, info.st_mtime_ns, info.st_size))
                except OSError:
                    stamp.append((path, None, None))
        return tuple(stamp)

    def _check_manifests(self):
        if self.queue.busy or not self.services.config.get('monitor'):
            return
        stamp = self._manifest_stamp()
        if self._monitor_stamp and stamp != self._monitor_stamp:
            self.scan()
        self._monitor_stamp = stamp

    def _loaded(self, ok):
        if not ok and not self._closing:
            QMessageBox.critical(self, '无法启动工作台', '请检查 Vue 前端的构建资源。')
            self.close()

    def _finish_closing(self):
        if self._closing and not self.queue.busy:
            QTimer.singleShot(0, self.close)

    def closeEvent(self, event):
        if not self._closing:
            self._closing = True
            self.monitor_timer.stop()
            self.web.stop()
            self.bridge.objects.close()
            self.bridge.characters.close()
            for section in self.bridge.sections.values():
                close = getattr(section, 'close', None)
                if close:
                    close()
            self.queue.shutdown()
        if self.queue.busy:
            event.ignore()
        else:
            self.preview_cache.shutdown()
            event.accept()
