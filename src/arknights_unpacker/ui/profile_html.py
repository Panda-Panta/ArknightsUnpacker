"""Render profile semantic blocks for Qt rich text."""
from html import escape

from arknights_unpacker.contracts import ModuleProfile, OperatorProfile, ReportDocument
from arknights_unpacker.reports.model import semantic_blocks


def _escaped_text(text):
    return escape(str(text), quote=True).replace('\n', '<br>')


PROFILE_ANCHOR_PREFIX = 'profile-section-'


def blocks_html(blocks, *, anchor_prefix=None):
    """Qt's rich text subset: no scripts, remote assets, or recursive raw evidence."""
    parts = []
    for index, block in enumerate(blocks, 1):
        anchor = '<a name="' + _escaped_text(f'{anchor_prefix}{index}') + '"></a>' if anchor_prefix else ''
        parts.append('<h2>' + anchor + _escaped_text(block.title) + '</h2>')
        if block.rows:
            parts.append('<table border="1" cellspacing="0" cellpadding="5" width="100%">')
            for key, text in block.rows:
                parts.append('<tr><th align="left" valign="top">' + _escaped_text(key) + '</th><td>' + _escaped_text(text) + '</td></tr>')
            parts.append('</table>')
        if block.columns:
            parts.append('<table border="1" cellspacing="0" cellpadding="4" width="100%"><tr>')
            parts.extend('<th>' + _escaped_text(column) + '</th>' for column in block.columns)
            parts.append('</tr>')
            for row in block.cells:
                parts.append('<tr>' + ''.join('<td>' + _escaped_text(cell) + '</td>' for cell in row) + '</tr>')
            parts.append('</table>')
        parts.extend('<p style="font-size:10px; color:#607786;"><b>' + _escaped_text(term) + '：</b>'
                     + _escaped_text(text) + '</p>' for term, text in block.notes)
    return ''.join(parts)


def profile_html(profile, *, blocks=None):
    document = ReportDocument(title=profile.name,
        operators=[profile] if isinstance(profile, OperatorProfile) else [],
        modules=[profile] if isinstance(profile, ModuleProfile) else [])
    if blocks is None:
        blocks = semantic_blocks(document)
    badge = '<div style="font-size:10px; font-weight:700; color:#0093a2; letter-spacing:1px; margin-bottom:4px;">PRTS // LOCAL DOSSIER ARCHIVE</div>'
    body = '<a name="' + PROFILE_ANCHOR_PREFIX + '0"></a>' + badge + '<h1>' + _escaped_text(document.title) + '</h1>' + blocks_html(blocks, anchor_prefix=PROFILE_ANCHOR_PREFIX)
    body += '<p class="footer-note">完整来源、字段读取证据及原始结构随 JSON 资料保存。</p>'
    css = (
        'body { font-family: -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei UI", sans-serif; color: #1c2834; background-color: #ffffff; padding: 6px; } '
        'h1 { font-size: 22px; font-weight: 700; color: #14222e; margin: 0 0 16px 0; padding-bottom: 8px; border-bottom: 2px solid #0093a2; } '
        'h2 { font-size: 15px; font-weight: 600; color: #1b3848; margin-top: 20px; margin-bottom: 8px; padding-left: 8px; border-left: 4px solid #0093a2; } '
        'table { border-collapse: collapse; border: 1px solid #d4dfe7; margin-bottom: 12px; } '
        'th { background-color: #f0f5f8; color: #2e4758; font-weight: 600; padding: 6px 10px; border: 1px solid #d4dfe7; font-size: 12px; } '
        'td { background-color: #ffffff; color: #1c2834; padding: 6px 10px; border: 1px solid #d4dfe7; font-size: 12px; line-height: 150%; } '
        'p { line-height: 150%; margin: 6px 0; } '
        '.footer-note { color: #607786; font-size: 11px; margin-top: 18px; border-top: 1px dashed #d4dfe7; padding-top: 8px; }'
    )
    return '<html><head><style>' + css + '</style></head><body>' + body + '</body></html>'
