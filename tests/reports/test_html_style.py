"""Selected export themes reach complete offline pages and batch directories."""
from html.parser import HTMLParser
from pathlib import Path
import re

import pytest

from arknights_unpacker.contracts import (
    ExportFormat, ModuleProfile, OperatorProfile, ReportOptions, ReportSelection,
)
from arknights_unpacker.reports import compose_report, export_report
from arknights_unpacker.reports.html_render import render_html, render_index
from arknights_unpacker.reports.style import ordered_groups, theme_colors, typography


class Page(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.root = {}
        self.styles = []
        self.sections = []
        self.stages = []
        self.buttons = []
        self.links = []
        self.in_style = False
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'html':
            self.root = attrs
        if tag == 'style':
            self.in_style = True
        if 'data-report-section' in attrs:
            self.sections.append(attrs['id'])
        if 'data-module-stage' in attrs:
            self.stages.append(attrs['data-module-stage'])
        if tag == 'button':
            self.buttons.append(attrs)
        if tag == 'a':
            self.links.append(attrs['href'])

    def handle_endtag(self, tag):
        if tag == 'style':
            self.in_style = False

    def handle_data(self, data):
        if self.in_style:
            self.styles.append(data)

    @property
    def css(self):
        return '\n'.join(self.styles)


def document(theme):
    module = ModuleProfile('equip_html', 'char_html', '主题干员', '主题模组', 'X', phases=[
        {'level': level, 'trait': f'{level}级完整效果',
         'attributes': [{'label': '攻击', 'value': level * 10}]} for level in (1, 2, 3)
    ])
    operator = OperatorProfile('char_html', '主题干员',
        summary={'profession': '术师', 'phase': 2, 'level': 90}, trait='法术伤害',
        skills=[{'index': 1, 'id': 'skill_html', 'name': '主题技能', 'description': '完整技能正文'}],
        modules=[module.__dict__], metadata={'version': 'v078'})
    return compose_report(ReportSelection([operator]), ReportOptions(theme=theme))


def assert_theme(page, theme):
    assert page.root.get('data-report-theme') == theme
    # The first root block is the screen palette. Printing gets its own light
    # palette later, so dark exports cannot accidentally pass by finding that.
    root = re.search(r':root\s*\{([^}]+)\}', page.css).group(1)
    assert f'color-scheme: {theme}' in root
    for role, value in theme_colors(theme).items():
        assert f'--{role.replace("_", "-")}: {value}' in root
    for role in ('body_family', 'heading_family', 'utility_family'):
        assert f'--{role.replace("_", "-")}: {typography()[role]}' in root


@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_selected_theme_reaches_complete_single_file_html(theme):
    report = document(theme)
    output = render_html(report)
    page = Page(output)
    assert_theme(page, theme)
    assert page.sections == [anchor for _, anchor, _, _ in ordered_groups(report)]
    assert page.stages == ['1', '2', '3']
    assert any(button.get('data-tab') == 'all' for button in page.buttons)
    assert [button['data-stage'] for button in page.buttons if 'data-stage' in button] == ['all', '1', '2', '3']
    assert all(phrase in output for phrase in ('完整技能正文', '1级完整效果', '2级完整效果', '3级完整效果'))
    assert 'fetch(' not in output and 'http://' not in output and 'https://' not in output
    assert '<link' not in output and '<script src=' not in output


@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_batch_index_inherits_selected_theme_and_relative_links(tmp_path, theme):
    report = compose_report(ReportSelection([
        OperatorProfile('char_one', '目录甲'), OperatorProfile('char_two', '目录乙'),
    ]), ReportOptions(theme=theme, title='主题批次'))
    artifacts = export_report(report, tmp_path, {ExportFormat.HTML})
    pages = [Path(item.path) for item in artifacts]
    assert len(pages) == 3 and pages[-1].name == 'index.html'
    for path in pages:
        assert_theme(Page(path.read_text('utf-8')), theme)
    from urllib.parse import unquote
    index = Page(pages[-1].read_text('utf-8'))
    assert {(pages[-1].parent / unquote(link)).resolve() for link in index.links} == {
        path.resolve() for path in pages[:-1]
    }


def test_index_legacy_call_keeps_offline_escaped_output():
    output = render_index([{'path': '资料 甲.html', 'title': '<干员甲>'}], '<离线目录>')
    assert_theme(Page(output), 'light')
    assert '&lt;离线目录&gt;' in output and '&lt;干员甲&gt;' in output
    assert '%20' in output and 'fetch(' not in output


def test_report_surfaces_and_print_use_shared_tokens_without_fixed_light_cards():
    page = Page(render_html(document('dark')))
    layout_css = page.css[page.css.index('* {'):]
    # Fixed white cards were the original dark-mode failure. All opaque colors
    # must now come from the shared runtime palette, including print overrides.
    before_print = layout_css.split('@media print', 1)[0]
    assert not re.search(r'#[0-9a-fA-F]{3,8}\b', before_print)
    assert 'background: var(--header)' in before_print
    assert 'background: var(--selected-bg)' in before_print
    assert 'color: var(--selected-ink)' in before_print
    assert 'font-family: var(--body-family)' in before_print
    assert 'var(--title-scale)' in before_print and 'var(--section-scale)' in before_print
    print_css = page.css[page.css.index('@media print'):]
    assert 'color-scheme: light' in print_css
    assert f'--paper: {theme_colors("light")["paper"]}' in print_css
    assert 'color: var(--ink)' in print_css


def test_no_script_controls_stay_hidden_until_script_initializes():
    css = Page(render_html(document('dark'))).css
    assert re.search(r'\.js-only\s*\{\s*display:\s*none', css)
    assert re.search(r'\.js \.js-only\s*\{\s*display:\s*flex', css)
    controls = re.search(r'\.controls,\s*\.stage-controls\s*\{([^}]+)\}', css).group(1)
    assert 'display:' not in controls


def test_html_uses_shared_grouping_including_additional_report_blocks(monkeypatch):
    from arknights_unpacker.reports import style
    from arknights_unpacker.reports.model import Block

    original = style.semantic_blocks
    monkeypatch.setattr(style, 'semantic_blocks', lambda report: [
        *original(report), Block('补充资料标题', [('内容', '补充资料正文')], group='补充分区'),
    ])
    output = render_html(document('light'))
    assert '补充资料标题' in output and '补充资料正文' in output
    assert 'data-report-group="补充分区"' in output
