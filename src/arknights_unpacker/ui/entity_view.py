from __future__ import annotations
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QCheckBox, QPushButton, QSplitter, QTableView, QTextBrowser, QAbstractItemView, QComboBox
from arknights_unpacker.contracts import BuildSpec
from .models import RecordsModel, STATUS, selected_records, value
from .report_preview import profile_html, changes_html


PROFESSIONS = {'PIONEER': '先锋', 'WARRIOR': '近卫', 'TANK': '重装', 'SNIPER': '狙击',
               'CASTER': '术师', 'MEDIC': '医疗', 'SUPPORT': '辅助', 'SPECIAL': '特种'}


def rarity_text(row):
    rarity = row.get('rarity', '')
    if str(rarity).startswith('TIER_'):
        return str(rarity).split('_')[-1] + ' ★'
    return str(rarity)


class _ModuleRecordsModel(RecordsModel):
    """Module-only checks follow IDs while the visible records change."""
    checks_changed = Signal()

    def __init__(self, columns, parent=None):
        super().__init__(columns, parent)
        self.checked_ids = set()

    def _checkable(self, index):
        return (index.isValid() and index.column() == 0 and 0 <= index.row() < len(self.rows)
                and self.rows[index.row()].get('status') != 'removed')

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.CheckStateRole and self._checkable(index):
            return Qt.CheckState.Checked if str(self.rows[index.row()]['id']) in self.checked_ids else Qt.CheckState.Unchecked
        return super().data(index, role)

    def flags(self, index):
        flags = super().flags(index)
        return flags | Qt.ItemFlag.ItemIsUserCheckable if self._checkable(index) else flags

    def setData(self, index, state, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.CheckStateRole or not self._checkable(index):
            return False
        checked = set(self.checked_ids)
        entity_id = str(self.rows[index.row()]['id'])
        if state in (Qt.CheckState.Checked, Qt.CheckState.Checked.value):
            checked.add(entity_id)
        else:
            checked.discard(entity_id)
        self.set_checked_ids(checked)
        return True

    def set_checked_ids(self, ids):
        ids = set(ids)
        if ids == self.checked_ids:
            return
        self.checked_ids = ids
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, 0), [Qt.ItemDataRole.CheckStateRole])
        self.checks_changed.emit()


class EntityView(QWidget):
    load_requested = Signal()
    export_requested = Signal(list, bool)
    profile_requested = Signal(str, object)
    preview_requested = Signal(list)

    def __init__(self, kind='operators', parent=None):
        super().__init__(parent)
        self.kind = kind
        self.all_rows = []
        self.changes = None
        self.current_profile = None
        self._active_entity_id = None
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        load = QPushButton('解析核心数据')
        load.setProperty('primary', True)
        load.clicked.connect(self.load_requested)
        top.addWidget(load)
        self.summary = QLabel('尚未解析。选择游戏目录后，手动解析核心数据以建立资料快照。')
        self.summary.setWordWrap(True)
        top.addWidget(self.summary, 1)
        layout.addLayout(top)
        self.diagnostics = QLabel()
        self.diagnostics.setObjectName(kind + 'Diagnostics')
        self.diagnostics.setWordWrap(True)
        self.diagnostics.setProperty('notice', 'warning')
        self.diagnostics.hide()
        layout.addWidget(self.diagnostics)
        tools = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索干员名称、模组名称或稳定 ID')
        self.search.setObjectName(kind + 'Search')
        tools.addWidget(self.search, 1)
        self.only_changes = QCheckBox('只看新增／变化')
        tools.addWidget(self.only_changes)
        self.only_new = QCheckBox('只看新增')
        tools.addWidget(self.only_new)
        layout.addLayout(tools)
        if kind == 'modules':
            check_note = QLabel('勾选可跨筛选保留，合并导出／预览包含全部已勾选项；未勾选时使用选中行。')
            check_note.setProperty('muted', True)
            check_note.setWordWrap(True)
            layout.addWidget(check_note)
        split = QSplitter()
        columns = [('干员名称', lambda r: r.get('name', '') + (' · 未确认可获取' if r.get('obtainable') is False else '')),
                   ('星级', rarity_text), ('职业', lambda r: PROFESSIONS.get(r.get('profession'), r.get('profession', ''))),
                   ('状态', lambda r: STATUS.get(r.get('status'), r.get('status', '历史未知'))), ('ID', 'id')]
        if kind == 'modules':
            columns = [('模组名称', 'name'), ('所属干员', 'char_name'), ('类型', 'type'), ('状态', lambda r: STATUS.get(r.get('status'), r.get('status', '历史未知'))), ('ID', 'id')]
        self.model = (_ModuleRecordsModel if kind == 'modules' else RecordsModel)(columns, self)
        self.table = QTableView()
        self.table.setObjectName(kind + 'Table')
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate([190, 140, 65, 110] if kind == 'modules' else [190, 70, 80, 110]):
            self.table.setColumnWidth(column, width)
        self.table.selectionModel().selectionChanged.connect(self.select_profile)
        split.addWidget(self.table)
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(4, 0, 0, 0)
        options = QHBoxLayout()
        options.addWidget(QLabel('静态面板'))
        self.module_choice = QComboBox()
        self.module_choice.addItem('无模组 · 满级／满潜／满信赖', None)
        self.module_choice.currentIndexChanged.connect(self.select_profile)
        options.addWidget(self.module_choice, 1)
        if kind == 'operators':
            detail_layout.addLayout(options)
        else:
            self.module_choice.hide()
        self.details = QTextBrowser()
        self.details.setObjectName(kind + 'Details')
        self.details.setOpenExternalLinks(False)
        self.details.setHtml('<h2>资料预览</h2><p>解析完成后选择一项查看。资料中的诊断与来源将随导出保留。</p>')
        detail_layout.addWidget(self.details)
        split.addWidget(detail)
        split.setSizes([600, 680])
        layout.addWidget(split, 1)
        buttons = QHBoxLayout()
        self.select_all_button = QPushButton('全选当前筛选' if kind == 'modules' else '全选当前筛选结果')
        self.select_all_button.clicked.connect(self.check_all_visible if kind == 'modules' else self.table.selectAll)
        buttons.addWidget(self.select_all_button)
        if kind == 'modules':
            self.select_all_button.setToolTip('将当前筛选中可导出的模组加入勾选，保留其他筛选中已勾选的项。')
            self.clear_checked_button = QPushButton('清空勾选')
            self.clear_checked_button.setToolTip('清除全部勾选，包括当前筛选中隐藏的模组。')
            self.clear_checked_button.clicked.connect(lambda: self.model.set_checked_ids(set()))
            buttons.addWidget(self.clear_checked_button)
        self.preview_selected = QPushButton('预览模组合集' if kind == 'modules' else '预览所选资料')
        self.preview_selected.clicked.connect(self.request_preview)
        buttons.addWidget(self.preview_selected)
        self.export_selected = QPushButton('合并导出选中模组' if kind == 'modules' else '导出选中资料')
        self.export_selected.clicked.connect(lambda: self.request_export(False))
        buttons.addWidget(self.export_selected)
        self.export_new = QPushButton('合并导出本次新增' if kind == 'modules' else '一键导出本次新增')
        if kind == 'modules':
            scope_tip = '优先使用全部已勾选模组（包含被筛选隐藏的项）；未勾选时使用选中行。PNG 按设置排版，HTML 合并为一个页面。'
            self.export_selected.setToolTip(scope_tip)
            self.preview_selected.setToolTip(scope_tip)
            self.export_new.setToolTip('合并导出相对历史基线已确认新增的全部模组，不受当前搜索、筛选或勾选影响。')
        self.export_new.setEnabled(False)
        self.export_new.clicked.connect(lambda: self.request_export(True))
        buttons.addWidget(self.export_new)
        buttons.addStretch()
        self.count = QLabel('0 项')
        if kind == 'modules':
            self.model.checks_changed.connect(self.update_count)
        buttons.addWidget(self.count)
        layout.addLayout(buttons)
        self.search.textChanged.connect(self.refresh)
        self.only_changes.toggled.connect(self.refresh)
        self.only_new.toggled.connect(self.refresh)

    def set_rows(self, rows, changes=None, snapshot=None):
        if self.kind == 'modules':
            self.model.set_checked_ids(set())
        self.changes = changes
        comparable = bool(value(changes, 'baseline_id'))
        diagnostics = value(changes, 'diagnostics', [])
        status_map = {str(r.get('id', r.get('char_id', r.get('equip_id', '')))): r.get('status', r.get('kind', 'unknown')) for r in value(changes, self.kind, [])}
        self.all_rows = []
        for row in rows:
            row = dict(row)
            # Without a baseline a service's first inventory never becomes all-new.
            row['status'] = status_map.get(str(row['id']), 'unknown' if diagnostics else 'unchanged') if comparable else 'unknown'
            if row['status'] == 'current':
                row['status'] = 'unchanged'
            self.all_rows.append(row)
        known_ids = {str(r['id']) for r in self.all_rows}
        if comparable:
            for change in value(changes, self.kind, []):
                entity_id = str(change.get('id', change.get('char_id', change.get('equip_id', ''))))
                if entity_id not in known_ids:
                    self.all_rows.append({'id': entity_id, 'name': change.get('name', entity_id),
                                          'status': change.get('kind', 'removed')})
        self.export_new.setEnabled(comparable and any(r['status'] in ('added', 'new') for r in self.all_rows))
        locale = value(snapshot, 'locale', 'unknown')
        locale_label = {'unknown': '区服未知', 'zh_CN': '简体中文／国服（用户声明）'}.get(locale, str(locale))
        self.summary.setText(f'{len(rows):,} 项资料　·　版本 {value(snapshot, "version", "未知")}　·　{locale_label}　·　' +
                             (f'对照基线 {value(changes, "baseline_id")}' if comparable else '首次数据快照，历史未知。可导入同服完整历史基线。'))
        self.diagnostics.setText('\n'.join(str(message) for message in diagnostics))
        self.diagnostics.setVisible(bool(diagnostics))
        self.refresh()

    def clear_data(self):
        if self.kind == 'modules':
            self.model.set_checked_ids(set())
        self.all_rows = []
        self.changes = self.current_profile = None
        self._active_entity_id = None
        self.model.replace([])
        self.export_new.setEnabled(False)
        self.summary.setText('尚未解析。点击“解析核心数据”建立当前目录的资料快照。')
        self.diagnostics.clear()
        self.diagnostics.hide()
        self.details.setHtml('<h2>资料预览</h2><p>解析完成后选择一项查看。</p>')
        self.module_choice.blockSignals(True)
        self.module_choice.clear()
        self.module_choice.addItem('无模组 · 满级／满潜／满信赖', None)
        self.module_choice.blockSignals(False)
        if self.kind == 'modules':
            self.update_count()
        else:
            self.count.setText('0 项')

    def refresh(self, *_):
        query = self.search.text().strip().casefold()
        rows = [r for r in self.all_rows if not query or query in ' '.join(str(v) for v in r.values()).casefold()]
        if self.only_changes.isChecked():
            rows = [r for r in rows if r.get('status') not in ('unknown', 'unchanged', '')]
        if self.only_new.isChecked():
            rows = [r for r in rows if r.get('status') in ('added', 'new')]
        self.model.replace(rows)
        self.update_count()

    @property
    def checked_ids(self):
        return frozenset(self.model.checked_ids) if self.kind == 'modules' else frozenset()

    def check_all_visible(self):
        if self.kind == 'modules':
            visible = {str(row['id']) for row in self.model.rows if row.get('status') != 'removed'}
            self.model.set_checked_ids(self.checked_ids | visible)

    def update_count(self):
        selected = len(selected_records(self.table))
        text = f'{len(self.model.rows):,} 项　·　已选 {selected:,} 项'
        if self.kind == 'modules':
            hidden = len(self.checked_ids - {str(row['id']) for row in self.model.rows})
            text += f'　·　已勾选 {len(self.checked_ids):,} 项'
            if hidden:
                text += f'（隐藏 {hidden:,} 项）'
        self.count.setText(text)

    def select_profile(self, *_):
        rows = selected_records(self.table)
        self.update_count()
        if len(rows) == 1:
            entity_id = str(rows[0]['id'])
            if entity_id != self._active_entity_id:
                self._active_entity_id = entity_id
                self.current_profile = None
                self.module_choice.blockSignals(True)
                self.module_choice.clear()
                self.module_choice.addItem('无模组 · 满级／满潜／满信赖', None)
                self.module_choice.blockSignals(False)
                self.details.setPlainText('正在读取当前资料…')
            if rows[0].get('status') == 'removed':
                self.details.setHtml('<h2>已删除的资料</h2>' + self.diff_html(str(rows[0]['id'])))
                return
            spec = BuildSpec(module_id=self.module_choice.currentData())
            self.profile_requested.emit(entity_id, spec)

    def set_profile(self, profile):
        self.current_profile = profile
        entity_id = value(profile, 'char_id') if self.kind == 'operators' else value(profile, 'equip_id')
        self.details.setHtml(profile_html(profile) + self.diff_html(str(entity_id)))
        if self.kind == 'operators':
            current = self.module_choice.currentData()
            self.module_choice.blockSignals(True)
            self.module_choice.clear()
            self.module_choice.addItem('无模组 · 满级／满潜／满信赖', None)
            for module in value(profile, 'modules', []):
                module_id = module.get('equip_id', module.get('id'))
                if module_id:
                    self.module_choice.addItem(f'{module.get("name", module_id)} · 三级', module_id)
            index = self.module_choice.findData(current)
            self.module_choice.setCurrentIndex(max(index, 0))
            self.module_choice.blockSignals(False)

    def diff_html(self, entity_id):
        return changes_html(self.changes, self.kind, entity_id)

    def request_export(self, only_new):
        if only_new:
            if not value(self.changes, 'baseline_id'):
                return
            ids = [str(r['id']) for r in self.all_rows if r['status'] in ('added', 'new')]
        else:
            ids = self.chosen_ids()
        if ids:
            self.export_requested.emit(ids, only_new)

    def request_preview(self):
        ids = self.chosen_ids()
        if ids:
            self.preview_requested.emit(ids)

    def chosen_ids(self):
        checked = self.checked_ids
        rows = self.all_rows if checked else selected_records(self.table)
        return [str(row['id']) for row in rows if row.get('status') != 'removed'
                and (not checked or str(row['id']) in checked)]
