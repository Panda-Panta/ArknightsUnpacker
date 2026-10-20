from copy import deepcopy
from datetime import datetime

from ..contracts import ReportDocument, ReportOptions, ReportSelection, as_jsonable

TEMPLATE_VERSION = '2.0.0'


def validate_options(options: ReportOptions) -> None:
    if not 320 <= options.width <= 4096:
        raise ValueError('图片宽度应在 320–4096 px 之间')
    if not 12 <= options.font_size <= 96:
        raise ValueError('正文字号应在 12–96 px 之间')
    if not max(400, options.font_size * 12) <= options.max_page_height <= 32000:
        raise ValueError('单页高度不足或超过 32000 px')
    if options.theme not in {'dark', 'light'}:
        raise ValueError('报告主题须为 dark 或 light')


def compose_report(selection: ReportSelection, options: ReportOptions | None = None) -> ReportDocument:
    """Freeze the already calculated profile values; never calculate game values."""
    options = deepcopy(options or ReportOptions())
    validate_options(options)
    names = [p.name for p in selection.operators]
    default = names[0] if len(names) == 1 and not selection.modules else '干员与模组资料'
    document = ReportDocument(options.title or default, deepcopy(selection.operators), deepcopy(selection.modules), options,
        {'template_version': TEMPLATE_VERSION, 'generated_at': datetime.now().astimezone().isoformat(timespec='seconds'),
         'changes': as_jsonable(deepcopy(selection.changes)) if selection.changes else None,
         'evidence_boundary': '资料由所选本地数据快照生成；数值由领域模型提供，报告不重新计算。'})
    restrict_changes(document)
    return document


def restrict_changes(document: ReportDocument) -> None:
    """Keep comparison rows scoped to the entities actually present in this page."""
    changes = document.metadata.get('changes')
    if not changes:
        return
    operators = {profile.char_id for profile in document.operators}
    modules = {profile.equip_id for profile in document.modules}
    modules.update(module.get('equip_id', module.get('id')) for profile in document.operators for module in profile.modules)
    changes['operators'] = [c for c in changes.get('operators', []) if c.get('char_id', c.get('id')) in operators]
    changes['modules'] = [c for c in changes.get('modules', []) if c.get('equip_id', c.get('id')) in modules]
