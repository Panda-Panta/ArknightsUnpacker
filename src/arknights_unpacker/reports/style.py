"""Runtime visual tokens and section hierarchy shared by the two report formats."""
from functools import lru_cache
import json

from ..paths import resource_root
from .model import semantic_blocks


REPORT_GROUPS = (
    ('草稿警告', 'notice', '阅读提示'), ('概览', 'overview', '干员信息'),
    ('特性', 'trait', '特性'), ('属性', 'attributes', '属性与加成'),
    ('天赋', 'talents', '天赋'), ('技能', 'skills', '技能'),
    ('后勤', 'building', '后勤技能'), ('潜能', 'potentials', '潜能提升'),
    ('模组', 'modules', '模组'),
    ('', 'notes', '提示'),
)


@lru_cache(maxsize=1)
def _source():
    return json.loads((resource_root() / 'resources/report_styles.json').read_text(encoding='utf-8'))


def theme_colors(theme: str) -> dict[str, str]:
    if theme not in ('light', 'dark'):
        raise ValueError('资料导出主题须为 light 或 dark')
    return dict(_source()['themes'][theme])


def typography() -> dict:
    return dict(_source()['typography'])


def style_version() -> str:
    return _source()['style_version']


def theme_css(theme: str) -> str:
    variables = {key.replace('_', '-'): value for key, value in theme_colors(theme).items()}
    variables.update({key.replace('_', '-'): value for key, value in typography().items()})
    declarations = ';\n'.join(f'--{key}: {value}' for key, value in variables.items())
    return f'/* report-style {style_version()} */\n:root {{ color-scheme: {theme};\n{declarations};\n}}'


def ordered_groups(document):
    """Return (group, anchor, title, indexed blocks), preserving all source blocks."""
    blocks = semantic_blocks(document)
    definitions = list(REPORT_GROUPS)
    known = {group for group, _, _ in definitions}
    for block in blocks:
        if block.group not in known:
            definitions.append((block.group, f'additional-{len(definitions)}', block.group or '资料'))
            known.add(block.group)
    return [(group, anchor, title, [(index, block) for index, block in enumerate(blocks) if block.group == group])
            for group, anchor, title in definitions if any(block.group == group for block in blocks)]
