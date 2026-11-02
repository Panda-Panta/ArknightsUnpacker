"""Talent glossary text is shared across formats and stays outside tables."""
from copy import deepcopy
from html.parser import HTMLParser

from arknights_unpacker.contracts import ModuleProfile, OperatorProfile, ReportDocument, as_jsonable
from arknights_unpacker.reports.html_render import render_html
from arknights_unpacker.reports.model import semantic_blocks, text_report
from arknights_unpacker.reports.render import layout_pages
from arknights_unpacker.ui.report_preview import profile_html


DEFINITION = '累计满时爆发（普通、精英敌人1000点、领袖2000点累计值），立即受到7000点元素伤害'


def talent():
    return {'name': '绝不妥协', 'description': '附带13%（+2%）的灼燃损伤；停止攻击3秒后提升（最高18%）。',
            'term_definitions': [{'term': '灼燃损伤', 'description': DEFINITION}]}


class TableText(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.depth = 0
        self.inside, self.outside = [], []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.depth += 1

    def handle_endtag(self, tag):
        if tag == 'table':
            self.depth -= 1

    def handle_data(self, text):
        (self.inside if self.depth else self.outside).append(text)


def test_talent_notes_are_deduplicated_without_extra_sections_or_mutation():
    effect = talent()
    effect['term_definitions'] *= 2
    profile = OperatorProfile('char', '塔露拉', talents=[effect])
    report = ReportDocument('资料', operators=[profile])
    original = deepcopy(as_jsonable(report))
    blocks = semantic_blocks(report)
    effect_block, = [block for block in blocks if block.title.startswith('天赋 · ')]
    assert effect_block.notes == [('灼燃损伤', DEFINITION)]
    assert not any('术语说明' in block.title for block in blocks)
    assert '最高18%' in text_report(report)
    assert text_report(report).count(DEFINITION) == 1
    assert as_jsonable(report) == original


def test_html_and_native_preview_put_glossary_outside_tables():
    profile = OperatorProfile('char', '塔露拉', talents=[talent()])
    report = ReportDocument('资料', operators=[profile])
    for markup in (render_html(report), profile_html(profile)):
        parsed = TableText(markup)
        assert DEFINITION in ''.join(parsed.outside)
        assert DEFINITION not in ''.join(parsed.inside)
        assert '附带13%（+2%）的灼燃损伤' in ''.join(parsed.inside)


def test_png_and_text_keep_complete_definition_without_matrix_cells():
    profile = OperatorProfile('char', '塔露拉', talents=[talent()])
    report = ReportDocument('资料', operators=[profile])
    lines = [line for page in layout_pages(report) for line in page]
    glossary_lines = [line for line in lines if DEFINITION[:5] in line.text]
    assert glossary_lines
    assert all(line.kind == 'note' and not line.cells for line in glossary_lines)
    assert '灼燃损伤：' + DEFINITION in text_report(report)


def test_module_glossary_is_outside_matrix_and_belongs_to_same_entry():
    module = ModuleProfile('equip', 'char', '塔露拉', '模组', phases=[
        {'level': level, 'talents': [talent()]} for level in (1, 2, 3)])
    report = ReportDocument('资料', modules=[module])
    blocks = semantic_blocks(report)
    effects, = [block for block in blocks if block.kind == 'module-effects']
    assert effects.notes == [('灼燃损伤', DEFINITION)]
    assert not any('术语说明' in block.title for block in blocks)
    parsed = TableText(render_html(report))
    assert DEFINITION not in ''.join(parsed.inside)
    assert DEFINITION in ''.join(parsed.outside)
