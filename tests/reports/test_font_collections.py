"""A selected Windows collection face must become the actual exported font."""
from base64 import b64decode
from io import BytesIO
import os
from pathlib import Path
import re

from PIL import ImageFont
import pytest

from arknights_unpacker.contracts import OperatorProfile, ReportDocument, ReportOptions
from arknights_unpacker.reports.fonts import load_custom_font
from arknights_unpacker.reports.html_render import render_html, render_index
from arknights_unpacker.reports.render import _Layout


@pytest.fixture
def collection():
    path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'
    if not path.exists():
        pytest.skip('A real font collection is unavailable on this host')
    return path


def embedded(html):
    encoded, = re.findall(r'data:font/(?:ttf|otf);base64,([A-Za-z0-9+/=]+)', html)
    return b64decode(encoded)


def test_selected_collection_face_matches_its_original_glyphs(collection):
    before = collection.read_bytes()
    selected = load_custom_font(str(collection), 1)
    original = ImageFont.truetype(str(collection), 32, index=1)
    actual = selected.at_size(32)
    assert actual.getname() == original.getname()
    assert bytes(actual.getmask('塔露拉 Aa 13%')) == bytes(original.getmask('塔露拉 Aa 13%'))
    assert not selected.data.startswith(b'ttcf')
    assert collection.read_bytes() == before


def test_layout_uses_selected_face_for_body_headings_and_notes(collection):
    layout = _Layout(ReportOptions(font_path=str(collection), font_index=1))
    expected = ImageFont.truetype(str(collection), 28, index=1).getname()
    assert all(font.getname() == expected for font in (layout.body, layout.note, layout.title, layout.caption))


def test_html_and_batch_index_embed_the_selected_standalone_face(collection):
    profile = OperatorProfile('char', '塔露拉')
    document = ReportDocument('塔露拉', operators=[profile],
                              options=ReportOptions(font_path=str(collection), font_index=1))
    expected = ImageFont.truetype(str(collection), 16, index=1).getname()
    for html in (render_html(document), render_index([], '资料目录', font_path=str(collection), font_index=1)):
        data = embedded(html)
        assert not data.startswith(b'ttcf')
        assert ImageFont.truetype(BytesIO(data), 16).getname() == expected


def test_missing_collection_face_is_an_explicit_error(collection):
    with pytest.raises(ValueError, match='字体|字形'):
        load_custom_font(str(collection), 9999)


@pytest.mark.parametrize('contents', [b'ttcf', b'ttcf' + bytes(12)])
def test_broken_collection_has_a_readable_error(tmp_path, contents):
    path = tmp_path / 'broken.ttc'
    path.write_bytes(contents)
    with pytest.raises(ValueError, match='字体|字形'):
        load_custom_font(str(path))
