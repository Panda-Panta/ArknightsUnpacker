from __future__ import annotations

from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QAbstractTableModel, Qt


def value(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def size_text(size):
    n = float(size or 0)
    for unit in ('B', 'KiB', 'MiB', 'GiB'):
        if n < 1024 or unit == 'GiB':
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024


def time_text(timestamp):
    if not timestamp:
        return '—'
    return datetime.fromtimestamp(timestamp).astimezone().strftime('%Y-%m-%d %H:%M:%S %z')


STATUS = {'added': '新增', 'new': '新增', 'modified': '已修改', 'changed': '已修改',
          'removed': '已删除', 'metadata_only': '仅元数据变化', 'unchanged': '元数据未变',
          'unknown': '历史未知', 'first_seen': '首次发现，历史未知', 'available': '可用',
          'verified': '已验证', 'missing': '未安装', 'unverified': '未验证'}
STATUS.update({'current': '当前候选（未核实内容）', 'form_added': '新增形态', 'stale': '仅有旧版',
               'metadata_unchanged': '元数据未变', 'error': '读取失败', 'unstable': '读取期间变化'})


class RecordsModel(QAbstractTableModel):
    """A row stores its domain record; no per-cell widget allocation."""
    def __init__(self, columns, parent=None):
        super().__init__(parent)
        self.columns = columns
        self.rows = []

    def replace(self, rows):
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.rows)

    def columnCount(self, parent=None):
        return len(self.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        row = self.rows[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return row
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            getter = self.columns[index.column()][1]
            result = getter(row) if callable(getter) else value(row, getter, '')
            return str(result if result is not None else '—')
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.columns[section][0]
        return super().headerData(section, orientation, role)

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        if not 0 <= column < len(self.columns):
            return
        getter = self.columns[column][1]
        self.layoutAboutToBeChanged.emit()
        persistent = self.persistentIndexList()
        # Retain each old row's identity, even when two records compare equal.
        indexed = list(enumerate(self.rows))
        indexed.sort(key=lambda pair: str(getter(pair[1]) if callable(getter) else value(pair[1], getter, '')).casefold(),
                     reverse=order == Qt.SortOrder.DescendingOrder)
        positions = {old_row: new_row for new_row, (old_row, _) in enumerate(indexed)}
        self.rows = [row for _, row in indexed]
        self.changePersistentIndexList(persistent, [self.index(positions[index.row()], index.column()) for index in persistent])
        self.layoutChanged.emit()


def selected_records(table):
    return [table.model().rows[i.row()] for i in table.selectionModel().selectedRows()]


def is_resource_record(record):
    return value(record, 'layer') in ('base', 'hot') or Path(value(record, 'path', '')).suffix.casefold() in {
        '.ab', '.bin', '.usm', '.idx', '.bytes', '.acb', '.awb'}
