from __future__ import annotations

from pathlib import Path
import json
from PySide6.QtCore import Qt, Signal, QDir
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTreeView,
    QTableView, QFileSystemModel, QLineEdit, QComboBox, QCheckBox, QLabel, QTextBrowser,
    QPushButton, QMenu, QHeaderView, QAbstractItemView)
from .models import RecordsModel, value, size_text, time_text, STATUS, selected_records, is_resource_record


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
        self._directory_rows = {}
        layout = QVBoxLayout(self)
        tools = QHBoxLayout()
        self.layer = QComboBox()
        self.layer.addItems(['原始文件 · 全部来源', '当前生效资源'])
        self.layer.setObjectName('resourceLayer')
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索名称、路径或用途')
        self.search.setObjectName('resourceSearch')
        self.ab_only = QCheckBox('仅 .ab')
        self.ab_only.setObjectName('abOnly')
        self.recursive = QCheckBox('包含子目录')
        self.recursive.setChecked(False)
        for control in (self.layer, self.search, self.ab_only, self.recursive):
            tools.addWidget(control)
        layout.addLayout(tools)
        split = QSplitter()
        self.fs = DirectoryModel(self)
        self.fs.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot)
        self.fs.setReadOnly(True)
        self.tree = QTreeView()
        self.tree.setObjectName('directoryTree')
        self.tree.setModel(self.fs)
        for column in (1, 2, 3):
            self.tree.hideColumn(column)
        self.tree.setHeaderHidden(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.directory_context_menu)
        split.addWidget(self.tree)
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        crumb_row = QHBoxLayout()
        up = QPushButton('↑ 上一级')
        up.clicked.connect(self.go_up)
        self.breadcrumb = QLineEdit()
        self.breadcrumb.setReadOnly(True)
        crumb_row.addWidget(up)
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
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((185, 145, 55, 75, 165, 155)):
            self.table.setColumnWidth(column, width)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.context_menu)
        self.table.doubleClicked.connect(lambda _: self.show_objects())
        self.table.selectionModel().selectionChanged.connect(self.update_selection)
        center_layout.addWidget(self.table, 1)
        self.count = QLabel('选择游戏目录后自动建立文件索引。')
        center_layout.addWidget(self.count)
        split.addWidget(center)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        self.details = QTextBrowser()
        self.details.setMinimumWidth(220)
        self.details.setHtml('<h3>资源详情</h3><p>选择一项，查看用途、来源与校验状态。</p>')
        right_layout.addWidget(self.details, 1)
        self.objects_button = QPushButton('查看内部对象／预览')
        self.objects_button.clicked.connect(self.show_objects)
        right_layout.addWidget(self.objects_button)
        self.extract_button = QPushButton('将所选加入解包队列')
        self.extract_button.setProperty('primary', True)
        self.extract_button.clicked.connect(self.extract_selected)
        right_layout.addWidget(self.extract_button)
        select_all = QPushButton('全选当前筛选结果')
        select_all.clicked.connect(self.table.selectAll)
        right_layout.addWidget(select_all)
        split.addWidget(right)
        split.setSizes([230, 780, 280])
        layout.addWidget(split, 1)
        self.tree.clicked.connect(self.select_directory)
        self.search.textChanged.connect(self.refresh)
        self.layer.currentIndexChanged.connect(self.refresh)
        self.ab_only.toggled.connect(self.refresh)
        self.recursive.toggled.connect(self.refresh)

    def set_root(self, root):
        self.root = Path(root)
        self.folder = ''
        self.fs.setRootPath(str(self.root))
        self.tree.setRootIndex(self.fs.index(str(self.root)))
        self.refresh()

    def set_data(self, snapshot, changes=None, catalog=None):
        self.snapshot, self.catalog = snapshot, catalog
        self.changes = {value(c, 'path'): value(c, 'kind') for c in value(changes, 'changes', [])}
        self._directory_rows = {}
        for record in value(snapshot, 'files', []):
            row = {k: value(record, k) for k in ('path', 'size', 'mtime_ns', 'category', 'layer', 'sha256', 'hash_status', 'first_seen_at', 'error')}
            row['status'] = self.changes.get(row['path'], 'unchanged' if value(changes, 'baseline_id') else 'first_seen')
            self._directory_rows.setdefault(Path(row['path']).parent.as_posix(), []).append(row)
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
        self.breadcrumb.setText(str(self.root / self.folder))
        if self.layer.currentIndex() == 1:
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
        elif self.recursive.isChecked():
            rows = [r for group in self._directory_rows.values() for r in group]
        else:
            rows = self._directory_rows.get(self.folder or '.', [])
        query = self.search.text().casefold().strip()
        prefix = self.folder.rstrip('/') + '/' if self.folder else ''
        visible = []
        for row in rows:
            path = row['path'].replace('\\', '/')
            if prefix and not path.startswith(prefix):
                continue
            if self.ab_only.isChecked() and Path(path).suffix.casefold() != '.ab':
                continue
            if query and query not in (path + ' ' + row.get('category', '')).casefold():
                continue
            visible.append(row)
        self.model.replace(visible)
        self.update_selection()

    def selected_paths(self):
        return [r.get('source_path') or str(self.root / r['path']) for r in selected_records(self.table)
                if (r.get('source_path') or self.layer.currentIndex() == 0) and is_resource_record(r)]

    def update_selection(self, *_):
        selected = selected_records(self.table)
        self.count.setText(f'当前结果 {self.model.rowCount():,} 项　·　已选 {len(selected):,} 项')
        self.extract_button.setEnabled(bool(self.selected_paths()))
        self.objects_button.setEnabled(len(selected) == 1 and bool(self.selected_paths()))
        if selected:
            from html import escape
            row = selected[0]
            text = '<h3>' + escape(Path(row['path']).name) + '</h3>'
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
        menu.addAction('加入解包队列', self.extract_selected)
        menu.addAction('查看内部对象／预览', self.show_objects)
        menu.addAction('全选当前筛选结果', self.table.selectAll)
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
