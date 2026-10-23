from pathlib import Path
import json
from PIL import Image
import pytest

from arknights_unpacker.contracts import (OperatorProfile, ModuleProfile, EntityChangeSet,
    ExportFormat, ReportOptions, ReportSelection)
from arknights_unpacker.reports import compose_report, export_report


@pytest.fixture
def selection():
    module = ModuleProfile('eq:1', 'char/1', '同名', '模组甲', 'X', phases=[
        {'level': n, 'attributes': [{'key': 'atk', 'label': '攻击', 'value': n * 10}],
         'trait': '特性提升', 'talents': [{'name': '天赋甲', 'description': '效果甲', 'potential_delta': '+2'}],
         'diagnostics': []} for n in (1, 2, 3)])
    operator = OperatorProfile('char/1', '同名</script><img src=x onerror=alert(1)>',
        summary={'profession': '术师', 'phase': 2, 'level': 90, 'potential': 6, 'trust': 200},
        attributes=[{'key':'atk', 'label':'攻击', 'base': 900, 'trust': 100, 'potential': 65, 'module':0, 'value':1065, 'unit':''}],
        trait='法术伤害', talents=[{'name':'天赋甲', 'description':'强化', 'potential_delta':'+2', 'unlock_condition':'精英2'}],
        skills=[{'index':1, 'id':'skill_1', 'name':'长中文技能', 'level':10, 'sp_type':'自动回复',
            'trigger':'手动触发', 'init_sp':15, 'sp_cost':30, 'duration':30,
            'description':'首行。' + '中文长描述不应被截断，测试技能末尾完整。' * 200 + '技能终点标记',
            'blackboard':{'atk':1.2}, 'diagnostics':[]}],
        building_skills=[{'name':'后勤甲', 'description':'制造站效率+25%', 'room':'制造站', 'unlock':'精英2'}],
        potentials=['部署费用-1', '天赋增强'], modules=[module.__dict__],
        metadata={'version':'v078', 'resource_version':'r1', 'source':'本地夹具'})
    return ReportSelection([operator, OperatorProfile('char/2', operator.name)], [module],
        EntityChangeSet('old', 'new', modules=[{'id':'eq:1','kind':'modified', 'before':{'name':'旧模组'},'after':{'name':'模组甲'}}]))


def test_semantic_does_not_mutate_and_distinguishes_missing(selection):
    document = compose_report(selection, ReportOptions())
    selection.operators[0].attributes[0]['value'] = 0
    assert document.operators[0].attributes[0]['value'] == 1065
    assert document.metadata['changes']['baseline_id'] == 'old'
    broken = OperatorProfile('broken', '缺数据', diagnostics=['skills: missing table'])
    doc = compose_report(ReportSelection([broken]), ReportOptions())
    assert doc.metadata['template_version']


def test_safe_offline_batch_full_content(tmp_path, selection):
    document = compose_report(selection, ReportOptions())
    artifacts = export_report(document, tmp_path, {ExportFormat.HTML, ExportFormat.JSON, ExportFormat.TXT})
    htmls = [Path(a.path) for a in artifacts if a.format == 'html']
    assert any(p.name == 'index.html' for p in htmls)
    assert len({p.name for p in htmls}) == len(htmls)
    text = '\n'.join(p.read_text('utf-8') for p in htmls)
    assert '技能终点标记' in text and '1065' in text and '潜能增量' in text
    assert '&lt;/script&gt;&lt;img' in text
    assert '<img src=x' not in text
    assert 'fetch(' not in text and 'https://' not in text and 'http://' not in text
    sidecar = next(Path(a.path) for a in artifacts if a.format == 'json')
    data = json.loads(sidecar.read_text('utf-8'))
    assert data['operators'][0]['attributes'][0]['value'] == 1065
    assert data['metadata']['changes']['modules'][0]['before']['name'] == '旧模组'
    assert '旧模组' in text
    repeated = export_report(document, tmp_path, {ExportFormat.JSON})
    assert Path(repeated[0].path).parent != sidecar.parent
    manifest=json.loads((sidecar.parent.parent/'manifest.json').read_text('utf8'))
    assert manifest['status']=='succeeded' and manifest['complete'] is True


def test_paginate_complete_text_and_png(tmp_path, selection):
    from arknights_unpacker.reports.render import layout_pages
    options = ReportOptions(width=600, font_size=24, max_page_height=1100)
    document = compose_report(ReportSelection(selection.operators[:1]), options)
    pages = layout_pages(document)
    assert len(pages) > 1
    drawn_text = ''.join(line.text for page in pages for line in page)
    assert '技能终点标记' in drawn_text
    assert drawn_text.count('中文长描述不应被截断，测试技能末尾完整。') == 200
    artifacts = export_report(document, tmp_path, {ExportFormat.PNG})
    assert len(artifacts) == len(pages)
    for a in artifacts:
        with Image.open(a.path) as image:
            assert image.width == 600 and image.height <= 1100
    assert not list(tmp_path.rglob('*.html'))


def test_empty_missing_and_invalid_options(tmp_path):
    empty = compose_report(ReportSelection([OperatorProfile('a','空')]), ReportOptions())
    broken = compose_report(ReportSelection([OperatorProfile('b','坏', diagnostics=['skills: missing table'])]), ReportOptions())
    paths = export_report(empty, tmp_path, {ExportFormat.TXT})
    assert '无技能' in Path(paths[0].path).read_text('utf-8')
    paths = export_report(broken, tmp_path, {ExportFormat.TXT})
    assert '技能资料不完整' in Path(paths[0].path).read_text('utf-8')
    with pytest.raises(ValueError):
        compose_report(ReportSelection(), ReportOptions(max_page_height=20))


def test_windows_names_source_guard_and_thread_safe(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from arknights_unpacker.reports.export import safe_filename
    assert safe_filename('CON.txt') == '_CON.txt'
    assert safe_filename('a:/b*? ') == 'a__b__'
    source = tmp_path / 'source'
    source.mkdir()
    profile = OperatorProfile('c', '线程测试', metadata={'source_root':str(source)})
    document = compose_report(ReportSelection([profile]), ReportOptions(width=500, font_size=20, max_page_height=1000))
    with pytest.raises(ValueError, match='输入目录'):
        export_report(document, source / 'nested', {ExportFormat.JSON})
    assert not (source / 'nested').exists()
    with ThreadPoolExecutor(max_workers=1) as pool:
        artifacts = pool.submit(export_report, document, tmp_path, {ExportFormat.PNG}).result()
    assert artifacts and all(Path(a.path).is_file() for a in artifacts)
    document.operators[0].metadata['source_root']='  '
    assert export_report(document,tmp_path,{ExportFormat.JSON})


def test_html_anchor_table_and_batch_png_groups(tmp_path, selection):
    from html.parser import HTMLParser
    from urllib.parse import unquote
    class Parser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.ids, self.links, self.sources, self.events = set(), [], [], []
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if 'id' in attrs:
                assert attrs['id'] not in self.ids
                self.ids.add(attrs['id'])
            if 'href' in attrs:
                self.links.append(attrs['href'])
            if 'src' in attrs:
                self.sources.append(attrs['src'])
            self.events.extend(k for k in attrs if k.startswith('on'))
    document = compose_report(selection, ReportOptions(width=600, font_size=20, max_page_height=4000))
    artifacts = export_report(document, tmp_path, {ExportFormat.HTML, ExportFormat.PNG})
    for artifact in [a for a in artifacts if a.format == 'html']:
        path = Path(artifact.path)
        parser = Parser()
        parser.feed(path.read_text('utf-8'))
        for link in parser.links:
            assert (link[1:] in parser.ids) if link.startswith('#') else (path.parent / unquote(link)).is_file()
        assert not parser.events
        assert all(source.startswith('data:image/') for source in parser.sources)
    pngs = [a for a in artifacts if a.format == 'png']
    assert any('001_char_1_' in Path(a.path).name for a in pngs)
    assert any('002_char_2_' in Path(a.path).name for a in pngs)
    assert any(Path(a.path).name.startswith('modules_') for a in pngs)


def test_real_clem_profile_player_view_and_lossless_sidecar(tmp_path):
    from arknights_unpacker.reports.model import text_report
    from arknights_unpacker.reports.html_render import render_html
    from arknights_unpacker.reports.render import layout_pages
    fixture = Path(__file__).parent / 'fixtures/clem_actual_profile.json'
    raw = json.loads(fixture.read_text('utf-8'))
    profile = OperatorProfile(**raw)
    document = compose_report(ReportSelection([profile]), ReportOptions())
    text = text_report(document)
    html = render_html(document)
    assert len(text) < 9000
    assert 'clz_Torappu' not in text + html
    assert 'field_evidence' not in text + html and 'getter' not in text + html
    assert '技能参数' not in text + html
    assert '近卫' in text and '6星' in text and '精英2' in text
    assert '攻击回复' in text and '手动触发' in text and '会客室' in text
    assert '1065' in text and '21' in text and '无模组' in text
    assert len(layout_pages(document)) == 1
    paths = export_report(document,tmp_path,{ExportFormat.JSON})
    sidecar = Path(paths[0].path).read_text('utf-8')
    assert 'clz_Torappu' in sidecar and 'field_evidence' in sidecar and 'blackboard' in sidecar


def test_changes_scoped_to_page_and_readable_field_deltas(tmp_path):
    from arknights_unpacker.reports.model import text_report
    p1,p2 = OperatorProfile('a','甲'),OperatorProfile('b','乙')
    changes = EntityChangeSet('old','new',operators=[
        {'id':'a','name':'甲','kind':'modified','changes':[{'field':'trait','before':'旧特性甲','after':'新特性甲'}]},
        {'id':'b','name':'乙','kind':'modified','changes':[{'field':'trait','before':'旧特性乙','after':'新特性乙'}]}])
    doc = compose_report(ReportSelection([p1],changes=changes),ReportOptions())
    assert len(doc.metadata['changes']['operators']) == 1
    assert '旧特性甲' in text_report(doc) and '新特性甲' in text_report(doc)
    artifacts = export_report(compose_report(ReportSelection([p1,p2],changes=changes),ReportOptions()),tmp_path,{ExportFormat.HTML})
    a_page = next(Path(a.path) for a in artifacts if a.title=='甲')
    content = a_page.read_text('utf-8')
    assert '旧特性甲' in content and '旧特性乙' not in content


def test_draft_badge_and_module_recipient_sections():
    from arknights_unpacker.reports.model import text_report
    broken=OperatorProfile('a','缺数据',diagnostics=['skill_table: missing'])
    warning=OperatorProfile('a','未知区服',diagnostics=['区服未知，仅比较同一安装位置内容'])
    assert '资料不完整' in text_report(compose_report(ReportSelection([broken]),ReportOptions()))
    assert '资料不完整' not in text_report(compose_report(ReportSelection([warning]),ReportOptions()))
    module=ModuleProfile('eq','a','甲','模组',phases=[{'level':3,'trait':'本体特性','attributes':[],
        'effects':[{'description':'不应重复显示'}], 'hidden_effects':[{'blackboard':[{'key':'raw','value':10}]}],
        'token_effects':[{'name':'召唤物强化','description':'召唤物攻击提升','potential_delta':'+2',
                         'scope':{'isToken':True,'validInGameTag':'特定玩法'}}],
        'token_attributes':{'token_1':[{'key':'max_hp','value':50}]},'scope':{'game_tag_meta':'限定模式'},'talents':[]}])
    text=text_report(compose_report(ReportSelection(modules=[module]),ReportOptions()))
    assert '召唤物效果' in text and '生命上限' in text and '+50（加成）' in text
    assert '召唤物1' in text and 'token_1' not in text
    assert '限定模式' in text and '特定玩法' in text
    assert 'hidden_effects' not in text and 'blackboard' not in text and '不应重复显示' not in text


def test_cancel_during_layout_and_partial_export_manifest(tmp_path, selection):
    from arknights_unpacker.contracts import CancelToken, CancelledError
    from arknights_unpacker.reports.render import layout_pages
    token=CancelToken()
    doc=compose_report(selection,ReportOptions(width=600,font_size=24,max_page_height=1200))
    def cancel_layout(event):
        if event['stage']=='report_layout' and event['current']==3:
            token.cancel()
    with pytest.raises(CancelledError):
        layout_pages(doc,cancel=token,emit=cancel_layout)
    token=CancelToken()
    def cancel_after_json(event):
        if event.get('format')=='json' and event.get('status')=='succeeded':
            token.cancel()
    with pytest.raises(CancelledError):
        export_report(doc,tmp_path,{ExportFormat.JSON,ExportFormat.HTML,ExportFormat.PNG},cancel=token,emit=cancel_after_json)
    manifest=json.loads(next(tmp_path.rglob('manifest.json')).read_text('utf8'))
    assert manifest['status']=='cancelled' and manifest['complete'] is False
    assert [a['format'] for a in manifest['artifacts']]==['json']
    assert not list(tmp_path.rglob('*.png'))


def test_cancel_after_first_png_page_preserves_receipt(tmp_path,selection):
    from arknights_unpacker.contracts import CancelToken,CancelledError
    token=CancelToken()
    doc=compose_report(ReportSelection(selection.operators[:1]),ReportOptions(width=600,font_size=24,max_page_height=1200))
    def cancel_after_page(event):
        if event.get('format')=='png':
            token.cancel()
    with pytest.raises(CancelledError):
        export_report(doc,tmp_path,{ExportFormat.PNG},cancel=token,emit=cancel_after_page)
    manifest=json.loads(next(tmp_path.rglob('manifest.json')).read_text('utf8'))
    assert manifest['status']=='cancelled' and manifest['complete'] is False
    assert len(manifest['artifacts'])==1 and len(list(tmp_path.rglob('*.png')))==1
