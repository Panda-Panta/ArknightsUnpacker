"""The shared style source has two usable palettes and preserves all report data."""
import json

import pytest

from arknights_unpacker.contracts import ModuleProfile, OperatorProfile, ReportDocument


@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_runtime_colors_and_css_come_from_the_same_resource(theme):
    from arknights_unpacker.reports.style import theme_colors, theme_css
    from arknights_unpacker.paths import resource_root
    source = json.loads((resource_root() / 'resources/report_styles.json').read_text('utf-8'))
    colors = theme_colors(theme)
    assert colors == source['themes'][theme]
    css = theme_css(theme)
    assert f'color-scheme: {theme}' in css
    for role, color in colors.items():
        assert f'--{role.replace("_", "-")}: {color}' in css
    colors['paper'] = '#123456'
    assert theme_colors(theme)['paper'] == source['themes'][theme]['paper']


def test_palettes_keep_body_text_readable_and_are_visibly_different():
    from arknights_unpacker.reports.style import theme_colors
    def luminance(color):
        channels = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]
        linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
        return sum(v * w for v, w in zip(linear, (.2126, .7152, .0722)))
    for theme in ('light', 'dark'):
        colors = theme_colors(theme)
        for foreground in ('ink', 'muted'):
            values = sorted((luminance(colors[foreground]), luminance(colors['paper'])))
            assert (values[1] + .05) / (values[0] + .05) >= 4.5
    assert theme_colors('light')['paper'] != theme_colors('dark')['paper']


def test_shared_group_order_contains_each_semantic_block_once():
    from arknights_unpacker.reports.style import ordered_groups, REPORT_GROUPS
    from arknights_unpacker.reports.model import semantic_blocks
    doc = ReportDocument('资料', [OperatorProfile('one', '甲', skills=[{'name':'技能甲'}])],
                         [ModuleProfile('eq', 'one', '甲', '模组甲')])
    grouped = ordered_groups(doc)
    flattened = [block for _, _, _, blocks in grouped for _, block in blocks]
    expected = semantic_blocks(doc)
    assert len(flattened) == len(expected)
    assert sorted(repr(block) for block in flattened) == sorted(repr(block) for block in expected)
    assert [group for group, _, _, _ in grouped] == [group for group, _, _ in REPORT_GROUPS if any(b.group == group for b in expected)]
