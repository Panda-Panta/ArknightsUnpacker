"""Skills and module matrices stay continuous without selection controls."""
from dataclasses import dataclass, field
from html.parser import HTMLParser

import pytest

from arknights_unpacker.contracts import ReportDocument, ReportOptions
from arknights_unpacker.reports import html_render
from arknights_unpacker.reports.model import Block


@dataclass
class Element:
    tag: str
    attrs: dict
    children: list = field(default_factory=list)

    @property
    def text(self):
        return ''.join(child.text if isinstance(child, Element) else child for child in self.children)

    def descendants(self, *, tag=None, attribute=None):
        output = []
        for child in self.children:
            if isinstance(child, Element):
                if (tag is None or child.tag == tag) and (attribute is None or attribute in child.attrs):
                    output.append(child)
                output.extend(child.descendants(tag=tag, attribute=attribute))
        return output


class Page(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.root = Element('', {})
        self.stack = [self.root]
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        element = Element(tag, dict(attrs))
        self.stack[-1].children.append(element)
        if tag not in {'meta', 'img', 'br', 'hr', 'input', 'link', 'wbr'}:
            self.stack.append(element)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


KINDS = ('module-attributes', 'module-effects', 'module-potential', 'module-summons', 'module-conditions')
HEADINGS = ('属性', '特性与天赋', '潜能分支', '召唤物效果', '生效条件')
COLUMNS = ['项目', '未装备', '1级', '2级', '3级']


def module_blocks(key, name):
    items = [Block(name, [('培养口径', '精英2 Lv.90 · 潜能1'), ('适用条件', '本体与指定召唤物')],
                   group='模组', entry_id=key, entry_title=name, kind='module-info')]
    for kind, heading in zip(KINDS, HEADINGS):
        items.append(Block(heading, columns=COLUMNS,
            cells=[[heading + '项目', '未装备完整值', '1级新增值', '同1级', '3级完整值 <保留 & 转义>']],
            group='模组', entry_id=key, entry_title=name, kind=kind))
    return items


@pytest.fixture
def render(monkeypatch):
    modules = [*module_blocks('equip_second', '乙 · X · 第二模组'),
               *module_blocks('equip_first', '甲 · Y · 第一模组')]
    skills = [Block('技能甲', [('说明', '技能甲正文')], group='技能', entry_id='skill_a', entry_title='技能甲'),
              Block('技能乙', [('说明', '技能乙正文')], group='技能', entry_id='skill_b', entry_title='技能乙')]
    indexed = list(enumerate([*skills, *modules]))
    monkeypatch.setattr(html_render, 'ordered_groups', lambda document: [
        ('技能', 'skills', '技能', indexed[:2]), ('模组', 'modules', '模组', indexed[2:]),
    ])
    return lambda theme='dark': html_render.render_html(ReportDocument('紧凑模组合集', options=ReportOptions(theme=theme)))


@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_all_module_categories_share_one_continuous_matrix_per_category(render, theme):
    output = render(theme)
    page = Page(output).root
    modules = page.descendants(attribute='data-module')
    assert [module.attrs['data-module'] for module in modules] == ['equip_second', 'equip_first']
    assert all(module.tag == 'article' and 'hidden' not in module.attrs for module in modules)
    for module in modules:
        assert len(module.descendants(tag='details')) == 1
        assert 'open' in module.descendants(tag='details')[0].attrs
        assert len(module.descendants(tag='h3')) == 1
        assert [heading.text for heading in module.descendants(tag='h4')] == list(HEADINGS)
        blocks = module.descendants(attribute='data-report-block')
        assert [block.attrs['data-module-kind'] for block in blocks] == ['module-info', *KINDS]
        matrices = module.descendants(attribute='data-module-matrix')
        assert len(matrices) == len(KINDS)
        for matrix, heading in zip(matrices, HEADINGS):
            assert matrix.tag == 'table'
            assert [cell.text for cell in matrix.descendants(tag='thead')[0].descendants(tag='th')] == COLUMNS
            row = matrix.descendants(tag='tbody')[0].descendants(tag='tr')[0]
            assert [cell.text for cell in row.children if isinstance(cell, Element)] == [
                heading + '项目', '未装备完整值', '1级新增值', '同1级', '3级完整值 <保留 & 转义>',
            ]
            assert row.children[0].tag == 'th' and row.children[0].attrs['scope'] == 'row'
    assert '&lt;保留 &amp; 转义&gt;' in output
    assert 'data-module-stage' not in output and 'data-stage-controls' not in output


def test_module_directory_uses_native_anchors_without_hiding_any_module(render):
    page = Page(render()).root
    modules = page.descendants(attribute='data-module')
    directories = [nav for nav in page.descendants(tag='nav') if nav.attrs.get('class') == 'module-directory']
    assert len(directories) == 1
    assert 'js-only' not in directories[0].attrs.get('class', '')
    links = directories[0].descendants(tag='a')
    assert [link.attrs['href'] for link in links] == ['#' + module.attrs['id'] for module in modules]
    assert [link.text for link in links] == ['乙 · X · 第二模组', '甲 · Y · 第一模组']
    assert not any(node.attrs.get('data-group') == '模组' for node in page.descendants())


def test_all_skills_and_module_matrices_stay_visible_without_selection_controls(render):
    page = Page(render()).root
    groups = [node for node in page.descendants() if 'data-group' in node.attrs]
    assert not groups
    skills = page.descendants(attribute='data-skill')
    assert [skill.attrs['data-skill'] for skill in skills] == ['skill_a', 'skill_b']
    assert all('hidden' not in skill.attrs for skill in skills)
    assert all('open' in detail.attrs for skill in skills for detail in skill.descendants(tag='details'))
    directories = [nav for nav in page.descendants(tag='nav') if nav.attrs.get('class') == 'skill-directory']
    assert len(directories) == 1
    assert [link.attrs['href'] for link in directories[0].descendants(tag='a')] == ['#' + skill.attrs['id'] for skill in skills]
    assert not page.descendants(attribute='data-tab')
    assert not page.descendants(attribute='data-stage')
    assert {button.attrs.get('id') for button in page.descendants(tag='button')} >= {
        'clear-search', 'expand-all', 'collapse-all', 'print-report',
    }
    assert all('hidden' not in node.attrs for node in page.descendants(attribute='data-module-matrix'))
