"""Browse the active game's level index and open verified previews."""
from pathlib import Path
import re

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QSplitter, QTabBar, QTableView, QVBoxLayout, QWidget,
)

from .models import RecordsModel, value
from .pages import PageController


_INDICATOR_CATEGORIES = {'全息作战矩阵', '危机合约'}


CATEGORY_ORDER = ('主线', '支线', '支线与插曲', '插曲', '集成战略', '特殊活动')
UNKNOWN_CHAPTER = ('', '')


def _label(text='', *, role=None, muted=False):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    if role:
        label.setProperty('role', role)
    if muted:
        label.setProperty('muted', True)
    return label


def _preview_status(row):
    if row['available'] and row.get('preview_ready'):
        return '动画试渲染可播放'
    if row.get('map_image'):
        return '游戏原图可预览'
    if not row['available']:
        return '关卡数据未安装'
    return '预览资源待校验'


def _chapter_key(row):
    chapter = row.get('chapter_id') or row.get('chapter')
    return (row['category'], chapter) if chapter else UNKNOWN_CHAPTER


def _chapter_label(row):
    return row.get('chapter') or row.get('chapter_id') or '未知章节'


def _level_name(row):
    return row.get('name') or row['id'].rsplit('/', 1)[-1]


def _chapter_order(key):
    parts = re.split(r'([0-9]+)', key[1].casefold())
    return key == UNKNOWN_CHAPTER, tuple(int(part) if i % 2 else part for i, part in enumerate(parts))


class LevelCatalogView(QWidget):
    preview_requested = Signal(str)
    tags_requested = Signal(str, str)
    replay_selection_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._catalog = None
        self._category = None
        self._chapter = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        self.categories = QTabBar()
        self.categories.setObjectName('levelCategories')
        self.categories.setAccessibleName('关卡分类')
        self.categories.setExpanding(False)
        self.categories.setUsesScrollButtons(True)
        layout.addWidget(self.categories)

        filters = QHBoxLayout()
        self.chapters = QComboBox()
        self.chapters.setObjectName('levelChapters')
        self.chapters.setAccessibleName('章节或活动')
        self.chapters.setMinimumContentsLength(12)
        self.chapters.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.chapters.setMaximumWidth(320)
        chapter_label = _label('章节 / 活动')
        chapter_label.setBuddy(self.chapters)
        filters.addWidget(chapter_label)
        filters.addWidget(self.chapters)
        self.search = QLineEdit()
        self.search.setObjectName('levelSearch')
        self.search.setAccessibleName('搜索关卡')
        self.search.setPlaceholderText('搜索编号、关卡名称、章节或路径')
        self.search.setClearButtonEnabled(True)
        filters.addWidget(self.search, 1)
        self.only_new = QCheckBox('仅看新增')
        self.only_new.setObjectName('levelOnlyNew')
        self.only_new.setToolTip('显示与上次同一安装目录的完整扫描相比新增的关卡。')
        filters.addWidget(self.only_new)
        layout.addLayout(filters)

        self.summary = _label(muted=True)
        self.diagnostics = _label()
        self.diagnostics.setProperty('notice', 'warning')
        layout.addWidget(self.summary)
        layout.addWidget(self.diagnostics)

        self.model = RecordsModel([
            ('编号', lambda row: row.get('code')), ('关卡名称', _level_name), ('分类', 'category'),
            ('更新', lambda row: '新增' if row['is_new'] else '—'),
            ('预览状态', _preview_status),
        ], self)
        self.table = QTableView()
        self.table.setObjectName('levelTable')
        self.table.setAccessibleName('关卡目录')
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.table.setSortingEnabled(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        selection = QFrame()
        selection.setProperty('role', 'surface')
        selection.setMinimumWidth(230)
        details = QVBoxLayout(selection)
        details.setContentsMargins(16, 14, 16, 14)
        details.addWidget(_label('所选关卡', role='sectionTitle'))
        self.selected_name = _label(role='pageTitle')
        details.addWidget(self.selected_name)
        self.details = _label(muted=True)
        details.addWidget(self.details)
        self.selected_path = _label(muted=True)
        self.selected_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        details.addWidget(self.selected_path)
        details.addStretch(1)
        self.tags_button = QPushButton('配置作战指标…')
        self.tags_button.setObjectName('levelTags')
        details.addWidget(self.tags_button)
        self.preview_button = QPushButton('打开地图预览')
        self.preview_button.setObjectName('openLevelPreview')
        self.preview_button.setProperty('primary', True)
        details.addWidget(self.preview_button)

        split = QSplitter()
        split.setChildrenCollapsible(False)
        split.addWidget(self.table)
        split.addWidget(selection)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        split.setSizes([680, 260])
        layout.addWidget(split, 1)

        self.categories.currentChanged.connect(self._category_changed)
        self.chapters.currentIndexChanged.connect(self._chapter_changed)
        self.search.textChanged.connect(self._refresh)
        self.only_new.toggled.connect(self._refresh)
        self.table.selectionModel().selectionChanged.connect(self._show_selection)
        self.table.doubleClicked.connect(self._open_index)
        self.tags_button.clicked.connect(self._request_tags)
        self.preview_button.clicked.connect(self._request_preview)
        self.set_catalog(None)

    def set_catalog(self, catalog):
        self._catalog = catalog
        rows = catalog['levels'] if catalog is not None else []
        categories = {row['category'] for row in rows}
        ordered = [category for category in CATEGORY_ORDER if category in categories]
        ordered.extend(sorted(categories.difference(CATEGORY_ORDER, {'其他'})))
        if '其他' in categories:
            ordered.append('其他')
        with QSignalBlocker(self.categories):
            while self.categories.count():
                self.categories.removeTab(0)
            self.categories.addTab('全部')
            for category in ordered:
                index = self.categories.addTab(category)
                self.categories.setTabData(index, category)
            self._select_category()
        diagnostics = '\n'.join(catalog.get('diagnostics', ())) if catalog else ''
        self.diagnostics.setText(diagnostics)
        self.diagnostics.setVisible(bool(diagnostics))
        self.categories.setEnabled(bool(rows))
        self.search.setEnabled(bool(rows))
        self.only_new.setEnabled(bool(rows))
        self._refresh_chapters()
        self._refresh()

    def save_state(self):
        return {'category': self._category, 'chapter': self._chapter, 'search': self.search.text(),
                'only_new': self.only_new.isChecked()}

    def restore_state(self, state):
        self._category = state.get('category')
        chapter = state.get('chapter')
        self._chapter = tuple(chapter) if isinstance(chapter, (list, tuple)) and len(chapter) == 2 else None
        with QSignalBlocker(self.categories), QSignalBlocker(self.search), QSignalBlocker(self.only_new):
            self._select_category()
            self.search.setText(state.get('search') or '')
            self.only_new.setChecked(bool(state.get('only_new')))
        self._refresh_chapters()
        self._refresh()

    def _select_category(self):
        for index in range(1, self.categories.count()):
            if self.categories.tabData(index) == self._category:
                self.categories.setCurrentIndex(index)
                return
        self.categories.setCurrentIndex(0)

    def _category_changed(self, index):
        self._category = self.categories.tabData(index)
        self._chapter = None
        self._refresh_chapters()
        self._refresh()

    def _chapter_changed(self, index):
        self._chapter = self.chapters.itemData(index)
        self._refresh()

    def _refresh_chapters(self):
        category = self.categories.tabData(self.categories.currentIndex())
        rows = self._catalog['levels'] if self._catalog is not None else []
        chapters = {_chapter_key(row): _chapter_label(row) for row in rows
                    if category is None or row['category'] == category}
        with QSignalBlocker(self.chapters):
            self.chapters.clear()
            self.chapters.addItem('全部章节')
            current = 0
            for index, key in enumerate(sorted(chapters, key=_chapter_order), start=1):
                self.chapters.addItem(chapters[key], key)
                if key == self._chapter:
                    current = index
            self.chapters.setCurrentIndex(current)
        self.chapters.setEnabled(bool(chapters))

    def _refresh(self, *_):
        previous = self._selected_row()
        category = self.categories.tabData(self.categories.currentIndex())
        chapter = self.chapters.currentData()
        query = self.search.text().strip().casefold()
        only_new = self.only_new.isChecked()
        rows = self._catalog['levels'] if self._catalog is not None else []
        matches = [row for row in rows
                   if (category is None or row['category'] == category)
                   and (chapter is None or _chapter_key(row) == chapter)
                   and (not only_new or row['is_new'])
                   and (not query or query in ' '.join((row.get('code') or '', _level_name(row),
                                                        _chapter_label(row), row.get('chapter_id') or '',
                                                        row['id'])).casefold())]
        self.model.replace(matches)
        if previous is not None:
            for index, row in enumerate(self.model.rows):
                if row['id'] == previous['id']:
                    self.table.selectRow(index)
                    break
        if self._catalog is None:
            self.summary.setText('请扫描游戏资源以建立关卡目录。')
        elif not rows:
            self.summary.setText('本次扫描未识别到关卡。')
        else:
            version = self._catalog['resource_version']
            shown = f'显示 {len(matches):,} 关' if matches else '没有符合条件的关卡'
            self.summary.setText(f'{shown} · 共 {len(rows):,} 关 · 资源版本 {version}')
        self._show_selection()

    def _selected_row(self):
        selected = self.table.selectionModel().selectedRows()
        return selected[0].data(Qt.ItemDataRole.UserRole) if selected else None

    def _show_selection(self, *_):
        row = self._selected_row()
        if row is None:
            self.selected_name.clear()
            self.details.setText('选择一条关卡查看资源状态。' if self.model.rowCount() else '')
            self.selected_path.clear()
        else:
            name = _level_name(row)
            code = row.get('code')
            self.selected_name.setText(f'{code} · {name}' if code and code != name else name)
            state = '关卡数据已安装' if row['available'] else '关卡数据未安装'
            preview = _preview_status(row)
            category = f"{row['category']} · 新增" if row['is_new'] else row['category']
            scene = row.get('scene')
            if scene is None:
                scene_status = '播放时查找原始场景'
            else:
                scene_status = '原始场景主包已安装' if scene['available'] else '原始场景主包未安装'
            self.details.setText(f'{category}\n{_chapter_label(row)}\n\n{state}\n{scene_status}\n{preview}')
            self.selected_path.setText(row['id'])
        self.preview_button.setEnabled(row is not None)
        self.tags_button.setVisible(bool(row and row['category'] in _INDICATOR_CATEGORIES))
        self.tags_button.setEnabled(bool(row and row['available']))
        self.tags_button.setText('导入赛季指标…' if row and row['category'] == '危机合约' else '配置作战指标…')
        self.replay_selection_changed.emit(row['id'] if row and row['available'] else None)

    def _request_tags(self):
        row = self._selected_row()
        if row and row['available'] and row['category'] in _INDICATOR_CATEGORIES:
            self.tags_requested.emit(row['id'], row.get('code') or _level_name(row))

    def _request_preview(self):
        row = self._selected_row()
        if row:
            self.preview_requested.emit(row['id'])

    def _open_index(self, index):
        row = index.data(Qt.ItemDataRole.UserRole)
        if row:
            self.preview_requested.emit(row['id'])


class LevelCatalogPage(PageController):
    def create_view(self):
        return LevelCatalogView()

    def __init__(self, window):
        self.root = None
        self._catalog = None
        self._metadata = None
        self._metadata_job = None
        self._tags_job = None
        self._tags_dialog = None
        self._applied_tags = {}
        self._preview_dialog = None
        self._map_job = None
        self._native_preloader = None
        super().__init__(window)

    def connect(self):
        self.window.tabs.currentChanged.connect(self._load_metadata)
        self.window.queue.settled.connect(self._metadata_settled)
        self.window.queue.settled.connect(self._tags_settled)
        self.view.tags_requested.connect(self._load_tags)
        self.view.preview_requested.connect(self._open_preview)
        from ..paths import resource_root

        project = resource_root() / 'scripts/level_preview/native_player'
        if (project / 'Godot.exe').is_file() and hasattr(self.window.services, 'cached_native_level_replay'):
            from .level_native_preview import NativeReplayPreloader

            self._native_preloader = NativeReplayPreloader(self.window, self.view, self._native_request, project)

    def set_root(self, root):
        root = Path(root).resolve()
        if root != self.root:
            self.root = root
            self._set_catalog(None)

    def scanned(self, snapshot, changes, catalog):
        self.data_loaded()

    def data_loaded(self):
        services = self.window.services
        root = value(services.installation, 'root')
        if root:
            self.set_root(root)
        levels = getattr(services, 'level_catalog', None)
        self._set_catalog(levels if levels and Path(levels['root']).resolve() == self.root else None)

    def _set_catalog(self, catalog):
        if catalog is self._catalog:
            return
        if self._identity(catalog) != self._identity(self._catalog):
            self._applied_tags.clear()
            if self._native_preloader is not None:
                self._native_preloader.cancel()
            if self._metadata_job is not None:
                self._metadata_job.token.cancel()
                self._metadata_job = None
            if self._tags_job is not None:
                self._tags_job.token.cancel()
                self._tags_job = None
            if self._tags_dialog is not None:
                self._tags_dialog.close()
            if self._preview_dialog is not None:
                self._preview_dialog.close()
            if self._map_job is not None:
                self._map_job.token.cancel()
            self._metadata = None
        self._catalog = catalog
        self._render()
        self._load_metadata()

    @staticmethod
    def _identity(catalog):
        return (catalog['root'], catalog['resource_version']) if catalog and catalog['levels'] else None

    def _render(self):
        catalog = self._catalog
        if catalog is not None:
            metadata = self._metadata or {}
            by_level = metadata.get('levels', {})
            chapters = metadata.get('chapters', {})
            clips = self._clips()
            catalog = {
                **catalog,
                'levels': [
                    {**self._with_metadata(row, by_level, chapters), 'preview_ready': row['id'] in clips}
                    for row in catalog['levels']
                ],
                'diagnostics': [*catalog['diagnostics'], *metadata.get('diagnostics', ())],
            }
        self.view.set_catalog(catalog)

    def _clips(self):
        identity = self._identity(self._catalog)
        find = getattr(self.window.services, 'level_preview_clips', None)
        return find(*identity) if identity is not None and find is not None else {}

    def _open_preview(self, path):
        if self._preview_dialog is not None:
            return
        if self._catalog is None:
            return
        row = next((item for item in self._catalog['levels'] if item['id'] == path), None)
        if row is None:
            return
        metadata = self._metadata['levels'].get(path, {}) if self._metadata else {}
        caption = ' · '.join(filter(None, (metadata.get('code'), metadata.get('name')))) or row['name']
        clip = self._clips().get(path)
        dialog = self._show_preview(clip, caption)
        if clip is not None:
            status = '原资源动画试渲染'
        elif row.get('map_image'):
            status = '游戏原图 · 关卡动画待适配'
            dialog.show_message('正在读取游戏原图…')
            self._load_map_image(path, dialog)
        elif row['available']:
            status = '关卡动画待适配'
            dialog.show_message('当前关卡还没有可播放动画或游戏原图。')
        else:
            status = '关卡资源未安装'
            dialog.show_message('请在游戏客户端下载关卡资源，然后重新扫描。')
        dialog.show_detail(status)
        if row['available']:
            info_job = self._load_preview_info(path, dialog, status)
            self._configure_replay(path, caption, dialog, info_job)

    def _native_request(self, path, caption=None):
        identity = self._identity(self._catalog)
        if identity is None:
            return None
        row = next((item for item in self._catalog['levels'] if item['id'] == path), None)
        if row is None or not row['available']:
            return None
        from .level_native_preview import NativeReplayRequest

        tags, archive = self._applied_tags.get(path, (None, None))
        return NativeReplayRequest(*identity, path, tuple(tags) if tags is not None else None,
                                   archive, caption or row['name'])

    def _apply_tags(self, path, ids, archive):
        self._applied_tags[path] = (ids, archive)
        if self._native_preloader is not None:
            self._native_preloader.timer.start()

    def _configure_replay(self, path, caption, dialog, info_job):
        load = getattr(self.window.services, 'load_level_replay', None)
        identity = self._identity(self._catalog)
        if identity is None or load is None:
            return
        native = self._native_preloader
        if native is not None and (request := self._native_request(path, caption)) is not None:
            native.attach(request, dialog, info_job)
            return
        from ..level_preview_server import LevelPreviewServer, missing_preview_runtime
        from ..paths import resource_root

        root, version = identity
        runtime = self.window.services.data_root / 'level-preview-runtime'
        player = resource_root() / 'scripts' / 'level_preview'
        server = None

        def play():
            if server is not None:
                dialog.toggle_replay()
                return
            if missing_preview_runtime(runtime):
                dialog.show_replay_status(f'缺少本机播放组件。配置目录为 {runtime}')
                return
            tags, archive = self._applied_tags.get(path, (None, None))
            try:
                lease = self.window.preview_cache.allocate('objects')
            except (OSError, ValueError) as error:
                dialog.show_replay_status(str(error))
                return
            dialog.replay_button.setEnabled(False)
            dialog.show_replay_status('正在准备游戏原场景、角色和波次…')
            if info_job is not None and info_job.status in ('排队中', '运行中'):
                info_job.token.cancel()
            shown = False

            def done(result):
                nonlocal server, shown
                if (job.token.cancelled or self._preview_dialog is not dialog or
                        self._identity(self._catalog) != identity):
                    return
                if result['level_id'] != path or result['resource_version'] != version:
                    raise ValueError('回放来源与当前关卡不匹配。')
                session = LevelPreviewServer(lease.path, player, runtime)
                try:
                    dialog.show_replay(session.url)
                except Exception:
                    session.close()
                    raise
                server = session
                shown = True
                dialog.show_replay_status(f"无部署出怪预览 · {result['spawns']} 次出怪 · {result['duration']:.1f} 秒")
                details = list(result.get('diagnostics') or ())
                if 'seed' in result:
                    details.insert(0, f"本次回放的随机种子为 {result['seed']}")
                dialog.replay_status.setToolTip('\n'.join(details))

            def settled(completed):
                if completed is not job:
                    return
                self.window.queue.settled.disconnect(settled)
                lease.finish()
                if not shown:
                    lease.release()
                if self._preview_dialog is dialog:
                    dialog.replay_button.setEnabled(True)
                    if not shown:
                        reason = [line for line in job.last_error.strip().splitlines()
                                  if line and not line.startswith('诊断日志：')]
                        message = reason[-1] if reason else ''
                        message = message.removeprefix('RuntimeError: ').removeprefix('ValueError: ')
                        dialog.show_replay_status(message or '出怪预览暂不可用。')

            def close(*_):
                nonlocal server
                job.token.cancel()
                if server is not None:
                    server.close()
                    server = None
                lease.release()

            job = self.window.queue.submit('准备关卡出怪预览', lambda **kw: load(
                root, path, version, lease.path, caption=caption, tag_ids=tags, crisis_info_path=archive, **kw),
                done, show_in_tasks=False)
            self.window.queue.settled.connect(settled)
            dialog.finished.connect(close)

        dialog.replay_button.clicked.connect(play)
        dialog.replay_button.show()

    def _show_preview(self, path, caption):
        from PySide6.QtCore import Qt
        from .level_preview_dialog import LevelPreviewDialog

        dialog = LevelPreviewDialog(path, caption, self.view)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.window._track_dialog(dialog)
        self._preview_dialog = dialog

        def closed(*_):
            self._preview_dialog = None

        dialog.finished.connect(closed)
        dialog.open()
        return dialog

    def _load_map_image(self, path, dialog):
        identity = self._identity(self._catalog)
        load = getattr(self.window.services, 'load_level_map_preview', None)
        if identity is None or load is None:
            return
        root, version = identity
        try:
            lease = self.window.preview_cache.allocate('objects')
        except (OSError, ValueError) as error:
            dialog.show_message(str(error))
            return
        def done(result):
            if (job.token.cancelled or self.window._closing or self._identity(self._catalog) != identity
                    or self._preview_dialog is not dialog or result['resource_version'] != version):
                return
            media = Path(result['path']).resolve()
            if media.parent != lease.path or media.suffix != '.png' or not media.is_file():
                raise ValueError('原版地图图像未生成到预览目录。')
            dialog.show_media(media)

        def settled(completed):
            if completed is not job:
                return
            self.window.queue.settled.disconnect(settled)
            if self._map_job is job:
                self._map_job = None
            lease.finish()
            if job.status != '成功' and self._preview_dialog is dialog:
                dialog.show_message('读取游戏原图失败，请检查游戏资源后重试。')

        job = self.window.queue.submit('读取游戏原版地图', lambda **kw: load(root, path, version, lease.path, **kw),
                                       done, show_in_tasks=False)
        self._map_job = job
        self.window.queue.settled.connect(settled)
        dialog.finished.connect(lambda *_: job.token.cancel())
        dialog.finished.connect(lambda *_: lease.release())

    def _load_preview_info(self, path, dialog, status):
        load = getattr(self.window.services, 'load_level_preview_info', None)
        identity = self._identity(self._catalog)
        if load is None or identity is None:
            return
        root, version = identity

        def done(info):
            if self._preview_dialog is not dialog or info['resource_version'] != version:
                return
            rows, columns = info['map_size']
            size = f'地图 {rows}×{columns} · ' if rows and columns else ''
            dialog.show_detail(f"{status} · {size}{info['wave_count']} 波 · {info['route_count']} 条路线")

        job = self.window.queue.submit('读取关卡脚本', lambda **kw: load(root, path, version, **kw),
                                       done, show_in_tasks=False)
        dialog.finished.connect(lambda *_: job.token.cancel())
        return job

    @staticmethod
    def _with_metadata(row, by_level, chapters):
        folder = row['id'].rsplit('/', 1)[0]
        while folder:
            chapter = chapters.get(folder + '/')
            if chapter:
                row = {**row, **chapter}
                break
            folder = folder.rpartition('/')[0]
        exact = by_level.get(row['id'], {})
        return {**row, **{key: value for key, value in exact.items() if value}}

    def _load_metadata(self, *_):
        if self.window.tabs.currentWidget() is not self.view:
            return
        identity = self._identity(self._catalog)
        load = getattr(self.window.services, 'load_level_metadata', None)
        if identity is None or load is None or self._metadata is not None or self._metadata_job is not None:
            return
        root, version = identity

        def done(result):
            if self._metadata_job is job and result['resource_version'] == version:
                self._metadata = result
                self._render()

        job = self.window.queue.submit('读取关卡名称和章节', lambda **kw: load(root, version, **kw),
                                       done, show_in_tasks=False)
        self._metadata_job = job

    def _metadata_settled(self, job):
        if job is not self._metadata_job:
            return
        self._metadata_job = None
        if job.status != '成功' and self._catalog is not None and not self.window._closing:
            self._metadata = {'levels': {}, 'diagnostics': ['章节与关卡名称读取失败，当前显示资源代号。']}
            self._render()

    def _load_tags(self, path, caption):
        identity = self._identity(self._catalog)
        load = getattr(self.window.services, 'load_level_tag_options', None)
        if identity is None or load is None or self._tags_job is not None or self._tags_dialog is not None:
            return
        root, version = identity
        options = {}
        if path.startswith('gamedata/levels/obt/crisis/'):
            from PySide6.QtWidgets import QFileDialog

            archive, _ = QFileDialog.getOpenFileName(self.window, '导入危机合约赛季指标', '',
                                                     '指标数据 (*.json)')
            if not archive:
                return
            options['crisis_info_path'] = archive

        def done(result):
            if self._tags_job is not job or result['resource_version'] != version:
                return
            if not result['tags']:
                self.window.show_status('；'.join(result['diagnostics']) or '此关卡没有作战指标。')
                return
            from PySide6.QtCore import Qt
            from .level_tags_dialog import LevelTagsDialog

            archive = options.get('crisis_info_path')
            previous = self._applied_tags.get(path)
            if previous is not None and previous[1] == archive:
                selected = set(previous[0])
                result = {**result, 'tags': [{**tag, 'selected': tag['id'] in selected} for tag in result['tags']]}
            dialog = LevelTagsDialog(result, caption, self.view)
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            self._tags_dialog = dialog
            dialog.variant_applied.connect(lambda ids: self._apply_tags(path, ids, archive))
            dialog.finished.connect(lambda *_: setattr(self, '_tags_dialog', None))
            dialog.open()

        job = self.window.queue.submit('读取关卡作战指标', lambda **kw: load(root, path, version, **options, **kw),
                                       done, show_in_tasks=False)
        self._tags_job = job

    def _tags_settled(self, job):
        if job is self._tags_job:
            self._tags_job = None

    def save_state(self):
        return self.view.save_state()

    def restore_state(self, state):
        self.view.restore_state(state)
