"""Compact navigation for the existing native profile detail browser."""
from collections import Counter
from html import escape

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from ..contracts import ModuleProfile, OperatorProfile, ReportDocument
from ..reports.model import semantic_blocks
from .profile_html import PROFILE_ANCHOR_PREFIX, profile_html


class ProfileNavigation(QWidget):
    def __init__(self, browser, parent=None):
        super().__init__(parent)
        self.browser = browser
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(QLabel('目录'))
        self.sections = QComboBox()
        self.sections.setObjectName('profileSections')
        self.sections.setAccessibleName('当前资料目录')
        self.sections.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.sections.setMinimumContentsLength(8)
        self.sections.setMinimumWidth(0)
        self.sections.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.sections.view().setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.sections.setMaxVisibleItems(24)
        self.section_choice = self.sections
        layout.addWidget(self.sections, 1)
        self.back_to_top = QPushButton('返回顶部')
        self.back_to_top.setObjectName('profileBackToTop')
        self.back_to_top.setToolTip('返回当前资料顶部')
        self.top_button = self.back_to_top
        layout.addWidget(self.back_to_top)
        self.sections.currentIndexChanged.connect(self._navigate)
        self.back_to_top.clicked.connect(self._to_top)
        self.clear()

    def set_profile(self, profile):
        self.clear()
        if profile is None:
            return
        document = ReportDocument(title=profile.name,
            operators=[profile] if isinstance(profile, OperatorProfile) else [],
            modules=[profile] if isinstance(profile, ModuleProfile) else [])
        blocks = semantic_blocks(document)
        labels = []
        for block in blocks:
            title = block.title
            if block.kind.startswith('module-') and block.kind != 'module-info' and block.entry_title:
                title = f'{block.entry_title} / {title}'
            if block.group and block.group != title and not title.startswith(block.group + ' · '):
                title = f'{block.group} · {title}'
            labels.append(title)
        totals, occurrences = Counter(labels), Counter()
        # Render the same final blocks used for the directory, including any
        # optional sections; anchors never incorporate names or game IDs.
        self.browser.setHtml(profile_html(profile, blocks=blocks))
        with QSignalBlocker(self.sections):
            self.sections.addItem('跳转章节…', None)
            for index, title in enumerate(labels, 1):
                occurrences[title] += 1
                label = f'{title}（{occurrences[title]}/{totals[title]}）' if totals[title] > 1 else title
                self.sections.addItem(label, f'{PROFILE_ANCHOR_PREFIX}{index}')
                self.sections.setItemData(self.sections.count() - 1, '<span>' + escape(label) + '</span>', Qt.ItemDataRole.ToolTipRole)
            self.sections.setCurrentIndex(0)
        self.sections.setEnabled(bool(blocks))
        self.back_to_top.setEnabled(bool(blocks))

    def clear(self):
        with QSignalBlocker(self.sections):
            self.sections.clear()
        self.sections.setEnabled(False)
        self.back_to_top.setEnabled(False)

    def _navigate(self, *_):
        anchor = self.sections.currentData()
        if anchor:
            self.browser.scrollToAnchor(anchor)

    def _to_top(self):
        self.browser.verticalScrollBar().setValue(self.browser.verticalScrollBar().minimum())
        self.browser.horizontalScrollBar().setValue(self.browser.horizontalScrollBar().minimum())
        self.sections.setCurrentIndex(0)
