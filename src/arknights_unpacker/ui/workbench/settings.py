"""Settings, scan preferences and data history for the local workbench."""
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog

from arknights_unpacker.paths import default_output_root, validate_output
from arknights_unpacker.reports.font_catalog import font_faces, system_font_faces


_CHOICES = {
    'extraction_mode': ('auto', ('auto', 'raw')),
    'report_theme': ('dark', ('dark', 'light')),
    'report_module_image_layout': ('single', ('single', 'paged')),
    'data_locale': ('unknown', ('unknown', 'zh_CN')),
    'scan_priority': ('data_first', ('data_first', 'data_only', 'files_only')),
}
_NUMBERS = {'report_width': (1200, 720, 3000), 'report_font_size': (28, 18, 56), 'hours': (24, 0.01, 876000)}
_FORMATS = ('png', 'html', 'json', 'txt')
_KINDS = ('image', 'text', 'audio', 'video', 'spine')


class WorkbenchSettings:
    def __init__(self, window, changed):
        self.window = window
        self.services = window.services
        self.changed = changed

    def _get(self):
        config = self.services.config
        kinds = set(config.get('extraction_kinds', ['image', 'text', 'audio', 'spine']))
        if config.get('extraction_video', True):
            kinds.add('video')
        return {'dataRoot': str(self.services.data_root), 'config': {
            **{key: config.get(key, default) for key, (default, _) in _CHOICES.items()},
            **{key: config.get(key, default) for key, (default, _, _) in _NUMBERS.items()},
            'output_root': str(config.get('output_root') or default_output_root()),
            'extraction_kinds': [kind for kind in _KINDS if kind in kinds],
            'formats': [fmt for fmt in _FORMATS if fmt in config.get('formats', ('png', 'html')) or fmt in ('json', 'txt')],
            'report_font_path': config.get('report_font_path', ''),
            'report_font_index': config.get('report_font_index', 0),
            'monitor': bool(config.get('monitor', False)), 'strict_scan': bool(config.get('strict_scan', False)),
        }}

    def _save(self, payload):
        config = self.services.config
        if self.window.queue.busy:
            raise ValueError('请等待当前任务完成再保存设置。')
        output = validate_output(payload.get('output_root') or default_output_root(), self.window.root)
        if any(output.is_relative_to(root) or root.is_relative_to(output) for root in self.window.preview_cache.roots):
            raise ValueError('请选择与预览缓存分开的输出目录。')
        selected = {'output_root': str(output)}
        for key, (default, allowed) in _CHOICES.items():
            item = payload.get(key, default)
            if item not in allowed:
                raise ValueError('设置中的选项已变化，请重新选择。')
            selected[key] = item
        for key, (default, lower, upper) in _NUMBERS.items():
            count = payload.get(key, default)
            if type(count) not in (int, float) or not lower <= count <= upper:
                raise ValueError('设置中的数值超出允许范围。')
            selected[key] = float(count) if key == 'hours' else int(count)
        kinds = payload.get('extraction_kinds', [])
        formats = payload.get('formats', [])
        if not isinstance(kinds, list) or not isinstance(formats, list):
            raise ValueError('请检查资源类型和资料保存格式。')
        selected['extraction_kinds'] = [kind for kind in _KINDS if kind in kinds]
        selected['extraction_video'] = 'video' in selected['extraction_kinds']
        selected['formats'] = [fmt for fmt in _FORMATS if fmt in formats or fmt in ('json', 'txt')]
        for key in ('monitor', 'strict_scan'):
            selected[key] = payload.get(key) is True
        font_path = str(payload.get('report_font_path') or '')
        font_index = payload.get('report_font_index', 0)
        if font_path and (font_path != config.get('report_font_path') or font_index != config.get('report_font_index')):
            try:
                faces = font_faces(font_path)
            except (OSError, ValueError, KeyError) as error:
                raise ValueError('无法读取所选字体。') from error
            if not any(face.index == font_index for face in faces):
                raise ValueError('请选择有效的字体字形。')
        selected['report_font_path'] = font_path
        selected['report_font_index'] = font_index if font_path else 0
        previous = dict(config)
        config.update(selected)
        try:
            self.services.save_config()
        except (OSError, ValueError):
            config.clear()
            config.update(previous)
            raise
        self.window.preview_cache.protected_roots = (output,)
        self.window.show_status('设置已保存。')
        self.changed()
        return self._get()

    def _history(self):
        installation = self.services.installation
        if installation is None:
            return []
        return [{**item, 'label': f'{item.get("version", "未知版本")} · {item["snapshot_id"]}' +
                 ('' if item.get('complete', True) else '（不完整）')}
                for item in self.services.store.list_data_snapshots(installation.profile_id)]

    def _edit_history(self, action, payload):
        if self.services.gamedata is None:
            raise ValueError('请先解析当前核心数据。')
        if self.window.queue.busy:
            raise ValueError('请等待当前任务完成。')
        if action == 'settingsCompareSnapshot':
            identifier = payload.get('snapshotId')
            if not isinstance(identifier, str) or not identifier:
                raise ValueError('请先选择历史资料快照。')
            self.window.queue.submit('比较历史资料快照', lambda **_: self.services.compare_snapshot(identifier),
                                     lambda _: self.changed())
        elif action == 'settingsImportBaseline':
            path, _ = QFileDialog.getOpenFileName(self.window, '导入同服历史资料基线', '', '资料快照 (*.json)')
            if path:
                self.window.queue.submit('导入历史资料基线', lambda **_: self.services.import_baseline(path),
                                         lambda _: self.changed())
        elif action == 'settingsExportSnapshot':
            output = self.window.output_root() or str(default_output_root())
            path, _ = QFileDialog.getSaveFileName(self.window, '导出资料快照',
                                                str(Path(output) / 'data-snapshot.json'), '资料快照 (*.json)')
            if path:
                target = validate_output(path, self.window.root)
                self.window.queue.submit('导出资料快照', lambda **_: self.services.export_snapshot(target),
                                         output=str(target.parent))

    def dispatch(self, action, payload):
        if action == 'settingsGet':
            return self._get()
        if action == 'settingsSave':
            return self._save(payload)
        if action == 'settingsChooseOutput':
            return QFileDialog.getExistingDirectory(self.window, '选择独立输出目录', payload.get('path', ''))
        if action == 'settingsOpenData':
            return QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.services.data_root)))
        if action == 'settingsFonts':
            return [asdict(face) for face in system_font_faces()]
        if action == 'settingsHistory':
            return self._history()
        if action in ('settingsCompareSnapshot', 'settingsImportBaseline', 'settingsExportSnapshot'):
            return self._edit_history(action, payload)
        raise ValueError('未知设置操作。')
