"""Locally identified modes and on-demand gameplay data in the workbench."""
from __future__ import annotations

from pathlib import Path
import re

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit,
    QPushButton, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)


KEY_ROLE = Qt.ItemDataRole.UserRole
TEXT_ROLE = KEY_ROLE + 1
PLACEHOLDER = re.compile(r'\{(\d+)(?::[^{}]+)?\}')


def _label(text=''):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


def _reader():
    reader = QPlainTextEdit()
    reader.setReadOnly(True)
    return reader


def _description(lines):
    return '\n\n'.join(str(line) for line in lines if line)


def _strategy_text(row):
    title = row.get('title')
    description = row.get('description') or ''
    if title:
        description = description.removeprefix(f'【{title}】').lstrip()
    hp = row.get('hp')
    unlock = row.get('unlock')
    return _description((title, description,
                         f'初始目标生命值 {hp}' if hp is not None else '',
                         f'解锁条件　{unlock}' if unlock else ''))


def _bond_text(row):
    descriptions = []
    indices = set()
    for scaling in row.get('scalings', ()):
        index = scaling['index']
        indices.add(index)
        percent = (scaling.get('format') or '').endswith('%')
        multiplier = 100 if percent else 1
        suffix = '%' if percent else ''
        unit = ' 个百分点' if percent else ''
        base = scaling['base'] * multiplier
        per_stack = scaling['per_stack'] * multiplier
        description = f'参数 {index + 1}　基础 {base:g}{suffix}，每层 {per_stack:+g}{unit}'
        cap = scaling.get('cap')
        if cap is not None:
            description += f'，上限 {cap * multiplier:g}{suffix}'
        descriptions.append(description)
    body = PLACEHOLDER.sub(
        lambda match: f'〔参数 {int(match[1]) + 1}〕' if int(match[1]) in indices else match[0],
        row.get('description') or '',
    )
    activation = row.get('activation')
    thresholds = ' / '.join(map(str, row.get('thresholds', ())))
    return _description((
        body, f'激活人数 {activation}' if activation is not None else '',
        f'{row.get("threshold_type") or "配置"}档位　{thresholds}' if thresholds else '',
        '\n'.join(descriptions),
    ))


def _shop_text(row, refresh_cost):
    def levels(key):
        return ' / '.join(str(value) if value is not None else '—' for value in row.get(key, ())) or '未知'

    return _description((
        f'普通刷新　{refresh_cost} 资金' if refresh_cost is not None else '普通刷新费用未知',
        '各项依次对应调度中心Ⅰ至Ⅵ级。升级费为配置中的初始价格。',
        f'初始升级费　{levels("upgrade_prices")}\n'
        f'干员栏位　{levels("operator_slots")}\n装备栏位　{levels("equipment_slots")}',
        '普通招募概率未知',
    ))


def _level_text(path, result):
    size = result.get('map_size') or []
    dimensions = f'{size[0]} × {size[1]}（行 × 列）' if len(size) == 2 and all(size) else '未知'
    return _description((
        result.get('level_id') or path, path,
        f'地图尺寸　{dimensions}',
        f'路线数　{result.get("route_count", "未知")}\n波次数　{result.get("wave_count", "未知")}',
        '敌人 ID\n' + '\n'.join(result['enemy_ids']) if result.get('enemy_ids') else '',
        '\n'.join(result.get('diagnostics', ())),
    ))


class EntryDetails(QSplitter):
    """A list of named records with a selectable plain-text detail pane."""

    def __init__(self):
        super().__init__()
        self.items = QListWidget()
        self.detail = _reader()
        self.addWidget(self.items)
        self.addWidget(self.detail)
        self.setStretchFactor(1, 1)
        self.setSizes([240, 600])
        self.items.currentItemChanged.connect(self._display)
        self._empty = ''

    def set_entries(self, rows, empty, *, select=True):
        self._empty = empty
        with QSignalBlocker(self.items):
            self.items.clear()
            for key, name, body in rows:
                item = QListWidgetItem(name)
                item.setData(KEY_ROLE, key)
                item.setData(TEXT_ROLE, body)
                item.setToolTip(name)
                self.items.addItem(item)
            if select and self.items.count():
                self.items.setCurrentRow(0)
        self._display(self.items.currentItem())

    def current_key(self):
        item = self.items.currentItem()
        return item.data(KEY_ROLE) if item is not None else None

    def _display(self, current, *_):
        self.detail.setPlainText(current.data(TEXT_ROLE) if current is not None else self._empty)


class GameplayModePanel(QWidget):
    retry_requested = Signal()
    level_requested = Signal()

    def __init__(self, mode):
        super().__init__()
        self.mode = mode
        self.state = 'new'
        self.revision = 0
        self.seasons = {}
        self.season_preference = None
        layout = QVBoxLayout(self)
        heading = QHBoxLayout()
        self.status = _label()
        self.status.setProperty('muted', True)
        self.retry = QPushButton('重试解析')
        self.retry.clicked.connect(self.retry_requested)
        self.retry.hide()
        heading.addWidget(self.status, 1)
        heading.addWidget(self.retry)
        layout.addLayout(heading)

        self.season = QComboBox()
        self.season.setAccessibleName('玩法赛季')
        self.season.currentIndexChanged.connect(self._show_season)
        self.season.hide()
        layout.addWidget(self.season)
        self.season_note = _label()
        self.season_note.setProperty('muted', True)
        layout.addWidget(self.season_note)

        self.sections = QTabWidget()
        self.strategies, self.bonds, self.shops, self.levels = (EntryDetails() for _ in range(4))
        self.resources = _reader()
        for tab, title in ((self.strategies, '策略'), (self.bonds, '盟约'),
                           (self.shops, '调度'), (self.levels, '关卡'), (self.resources, '资源')):
            self.sections.addTab(tab, title)
        self.sections.currentChanged.connect(self._request_level)
        self.levels.items.currentItemChanged.connect(self._request_level)
        self.levels.items.itemActivated.connect(self._request_level)
        layout.addWidget(self.sections, 1)
        self.reset()

    def set_mode(self, mode):
        previous_levels = self.mode.get('level_paths')
        self.mode = mode
        resources = dict.fromkeys((*mode.get('resources', ()), *mode.get('level_paths', ())))
        self.resources.setPlainText('\n'.join(resources) or '索引中暂无可列出的资源。')
        if previous_levels != mode.get('level_paths') and self.season.currentData() in self.seasons:
            self._show_levels(self.season.currentData()[0])

    def reset(self):
        self.revision += 1
        self.seasons.clear()
        with QSignalBlocker(self.season):
            self.season.clear()
        self.season.hide()
        self._show_season()
        self._show_detail_sections(False)
        self.retry.hide()
        self.status.setToolTip('')
        if not self.mode.get('available', True):
            self.state = 'unavailable'
            self.status.setText('已识别玩法，当前安装缺少数据资源。')
        elif not self.mode['supported']:
            self.state = 'unsupported'
            self.status.setText('已识别玩法，详情待适配。可浏览索引中的资源。')
        else:
            self.state = 'new'
            self.status.setText('打开此玩法后读取当前安装的赛季资料。')

    def _show_detail_sections(self, visible):
        for tab in (self.strategies, self.bonds, self.shops, self.levels):
            self.sections.setTabVisible(self.sections.indexOf(tab), visible)
        if visible:
            self.sections.setCurrentWidget(self.strategies)
        else:
            self.sections.setCurrentWidget(self.resources)

    def set_result(self, result):
        self.seasons = {(row['activity_id'], row['season_id']): row for row in result['seasons']}
        with QSignalBlocker(self.season):
            self.season.clear()
            for key, row in self.seasons.items():
                title = row['title']
                self.season.addItem(f'{title} · {key[1]}', key)
            index = self.season.findData(self.season_preference)
            self.season.setCurrentIndex(max(0, index) if self.seasons else -1)
        diagnostics = list(result.get('diagnostics', ()))
        if not self.seasons:
            self.failed('；'.join(diagnostics) or '当前资源中没有可解析的赛季。')
            return
        self.state = 'loaded'
        self.status.setText(f'游戏数据 {result["game_version"]} · {len(self.seasons)} 个赛季')
        self.status.setToolTip('\n'.join(diagnostics))
        self.season.show()
        self._show_season()
        self._show_detail_sections(True)

    def failed(self, message):
        self.state = 'failed'
        self.status.setText('玩法资料读取失败 · ' + message)
        self.retry.show()

    def set_season_preference(self, key):
        self.season_preference = key
        index = self.season.findData(key)
        if index >= 0:
            self.season.setCurrentIndex(index)

    def _show_season(self, *_):
        key = self.season.currentData()
        row = self.seasons.get(key)
        diagnostics = '\n'.join(row.get('diagnostics', ())) if row is not None else ''
        self.season_note.setText(diagnostics)
        self.season_note.setVisible(bool(diagnostics))
        if row is None:
            self.strategies.set_entries((), '暂无可用策略。')
            self.bonds.set_entries((), '暂无可用盟约。')
            self.shops.set_entries((), '暂无可用调度配置。')
            self._show_levels('')
            return
        self.season_preference = key
        self.strategies.set_entries(
            ((item.get('id'), item['name'], _strategy_text(item)) for item in row['strategies']),
            '此赛季暂无可用策略资料。',
        )
        self.bonds.set_entries(
            ((item.get('id'), item['name'], _bond_text(item)) for item in row['bonds']),
            '此赛季暂无可用盟约资料。',
        )
        self.shops.set_entries(
            ((item.get('id'), item['name'], _shop_text(item, row.get('refresh_cost'))) for item in row['shops']),
            '此赛季暂无可用调度配置。\n普通招募概率未知。',
        )
        self._show_levels(key[0])

    def _show_levels(self, activity_id):
        paths = (path for path in self.mode.get('level_paths', ())
                 if activity_id and activity_id in path.split('/'))
        self.levels.set_entries(((path, path.rsplit('/', 1)[-1], path) for path in paths),
                                '选择一个关卡后读取地图、路线及波次。', select=False)
        if not self.levels.items.count():
            self.levels.detail.setPlainText('资源索引中没有与所选赛季匹配的关卡。可在「资源」页核对路径。')

    def _request_level(self, *_):
        if self.sections.currentWidget() is self.levels and self.levels.current_key():
            self.level_requested.emit()


class GameplayView(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.root = None
        self.identity = None
        self.panels = {}
        self.jobs = {}
        self.level_pending = set()
        self.level_results = {}
        self.mode_preference = None
        self.season_preferences = {}
        layout = QVBoxLayout(self)
        self.status = _label('请扫描游戏资源以识别玩法。')
        self.status.setProperty('muted', True)
        layout.addWidget(self.status)
        self.modes = QTabWidget()
        self.modes.setObjectName('gameplayModes')
        self.modes.hide()
        layout.addWidget(self.modes, 1)

    def connect(self):
        self.window.tabs.currentChanged.connect(self._current_changed)
        self.modes.currentChanged.connect(self._current_changed)
        self.window.queue.settled.connect(self._settled)

    def set_root(self, root):
        root = str(Path(root).resolve()) if root else None
        if root != self.root:
            self.root = root
            self.mode_preference = None
            self.season_preferences.clear()
            self.set_catalog(None)

    def set_catalog(self, catalog):
        if catalog is not None and str(Path(catalog['root']).resolve()) != self.root:
            catalog = None
        identity = (self.root, catalog['resource_version']) if catalog is not None else None
        changed = identity != self.identity
        if changed:
            self.identity = identity
            for job, _ in self.jobs.values():
                job.token.cancel()
            self.jobs.clear()
            self.level_pending.clear()
            self.level_results.clear()

        current = self.modes.currentWidget()
        preferred = current.mode['id'] if current is not None else self.mode_preference
        entries = catalog['modes'] if catalog is not None else []
        remaining = {mode['id'] for mode in entries}
        with QSignalBlocker(self.modes):
            for mode_id in list(self.panels):
                if mode_id not in remaining:
                    panel = self.panels.pop(mode_id)
                    self.modes.removeTab(self.modes.indexOf(panel))
                    panel.deleteLater()
            for mode in entries:
                mode_id = mode['id']
                panel = self.panels.get(mode_id)
                if panel is None:
                    panel = GameplayModePanel(mode)
                    self.panels[mode_id] = panel
                    panel.retry_requested.connect(lambda panel=panel: self._load(panel, retry=True))
                    panel.level_requested.connect(lambda panel=panel: self._load_level(panel))
                    self.modes.addTab(panel, mode['name'])
                    panel.set_season_preference(self.season_preferences.get(mode_id))
                changed_availability = any(mode.get(key, True) != panel.mode.get(key, True)
                                           for key in ('supported', 'available'))
                panel.set_mode(mode)
                self.modes.setTabText(self.modes.indexOf(panel), mode['name'])
                if changed or changed_availability:
                    panel.reset()
            if preferred in self.panels:
                self.modes.setCurrentWidget(self.panels[preferred])
        diagnostics = list(catalog.get('diagnostics', ())) if catalog is not None else []
        if catalog is None:
            message = '请扫描游戏资源以识别玩法。'
        elif not entries:
            message = '本次扫描未识别到特殊玩法。'
        else:
            message = f'已识别 {len(entries)} 种玩法 · 资源版本 {identity[1]}'
        if diagnostics:
            message += '\n' + '\n'.join(diagnostics)
        self.status.setText(message)
        self.modes.setVisible(bool(entries))
        self._current_changed()

    def save_state(self):
        panel = self.modes.currentWidget()
        seasons = {mode_id: list(view.season_preference) for mode_id, view in self.panels.items()
                   if view.season_preference}
        return {'mode': panel.mode['id'] if panel is not None else self.mode_preference,
                'seasons': {**self.season_preferences, **seasons}}

    def restore_state(self, state):
        self.mode_preference = state.get('mode')
        self.season_preferences = {
            mode_id: tuple(key) for mode_id, key in state.get('seasons', {}).items()
            if isinstance(key, (list, tuple)) and len(key) == 2
        }
        for mode_id, panel in self.panels.items():
            if mode_id in self.season_preferences:
                panel.set_season_preference(self.season_preferences[mode_id])
        if self.mode_preference in self.panels:
            self.modes.setCurrentWidget(self.panels[self.mode_preference])

    def _active(self, panel):
        return (not self.window._closing and panel is not None
                and self.window.tabs.currentWidget() is self and self.modes.currentWidget() is panel)

    def _current_changed(self, *_):
        panel = self.modes.currentWidget()
        if self._active(panel):
            self._load(panel)
            if panel.sections.currentWidget() is panel.levels:
                self._load_level(panel)

    def _submit(self, title, call, done, failed):
        def accept(result):
            if job.job_id in self.jobs and not job.token.cancelled and not self.window._closing:
                done(result)

        def work(**kwargs):
            kwargs['cancel'].check()
            return call(**kwargs)

        job = self.window.queue.submit(title, work, accept, show_in_tasks=False)
        self.jobs[job.job_id] = (job, failed)

    def _settled(self, job):
        record = self.jobs.pop(job.job_id, None)
        if record is not None and job.status != '成功' and not self.window._closing:
            error = (job.last_error or job.status).strip().splitlines()[-1]
            record[1](error)

    def _load(self, panel, *, retry=False):
        if self.identity is None or not self._active(panel):
            return
        if panel.state != ('failed' if retry else 'new'):
            return
        root, version = self.identity
        mode_id = panel.mode['id']
        revision = panel.revision
        panel.state = 'loading'
        panel.retry.hide()
        panel.status.setText('正在读取玩法资料…')

        def is_current():
            return self.panels.get(mode_id) is panel and panel.revision == revision

        def done(result):
            if not is_current():
                return
            if result['resource_version'] != version:
                panel.failed('资源版本已变更，请重新扫描。')
                return
            panel.set_result(result)

        def failed(error):
            if is_current():
                panel.failed(error)

        self._submit('读取玩法资料 · ' + panel.mode['name'],
                     lambda **kw: self.window.services.load_gameplay(root, mode_id, version, **kw),
                     done, failed)

    def _load_level(self, panel):
        path = panel.levels.current_key()
        if self.identity is None or not path or not self._active(panel):
            return
        load = getattr(self.window.services, 'load_gameplay_level', None)
        if load is None:
            panel.levels.detail.setPlainText(path + '\n\n关卡详情待适配。')
            return
        if path in self.level_results:
            panel.levels.detail.setPlainText(self.level_results[path])
            return
        panel.levels.detail.setPlainText(path + '\n\n正在读取关卡资料…')
        if path in self.level_pending:
            return
        root, version = self.identity
        self.level_pending.add(path)

        def show(text):
            if self.panels.get(panel.mode['id']) is panel and panel.levels.current_key() == path:
                panel.levels.detail.setPlainText(text)

        def done(result):
            self.level_pending.discard(path)
            self.level_results[path] = _level_text(path, result)
            show(self.level_results[path])

        def failed(error):
            self.level_pending.discard(path)
            show(path + '\n\n读取失败 · ' + error + '\n双击此关卡条目重试。')

        self._submit('读取关卡资料 · ' + path.rsplit('/', 1)[-1],
                     lambda **kw: load(root, path, version, **kw), done, failed)
