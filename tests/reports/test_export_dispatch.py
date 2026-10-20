"""Export formats stay independent while sharing one batch lifecycle."""
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from textwrap import dedent

import pytest


SOURCE = Path(__file__).resolve().parents[2] / 'src'
HTML_RENDERER = 'arknights_unpacker.reports.html_render'
PNG_RENDERER = 'arknights_unpacker.reports.render'
UNRELATED = ('PySide6', 'UnityPy', 'arknights_unpacker.extraction')


def run_isolated(tmp_path, body, blocked):
    """Exercise real imports in a fresh interpreter, including HTML asset I/O."""
    script = dedent(f'''\
        import importlib.abc
        import json
        from pathlib import Path
        import sys

        destination = Path(sys.argv[1])
        source = Path(sys.argv[2])
        sys.path.insert(0, str(source))
        blocked = {blocked!r}

        class RejectDependencies(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if any(fullname == name or fullname.startswith(name + '.') for name in blocked):
                    raise ModuleNotFoundError('blocked dependency: ' + fullname, name=fullname)
                return None

        sys.meta_path.insert(0, RejectDependencies())
        html_assets = source.parent / 'resources' / 'html'
        asset_reads = []

        def reject_html_assets(event, args):
            if event == 'open' and isinstance(args[0], str):
                path = Path(args[0]).resolve()
                if path.is_relative_to(html_assets):
                    asset_reads.append(str(path))
                    raise FileNotFoundError('HTML assets unavailable: ' + str(path))

        sys.addaudithook(reject_html_assets)
    ''') + '\n' + dedent(body)
    result = subprocess.run([sys.executable, '-I', '-c', script, str(tmp_path), str(SOURCE)],
                            capture_output=True, text=True, encoding='utf-8', timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


DOCUMENT = '''\
from arknights_unpacker.contracts import ExportFormat, OperatorProfile, ReportOptions, ReportSelection
from arknights_unpacker.reports import compose_report, export_report
document = compose_report(ReportSelection([OperatorProfile('char:test', '独立导出',
    attributes=[{'label': '攻击', 'value': 321}], trait='真实特性')]),
    ReportOptions(width=400, font_size=16, max_page_height=1000))
'''


def test_package_and_composition_do_not_load_renderers_or_assets(tmp_path):
    run_isolated(tmp_path, DOCUMENT + '''\
assert document.operators[0].attributes[0]['value'] == 321
assert not asset_reads
assert not any(name.startswith('arknights_unpacker.reports.model') for name in sys.modules)
''', (HTML_RENDERER, PNG_RENDERER, 'arknights_unpacker.reports.model', 'PIL', *UNRELATED))


@pytest.mark.parametrize('formats', [('json',), ('txt',), ('json', 'txt')])
def test_json_and_text_export_without_html_png_qt_or_extraction(tmp_path, formats):
    run_isolated(tmp_path, DOCUMENT + f'''\
artifacts = export_report(document, destination, {{ExportFormat(value) for value in {formats!r}}})
assert [item.format for item in artifacts] == list({formats!r})
for artifact in artifacts:
    path = Path(artifact.path)
    if artifact.format == 'json':
        assert json.loads(path.read_text('utf-8'))['operators'][0]['attributes'][0]['value'] == 321
    else:
        assert '真实特性' in path.read_text('utf-8') and '321' in path.read_text('utf-8')
manifest = json.loads((Path(artifacts[0].path).parent.parent / 'manifest.json').read_text('utf-8'))
assert manifest['status'] == 'succeeded' and manifest['complete']
assert not asset_reads
assert {HTML_RENDERER!r} not in sys.modules and {PNG_RENDERER!r} not in sys.modules
''', (HTML_RENDERER, PNG_RENDERER, 'PIL', *UNRELATED))


def test_png_export_without_html_qt_or_extraction(tmp_path):
    run_isolated(tmp_path, DOCUMENT + f'''\
artifacts = export_report(document, destination, {{ExportFormat.PNG}})
assert artifacts and all(item.format == 'png' for item in artifacts)
from PIL import Image
for item in artifacts:
    with Image.open(item.path) as image:
        assert image.format == 'PNG' and image.width == 400
manifest = json.loads((Path(artifacts[0].path).parent.parent / 'manifest.json').read_text('utf-8'))
assert manifest['status'] == 'succeeded' and manifest['complete']
assert not asset_reads and {HTML_RENDERER!r} not in sys.modules
''', (HTML_RENDERER, *UNRELATED))


def test_missing_html_renderer_records_real_failure_after_completed_formats(tmp_path):
    run_isolated(tmp_path, DOCUMENT + '''\
from hashlib import sha256
try:
    export_report(document, destination, {ExportFormat.JSON, ExportFormat.TXT, ExportFormat.HTML, ExportFormat.PNG})
except ModuleNotFoundError as error:
    assert error.name == 'arknights_unpacker.reports.html_render'
else:
    raise AssertionError('An unavailable requested renderer must fail')
manifest_path, = destination.rglob('manifest.json')
manifest = json.loads(manifest_path.read_text('utf-8'))
assert manifest['status'] == 'failed' and not manifest['complete']
assert [item['format'] for item in manifest['artifacts']] == ['json', 'txt']
assert manifest['requested_formats'] == ['html', 'json', 'png', 'txt']
assert manifest['errors'][0]['type'] == 'ModuleNotFoundError'
assert 'blocked dependency' in manifest['errors'][0]['message']
for item in manifest['artifacts']:
    assert sha256((manifest_path.parent / item['path']).read_bytes()).hexdigest() == item['sha256']
assert not list(destination.rglob('*.html')) and not list(destination.rglob('*.png'))
assert not asset_reads
''', (HTML_RENDERER, PNG_RENDERER, *UNRELATED))


def test_missing_html_assets_fail_only_when_html_is_requested(tmp_path):
    run_isolated(tmp_path, DOCUMENT + '''\
completed = export_report(document, destination / 'text', {ExportFormat.JSON, ExportFormat.TXT})
assert len(completed) == 2 and not asset_reads
try:
    export_report(document, destination / 'html', {ExportFormat.HTML})
except FileNotFoundError as error:
    assert 'HTML assets unavailable' in str(error)
else:
    raise AssertionError('A requested HTML renderer must read its actual assets')
manifest_path, = (destination / 'html').rglob('manifest.json')
manifest = json.loads(manifest_path.read_text('utf-8'))
assert manifest['status'] == 'failed' and not manifest['complete']
assert manifest['artifacts'] == [] and manifest['errors'][0]['type'] == 'FileNotFoundError'
assert asset_reads
''', UNRELATED)


def test_cancellation_prevents_loading_the_next_renderer(tmp_path):
    run_isolated(tmp_path, DOCUMENT + '''\
from arknights_unpacker.contracts import CancelToken, CancelledError
token = CancelToken()
events = []
def cancel_after_json(event):
    events.append(event)
    if event.get('format') == 'json':
        token.cancel()
try:
    export_report(document, destination, {ExportFormat.JSON, ExportFormat.HTML}, cancel=token, emit=cancel_after_json)
except CancelledError:
    pass
else:
    raise AssertionError('Cancellation must propagate to the caller')
manifest_path, = destination.rglob('manifest.json')
manifest = json.loads(manifest_path.read_text('utf-8'))
assert manifest['status'] == 'cancelled' and not manifest['complete']
assert [item['format'] for item in manifest['artifacts']] == ['json']
assert manifest['errors'][0]['type'] == 'CancelledError'
assert len(events) == 1 and not asset_reads
''', (HTML_RENDERER, PNG_RENDERER, *UNRELATED))


def manifest_under(directory):
    path, = directory.rglob('manifest.json')
    return path, json.loads(path.read_text('utf-8'))


def test_dispatch_preserves_order_page_names_scoped_changes_and_index(tmp_path):
    from arknights_unpacker.contracts import (EntityChangeSet, ExportFormat, ModuleProfile,
        OperatorProfile, ReportOptions, ReportSelection)
    from arknights_unpacker.reports import compose_report, export_report

    operators = [OperatorProfile('char/one', '甲', summary={'profession': '术师'}, metadata={'version': 'v1'}),
                 OperatorProfile('char:two', '乙', metadata={'version': 'v2'})]
    module = ModuleProfile('equip:one', 'char/one', '甲', '共同模组', phases=[{'level': 1, 'trait': '完整模组效果'}])
    changes = EntityChangeSet('before', 'after', operators=[
        {'id': profile.char_id, 'kind': 'modified', 'changes': [
            {'field': 'trait', 'before': f'旧特性{profile.name}', 'after': f'新特性{profile.name}'}]}
        for profile in operators])
    document = compose_report(ReportSelection(operators, [module], changes),
                              ReportOptions(title='混合资料', width=500, font_size=16, max_page_height=3000))
    events = []
    artifacts = export_report(document, tmp_path, set(ExportFormat), emit=events.append)
    assert [item.format for item in artifacts] == ['json', 'txt', 'html', 'html', 'html', 'html', 'png', 'png', 'png']
    html = [item for item in artifacts if item.format == 'html']
    names = [f'001_char_one_{sha256(b"char/one").hexdigest()[:8]}_甲_v1',
             f'002_char_two_{sha256(b"char:two").hexdigest()[:8]}_乙_v2', 'modules']
    assert [Path(item.path).stem for item in html] == [*names, 'index']
    assert [item.title for item in html] == ['甲', '乙', '模组资料合集', '混合资料 · 目录']
    for item, own, other in zip(html[:2], ('甲', '乙'), ('乙', '甲')):
        text = Path(item.path).read_text('utf-8')
        assert f'旧特性{own}' in text and f'旧特性{other}' not in text
    assert '完整模组效果' in Path(html[2].path).read_text('utf-8')
    index = Path(html[-1].path).read_text('utf-8')
    from urllib.parse import quote
    assert all(quote(Path(item.path).name) in index for item in html[:-1])
    png = [item for item in artifacts if item.format == 'png']
    assert [Path(item.path).stem for item in png] == [name + '_p01' for name in names]
    completed = [event for event in events if event.get('stage') == 'report_export']
    assert [event['path'] for event in completed] == [item.path for item in artifacts]
    assert all(event['kind'] == 'progress' and event['status'] == 'succeeded' for event in completed)
    manifest_path, manifest = manifest_under(tmp_path)
    assert manifest['status'] == 'succeeded' and manifest['complete'] and not manifest['errors']
    assert [item['format'] for item in manifest['artifacts']] == [item.format for item in artifacts]
    for item in manifest['artifacts']:
        assert sha256((manifest_path.parent / item['path']).read_bytes()).hexdigest() == item['sha256']


def test_dispatch_retains_completed_html_when_a_later_page_fails(tmp_path, monkeypatch):
    from arknights_unpacker.contracts import ExportFormat, OperatorProfile, ReportSelection
    from arknights_unpacker.reports import compose_report, export_report
    from arknights_unpacker.reports import html_render

    original = html_render.render_html
    def fail_second_page(document):
        if document.title == '失败页':
            raise OSError('HTML page write fixture failed')
        return original(document)
    monkeypatch.setattr(html_render, 'render_html', fail_second_page)
    document = compose_report(ReportSelection([OperatorProfile('a', '成功页'), OperatorProfile('b', '失败页')]))
    with pytest.raises(OSError, match='fixture failed'):
        export_report(document, tmp_path, {ExportFormat.JSON, ExportFormat.TXT, ExportFormat.HTML, ExportFormat.PNG})
    manifest_path, manifest = manifest_under(tmp_path)
    assert manifest['status'] == 'failed' and not manifest['complete']
    assert [item['format'] for item in manifest['artifacts']] == ['json', 'txt', 'html']
    assert manifest['artifacts'][-1]['title'] == '成功页'
    assert manifest['errors'] == [{'type': 'OSError', 'message': 'HTML page write fixture failed'}]
    assert all((manifest_path.parent / item['path']).is_file() for item in manifest['artifacts'])
    assert not list(tmp_path.rglob('index.html')) and not list(tmp_path.rglob('*.png'))
