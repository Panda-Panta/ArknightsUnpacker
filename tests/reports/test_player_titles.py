"""Missing game names must not expose internal fallback IDs in readable titles."""
import json
from html.parser import HTMLParser
from pathlib import Path

from PIL import ImageDraw

from arknights_unpacker.contracts import ExportFormat, OperatorProfile, ReportOptions, ReportSelection, as_jsonable
from arknights_unpacker.reports import compose_report, export_report


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden -= 1

    def handle_data(self, value):
        if not self.hidden:
            self.parts.append(value)


def test_missing_name_titles_and_index_are_readable_while_json_keeps_original(tmp_path, monkeypatch):
    identifier = 'char_private_fallback'
    missing = OperatorProfile(identifier, identifier)
    # The batch exercises single-page title replacement and the index adapter.
    document = compose_report(ReportSelection([missing, OperatorProfile('char_good', '已命名干员')]))
    original = as_jsonable(document)
    drawn = []
    draw_text = ImageDraw.ImageDraw.text

    def capture(draw, xy, text, *args, **kwargs):
        drawn.append(str(text))
        return draw_text(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, 'text', capture)
    outputs = export_report(document, tmp_path, set(ExportFormat))
    assert '未命名干员' in ''.join(drawn)
    assert identifier not in ''.join(drawn)
    for output in outputs:
        path = Path(output.path)
        if output.format == 'html':
            parser = VisibleText()
            parser.feed(path.read_text('utf-8'))
            assert identifier not in '\n'.join(parser.parts)
        elif output.format == 'txt':
            assert identifier not in path.read_text('utf-8')
        elif output.format == 'json':
            assert json.loads(path.read_text('utf-8')) == original
    assert as_jsonable(document) == original


def test_single_report_title_uses_fallback_and_custom_title_remains_intact(tmp_path):
    missing = OperatorProfile('char_private_fallback', 'char_private_fallback')
    for title in ('', '我的干员资料'):
        document = compose_report(ReportSelection([missing]), ReportOptions(title=title))
        original = as_jsonable(document)
        output, = export_report(document, tmp_path, {ExportFormat.TXT})
        assert Path(output.path).read_text('utf-8').splitlines()[0] == (title or '未命名干员')
        assert as_jsonable(document) == original
