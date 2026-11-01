from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import Qt, Signal, QDir, QSignalBlocker
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTreeView,
    QTableView, QFileSystemModel, QLineEdit, QComboBox, QCheckBox, QLabel, QTextBrowser,
    QPushButton, QMenu, QHeaderView, QAbstractItemView, QFrame, QStackedWidget)
from .models import RecordsModel, value, size_text, time_text, STATUS, selected_records, is_resource_record
from ..library.classifications import category_labels


def category_description(path, category):
    try:
        from arknights_unpacker.library.classifications import describe
        return str(describe(path))
    except (ImportError, TypeError):
        return f'{category}。用途标签用于定位资源；实际解包方式由文件签名和内部对象决定。'


class DirectoryModel(QFileSystemModel):
    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        original = super().data(index, role)
        if index.column() != 0 or role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return original
        path = self.filePath(index).replace('\\', '/')
        root = self.rootPath().replace('\\', '/')
        relative = path[len(root):].strip('/') if path.startswith(root) else path
        try:
            from arknights_unpacker.library.classifications import classify
            layer = 'other'
            for marker, source in (('streamingassets/ab/windows/', 'base'), ('persistentdata/bundles/', 'hot')):
                found = path.lower().find(marker)
                if found >= 0:
                    relative, layer = path[found + len(marker):], source
                    break
            category = classify(relative, layer)
        except (ImportError, KeyError):
            category = '尚未分类'
        if role == Qt.ItemDataRole.ToolTipRole:
            return path + '\n' + category_description(relative, category)
        return f'{original}  ·  {category}'


class ExplorerView(QWidget):
    extract_requested = Signal(list)
    objects_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.root = Path('.')
        self.snapshot = None
        self.catalog = None
        self.changes = {}
        self.folder = ''
        self._root_selected = False
        self._directory_rows = {}
        self._resource_rows = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        tools = QHBoxLayout()
        tools.setSpacing(10)
        self.layer = QComboBox()
        self.layer.addItems(['原始文件 · 全部来源', '当前生效资源'])
        self.layer.setObjectName('resourceLayer')
        self.layer.setToolTip('原始文件按实际目录浏览；当前生效资源按扫描得到的来源选择结果浏览。')
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索名称、路径或用途')
        self.search.setObjectName('resourceSearch')
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName('搜索资源')
        self.ab_only = QCheckBox('仅 .ab')
        self.ab_only.setObjectName('abOnly')
        self.recursive = QCheckBox('包含子目录')
        self.recursive.setChecked(False)
        tools.addWidget(self.layer)
        tools.addWidget(self.search, 1)
        tools.addWidget(self.ab_only)
        tools.addWidget(self.recursive)
        layout.addLayout(tools)
        filters = QHBoxLayout()
        filters.addWidget(QLabel('文件类型'))
        self.file_type = QComboBox()
        self.file_type.setObjectName('resourceFileType')
        self.file_type.setAccessibleName('资源文件类型')
        self.file_type.setToolTip('按目录用途筛选，例如剧情插图、剧情背景或干员头像。')
        self.file_type.addItem('全部类型', None)
        for category in category_labels():
            self.file_type.addItem(category, category)
        filters.addWidget(self.file_type)
        filters.addStretch()
        layout.addLayout(filters)
        self.splitter = QSplitter()
        self.splitter.setObjectName('resourceSplitter')
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(8)
        left = QWidget()
        left.setMinimumWidth(160)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        directory_title = QLabel('目录')
        directory_title.setProperty('role', 'sectionTitle')
        left_layout.addWidget(directory_title)
        directory_hint = QLabel('选择目录，查看其中的文件')
        directory_hint.setProperty('muted', True)
        directory_hint.setWordWrap(True)
        left_layout.addWidget(directory_hint)
        self.fs = DirectoryModel(self)
        self.fs.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot)
        self.fs.setReadOnly(True)
        self.tree = QTreeView()
        self.tree.setObjectName('directoryTree')
        self.tree.setModel(self.fs)
        for column in (1, 2, 3):
            self.tree.hideColumn(column)
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(16)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.directory_context_menu)
        self.directory_stack = QStackedWidget()
        self.directory_stack.addWidget(self.tree)
        self.directory_empty = QFrame()
        self.directory_empty.setProperty('role', 'surface')
        directory_empty_layout = QVBoxLayout(self.directory_empty)
        directory_empty_layout.setContentsMargins(14, 14, 14, 14)
        directory_empty_text = QLabel('尚未选择游戏目录。\n\n在上方选择目录后，这里会显示目录结构。')
        directory_empty_text.setProperty('muted', True)
        directory_empty_text.setWordWrap(True)
        directory_empty_layout.addWidget(directory_empty_text)
        directory_empty_layout.addStretch()
        self.directory_stack.addWidget(self.directory_empty)
        self.directory_stack.setCurrentWidget(self.directory_empty)
        left_layout.addWidget(self.directory_stack, 1)
        self.splitter.addWidget(left)
        center = QWidget()
        center.setMinimumWidth(280)
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        files_title = QLabel('文件')
        files_title.setProperty('role', 'sectionTitle')
        center_layout.addWidget(files_title)
        crumb_row = QHBoxLayout()
        self.up_button = QPushButton('↑ 上一级')
        self.up_button.setToolTip('返回当前目录的上一级')
        self.up_button.clicked.connect(self.go_up)
        self.breadcrumb = QLineEdit()
        self.breadcrumb.setReadOnly(True)
        self.breadcrumb.setPlaceholderText('选择游戏目录后显示路径')
        self.breadcrumb.setAccessibleName('当前资源目录')
        crumb_row.addWidget(self.up_button)
        crumb_row.addWidget(self.breadcrumb, 1)
        center_layout.addLayout(crumb_row)
        self.model = RecordsModel([
            ('名称', lambda r: Path(r['path']).name), ('目录用途', 'category'),
            ('类型', lambda r: Path(r['path']).suffix.upper() or '无扩展名'),
            ('大小', lambda r: size_text(r['size'])),
            ('修改时间', lambda r: time_text(r.get('mtime_ns', 0) / 1e9)),
            ('状态／来源', lambda r: STATUS.get(r.get('status'), r.get('status', '')) + ' · ' + r.get('layer', ''))], self)
        self.table = QTableView()
        self.table.setObjectName('resourceTable')
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((185, 145, 55, 75, 165, 155)):
            self.table.setColumnWidth(column, width)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.context_menu)
        self.table.doubleClicked.connect(lambda _: self.show_objects())
        self.table.selectionModel().selectionChanged.connect(self.update_selection)
        self.results = QStackedWidget()
        self.results.addWidget(self.table)
        self.empty_panel = QFrame()
        self.empty_panel.setProperty('role', 'surface')
        empty_layout = QVBoxLayout(self.empty_panel)
        empty_layout.setContentsMargins(22, 22, 22, 22)
        empty_layout.addStretch()
        self.empty_title = QLabel()
        self.empty_title.setProperty('role', 'emptyTitle')
        self.empty_title.setWordWrap(True)
        empty_layout.addWidget(self.empty_title)
        self.empty = QLabel()
        self.empty.setProperty('muted', True)
        self.empty.setWordWrap(True)
        empty_layout.addWidget(self.empty)
        self.clear_filters_button = QPushButton('清除筛选')
        self.clear_filters_button.clicked.connect(self.clear_filters)
        empty_layout.addWidget(self.clear_filters_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.include_subfolders_button = QPushButton('包含子目录')
        self.include_subfolders_button.clicked.connect(lambda: self.recursive.setChecked(True))
        empty_layout.addWidget(self.include_subfolders_button, 0, Qt.AlignmentFlag.AlignLeft)
        empty_layout.addStretch()
        self.results.addWidget(self.empty_panel)
        center_layout.addWidget(self.results, 1)
        self.count = QLabel()
        self.count.setProperty('muted', True)
        self.count.setWordWrap(True)
        center_layout.addWidget(self.count)
        self.splitter.addWidget(center)
        right = QWidget()
        right.setMinimumWidth(210)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        details_title = QLabel('资源详情')
        details_title.setProperty('role', 'sectionTitle')
        right_layout.addWidget(details_title)
        self.details = QTextBrowser()
        self.details.setMinimumWidth(0)
        right_layout.addWidget(self.details, 1)
        self.objects_button = QPushButton('查看内部对象／预览')
        self.objects_button.clicked.connect(self.show_objects)
        right_layout.addWidget(self.objects_button)
        self.extract_button = QPushButton('加入解包队列')
        self.extract_button.setToolTip('将所选的可解包文件加入任务队列。')
        self.extract_button.setProperty('primary', True)
        self.extract_button.clicked.connect(self.extract_selected)
        right_layout.addWidget(self.extract_button)
        self.select_all_button = QPushButton('全选当前筛选结果')
        self.select_all_button.clicked.connect(self.table.selectAll)
        right_layout.addWidget(self.select_all_button)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([215, 650, 250])
        layout.addWidget(self.splitter, 1)
        self.tree.clicked.connect(self.select_directory)
        self.search.textChanged.connect(self.refresh)
        self.layer.currentIndexChanged.connect(self.refresh)
        self.ab_only.toggled.connect(self.refresh)
        self.recursive.toggled.connect(self.refresh)
        self.file_type.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def set_root(self, root):
        self.root = Path(root)
        self._resource_rows = None
        self.folder = ''
        self._root_selected = True
        self.fs.setRootPath(str(self.root))
        self.tree.setRootIndex(self.fs.index(str(self.root)))
        self.directory_stack.setCurrentWidget(self.tree)
        self.refresh()

    def set_data(self, snapshot, changes=None, catalog=None):
        self.snapshot, self.catalog = snapshot, catalog
        self._resource_rows = None
        self.changes = {value(c, 'path'): value(c, 'kind') for c in value(changes, 'changes', [])}
        selected = self.file_type.currentData()
        categories = set(category_labels())
        self._directory_rows = {}
        for record in value(snapshot, 'files', []):
            row = {k: value(record, k) for k in ('path', 'size', 'mtime_ns', 'category', 'layer', 'sha256', 'hash_status', 'first_seen_at', 'error')}
            row['status'] = self.changes.get(row['path'], 'unchanged' if value(changes, 'baseline_id') else 'first_seen')
            self._directory_rows.setdefault(Path(row['path']).parent.as_posix(), []).append(row)
            categories.add(row['category'])
        categories.update(value(resource, 'category', '未知用途') for resource in value(catalog, 'resources', {}).values())
        if selected:
            categories.add(selected)
        with QSignalBlocker(self.file_type):
            self.file_type.clear()
            self.file_type.addItem('全部类型', None)
            for category in sorted(categories):
                self.file_type.addItem(category, category)
            self.file_type.setCurrentIndex(max(0, self.file_type.findData(selected)))
        self.refresh()

    def select_directory(self, index):
        path = Path(self.fs.filePath(index))
        try:
            self.folder = path.relative_to(self.root).as_posix()
        except ValueError:
            self.folder = ''
        if self.folder == '.':
            self.folder = ''
        self.refresh()

    def go_up(self):
        self.folder = Path(self.folder).parent.as_posix() if self.folder else ''
        if self.folder == '.':
            self.folder = ''
        self.refresh()

    def refresh(self, *_):
        category = self.file_type.currentData()
        global_filter = category is not None
        if global_filter:
            scope = '全部生效资源' if self.layer.currentIndex() == 1 else '全部已扫描资源'
            self.breadcrumb.setText('全库筛选 · ' + scope)
            self.breadcrumb.setToolTip(str(self.root) if self._root_selected else '选择游戏目录并扫描后显示全库结果。')
        else:
            self.breadcrumb.setText(str(self.root / self.folder) if self._root_selected else '')
            self.breadcrumb.setToolTip(self.breadcrumb.text())
        self.tree.setEnabled(not global_filter)
        self.recursive.setEnabled(not global_filter)
        self.up_button.setEnabled(bool(self.folder) and not global_filter)
        if self.layer.currentIndex() == 1:
            rows = self._current_resource_rows()
        elif global_filter or self.recursive.isChecked():
            rows = [r for group in self._directory_rows.values() for r in group]
        else:
            rows = self._directory_rows.get(self.folder or '.', [])
        query = self.search.text().casefold().strip()
        prefix = self.folder.rstrip('/') + '/' if self.folder and not global_filter else ''
        visible = []
        scope_count = 0
        for row in rows:
            path = row['path'].replace('\\', '/')
            if prefix and not path.startswith(prefix):
                continue
            scope_count += 1
            if global_filter and row.get('category') != category:
                continue
            if self.ab_only.isChecked() and Path(path).suffix.casefold() != '.ab':
                continue
            if query and query not in (path + ' ' + row.get('category', '')).casefold():
                continue
            visible.append(row)
        self.model.replace(visible)
        self.update_selection()
        self.update_empty_state(scope_count)

    def _current_resource_rows(self):
        # Catalog/root changes invalidate these display rows. Search, category
        # and directory filters can then reuse paths instead of converting the
        # entire active manifest again for every keystroke.
        if self._resource_rows is None:
            rows = []
            for resource in value(self.catalog, 'resources', {}).values():
                path = value(resource, 'path')
                try:
                    relative = Path(path).relative_to(self.root).as_posix() if path else value(resource, 'logical_key', '')
                except ValueError:
                    relative = str(path)
                rows.append({'path': relative, 'size': value(resource, 'size', 0), 'category': value(resource, 'category', '未知用途'),
                             'layer': value(resource, 'layer', ''), 'status': value(resource, 'status', 'unknown'),
                             'logical_key': value(resource, 'logical_key'), 'source_path': path, 'mtime_ns': 0})
            self._resource_rows = rows
        return self._resource_rows

    def clear_filters(self):
        with QSignalBlocker(self.search), QSignalBlocker(self.ab_only), QSignalBlocker(self.file_type):
            self.search.clear()
            self.ab_only.setChecked(False)
            self.file_type.setCurrentIndex(0)
        self.refresh()

    def update_empty_state(self, scope_count):
        self.clear_filters_button.hide()
        self.include_subfolders_button.hide()
        if self.model.rowCount():
            self.results.setCurrentWidget(self.table)
            return
        self.results.setCurrentWidget(self.empty_panel)
        global_filter = self.file_type.currentData() is not None
        if self.snapshot is None and (self.layer.currentIndex() == 0 or self.catalog is None):
            self.empty_title.setText('尚未扫描资源')
            self.empty.setText('在上方选择游戏目录并扫描，完成后即可按目录浏览、预览和解包。')
        elif scope_count:
            self.empty_title.setText('没有匹配的文件')
            self.empty.setText('全库资源没有命中筛选条件。尝试调整文件类型或关键词，或清除筛选恢复原目录。' if global_filter
                               else '当前目录有文件，但没有命中筛选条件。尝试调整文件类型或关键词，或清除筛选。')
            self.clear_filters_button.show()
        elif self.layer.currentIndex() == 1:
            self.empty_title.setText('当前来源没有生效资源' if global_filter else '当前范围没有生效资源')
            self.empty.setText('切换到“原始文件 · 全部来源”查看已扫描的文件，或重新扫描更新资源。' if global_filter
                               else '可选择其他目录，或切换到“原始文件 · 全部来源”查看已扫描的文件。')
        elif global_filter:
            self.empty_title.setText('全库没有已索引文件')
            self.empty.setText('重新扫描以更新资源索引，或清除筛选恢复原目录。')
            self.clear_filters_button.show()
        else:
            prefix = self.folder.rstrip('/') + '/' if self.folder else ''
            has_descendants = any(
                group and folder != (self.folder or '.') and (not prefix or folder.startswith(prefix))
                for folder, group in self._directory_rows.items())
            self.empty_title.setText('当前目录没有已索引文件')
            if not self.recursive.isChecked() and has_descendants:
                self.empty.setText('文件位于子目录中。选择左侧子目录，或开启“包含子目录”。')
                self.include_subfolders_button.show()
            else:
                self.empty.setText('选择其他目录，或重新扫描以更新文件索引。')

    def selected_paths(self):
        return [r.get('source_path') or str(self.root / r['path']) for r in selected_records(self.table)
                if (r.get('source_path') or self.layer.currentIndex() == 0) and is_resource_record(r)]

    def update_selection(self, *_):
        selected = selected_records(self.table)
        paths = self.selected_paths()
        self.count.setText(f'当前结果 {self.model.rowCount():,} 项 · 已选 {len(selected):,} 项 · 可解包 {len(paths):,} 项')
        self.extract_button.setEnabled(bool(paths))
        self.objects_button.setEnabled(len(selected) == 1 and bool(paths))
        self.select_all_button.setEnabled(self.model.rowCount() > 0)
        if selected:
            from html import escape
            row = selected[0]
            text = '<h3>' + escape(Path(row['path']).name) + '</h3>'
            if len(selected) > 1:
                text += f'<p>已选 {len(selected):,} 项，下方显示其中一个文件的详情。</p>'
            text += '<p>' + escape(category_description(row['path'], row.get('category', '未知用途'))) + '</p>'
            labels = {'path': '路径', 'layer': '来源层', 'status': '状态', 'logical_key': '逻辑资源', 'sha256': 'SHA-256', 'hash_status': '校验依据', 'error': '诊断'}
            for key, label in labels.items():
                if row.get(key):
                    display = row[key]
                    if key in ('status', 'hash_status'):
                        display = STATUS.get(display, {'metadata_only': '仅记录元数据'}.get(display, display))
                    if key == 'layer':
                        display = {'base': '初始资源', 'hot': '热更资源', 'other': '其他游戏文件'}.get(display, display)
                    text += f'<p><b>{label}</b><br>{escape(str(display))}</p>'
            if row.get('first_seen_at'):
                text += '<p><b>首次观测</b><br>' + time_text(row['first_seen_at']) + '</p>'
            self.details.setHtml(text)
        else:
            self.details.setHtml('<h3>选择一个文件</h3><p>查看用途、来源与校验状态。</p>'
                                 '<p>按住 Ctrl 或 Shift 可选择多个文件，一起加入解包队列。</p>')

    def extract_selected(self):
        paths = self.selected_paths()
        if paths:
            self.extract_requested.emit(paths)

    def show_objects(self):
        paths = self.selected_paths()
        if len(paths) == 1:
            self.objects_requested.emit(paths[0])

    def context_menu(self, point):
        menu = QMenu(self)
        extract = menu.addAction('加入解包队列', self.extract_selected)
        extract.setEnabled(self.extract_button.isEnabled())
        objects = menu.addAction('查看内部对象／预览', self.show_objects)
        objects.setEnabled(self.objects_button.isEnabled())
        select_all = menu.addAction('全选当前筛选结果', self.table.selectAll)
        select_all.setEnabled(self.select_all_button.isEnabled())
        menu.exec(self.table.viewport().mapToGlobal(point))

    def directory_context_menu(self, point):
        index = self.tree.indexAt(point)
        if not index.isValid():
            return
        self.tree.setCurrentIndex(index)
        self.select_directory(index)
        menu = QMenu(self)
        menu.addAction('显示目录中的全部文件（含子目录）', lambda: self.recursive.setChecked(True))
        menu.addAction('将整个目录加入解包队列（递归）', self.extract_directory)
        menu.exec(self.tree.viewport().mapToGlobal(point))

    def extract_directory(self):
        prefix = self.folder.rstrip('/') + '/' if self.folder else ''
        paths = [str(self.root / row['path']) for rows in self._directory_rows.values() for row in rows
                 if (not prefix or row['path'].startswith(prefix)) and is_resource_record(row)]
        if paths:
            self.extract_requested.emit(paths)
