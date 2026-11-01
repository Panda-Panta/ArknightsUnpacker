"""The detail-page directory targets real Qt rich-text sections in place."""
from copy import deepcopy
from html.parser import HTMLParser

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QTextBrowser, QVBoxLayout, QWidget

from arknights_unpacker.contracts import OperatorProfile, ReportDocument, as_jsonable
from arknights_unpacker.reports.model import semantic_blocks
from arknights_unpacker.ui.report_preview import profile_html


class Anchors(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.names = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.names.extend(value for key, value in attrs if key == 'name')


def long_profile():
    return OperatorProfile('char_navigation', '目录验收干员',
        summary={'profession': 'SNIPER', 'phase': 2, 'level': 90},
        trait='优先攻击空中单位',
        attributes=[{'key': 'atk', 'label': '攻击', 'value': 657}],
        skills=[{'index': index, 'id': f'skill_{index}', 'name': f'当前技能{index}',
                 'description': ('当前技能完整内容。' * 200) + f'技能终点{index}'} for index in (1, 2, 3)],
        talents=[{'name': '导航天赋', 'description': '当前天赋效果'}],
        building_skills=[
            {'slot': 1, 'name': '同名后勤', 'description': '制造效率+10%',
             'room': 'MANUFACTURE', 'unlock': {'phase': 'PHASE_0', 'level': 1}},
            {'slot': 1, 'name': '同名后勤', 'description': '制造效率+25%',
             'room': 'MANUFACTURE', 'unlock': {'phase': 'PHASE_2', 'level': 30}}],
        potentials=[f'当前潜能{i}：' + '详细潜能效果。' * 40 for i in range(30)])


@pytest.fixture
def navigation(qtbot):
    from arknights_unpacker.ui.profile_navigation import ProfileNavigation
    container = QWidget()
    layout = QVBoxLayout(container)
    browser = QTextBrowser()
    controls = ProfileNavigation(browser, container)
    layout.addWidget(controls)
    layout.addWidget(browser, 1)
    container.resize(1000, 600)
    qtbot.addWidget(container)
    container.show()
    qtbot.waitUntil(container.isVisible)
    return container, browser, controls


def test_profile_html_anchors_cover_actual_sections_with_safe_numeric_identifiers():
    profile = long_profile()
    blocks = semantic_blocks(ReportDocument(profile.name, operators=[profile]))
    names = Anchors(profile_html(profile)).names
    assert names == [f'profile-section-{index}' for index in range(len(blocks) + 1)]
    assert len(names) == len(set(names))
    assert not any(profile.char_id in name for name in names)


def test_directory_selection_scrolls_to_real_section_and_top_button_returns_to_top(navigation, qtbot):
    _, browser, controls = navigation
    profile = long_profile()
    original = deepcopy(as_jsonable(profile))
    controls.set_profile(profile)
    labels = [controls.sections.itemText(index) for index in range(controls.sections.count())]
    assert '天赋 · 导航天赋' in labels
    assert not any('后勤 · 后勤 · ' in label or '天赋 · 天赋 · ' in label for label in labels)
    qtbot.waitUntil(lambda: browser.verticalScrollBar().maximum() > 0)
    entries = [index for index in range(controls.sections.count())
               if '后勤' in controls.sections.itemText(index) and controls.sections.itemData(index)]
    assert entries
    controls.sections.setCurrentIndex(entries[0])
    qtbot.waitUntil(lambda: browser.verticalScrollBar().value() > 0)
    assert controls.back_to_top.isEnabled()
    controls.back_to_top.click()
    assert browser.verticalScrollBar().value() == browser.verticalScrollBar().minimum()
    assert as_jsonable(profile) == original


def test_duplicate_section_names_have_distinct_targets_and_scroll_positions(navigation, qtbot):
    _, browser, controls = navigation
    controls.set_profile(long_profile())
    qtbot.waitUntil(lambda: browser.verticalScrollBar().maximum() > 0)
    duplicate = [index for index in range(controls.sections.count())
                 if '同名后勤' in controls.sections.itemText(index)]
    assert len(duplicate) == 2
    assert controls.sections.itemText(duplicate[0]) != controls.sections.itemText(duplicate[1])
    assert controls.sections.itemData(duplicate[0]) != controls.sections.itemData(duplicate[1])
    controls.sections.setCurrentIndex(duplicate[0])
    first = browser.verticalScrollBar().value()
    controls.sections.setCurrentIndex(duplicate[1])
    assert browser.verticalScrollBar().value() > first > 0


def test_clear_preserves_host_placeholder_and_profile_rebuild_removes_old_entries(navigation):
    _, browser, controls = navigation
    controls.set_profile(long_profile())
    browser.setPlainText('由宿主负责的多选或空状态提示')
    controls.clear()
    assert browser.toPlainText() == '由宿主负责的多选或空状态提示'
    assert controls.sections.count() == 0
    assert not controls.sections.isEnabled() and not controls.back_to_top.isEnabled()
    replacement = OperatorProfile('char_second', '另一干员', trait='第二份当前特性')
    controls.set_profile(replacement)
    assert not any('同名后勤' in controls.sections.itemText(index) for index in range(controls.sections.count()))
    assert '另一干员' in browser.toPlainText() and '第二份当前特性' in browser.toPlainText()
    assert '目录验收干员' not in browser.toPlainText()
    actual = semantic_blocks(ReportDocument(replacement.name, operators=[replacement]))
    anchors = set(Anchors(profile_html(replacement)).names)
    targets = [controls.sections.itemData(index) for index in range(controls.sections.count())
               if controls.sections.itemData(index)]
    assert len(targets) == len(actual)
    assert set(targets) <= anchors


def test_malicious_titles_are_plain_directory_labels_and_escaped_in_body(navigation):
    _, browser, controls = navigation
    profile = long_profile()
    profile.name = '名称"><img src=x onerror=alert(1)>'
    profile.building_skills[0]['name'] = '后勤<script>alert(2)</script>'
    original = deepcopy(as_jsonable(profile))
    controls.set_profile(profile)
    html = profile_html(profile)
    assert '<img src=x' not in html and '<script>alert(2)</script>' not in html
    assert '&lt;img src=x' in html and '&lt;script&gt;' in html
    assert profile.name in browser.toPlainText()
    assert any('<script>' in controls.sections.itemText(index) for index in range(controls.sections.count()))
    tooltips = [controls.sections.itemData(index, Qt.ItemDataRole.ToolTipRole)
                for index in range(1, controls.sections.count())]
    assert any('&lt;script&gt;' in tooltip for tooltip in tooltips)
    assert not any('<script>' in tooltip or '<img src=x' in tooltip for tooltip in tooltips)
    assert all(target.startswith('profile-section-') and target.removeprefix('profile-section-').isdigit()
               for target in Anchors(html).names)
    assert as_jsonable(profile) == original


@pytest.mark.parametrize('width', [300, 480, 1000])
def test_compact_directory_fits_a_narrow_detail_pane(navigation, qtbot, width):
    container, _, controls = navigation
    controls.set_profile(long_profile())
    container.resize(width, 520)
    qtbot.wait(20)
    assert container.width() <= width
    for widget in (controls.sections, controls.back_to_top):
        assert controls.rect().contains(widget.mapTo(controls, QPoint(0, 0)))
        assert controls.rect().contains(widget.mapTo(controls, widget.rect().bottomRight()))
