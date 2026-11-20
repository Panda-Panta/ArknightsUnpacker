"""Expose scanned gameplay and on-demand season data to the Vue workbench."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

PLACEHOLDER = re.compile(r'\{(\d+)(?::[^{}]+)?\}')


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


@dataclass
class _Read:
    loading: bool = True
    error: str = ''
    detail: dict | None = None

    def state(self):
        return {'loading': self.loading, 'error': self.error, 'detail': self.detail}


def _entries(rows, describe):
    return [{'key': row.get('id') or str(index), 'name': row['name'], 'text': describe(row)}
            for index, row in enumerate(rows)]


def _mode_detail(result, version):
    if result['resource_version'] != version:
        raise ValueError('资源版本已变更，请重新扫描。')
    seasons = []
    for row in result['seasons']:
        refresh_cost = row.get('refresh_cost')
        seasons.append({
            'activityId': row['activity_id'], 'seasonId': row['season_id'],
            'title': row['title'], 'diagnostics': row.get('diagnostics', []),
            'strategies': _entries(row['strategies'], _strategy_text),
            'bonds': _entries(row['bonds'], _bond_text),
            'shops': _entries(row['shops'], lambda item: _shop_text(item, refresh_cost)),
        })
    diagnostics = result.get('diagnostics', [])
    if not seasons:
        raise ValueError('；'.join(diagnostics) or '当前资源中没有可解析的赛季。')
    return {'version': result['game_version'], 'seasons': seasons, 'diagnostics': diagnostics}


class WorkbenchGameplay:
    def __init__(self, window, changed):
        self.window = window
        self.changed = changed
        self._catalog = None
        self._reads = {}
        self._pending = {}
        window.queue.settled.connect(self._settled)

    def _sync(self):
        catalog = self.window.services.gameplay_catalog
        root = self.window.root
        if catalog and (not root or Path(catalog['root']).resolve() != Path(root).resolve()):
            catalog = None
        if catalog is not self._catalog:
            for job, _ in self._pending.values():
                job.token.cancel()
            self._pending.clear()
            self._reads.clear()
            self._catalog = catalog
        return catalog

    def dispatch(self, action, payload):
        catalog = self._sync()
        if action == 'gameplayCatalog':
            if catalog is None:
                return {'resourceVersion': '', 'modes': [], 'diagnostics': [], 'scanned': False}
            return {'resourceVersion': catalog['resource_version'], 'modes': catalog['modes'],
                    'diagnostics': catalog.get('diagnostics', []), 'scanned': True}
        if catalog is None:
            raise ValueError('请扫描当前游戏目录以识别玩法。')

        root = catalog['root']
        version = catalog['resource_version']
        services = self.window.services
        retry = payload.get('retry') is True
        if action == 'gameplayMode':
            mode_id = payload.get('id')
            mode = next((item for item in catalog['modes'] if item['id'] == mode_id), None)
            if mode is None or not mode['supported'] or not mode['available']:
                raise ValueError('当前安装没有可读取的玩法资料。')
            return self._read(('mode', mode_id), '读取玩法资料 · ' + mode['name'], retry,
                              lambda **kw: services.load_gameplay(root, mode_id, version, **kw),
                              lambda result: _mode_detail(result, version))
        if action == 'gameplayLevel':
            path = payload.get('path')
            autochess = next((item for item in catalog['modes'] if item['id'] == 'autochess'), None)
            if (autochess is None or not autochess['available']
                    or path not in autochess.get('level_paths', ())):
                raise ValueError('关卡不在当前安装的卫戍协议资源中。')
            name = path.rsplit('/', 1)[-1]
            return self._read(('level', path), '读取关卡资料 · ' + name, retry,
                              lambda **kw: services.load_gameplay_level(root, path, version, **kw),
                              lambda result: self._level_detail(path, result, version))
        raise ValueError('未知的玩法资料操作。')

    @staticmethod
    def _level_detail(path, result, version):
        if result['resource_version'] != version:
            raise ValueError('资源版本已变更，请重新扫描。')
        return {'text': _level_text(path, result)}

    def _read(self, key, title, retry, call, transform):
        read = self._reads.get(key)
        if read is not None and (not retry or not read.error):
            return read.state()
        read = _Read()
        self._reads[key] = read

        def work(**kwargs):
            kwargs['cancel'].check()
            result = call(**kwargs)
            return transform(result)

        def accepted(detail):
            if self._reads.get(key) is read:
                read.detail = detail

        job = self.window.queue.submit(title, work, accepted, show_in_tasks=False)
        self._pending[job.job_id] = (job, read)
        return read.state()

    def _settled(self, job):
        record = self._pending.pop(job.job_id, None)
        if record is None:
            return
        _, read = record
        read.loading = False
        if job.status != '成功':
            read.error = (job.last_error or job.status).strip().splitlines()[-1]
        self.changed()
