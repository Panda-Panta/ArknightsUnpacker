from __future__ import annotations

from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QAbstractTableModel, Qt
from ..library.preview_types import source_preview_type


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
    """Columns contain a label, display getter and optional raw sort getter."""
    def __init__(self, columns, parent=None):
        super().__init__(parent)
        self.columns = columns
        self.rows = []
        self._sort_column = None
        self._sort_order = Qt.SortOrder.AscendingOrder

    def replace(self, rows):
        rows = list(rows)
        if self._sort_column is not None:
            rows = [row for _, row in self._ordered(enumerate(rows), self._sort_column, self._sort_order)]
        self.beginResetModel()
        self.rows = rows
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
        self._sort_column, self._sort_order = column, order
        self.layoutAboutToBeChanged.emit()
        persistent = self.persistentIndexList()
        # Retain each old row's identity, even when two records compare equal.
        indexed = self._ordered(enumerate(self.rows), column, order)
        positions = {old_row: new_row for new_row, (old_row, _) in enumerate(indexed)}
        self.rows = [row for _, row in indexed]
        self.changePersistentIndexList(persistent, [self.index(positions[index.row()], index.column()) for index in persistent])
        self.layoutChanged.emit()

    def _ordered(self, indexed, column, order):
        specification = self.columns[column]
        getter = specification[2] if len(specification) > 2 else specification[1]
        known, unknown = [], []
        for position, row in indexed:
            result = getter(row) if callable(getter) else value(row, getter)
            if result is None:
                unknown.append((position, row))
            else:
                # Numeric domains retain their precision, including integer ns
                # and byte counts whose formatted labels may compare equally.
                key = (0, result) if isinstance(result, (int, float)) else (1, str(result).casefold())
                known.append((key, position, row))
        known.sort(key=lambda item: item[0], reverse=order == Qt.SortOrder.DescendingOrder)
        # Unknown observations remain last in either direction, and Python's
        # stable sort preserves the identity/order of records with equal keys.
        return [(position, row) for _, position, row in known] + unknown


def selected_records(table):
    return [table.model().rows[i.row()] for i in table.selectionModel().selectedRows()]


def is_resource_record(record):
    return value(record, 'layer') in ('base', 'hot') or Path(value(record, 'path', '')).suffix.casefold() in {
        '.ab', '.bin', '.usm', '.idx', '.bytes', '.acb', '.awb'} or source_preview_type(value(record, 'path', '')) is not None
