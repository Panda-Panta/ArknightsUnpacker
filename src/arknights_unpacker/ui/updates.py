from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import Signal, Qt, QSignalBlocker
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QTableView, QPushButton, QAbstractItemView, QLineEdit, QCheckBox, QMenu, QFrame,
    QStackedWidget)
from .models import RecordsModel, value, size_text, time_text, STATUS, selected_records, is_resource_record
from ..library.classifications import category_labels


class UpdatesView(QWidget):
    extract_requested = Signal(list)
    images_requested = Signal(list)
    objects_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.snapshot = None
        self.changes = None
        self.hours = 24.0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        summary_panel = QFrame()
        summary_panel.setProperty('role', 'surface')
        summary_layout = QHBoxLayout(summary_panel)
        summary_layout.setContentsMargins(14, 12, 14, 12)
        summary_title = QLabel('扫描与对照')
        summary_title.setProperty('role', 'sectionTitle')
        summary_layout.addWidget(summary_title, 0, Qt.AlignmentFlag.AlignTop)
        self.summary = QLabel()
        self.summary.setObjectName('updatesSummary')
        self.summary.setWordWrap(True)
        self.summary.setProperty('muted', True)
        summary_layout.addWidget(self.summary, 1)
        layout.addWidget(summary_panel)
        row = QHBoxLayout()
        row.addWidget(QLabel('显示范围'))
        self.mode = QComboBox()
        self.mode.setObjectName('updateScope')
        self.mode.addItems(['最近写入', '相对文件基线变化', '任一命中', '两者交集'])
        self.mode.setCurrentIndex(2)
        self.mode.setToolTip('任一命中：最近写入或相对基线有变化；两者交集：同时满足两种条件。')
        self.mode.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.mode)
        self.search = QLineEdit()
        self.search.setObjectName('updatesSearch')
        self.search.setPlaceholderText('搜索文件名、路径或用途')
        self.search.setAccessibleName('搜索更新记录')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        row.addWidget(self.search, 1)
        self.ab_only = QCheckBox('仅 .ab')
        self.ab_only.setObjectName('updatesAbOnly')
        self.ab_only.toggled.connect(self.refresh)
        row.addWidget(self.ab_only)
        layout.addLayout(row)
        filters = QHBoxLayout()
        filters.addWidget(QLabel('文件类型'))
        self.file_type = QComboBox()
        self.file_type.setObjectName('updatesFileType')
        self.file_type.setAccessibleName('更新记录文件类型')
        self.file_type.setToolTip('按目录用途筛选，例如剧情插图、剧情背景或干员头像。')
        self.file_type.addItem('全部类型', None)
        for category in category_labels():
            self.file_type.addItem(category, category)
        self.file_type.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.file_type)
        self.exclude_deleted = QCheckBox('排除已删除文件')
        self.exclude_deleted.setObjectName('updatesExcludeDeleted')
        self.exclude_deleted.setChecked(True)
        self.exclude_deleted.toggled.connect(self.refresh)
        filters.addWidget(self.exclude_deleted)
        filters.addStretch()
        layout.addLayout(filters)
        records_header = QHBoxLayout()
        records_title = QLabel('文件记录')
        records_title.setProperty('role', 'sectionTitle')
        records_header.addWidget(records_title)
        records_header.addStretch()
        self.result_count = QLabel()
        self.result_count.setProperty('muted', True)
        records_header.addWidget(self.result_count)
        layout.addLayout(records_header)
        self.model = RecordsModel([('文件路径', 'path'), ('目录用途', 'category'), ('检测状态', 'status'),
                                   ('大小', lambda r: size_text(r.get('size'))), ('修改时间', 'mtime'),
                                   ('首次观测', 'first_seen'), ('检测依据', 'evidence')], self)
        self.table = QTableView()
        self.table.setObjectName('updatesTable')
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((390, 110, 140, 85, 210, 210)):
            self.table.setColumnWidth(column, width)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.selectionModel().selectionChanged.connect(self.update_selection)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.context_menu)
        self.table.doubleClicked.connect(self.show_objects)
        self.results = QStackedWidget()
        self.results.addWidget(self.table)
        self.empty_panel = QFrame()
        self.empty_panel.setProperty('role', 'surface')
        empty_layout = QVBoxLayout(self.empty_panel)
        empty_layout.setContentsMargins(24, 22, 24, 22)
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
        empty_layout.addStretch()
        self.results.addWidget(self.empty_panel)
        layout.addWidget(self.results, 1)
        self.diagnostics = QLabel()
        self.diagnostics.setWordWrap(True)
        self.diagnostics.setProperty('notice', 'warning')
        layout.addWidget(self.diagnostics)
        self.selection_count = QLabel()
        self.selection_count.setProperty('muted', True)
        self.selection_count.setWordWrap(True)
        layout.addWidget(self.selection_count)
        actions = QHBoxLayout()
        self.select_all_button = QPushButton('全选当前结果')
        self.select_all_button.clicked.connect(self.table.selectAll)
        actions.addWidget(self.select_all_button)
        self.clear_selection_button = QPushButton('取消选择')
        self.clear_selection_button.clicked.connect(self.table.clearSelection)
        actions.addWidget(self.clear_selection_button)
        actions.addStretch()
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
        layout.addLayout(actions)
        self.refresh()

    def set_data(self, snapshot, changes, hours=24):
        self.snapshot, self.changes, self.hours = snapshot, changes, hours
        selected = self.file_type.currentData()
        categories = set(category_labels())
        records = list(value(snapshot, 'files', []))
        for change in value(changes, 'changes', []):
            records.extend(record for record in (value(change, 'before'), value(change, 'after')) if record)
        categories.update(value(record, 'category', '未知用途') for record in records)
        if selected:
            categories.add(selected)
        with QSignalBlocker(self.file_type):
            self.file_type.clear()
            self.file_type.addItem('全部类型', None)
            for category in sorted(categories):
                self.file_type.addItem(category, category)
            self.file_type.setCurrentIndex(max(0, self.file_type.findData(selected)))
        self.refresh()

    def refresh(self, *_):
        snapshot = self.snapshot
        if snapshot is None:
            self.summary.setText('尚未扫描。选择游戏目录后扫描，也可在下次启动时读取已保存的结果。')
            self.summary.setToolTip('')
            self.model.replace([])
            self.update_selection()
            self.empty_title.setText('还没有更新记录')
            self.empty.setText('先扫描游戏目录，再查看最近写入和相对上次文件基线的变化。首次完整扫描会建立基线。')
            self.clear_filters_button.hide()
            self.diagnostics.hide()
            self.results.setCurrentWidget(self.empty_panel)
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
            if self.exclude_deleted.isChecked() and kind == 'removed':
                continue
            if self.file_type.currentData() and category != self.file_type.currentData():
                continue
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
        self.diagnostics.setText('\n'.join(diagnostics[:6]))
        self.diagnostics.setVisible(bool(diagnostics))
        self.clear_filters_button.hide()
        if rows:
            self.results.setCurrentWidget(self.table)
        else:
            self.results.setCurrentWidget(self.empty_panel)
            if keys:
                self.empty_title.setText('没有匹配的更新记录')
                self.empty.setText('筛选后没有记录。尝试调整文件类型、关键词或“仅 .ab”；需要查看删除记录时，取消勾选“排除已删除文件”。')
                self.clear_filters_button.show()
            elif not baseline and self.mode.currentIndex() in (1, 3):
                self.empty_title.setText('尚无可比较的文件基线')
                self.empty.setText('当前范围没有记录。首次扫描只记录文件现状，可切换为“最近写入”或“任一命中”；后续完整扫描会与基线对照。')
            else:
                self.empty_title.setText('暂时没有更新记录')
                self.empty.setText('当前范围没有记录。可切换“显示范围”，或调整顶部“扫描选项”中的时间窗口后重新扫描。此列表反映本机文件观测，不代表实际发布时间。')

    def clear_filters(self):
        with QSignalBlocker(self.search), QSignalBlocker(self.ab_only), QSignalBlocker(self.file_type), QSignalBlocker(self.exclude_deleted):
            self.search.clear()
            self.ab_only.setChecked(False)
            self.file_type.setCurrentIndex(0)
            self.exclude_deleted.setChecked(True)
        self.refresh()

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
        extractable = len(self.selected_paths())
        self.result_count.setText(f'{self.model.rowCount():,} 条记录')
        self.selection_count.setText(f'已选 {selected:,} 项 · 可导图 {images:,} 包 · 可解包 {extractable:,} 项')
        self.images_button.setEnabled(images > 0)
        self.extract_button.setEnabled(extractable > 0)
        self.select_all_button.setEnabled(self.model.rowCount() > 0)
        self.clear_selection_button.setEnabled(selected > 0)

    def extract_selected(self):
        paths = self.selected_paths()
        if paths:
            self.extract_requested.emit(paths)

    def extract_images(self):
        paths = self.selected_paths(images_only=True)
        if paths:
            self.images_requested.emit(paths)

    def show_objects(self, index):
        row = self.model.data(index, Qt.ItemDataRole.UserRole)
        if self.snapshot is None or not row or not row.get('exists') or not is_resource_record(row):
            return
        root = Path(value(self.snapshot, 'root', '')).resolve()
        path = (root / row['path']).resolve()
        if path.is_relative_to(root):
            self.objects_requested.emit(str(path))

    def context_menu(self, point):
        menu = QMenu(self)
        images = menu.addAction('导出所选包内图片', self.extract_images)
        images.setEnabled(self.images_button.isEnabled())
        extract = menu.addAction('解包所选文件…', self.extract_selected)
        extract.setEnabled(self.extract_button.isEnabled())
        menu.addSeparator()
        menu.addAction('全选当前结果', self.table.selectAll)
        menu.exec(self.table.viewport().mapToGlobal(point))
