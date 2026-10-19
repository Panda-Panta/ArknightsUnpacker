from __future__ import annotations
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QTableView, QPushButton, QAbstractItemView
from .models import RecordsModel, value, time_text, STATUS, selected_records, is_resource_record


class UpdatesView(QWidget):
    extract_requested = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.snapshot = None
        self.changes = None
        self.hours = 24.0
        layout = QVBoxLayout(self)
        self.summary = QLabel('尚未扫描。最近写入依据本机修改时间；业务新增需要完整历史数据基线。')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        row = QHBoxLayout()
        row.addWidget(QLabel('显示范围'))
        self.mode = QComboBox()
        self.mode.addItems(['最近写入', '相对文件基线变化', '任一命中', '两者交集'])
        self.mode.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.mode)
        row.addStretch()
        extract = QPushButton('解包选中的现存文件')
        extract.clicked.connect(self.extract_selected)
        row.addWidget(extract)
        layout.addLayout(row)
        self.model = RecordsModel([('文件路径', 'path'), ('检测状态', 'status'), ('修改时间', 'mtime'),
                                   ('首次观测', 'first_seen'), ('检测依据', 'evidence')], self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 430)
        self.table.setColumnWidth(2, 220)
        self.table.setColumnWidth(3, 220)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)
        self.empty = QLabel('')
        layout.addWidget(self.empty)

    def set_data(self, snapshot, changes, hours=24):
        self.snapshot, self.changes, self.hours = snapshot, changes, hours
        self.refresh()

    def refresh(self, *_):
        snapshot = self.snapshot
        if snapshot is None:
            return
        complete = value(snapshot, 'complete', False)
        baseline = value(self.changes, 'baseline_id')
        self.summary.setText(('完整扫描' if complete else '部分扫描：存在错误，未推进完整基线') +
            f'　·　最近 {self.hours:g} 小时（本机写入时间）　·　' +
            (f'文件基线 {baseline}' if baseline else '首次发现，历史未知；不认定为本次新增') +
            '\n内容变化是两次观测间发现的变化，实际发布时间未知。')
        files = {value(f, 'path'): f for f in value(snapshot, 'files', [])}
        changed = {value(c, 'path'): c for c in value(self.changes, 'changes', [])}
        end = value(snapshot, 'started_at', 0)
        recent = {p for p, f in files.items() if end - self.hours * 3600 <= value(f, 'mtime_ns', 0) / 1e9 <= end}
        changed_keys = set(changed) if baseline else set()
        keys = [recent, changed_keys, recent | changed_keys, recent & changed_keys][self.mode.currentIndex()]
        rows = []
        for path in sorted(keys):
            change = changed.get(path)
            record = files.get(path) or value(change, 'before')
            kind = value(change, 'kind', 'unchanged') if baseline else 'first_seen'
            rows.append({'path': path, 'status': STATUS.get(kind, kind),
                         'mtime': time_text(value(record, 'mtime_ns', 0) / 1e9),
                         'first_seen': time_text(value(record, 'first_seen_at')),
                         'evidence': ('本机修改时间' if path in recent else '') + ('；两次完整观测比较' if path in changed_keys else ''),
                         'exists': path in files, 'layer': value(record, 'layer', 'other')})
        self.model.replace(rows)
        diagnostics = value(snapshot, 'errors', []) + value(self.changes, 'diagnostics', [])
        self.empty.setText(('当前范围没有记录。' if not rows else f'{len(rows):,} 条记录。') + ('\n' + '\n'.join(diagnostics[:6]) if diagnostics else ''))

    def extract_selected(self):
        from pathlib import Path
        paths = [str(Path(value(self.snapshot, 'root', '')) / r['path']) for r in selected_records(self.table) if r['exists'] and is_resource_record(r)]
        if paths:
            self.extract_requested.emit(paths)
