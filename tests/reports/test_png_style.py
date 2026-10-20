"""Actual PNG surfaces and glyph positions follow the shared report design."""
from collections import Counter

from PIL import Image, ImageColor, ImageDraw
import pytest

from arknights_unpacker.contracts import OperatorProfile, ReportDocument, ReportOptions
from arknights_unpacker.reports import render
from arknights_unpacker.reports.style import ordered_groups, theme_colors, typography


def styled_document(theme='light'):
    profile = OperatorProfile('char_style', '样式验收干员',
        summary={'profession': '近卫', 'rarity': 6, 'phase': 2, 'level': 90},
        attributes=[{'label': '攻击', 'value': 1065, 'base': 900, 'trust': 100,
                     'potential': 65, 'module': 0, 'unit': ''},
                    {'label': '生命上限', 'value': 2500, 'base': 2400, 'trust': 100,
                     'potential': 0, 'module': 0, 'unit': ''}],
        trait='造成物理伤害', talents=[{'name': '先显示的天赋', 'description': '天赋内容'}],
        skills=[{'index': 1, 'name': '技能甲', 'description': '技能内容'}],
        potentials=['部署费用－1'])
    return ReportDocument('共同样式验收', operators=[profile],
        options=ReportOptions(width=1200, font_size=24, theme=theme),
        metadata={'template_version': '2.1.0'})


@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_png_has_actual_shared_masthead_card_table_and_theme_colors(tmp_path, theme):
    path, = render.render_png(styled_document(theme), tmp_path, theme)
    palette = theme_colors(theme)
    with Image.open(path) as image:
        colors = {rgb: count for count, rgb in image.getcolors(image.width * image.height)}
        # These are large, visible regions of the image, not a metadata claim.
        for role in ('canvas', 'bar', 'paper', 'header', 'table_alt', 'accent', 'rule'):
            assert colors.get(ImageColor.getrgb(palette[role]), 0) >= 80, role
        assert colors.get(ImageColor.getrgb(palette['ink']), 0) > 20
        assert colors.get(ImageColor.getrgb(palette['bar_ink']), 0) > 20


def test_png_section_order_and_type_hierarchy_match_shared_report_design(tmp_path, monkeypatch):
    document = styled_document()
    pages = render.layout_pages(document)
    sections = [line.text for page in pages for line in page if line.kind == 'section']
    assert sections == [title for _, _, title, _ in ordered_groups(document)]
    assert sections.index('天赋') < sections.index('技能')
    assert sections[-1] == '资料版本与口径'
    sizes = {}
    original = ImageDraw.ImageDraw.text

    def capture(draw, xy, text, *args, **kwargs):
        sizes[str(text)] = kwargs['font'].size
        return original(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, 'text', capture)
    render.render_png(document, tmp_path, 'hierarchy')
    assert (sizes[document.title] > sizes['干员信息'] >
            sizes['样式验收干员 · char_style'] > sizes['说明：造成物理伤害'])


@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_long_title_and_table_remain_complete_above_footer_on_every_page(tmp_path, monkeypatch, theme):
    document = styled_document(theme)
    document.title = '长标题' + '籁' * 100 + '文档标题终点'
    document.options.width = 800
    document.options.font_size = 24
    document.options.max_page_height = 850
    document.operators[0].attributes[0]['label'] = '龘' * 180 + '表格终点'
    document.operators[0].attributes[0]['value'] = '鹱' * 150 + '数值终点'
    drawn = []
    original = ImageDraw.ImageDraw.text

    def capture(draw, xy, text, *args, **kwargs):
        bbox = draw.textbbox(xy, str(text), font=kwargs['font'], anchor=kwargs.get('anchor'))
        drawn.append((draw._image, str(text), bbox))
        return original(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, 'text', capture)
    paths = render.render_png(document, tmp_path, f'long-{theme}')
    assert len(paths) > 1
    actual = ''.join(text for _, text, _ in drawn)
    assert document.title in actual
    assert Counter(actual)['龘'] == 180 and Counter(actual)['鹱'] == 150
    assert '…' not in actual
    for path in paths:
        with Image.open(path) as image:
            assert image.width == 800 and image.height <= 850
    for image, text, bbox in drawn:
        assert bbox[0] >= 0 and bbox[1] >= 0, text
        assert bbox[2] <= image.width and bbox[3] <= image.height, text
        if not text.startswith('第 '):
            footer_top = min(bounds[1] for target, caption, bounds in drawn
                             if target is image and caption.startswith('第 '))
            assert bbox[3] < footer_top, text


def test_large_font_on_minimum_width_keeps_full_title_and_content(tmp_path, monkeypatch):
    document = styled_document()
    document.title = '窄图标题完整保留直到终点'
    document.options = ReportOptions(width=320, font_size=96, max_page_height=1200)
    drawn = []
    original = ImageDraw.ImageDraw.text

    def capture(draw, xy, text, *args, **kwargs):
        bbox = draw.textbbox(xy, str(text), font=kwargs['font'], anchor=kwargs.get('anchor'))
        assert 0 <= bbox[0] <= bbox[2] <= draw._image.width
        assert 0 <= bbox[1] <= bbox[3] <= draw._image.height
        drawn.append((str(text), kwargs['font'].size))
        return original(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, 'text', capture)
    render.render_png(document, tmp_path, 'large-font')
    title_size = round(document.options.font_size * typography()['title_scale'])
    assert ''.join(text for text, size in drawn if size == title_size) == document.title
    assert '技能内容' in ''.join(line.text for page in render.layout_pages(document) for line in page)
