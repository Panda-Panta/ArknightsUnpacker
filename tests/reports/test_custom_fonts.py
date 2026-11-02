"""A selected local font controls actual PNG glyphs and offline HTML bytes."""
from base64 import b64decode
from io import BytesIO
from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageFont
import pytest

from arknights_unpacker.contracts import ExportFormat, OperatorProfile, ReportDocument, ReportOptions
from arknights_unpacker.reports import export_report
from arknights_unpacker.reports.html_render import render_html
from arknights_unpacker.reports import render


@pytest.fixture
def local_font(tmp_path):
    candidates = [Path('C:/Windows/Fonts/consola.ttf'),
                  Path('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'),
                  Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.otf')]
    source = next((path for path in candidates if path.is_file()), None)
    if source is None:
        pytest.skip('需要本机实际TTF/OTF字体样本')
    selected = tmp_path / ('用户自选字体' + source.suffix)
    selected.write_bytes(source.read_bytes())
    return selected


def document(font_path='', *, batch=False):
    talent = {'name': '自选字体测量与绘制', 'description': 'WWWWiiiiMMMMllll' * 8,
              'term_definitions': [{'term': '小字注释', 'description': 'selected-font notes ' * 8}]}
    operators = [OperatorProfile('one', '自选字体报告', talents=[talent])]
    if batch:
        operators.append(OperatorProfile('two', '另一份资料'))
    return ReportDocument('字体资料', operators=operators,
                          options=ReportOptions(width=500, font_size=24, font_path=str(font_path)))


def embedded_bytes(markup):
    match = re.search(r'url\([\"\']?data:font/(?:ttf|otf);base64,([A-Za-z0-9+/=]+)', markup)
    assert match, 'HTML must contain the selected font, not just a local file reference'
    return b64decode(match.group(1))


def test_png_uses_selected_font_for_measurement_and_every_drawn_text(local_font, tmp_path, monkeypatch):
    chosen = document(local_font)
    expected = ImageFont.truetype(str(local_font), chosen.options.font_size)
    painted = []
    original_text = ImageDraw.ImageDraw.text

    def capture(draw, xy, text, *args, **kwargs):
        font = kwargs['font']
        expected_size = ImageFont.truetype(str(local_font), font.size)
        assert font.getname() == expected_size.getname()
        assert bytes(font.getmask('Aa资料')) == bytes(expected_size.getmask('Aa资料'))
        painted.append((str(text), font.size))
        return original_text(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, 'text', capture)
    monkeypatch.setattr(render, '_font', lambda *args, **kwargs: pytest.fail('custom export used default font'))
    layout = render._Layout(chosen.options)
    assert layout.body.getlength('WWWWiiiiMMMMllll') == expected.getlength('WWWWiiiiMMMMllll')
    assert layout.note.getname() == expected.getname()
    artifacts = export_report(chosen, tmp_path / 'output', {ExportFormat.PNG})
    assert artifacts and all(item.format == 'png' for item in artifacts)
    with Image.open(artifacts[0].path) as image:
        assert image.width == 500
    assert any(size < 24 for _, size in painted)
    assert any('小字注释' in text for text, _ in painted)
    assert any('自选字体报告' in text for text, _ in painted)


def test_html_embeds_exact_selected_bytes_and_all_font_roles(local_font):
    markup = render_html(document(local_font))
    assert embedded_bytes(markup) == local_font.read_bytes()
    for role in ('body', 'heading', 'utility'):
        assert re.search(r'--' + role + r'-family\s*:\s*[\"\']?ArknightsCustomExport', markup)
    assert str(local_font) not in markup


def test_batch_index_and_each_document_embed_font_for_offline_use(local_font, tmp_path):
    artifacts = export_report(document(local_font, batch=True), tmp_path / 'output', {ExportFormat.HTML})
    assert len(artifacts) == 3
    assert any(Path(item.path).name == 'index.html' for item in artifacts)
    expected = local_font.read_bytes()
    local_font.unlink()  # No installed font or original path is needed by saved HTML.
    assert all(embedded_bytes(Path(item.path).read_text('utf-8')) == expected for item in artifacts)


@pytest.mark.parametrize('format', [ExportFormat.PNG, ExportFormat.HTML])
@pytest.mark.parametrize('kind', ['missing', 'invalid'])
def test_invalid_custom_font_is_an_explicit_failure(tmp_path, format, kind):
    path = tmp_path / 'broken.ttf'
    if kind == 'invalid':
        path.write_bytes(b'not an actual font')
    with pytest.raises(ValueError, match='字体'):
        export_report(document(path), tmp_path / 'output', {format})
    assert not list((tmp_path / 'output').rglob('*.png'))
    assert not list((tmp_path / 'output').rglob('*.html'))


def test_json_and_text_export_do_not_load_the_selected_font(tmp_path, monkeypatch):
    path = tmp_path / 'missing.ttf'
    original = Path.read_bytes

    def read_bytes(candidate):
        if candidate == path:
            pytest.fail('JSON/TXT opened custom font')
        return original(candidate)

    monkeypatch.setattr(Path, 'read_bytes', read_bytes)
    artifacts = export_report(document(path), tmp_path / 'output', {ExportFormat.JSON, ExportFormat.TXT})
    assert {item.format for item in artifacts} == {'json', 'txt'}


def test_default_html_does_not_load_a_font_or_add_custom_css(monkeypatch):
    original = Path.read_bytes

    def read_bytes(path):
        if path.suffix.lower() in {'.ttf', '.otf', '.ttc'}:
            pytest.fail('default HTML export opened a font')
        return original(path)

    monkeypatch.setattr(Path, 'read_bytes', read_bytes)
    markup = render_html(document())
    assert 'ArknightsCustomExport' not in markup
    assert 'data:font/' not in markup
