"""Browse the active game's level index and open verified previews."""
import re

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QSplitter, QTabBar, QTableView, QVBoxLayout, QWidget,
)

from .models import RecordsModel


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
