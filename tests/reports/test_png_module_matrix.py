"""Four-state module matrices stay compact and paint entirely inside their cells."""
from collections import Counter

from PIL import Image, ImageDraw
import pytest

from arknights_unpacker.contracts import ModuleProfile, ReportDocument, ReportOptions
from arknights_unpacker.reports.model import Block
from arknights_unpacker.reports import render


def matrix_document(theme='light', *, width=1200, font_size=28, paged=False):
    columns = ['项目', '未装备', '1级', '2级', '3级']
    entry = dict(group='模组', entry_id='module:style:eq', entry_title='模组甲')
    blocks = [
        Block('样式干员 · 模组甲', [('适用干员', '样式干员'), ('模组类型', 'X')], kind='module-info', **entry),
        Block('属性面板', columns=columns, cells=[
            ['生命上限', '1800', '1900（+100）', '1950（+150）', '2000（+200）'],
            ['攻击', '500', '520（+20）', '530（+30）', '540（+40）'],
        ], kind='module-attributes', **entry),
        Block('特性与天赋', columns=columns, cells=[
            ['天赋', *[character * 40 + '，完整说明gjpq。' for character in '龘鹱籁靐']],
        ], kind='module-effects', **entry),
    ]
    document = ReportDocument('横向对照验收', modules=[ModuleProfile('eq', 'style', '样式干员', '模组甲')],
        options=ReportOptions(width=width, font_size=font_size, theme=theme,
                              max_page_height=800 if paged else 16000,
                              module_image_layout='paged' if paged else 'single'))
    return document, blocks


def use_blocks(monkeypatch, blocks):
    monkeypatch.setattr(render, 'ordered_groups',
        lambda document: [('模组', 'modules', '模组', list(enumerate(blocks)))])


@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_default_matrix_gives_four_states_equal_room_and_keeps_glyphs_in_real_cells(tmp_path, monkeypatch, theme):
    document, blocks = matrix_document(theme)
    use_blocks(monkeypatch, blocks)
    lines = [line for page in render.layout_pages(document) for line in page]
    headers = [line for line in lines if line.kind == 'table-header']
    assert len(headers) == 2 and all(line.cells == blocks[1].columns for line in headers)
    for line in headers:
        label, *states = line.column_widths
        assert label < min(states), 'Short item labels must not consume more room than a complete state'
        assert label <= sum(line.column_widths) * .18
        assert max(states) - min(states) <= 1

    rectangles, drawn = [], []
    original_rectangle = ImageDraw.ImageDraw.rectangle
    original_text = ImageDraw.ImageDraw.text

    def capture_rectangle(draw, xy, *args, **kwargs):
        if len(xy) == 4 and document.options.font_size * 2 <= xy[2] - xy[0] < document.options.width * .4:
            rectangles.append(tuple(xy))
        return original_rectangle(draw, xy, *args, **kwargs)

    def capture_text(draw, xy, text, *args, **kwargs):
        bbox = draw.textbbox(xy, str(text), font=kwargs['font'], anchor=kwargs.get('anchor'))
        drawn.append((str(text), tuple(xy), bbox))
        return original_text(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, 'rectangle', capture_rectangle)
    monkeypatch.setattr(ImageDraw.ImageDraw, 'text', capture_text)
    path, = render.render_png(document, tmp_path, f'matrix-{theme}')
    fragments = {cell for line in lines if line.kind in {'table', 'table-header'} for cell in line.cells if cell}
    actual = Counter(''.join(text for text, _, _ in drawn))
    assert all(actual[character] == 40 for character in '龘鹱籁靐')
    for text, origin, bbox in drawn:
        if text in fragments:
            cells = [cell for cell in rectangles if cell[0] <= origin[0] < cell[2] and cell[1] <= origin[1] < cell[3]]
            assert cells, text
            assert any(cell[0] <= bbox[0] <= bbox[2] <= cell[2] and
                       cell[1] <= bbox[1] <= bbox[3] <= cell[3] for cell in cells), (text, bbox, cells)
    with Image.open(path) as image:
        assert image.info['report_theme'] == theme
        assert image.width == 1200


def test_module_matrix_reduces_real_image_height_without_shrinking_body_font(tmp_path, monkeypatch):
    document, blocks = matrix_document()
    use_blocks(monkeypatch, blocks)
    sizes = set()
    original = ImageDraw.ImageDraw.text

    def capture(draw, xy, text, *args, **kwargs):
        if any(character in str(text) for character in '龘鹱籁靐'):
            sizes.add(kwargs['font'].size)
        return original(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, 'text', capture)
    compact, = render.render_png(document, tmp_path, 'compact')
    with Image.open(compact) as compact_image:
        # This exact five-column fixture was 1328px with the 0.1.7 generic
        # spacing/1.6 label weight, recorded by the initial failing regression.
        assert compact_image.height < 1328 * .85
    assert sizes == {document.options.font_size}


@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_narrow_paged_module_matrix_preserves_every_state_and_has_no_clipped_text(tmp_path, monkeypatch, theme):
    document, blocks = matrix_document(theme, width=400, font_size=24, paged=True)
    use_blocks(monkeypatch, blocks)
    drawn = []
    original = ImageDraw.ImageDraw.text

    def capture(draw, xy, text, *args, **kwargs):
        bbox = draw.textbbox(xy, str(text), font=kwargs['font'], anchor=kwargs.get('anchor'))
        assert 0 <= bbox[0] <= bbox[2] <= draw._image.width, text
        assert 0 <= bbox[1] <= bbox[3] <= draw._image.height, text
        drawn.append(str(text))
        return original(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, 'text', capture)
    paths = render.render_png(document, tmp_path, f'narrow-{theme}')
    assert len(paths) > 1
    actual = Counter(''.join(drawn))
    assert all(actual[character] == 40 for character in '龘鹱籁靐')
    for path in paths:
        with Image.open(path) as image:
            assert image.height <= 800
