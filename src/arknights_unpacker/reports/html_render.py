"""Offline reference pages with semantic entry/level grouping and inline assets."""
from base64 import b64encode
from collections import OrderedDict
from html import escape
from pathlib import Path
from string import Template
from urllib.parse import quote

from ..contracts import ReportDocument
from ..paths import resource_root
from .model import Block, plain, present
from .style import ordered_groups, theme_css

_ASSETS = resource_root() / 'resources' / 'html'
CSS = (_ASSETS / 'report.css').read_text(encoding='utf-8')
JS = (_ASSETS / 'report.js').read_text(encoding='utf-8')
_PAGE = Template((_ASSETS / 'operator.html').read_text(encoding='utf-8'))


def _e(value) -> str:
    return escape(str(value), quote=True)


def _styles(theme: str) -> str:
    # Exported files stay self-contained. Paper printing always uses the shared
    # light palette while the screen preserves the selected export theme.
    return theme_css(theme) + '\n' + CSS + '\n@media print {\n' + theme_css('light') + '\n}'


def _portrait(document: ReportDocument) -> str:
    if not document.operators:
        return ''
    metadata = document.operators[0].metadata
    path = metadata.get('avatar_path') or metadata.get('portrait_path')
    if path and isinstance(path, str):
        candidate = Path(path)
        if candidate.is_file() and candidate.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp'} and candidate.stat().st_size <= 5 * 1024 * 1024:
            from PIL import Image
            try:
                with Image.open(candidate) as image:
                    image.verify()
                mime = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}[candidate.suffix.lower()]
                uri = f'data:{mime};base64,' + b64encode(candidate.read_bytes()).decode('ascii')
                return f'<img class="portrait" alt="干员肖像" src="{uri}">'
            except (OSError, ValueError):
                pass
    return ''


def _header(document: ReportDocument) -> str:
    chips, version = [], ''
    if len(document.operators) == 1:
        profile = document.operators[0]
        summary = profile.summary
        for key in ('profession', 'rarity', 'phase'):
            if summary.get(key) is not None:
                chips.append(present(key, summary[key]))
        if summary.get('level') is not None:
            chips.append('Lv.' + plain(summary['level']))
        if summary.get('potential') is not None:
            chips.append('潜能 ' + plain(summary['potential']))
        if summary.get('trust') is not None:
            chips.append('信赖 ' + plain(summary['trust']))
        version = profile.metadata.get('version') or ''
    elif document.modules:
        chips.append('模组资料')
        version = document.modules[0].metadata.get('version') or ''
    badges = ''.join(f'<span>{_e(value)}</span>' for value in chips)
    return '<header class="operator-header">' + _portrait(document) + '<div class="operator-identity">' + \
        '<p class="eyebrow">OPERATOR FILE <span>本地资料快照</span></p><h1>' + _e(document.title or '干员与模组资料') + '</h1>' + \
        '<div class="identity-tags">' + badges + '</div>' + \
        (f'<p class="snapshot-label">游戏数据版本 {_e(version)}</p>' if version else '') + '</div></header>'


def _block(index: int, block: Block, heading: str = 'h3', *, module_intro: bool = False) -> str:
    rows = ''.join(f'<tr><th scope="row" class="key">{_e(key)}</th>'
                   f'<td class="{"potential" if "潜能" in key else ""}">{_e(value)}</td></tr>'
                   for key, value in block.rows)
    table = f'<table><tbody>{rows}</tbody></table>' if rows else ''
    if block.columns:
        heads = ''.join(f'<th scope="col">{_e(column)}</th>' for column in block.columns)
        cells = ''.join('<tr>' + ''.join(
            f'<td class="{"potential" if block.columns[column] == "潜能" else ""}">{_e(value)}</td>'
            for column, value in enumerate(row)) + '</tr>' for row in block.cells)
        table += f'<div class="table-wrap"><table class="attributes"><thead><tr>{heads}</tr></thead><tbody>{cells}</tbody></table></div>'
    intro = ' data-module-intro' if module_intro else ''
    return f'<div class="report-block" data-report-block{intro} id="block-{index}"><details class="block" open>' + \
        f'<summary><{heading}>{_e(block.title)}</{heading}><span class="fold-label" aria-hidden="true">展开 / 收起</span></summary>' + \
        f'<div class="block-body">{table}</div></details></div>'


def _entries(items):
    entries = OrderedDict()
    for index, block in items:
        if block.entry_id:
            entries.setdefault(block.entry_id, []).append((index, block))
    return entries


def _controls(group: str, entries, *, show_all=True) -> str:
    if not entries:
        return ''
    buttons = f'<button type="button" data-tab="all" aria-pressed="true">全部{group}</button>' if show_all else ''
    for key, items in entries.items():
        first = items[0][1]
        title = first.title if group == '技能' else first.entry_title
        buttons += f'<button type="button" data-tab="{_e(key)}" aria-pressed="false">{_e(title)}</button>'
    return f'<div class="controls js-only" data-group="{group}" role="group" aria-label="{group}选择">{buttons}</div>'


def _skills(items) -> str:
    entries = _entries(items)
    output = [_controls('技能', entries)]
    for key, children in entries.items():
        title = children[0][1].entry_title
        output.append(f'<div class="entry-panel skill-panel" data-skill="{_e(key)}" data-entry-title="{_e(title)}">')
        output.extend(_block(index, block) for index, block in children)
        output.append('</div>')
    output.extend(_block(index, block) for index, block in items if not block.entry_id)
    return ''.join(output)


def _modules(items) -> str:
    entries = _entries(items)
    output = [_controls('模组', entries, show_all=len(entries) > 1)]
    for key, children in entries.items():
        title = children[0][1].entry_title
        output.append(f'<div class="entry-panel module-panel" data-module="{_e(key)}" data-entry-title="{_e(title)}">')
        output.extend(_block(index, block, module_intro=True) for index, block in children if block.stage is None)
        stages = sorted({block.stage for _, block in children if block.stage is not None})
        if stages:
            buttons = '<button type="button" data-stage="all" aria-pressed="true">全部等级</button>' + ''.join(
                f'<button type="button" data-stage="{level}" aria-pressed="false">{level}级</button>' for level in stages)
            output.append(f'<div class="stage-controls js-only" data-stage-controls role="group" aria-label="{_e(title)}等级">{buttons}</div>')
        for level in stages:
            output.append(f'<div class="module-stage" data-module-stage="{level}">')
            output.extend(_block(index, block, 'h4') for index, block in children if block.stage == level)
            output.append('</div>')
        output.append('</div>')
    output.extend(_block(index, block) for index, block in items if not block.entry_id)
    return ''.join(output)


def render_html(document: ReportDocument) -> str:
    content, directory = [], []
    for group, anchor, title, items in ordered_groups(document):
        directory.append(f'<li><a href="#{anchor}">{_e(title)}</a></li>')
        classes = 'report-section' + (' warning' if group == '草稿警告' else '') + (' auxiliary' if anchor in {'version', 'sources'} else '')
        content.append(f'<section class="{classes}" id="{anchor}" data-report-section data-report-group="{_e(group)}">'
                       f'<h2>{_e(title)}<a class="section-link" href="#{anchor}" aria-label="{_e(title)}分区链接">#</a></h2>')
        if group == '技能':
            content.append(_skills(items))
        elif group == '模组':
            content.append(_modules(items))
        else:
            content.extend(_block(index, block) for index, block in items)
        content.append('</section>')
    return _PAGE.substitute(title=_e(document.title or '干员与模组资料'), theme=_e(document.options.theme),
                            css=_styles(document.options.theme), script=JS,
                            directory=''.join(directory), header=_header(document), content=''.join(content))


def render_index(entries: list[dict[str, str]], title: str, theme: str = 'light') -> str:
    rows = ''.join('<tr>' + f'<td><a href="{quote(entry["path"])}">{_e(entry["title"])}</a></td>' + ''.join(
        f'<td>{_e(entry.get(key, ""))}</td>' for key in ('profession', 'version', 'status')) + '</tr>' for entry in entries)
    return ('<!doctype html>'
            f'<html lang="zh-CN" data-report-theme="{_e(theme)}"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{_e(title)}</title><style>{_styles(theme)}</style></head>'
            f'<body><main class="index-main"><h1>{_e(title)}</h1>'
            '<p>离线资料目录 · 移动整个任务文件夹后仍可使用</p>'
            '<div class="table-wrap"><table><thead><tr>'
            '<th>资料</th><th>职业</th><th>数据版本</th><th>状态</th>'
            f'</tr></thead><tbody>{rows}</tbody></table></div></main></body></html>')
