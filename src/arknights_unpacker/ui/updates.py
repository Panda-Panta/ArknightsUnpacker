from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QTableView, QPushButton, QAbstractItemView, QLineEdit, QCheckBox, QMenu)
from .models import RecordsModel, value, size_text, time_text, STATUS, selected_records, is_resource_record


class UpdatesView(QWidget):
    extract_requested = Signal(list)
    images_requested = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.snapshot = None
        self.changes = None
        self.hours = 24.0
        layout = QVBoxLayout(self)
        self.summary = QLabel('尚未扫描。选择游戏目录后扫描，或在下次启动时读取已保存的结果。')
        self.summary.setObjectName('updatesSummary')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        row = QHBoxLayout()
        row.addWidget(QLabel('显示范围'))
        self.mode = QComboBox()
        self.mode.setObjectName('updateScope')
        self.mode.addItems(['最近写入', '相对文件基线变化', '任一命中', '两者交集'])
        self.mode.setCurrentIndex(2)
        self.mode.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.mode)
        self.search = QLineEdit()
        self.search.setObjectName('updatesSearch')
        self.search.setPlaceholderText('搜索文件名、路径或用途')
        self.search.textChanged.connect(self.refresh)
        row.addWidget(self.search, 1)
        self.ab_only = QCheckBox('仅 .ab')
        self.ab_only.setObjectName('updatesAbOnly')
        self.ab_only.toggled.connect(self.refresh)
        row.addWidget(self.ab_only)
        layout.addLayout(row)
        self.model = RecordsModel([('文件路径', 'path'), ('目录用途', 'category'), ('检测状态', 'status'),
                                   ('大小', lambda r: size_text(r.get('size'))), ('修改时间', 'mtime'),
                                   ('首次观测', 'first_seen'), ('检测依据', 'evidence')], self)
        self.table = QTableView()
        self.table.setObjectName('updatesTable')
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((390, 110, 140, 85, 210, 210)):
            self.table.setColumnWidth(column, width)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.selectionModel().selectionChanged.connect(self.update_selection)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.context_menu)
        layout.addWidget(self.table)
        actions = QHBoxLayout()
        select_all = QPushButton('全选当前结果')
        select_all.clicked.connect(self.table.selectAll)
        actions.addWidget(select_all)
        self.images_button = QPushButton('导出所选包内图片')
        self.images_button.setObjectName('exportUpdateImages')
        self.images_button.setProperty('primary', True)
        self.images_button.setToolTip('批量导出原始像素 PNG；单图平铺，多图按包建目录。')
        self.images_button.clicked.connect(self.extract_images)
        actions.addWidget(self.images_button)
        self.extract_button = QPushButton('解包所选文件…')
        self.extract_button.setToolTip('使用设置中的资源类型和解包方式。')
        self.extract_button.clicked.connect(self.extract_selected)
        actions.addWidget(self.extract_button)
        actions.addStretch()
        self.selection_count = QLabel()
        actions.addWidget(self.selection_count)
        layout.addLayout(actions)
        self.empty = QLabel('')
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        self.update_selection()

    def set_data(self, snapshot, changes, hours=24):
        self.snapshot, self.changes, self.hours = snapshot, changes, hours
        self.refresh()

    def refresh(self, *_):
        snapshot = self.snapshot
        if snapshot is None:
            self.model.replace([])
            self.update_selection()
            return
        complete = value(snapshot, 'complete', False)
        baseline = value(self.changes, 'baseline_id')
        self.summary.setText(('完整扫描' if complete else '部分扫描：存在错误，未推进完整基线') +
            f'　·　最近 {self.hours:g} 小时（本机写入时间）　·　' +
            ('已有文件基线' if baseline else '首次发现，历史未知；不认定为本次新增') +
            f'\n扫描时间：{time_text(value(snapshot, "finished_at"))}。文件变化来自两次观测比较，实际发布时间未知。')
        self.summary.setToolTip(f'对照文件快照：{baseline or "无"}；当前快照：{value(snapshot, "snapshot_id", "")}')
        files = {value(f, 'path'): f for f in value(snapshot, 'files', [])}
        changed = {value(c, 'path'): c for c in value(self.changes, 'changes', [])}
        end = value(snapshot, 'started_at', 0)
        recent = {p for p, f in files.items() if end - self.hours * 3600 <= value(f, 'mtime_ns', 0) / 1e9 <= end}
        changed_keys = set(changed) if baseline else set()
        keys = [recent, changed_keys, recent | changed_keys, recent & changed_keys][self.mode.currentIndex()]
        rows = []
        query = self.search.text().strip().casefold()
        for path in sorted(keys):
            change = changed.get(path)
            record = files.get(path) or value(change, 'before')
            kind = value(change, 'kind', 'unchanged') if baseline else 'first_seen'
            status = STATUS.get(kind, kind)
            category = value(record, 'category', '未知用途')
            if self.ab_only.isChecked() and Path(path).suffix.casefold() != '.ab':
                continue
            if query and query not in f'{path} {category} {status}'.casefold():
                continue
            rows.append({'path': path, 'status': status, 'category': category,
                         'size': value(record, 'size', 0),
                         'mtime': time_text(value(record, 'mtime_ns', 0) / 1e9),
                         'first_seen': time_text(value(record, 'first_seen_at')),
                         'evidence': ('本机修改时间' if path in recent else '') + ('；两次完整观测比较' if path in changed_keys else ''),
                         'exists': path in files, 'layer': value(record, 'layer', 'other')})
        self.model.replace(rows)
        self.update_selection()
        diagnostics = value(snapshot, 'errors', []) + value(self.changes, 'diagnostics', [])
        self.empty.setText(('当前范围没有记录。' if not rows else f'{len(rows):,} 条记录。') + ('\n' + '\n'.join(diagnostics[:6]) if diagnostics else ''))

    def selected_paths(self, *, images_only=False):
        if self.snapshot is None:
            return []
        root = Path(value(self.snapshot, 'root', '')).resolve()
        paths = []
        for row in selected_records(self.table):
            if not row.get('exists') or not is_resource_record(row):
                continue
            path = (root / row['path']).resolve()
            if not path.is_relative_to(root):
                continue
            if images_only and path.suffix.casefold() in {'.usm', '.idx', '.acb', '.awb'}:
                continue
            paths.append(str(path))
        return list(dict.fromkeys(paths))

    def update_selection(self, *_):
        selected = len(selected_records(self.table))
        images = len(self.selected_paths(images_only=True))
        self.selection_count.setText(f'已选 {selected:,} 项 · 可导图 {images:,} 包')
        self.images_button.setEnabled(images > 0)
        self.extract_button.setEnabled(bool(self.selected_paths()))

    def extract_selected(self):
        paths = self.selected_paths()
        if paths:
            self.extract_requested.emit(paths)

    def extract_images(self):
        paths = self.selected_paths(images_only=True)
        if paths:
            self.images_requested.emit(paths)

    def context_menu(self, point):
        menu = QMenu(self)
        images = menu.addAction('导出所选包内图片', self.extract_images)
        images.setEnabled(self.images_button.isEnabled())
        extract = menu.addAction('解包所选文件…', self.extract_selected)
        extract.setEnabled(self.extract_button.isEnabled())
        menu.addSeparator()
        menu.addAction('全选当前结果', self.table.selectAll)
        menu.exec(self.table.viewport().mapToGlobal(point))
