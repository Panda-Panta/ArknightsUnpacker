from pathlib import Path

from arknights_unpacker.contracts import ExportFormat, ModuleProfile, ReportOptions, ReportSelection
from arknights_unpacker.reports import compose_report, export_report


def test_module_collection_has_explicit_default_title():
    document = compose_report(ReportSelection(modules=[ModuleProfile('eq', 'char', '干员', '模组')]))
    assert document.title == '模组资料合集'


def test_one_module_html_keeps_collection_title_and_all_parents(tmp_path):
    modules = [ModuleProfile(f'eq-{n}', f'char-{n}', f'干员{n}', f'模组{n}',
        phases=[{'level': level, 'trait': f'第{n}模组第{level}级完整效果'} for level in (1, 2, 3)])
        for n in (1, 2)]
    document = compose_report(ReportSelection(modules=modules), ReportOptions(title='本次新增模组'))
    artifacts = export_report(document, tmp_path, {ExportFormat.HTML})
    assert len(artifacts) == 1
    page = Path(artifacts[0].path)
    assert page.name == 'modules.html'
    html = page.read_text('utf-8')
    assert '<title>本次新增模组</title>' in html
    for module in modules:
        assert module.name in html
        for phase in module.phases:
            assert phase['trait'] in html
