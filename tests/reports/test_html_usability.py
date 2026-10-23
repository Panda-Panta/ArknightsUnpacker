"""Offline reports expose useful navigation and accessible local table scrolling."""
from html.parser import HTMLParser

from arknights_unpacker.contracts import ModuleProfile, OperatorProfile, ReportOptions, ReportSelection
from arknights_unpacker.reports import compose_report
from arknights_unpacker.reports.html_render import render_html, render_index


class Markup(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.elements = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def find(self, tag, **attributes):
        return [attrs for kind, attrs in self.elements if kind == tag
                and all(attrs.get(key) == value for key, value in attributes.items())]


def report():
    module = ModuleProfile('equip_reader', 'char_reader', '阅读测试', '对照模组', 'X', phases=[
        {'level': level, 'trait': f'{level}级效果',
         'attributes': [{'key': 'atk', 'label': '攻击', 'value': level * 10}]} for level in (1, 2, 3)
    ])
    profile = OperatorProfile('char_reader', '阅读测试',
        summary={'profession': '近卫', 'phase': 2, 'level': 90},
        skills=[{'index': 1, 'id': 'skill_reader', 'name': '阅读技能', 'description': '完整技能效果'}],
        modules=[module.__dict__])
    return compose_report(ReportSelection([profile]), ReportOptions())


def test_report_has_truthful_identity_and_native_keyboard_entry():
    output = render_html(report())
    page = Markup(output)
    assert '离线档案' in output
    assert 'STATUS // ONLINE' not in output and 'OS v3.4' not in output
    assert page.find('a', **{'class': 'skip-link', 'href': '#report-content'})
    assert page.find('main', id='report-content', tabindex='-1')
    assert page.find('a', **{'class': 'back-to-top', 'href': '#report-content'})
    assert page.find('input', id='report-search')[0]['aria-describedby'] == 'search-status'


def test_wide_tables_are_named_keyboard_scroll_regions_without_javascript():
    page = Markup(render_html(report()))
    tables = page.find('table', **{'class': 'module-matrix'})
    regions = page.find('div', **{'class': 'table-wrap'})
    assert tables and len(regions) >= len(tables)
    assert all(region.get('role') == 'region' and region.get('tabindex') == '0' for region in regions)
    assert all(region.get('aria-label', '').endswith('表格，可横向滚动') for region in regions)
    assert all(table.get('aria-label') for table in tables)
    assert all('open' in detail for detail in page.find('details'))


def test_batch_directory_states_actual_count_and_identifies_column_headers():
    output = render_index([{'path': '甲.html', 'title': '甲'}, {'path': '乙.html', 'title': '乙'}], '资料合集')
    page = Markup(output)
    assert '共 2 份资料' in output
    assert all(heading.get('scope') == 'col' for heading in page.find('th'))
    assert page.find('div', role='region', tabindex='0')
