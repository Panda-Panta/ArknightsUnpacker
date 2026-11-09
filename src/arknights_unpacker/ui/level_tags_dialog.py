"""Edit a level's client-defined modifiers and apply supported script changes."""
from collections import defaultdict

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QDialogButtonBox, QGroupBox, QLabel,
    QPushButton, QRadioButton, QScrollArea, QVBoxLayout, QWidget,
)

from ..extraction.level_variants import apply_level_tags


class LevelTagsDialog(QDialog):
    variant_applied = Signal(list)

    def __init__(self, source, caption, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'{caption} · 作战指标')
        self.resize(620, 660)
        self.tags = source['tags']
        self.graph = source.get('graph')
        self.level = source['level']
        self.buttons = {}
        self.groups = []
        self.variant = None

        layout = QVBoxLayout(self)
        self.score = QLabel()
        layout.addWidget(self.score)
        if self.graph is not None:
            rules = QLabel('指标须通过所选节点连到赛季起点。关键节点解锁进度由游戏记录。')
            rules.setWordWrap(True)
            layout.addWidget(rules)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        options = QWidget()
        options_layout = QVBoxLayout(options)
        scroll.setWidget(options)
        layout.addWidget(scroll, 1)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        apply = QPushButton('应用到关卡脚本')
        apply.setProperty('primary', True)
        controls.addButton(apply, QDialogButtonBox.ButtonRole.ApplyRole)
        controls.rejected.connect(self.reject)
        apply.clicked.connect(self._apply)
        layout.addWidget(controls)

        alternatives = defaultdict(list)
        for tag in self.tags:
            if tag['group']:
                alternatives[tag['group']].append(tag)
            else:
                button = QCheckBox()
                self._setup_button(button, tag)
                button.setEnabled(not tag['required'])
                options_layout.addWidget(button)
        for index, choices in enumerate(alternatives.values(), 1):
            required = any(tag['required'] for tag in choices)
            box = QGroupBox(f'互斥组 {index} · ' + ('必选一项' if required else '最多一项'))
            group_layout = QVBoxLayout(box)
            group = QButtonGroup(self)
            self.groups.append(group)
            for tag in choices:
                button = QRadioButton()
                group.addButton(button)
                self._setup_button(button, tag)
                group_layout.addWidget(button)
            if not required:
                none = QRadioButton('不选')
                group.addButton(none)
                none.setChecked(not any(tag['selected'] for tag in choices))
                group_layout.addWidget(none)
            options_layout.addWidget(box)
        options_layout.addStretch(1)
        self._apply()

    def _setup_button(self, button, tag):
        button.setText(f"{tag['name']}  ·  {tag['score']} 分")
        button.setToolTip(tag['description'])
        button.setChecked(tag['selected'])
        self.buttons[tag['id']] = button
        button.toggled.connect(self._refresh_score)

    def _selected(self):
        return [tag for tag in self.tags if self.buttons[tag['id']].isChecked()]

    def _refresh_score(self, *_):
        self._show_selection_score(self._selected())
        self.status.setText('选择已变更。应用后会重新生成受支持的关卡脚本。')

    def _show_selection_score(self, selected):
        text = f'已选 {len(selected)} 项'
        if self.graph is None:
            text += f" · {sum(tag['score'] for tag in selected)} 分"
        self.score.setText(text)

    def _apply(self):
        selected = self._selected()
        self._show_selection_score(selected)
        try:
            self.variant = apply_level_tags(self.level, self.tags, [tag['id'] for tag in selected], graph=self.graph)
        except ValueError as error:
            self.status.setText(str(error))
            return
        result = self.variant
        self.variant_applied.emit(result['selected_ids'])
        changes = result['changes']
        self.status.setText(
            f"脚本启用 {changes['enabled_actions']} 个动作，停用 {changes['disabled_actions']} 个动作，"
            f"替换 {changes['replaced_actions']} 个敌人动作，禁部署 {changes['forbidden_tiles']} 格。"
            f"{len(result['unapplied'])} 个效果尚待适配。"
        )
