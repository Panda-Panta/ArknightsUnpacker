"""Offline reference pages with continuous skills and compact module matrices."""
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
        '<p class="eyebrow">LOCAL DOSSIER <span>本地资料快照</span></p><h1>' + _e(document.title or '干员与模组资料') + '</h1>' + \
        '<div class="identity-tags">' + badges + '</div>' + \
        (f'<p class="snapshot-label">游戏数据版本 {_e(version)}</p>' if version else '') + '</div></header>'


def _tables(block: Block, *, matrix: bool = False) -> str:
    rows = ''.join(f'<tr><th scope="row" class="key">{_e(key)}</th>'
                   f'<td class="{"potential" if "潜能" in key else ""}">{_e(value)}</td></tr>'
                   for key, value in block.rows)
    table = f'<table><tbody>{rows}</tbody></table>' if rows else ''
    if block.columns:
        heads = ''.join(f'<th scope="col">{_e(column)}</th>' for column in block.columns)
        cells = []
        for row in block.cells:
            values = []
            for column, value in enumerate(row):
                if matrix and column == 0:
                    values.append(f'<th scope="row">{_e(value)}</th>')
                else:
                    potential = 'potential' if block.columns[column] == '潜能' else ''
                    values.append(f'<td class="{potential}">{_e(value)}</td>')
            cells.append('<tr>' + ''.join(values) + '</tr>')
        attributes = 'class="module-matrix" data-module-matrix' if matrix else 'class="attributes"'
        label = _e(block.title)
        table += (f'<div class="table-area"><div class="table-wrap" tabindex="0" role="region" '
                  f'aria-label="{label}表格，可横向滚动"><table {attributes} aria-label="{label}">'
                  f'<thead><tr>{heads}</tr></thead><tbody>{"".join(cells)}</tbody></table></div>'
                  '<p class="table-hint" aria-hidden="true">← 左右滚动查看全部列 · 聚焦表格后可使用方向键 →</p></div>')
    return table


def _block(index: int, block: Block, heading: str = 'h3') -> str:
    return f'<div class="report-block" data-report-block id="block-{index}"><details class="block" open>' + \
        f'<summary><{heading}>{_e(block.title)}</{heading}><span class="fold-label" aria-hidden="true">展开 / 收起</span></summary>' + \
        f'<div class="block-body">{_tables(block)}</div></details></div>'


def _entries(items):
    entries = OrderedDict()
    for index, block in items:
        if block.entry_id:
            entries.setdefault(block.entry_id, []).append((index, block))
    return entries


def _entry_directory(entries, prefix: str, label: str) -> str:
    if len(entries) < 2:
        return ''
    links = ''.join(f'<a href="#{prefix}-{children[0][0]}">{_e(children[0][1].entry_title)}</a>'
                    for children in entries.values())
    return f'<nav class="{prefix}-directory" aria-label="{label}目录">{links}</nav>'


def _skills(items) -> str:
    entries = _entries(items)
    output = [_entry_directory(entries, 'skill', '技能')]
    for key, children in entries.items():
        title = children[0][1].entry_title
        output.append(f'<div class="entry-panel skill-panel" id="skill-{children[0][0]}" '
                      f'data-skill="{_e(key)}" data-entry-title="{_e(title)}">')
        output.extend(_block(index, block) for index, block in children)
        output.append('</div>')
    output.extend(_block(index, block) for index, block in items if not block.entry_id)
    return ''.join(output)


def _modules(items) -> str:
    entries = _entries(items)
    output = [_entry_directory(entries, 'module', '模组')]
    for key, children in entries.items():
        first_index = children[0][0]
        title = children[0][1].entry_title
        output.append(f'<article class="entry-panel module-panel" id="module-{first_index}" '
                      f'data-module="{_e(key)}" data-entry-title="{_e(title)}" aria-labelledby="module-title-{first_index}">'
                      '<details class="block module-details" open><summary>'
                      f'<h3 id="module-title-{first_index}">{_e(title)}</h3>'
                      '<span class="fold-label" aria-hidden="true">展开 / 收起</span></summary>')
        for index, block in children:
            intro = block.kind == 'module-info' or (not block.kind and block.stage is None and block.title == title)
            attributes = ' data-module-intro' if intro else ''
            classes = 'report-block module-block' + (' module-info' if intro else '')
            output.append(f'<section class="{classes}" data-report-block data-module-kind="{_e(block.kind)}"'
                          f'{attributes} id="block-{index}">')
            if not intro:
                output.append(f'<h4>{_e(block.title)}</h4>')
            output.append(f'<div class="block-body">{_tables(block, matrix=True)}</div></section>')
        output.append('</details></article>')
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
            f'<body><main class="index-main"><p class="eyebrow">LOCAL ARCHIVE <span>离线资料目录</span></p><h1>{_e(title)}</h1>'
            f'<p class="index-description">共 {len(entries)} 份资料 · 点击名称打开，移动整个任务文件夹后仍可使用</p>'
            '<div class="table-wrap" tabindex="0" role="region" aria-label="离线资料目录表格，可横向滚动"><table class="index-table"><thead><tr>'
            '<th scope="col">资料</th><th scope="col">职业</th><th scope="col">数据版本</th><th scope="col">状态</th>'
            f'</tr></thead><tbody>{rows}</tbody></table></div></main></body></html>')
