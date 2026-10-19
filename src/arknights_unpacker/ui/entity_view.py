from __future__ import annotations
from PySide6.QtCore import Signal
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
        self.diagnostics.setStyleSheet('color: #785223; background: #fff4dd; padding: 8px;')
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
        split = QSplitter()
        columns = [('干员名称', lambda r: r.get('name', '') + (' · 未确认可获取' if r.get('obtainable') is False else '')),
                   ('星级', rarity_text), ('职业', lambda r: PROFESSIONS.get(r.get('profession'), r.get('profession', ''))),
                   ('状态', lambda r: STATUS.get(r.get('status'), r.get('status', '历史未知'))), ('ID', 'id')]
        if kind == 'modules':
            columns = [('模组名称', 'name'), ('所属干员', 'char_name'), ('类型', 'type'), ('状态', lambda r: STATUS.get(r.get('status'), r.get('status', '历史未知'))), ('ID', 'id')]
        self.model = RecordsModel(columns, self)
        self.table = QTableView()
        self.table.setObjectName(kind + 'Table')
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
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
        self.details.setOpenExternalLinks(False)
        self.details.setHtml('<h2>资料预览</h2><p>解析完成后选择一项查看。资料中的诊断与来源将随导出保留。</p>')
        detail_layout.addWidget(self.details)
        split.addWidget(detail)
        split.setSizes([600, 680])
        layout.addWidget(split, 1)
        buttons = QHBoxLayout()
        select = QPushButton('全选当前筛选结果')
        select.clicked.connect(self.table.selectAll)
        buttons.addWidget(select)
        self.preview_selected = QPushButton('预览所选资料')
        self.preview_selected.clicked.connect(self.request_preview)
        buttons.addWidget(self.preview_selected)
        self.export_selected = QPushButton('导出选中资料')
        self.export_selected.clicked.connect(lambda: self.request_export(False))
        buttons.addWidget(self.export_selected)
        self.export_new = QPushButton('一键导出本次新增')
        self.export_new.setEnabled(False)
        self.export_new.clicked.connect(lambda: self.request_export(True))
        buttons.addWidget(self.export_new)
        buttons.addStretch()
        self.count = QLabel('0 项')
        buttons.addWidget(self.count)
        layout.addLayout(buttons)
        self.search.textChanged.connect(self.refresh)
        self.only_changes.toggled.connect(self.refresh)
        self.only_new.toggled.connect(self.refresh)

    def set_rows(self, rows, changes=None, snapshot=None):
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
        self.count.setText('0 项')

    def refresh(self, *_):
        query = self.search.text().strip().casefold()
        rows = [r for r in self.all_rows if not query or query in ' '.join(str(v) for v in r.values()).casefold()]
        if self.only_changes.isChecked():
            rows = [r for r in rows if r.get('status') not in ('unknown', 'unchanged', '')]
        if self.only_new.isChecked():
            rows = [r for r in rows if r.get('status') in ('added', 'new')]
        self.model.replace(rows)
        self.count.setText(f'{len(rows):,} 项　·　已选 0 项')

    def select_profile(self, *_):
        rows = selected_records(self.table)
        self.count.setText(f'{len(self.model.rows):,} 项　·　已选 {len(rows):,} 项')
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
            ids = [str(r['id']) for r in selected_records(self.table) if r.get('status') != 'removed']
        if ids:
            self.export_requested.emit(ids, only_new)

    def request_preview(self):
        ids = [str(r['id']) for r in selected_records(self.table) if r.get('status') != 'removed']
        if ids:
            self.preview_requested.emit(ids)
