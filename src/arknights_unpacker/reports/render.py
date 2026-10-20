"""Pillow CJK renderer: no Qt application or main-thread requirement."""
from dataclasses import dataclass, field
from pathlib import Path
import math
import os

from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo

from ..contracts import ReportDocument, CancelToken, null_progress
from .style import ordered_groups, style_version, theme_colors, typography

MAX_SINGLE_IMAGE_PIXELS = 80_000_000


@dataclass
class DrawLine:
    text: str
    height: int
    kind: str = 'body'
    continued: bool = False
    cells: list[str] = field(default_factory=list)
    column_labels: list[str] = field(default_factory=list)
    column_widths: list[int] = field(default_factory=list)
    padding_top: int = 0
    padding_bottom: int = 0
    first: bool = False
    last: bool = False
    row_index: int = -1
    group: str = ''
    inset: int = 0


def _font(size: int, bold: bool = False):
    candidates = [
        Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / ('msyhbd.ttc' if bold else 'msyh.ttc'),
        Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'),
        Path('/usr/share/fonts/truetype/wqy/wqy-microhei.ttc'),
        Path('/System/Library/Fonts/PingFang.ttc'),
    ]
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    raise RuntimeError('未找到中文字体。请安装微软雅黑、苹方或 Noto Sans CJK 后重试。')


def wrap_text(text: str, font, width: int, *, cancel: CancelToken | None = None) -> list[str]:
    """Measure CJK and Latin glyphs; each source character appears exactly once."""
    lines = []
    for paragraph in str(text).split('\n'):
        if not paragraph:
            lines.append('')
            continue
        current = ''
        for index, character in enumerate(paragraph):
            if cancel and index % 128 == 0:
                cancel.check()
            candidate = current + character
            bounds = font.getbbox(candidate)
            measured_width = max(font.getlength(candidate), bounds[2] - min(0, bounds[0]))
            if current and measured_width > width:
                lines.append(current)
                current = character
            else:
                current = candidate
        if current:
            lines.append(current)
    return lines


class _Layout:
    """Measure once with the fonts that will actually paint every line."""
    def __init__(self, options):
        type_style = typography()
        self.body = _font(options.font_size)
        self.table_heading = _font(options.font_size, True)
        self.heading = _font(round(options.font_size * type_style['heading_scale']), True)
        self.section = _font(round(options.font_size * type_style['section_scale']), True)
        self.title = _font(round(options.font_size * type_style['title_scale']), True)
        # Fixed page furniture stays readable even at the 320px/96px extreme.
        self.caption = _font(max(10, min(22, round(options.font_size * type_style['caption_scale']))))
        self.margin = min(48, options.width // 14)
        self.width = options.width - self.margin * 2
        self.padding = min(14, max(6, round(options.font_size * .35)))
        self.gap = max(6, round(options.font_size * .22))
        self.chrome_padding = min(24, max(12, options.font_size // 2))
        self.body_height = math.ceil(options.font_size * type_style['line_height'])
        self.heading_height = math.ceil(self.heading.size * 1.35)
        self.section_height = math.ceil(self.section.size * 1.3)
        self.title_height = math.ceil(self.title.size * 1.35)
        self.caption_height = math.ceil(self.caption.size * type_style['line_height'])
        self.header_height = self.caption_height + self.chrome_padding * 2
        self.footer_height = self.caption_height + self.chrome_padding * 2
        self.page_height = min(options.max_page_height, 20_000_000 // options.width)
        self.capacity = self.page_height - self.header_height - self.footer_height


def _table_widths(width: int, count: int, label_width: int | None = None) -> list[int]:
    if label_width is not None:
        state_width, remainder = divmod(width - label_width, count - 1)
        return [label_width] + [state_width + (index < remainder) for index in range(count - 1)]
    weights = [1.6] + [1] * (count - 1)
    widths = [int(width * weight / sum(weights)) for weight in weights]
    widths[-1] += width - sum(widths)
    return widths


def _text_y(font, text: str, y: int, height: int) -> int:
    bounds = font.getbbox(text, anchor='lt')
    return y + (height - (bounds[3] - bounds[1])) // 2 - bounds[1]


def _block_lines(block, layout: _Layout, cancel) -> list[DrawLine]:
    lines = []
    compact = block.kind.startswith('module-')
    inset = max(5, min(layout.padding, round(layout.body.size * .28))) if compact else layout.padding
    padding = max(4, layout.padding // 2)
    gap = layout.gap
    body_height = layout.body_height
    heading_height = layout.heading_height

    def fitted_height(texts, font, minimum):
        # Compact spacing must still contain the actual glyphs, including Latin
        # descenders and combining marks, rather than assuming font.size bounds.
        return max(minimum, max((font.getbbox(text, anchor='lt')[3] -
                                font.getbbox(text, anchor='lt')[1] for text in texts), default=0) + 4)

    heading = wrap_text(block.title, layout.heading, layout.width - inset * 2, cancel=cancel)
    for index, text in enumerate(heading):
        top = padding if index == 0 else 0
        bottom = padding if index == len(heading) - 1 else 0
        lines.append(DrawLine(text, fitted_height([text], layout.heading, heading_height) + top + bottom,
            'warning-heading' if block.group == '草稿警告' else 'heading',
            padding_top=top, padding_bottom=bottom, first=index == 0,
            last=index == len(heading) - 1, group=block.group, inset=inset))

    def add_row(key, value, row_index=-1):
        wrapped = wrap_text(f'{key}：{value}', layout.body, layout.width - inset * 2, cancel=cancel)
        for index, text in enumerate(wrapped):
            lines.append(DrawLine(text, fitted_height([text], layout.body, body_height),
                'potential' if '潜能' in key else 'body', index > 0,
                first=index == 0, last=index == len(wrapped) - 1,
                row_index=row_index, group=block.group, inset=inset))

    for row_index, (key, value) in enumerate(block.rows):
        add_row(key, value, row_index)
    if block.columns:
        if layout.width >= (len(block.columns) * 3 + 4) * layout.body.size:
            label_width = None
            if compact and len(block.columns) == 5:
                labels = [block.columns[0], *(str(row[0]) for row in block.cells if row)]
                measured = max(layout.body.getlength(part) for label in labels for part in label.split('\n'))
                maximum = round(layout.width * .17)
                minimum = min(maximum, math.ceil(layout.body.size * 3 + inset * 2))
                label_width = min(maximum, max(minimum, math.ceil(measured) + inset * 2))
            widths = _table_widths(layout.width, len(block.columns), label_width)
            for row_index, row in enumerate([block.columns, *block.cells]):
                font = layout.table_heading if row_index == 0 else layout.body
                wrapped = [wrap_text(str(row[column]) if column < len(row) else '', font,
                                     width - inset * 2, cancel=cancel)
                           for column, width in enumerate(widths)]
                fragments = max(map(len, wrapped), default=1)
                for part in range(fragments):
                    cells = [values[part] if part < len(values) else '' for values in wrapped]
                    lines.append(DrawLine(' | '.join(cells), fitted_height(cells, font, body_height),
                        'table-header' if row_index == 0 else 'table', cells=cells,
                        column_labels=block.columns, column_widths=widths,
                        first=part == 0, last=part == fragments - 1,
                        row_index=row_index - 1, group=block.group, inset=inset))
        else:
            # Preserve the labeled fallback rather than compressing seven columns.
            for row_index, row in enumerate(block.cells):
                for column, key in enumerate(block.columns):
                    add_row(key, str(row[column]) if column < len(row) else '', row_index)
                lines.append(DrawLine('', max(4, gap // 2), 'separator', group=block.group))
    lines.append(DrawLine('', padding + gap, 'card-end', padding_bottom=gap,
                          group=block.group))
    return lines


def layout_pages(document: ReportDocument, *, cancel: CancelToken | None = None, emit=null_progress) -> list[list[DrawLine]]:
    options = document.options
    single_module_image = bool(document.modules) and not document.operators and options.module_image_layout == 'single'
    layout = _Layout(options)
    capacity = None if single_module_image else layout.capacity
    pages: list[list[DrawLine]] = []
    current: list[DrawLine] = []
    used = 0

    def add(line: DrawLine):
        nonlocal current, used
        if cancel:
            cancel.check()
        if capacity is not None and used + line.height > capacity and current:
            pages.append(current)
            current, used = [], 0
            # An empty card tail must not create a page containing only whitespace.
            if line.kind == 'card-end':
                return
        if capacity is not None and line.height > capacity:
            raise ValueError('图片分页空间不足。请增加单页高度或减小字号。')
        current.append(line)
        used += line.height

    def keep_with_content(required):
        nonlocal current, used
        if capacity is not None and current and required <= capacity and used + required > capacity:
            pages.append(current)
            current, used = [], 0

    # The full source title participates in pagination, even when it alone needs
    # several pages. A short masthead is repeated without duplicating source text.
    for text in wrap_text(document.title, layout.title, layout.width, cancel=cancel):
        add(DrawLine(text, layout.title_height, 'title'))
    add(DrawLine('', layout.chrome_padding + layout.gap, 'title-end', padding_bottom=layout.gap))
    groups = ordered_groups(document)
    total = sum(len(blocks) for _, _, _, blocks in groups)
    block_index = 0
    for group, _, title, blocks in groups:
        section = wrap_text(title, layout.section, layout.width - 16, cancel=cancel)
        section_lines = [DrawLine(text, layout.section_height + (layout.gap if index == 0 else 0) +
                                 (layout.gap if index == len(section) - 1 else 0), 'section',
                                 padding_top=layout.gap if index == 0 else 0,
                                 padding_bottom=layout.gap if index == len(section) - 1 else 0,
                                 last=index == len(section) - 1, group=group)
                         for index, text in enumerate(section)]
        for group_index, (_, block) in enumerate(blocks):
            if cancel:
                cancel.check()
            block_index += 1
            emit({'kind':'progress','stage':'report_layout','current':block_index,'total':total,'message':block.title})
            lines = _block_lines(block, layout, cancel)
            heading_size = sum(line.height for line in lines if line.kind in {'heading', 'warning-heading'})
            first_content = next((line.height for line in lines if line.kind not in {'heading', 'warning-heading'}), 0)
            if group_index == 0:
                keep_with_content(sum(line.height for line in section_lines) + heading_size + first_content)
                for line in section_lines:
                    add(line)
            keep_with_content(heading_size + first_content)
            for line in lines:
                add(line)
    if current:
        pages.append(current)
    return pages


def render_png(document: ReportDocument, directory: Path, stem: str, *, cancel: CancelToken | None = None,
               emit=null_progress, on_page=None) -> list[Path]:
    options = document.options
    single_module_image = bool(document.modules) and not document.operators and options.module_image_layout == 'single'
    pages = layout_pages(document, cancel=cancel, emit=emit)
    colors = theme_colors(options.theme)
    layout = _Layout(options)
    margin = layout.margin
    right = options.width - margin
    paths = []
    for index, lines in enumerate(pages, 1):
        if cancel:
            cancel.check()
        emit({'kind':'progress','stage':'report_png','current':index,'total':len(pages),'message':f'{document.title} · 第{index}页'})
        if cancel:
            cancel.check()
        height = layout.header_height + layout.footer_height + sum(line.height for line in lines)
        if not single_module_image and height > layout.page_height:
            raise ValueError('图片排版超过单页高度，未生成裁切图片。请增加单页高度或减小字号。')
        # RGB alone needs three bytes per pixel, with extra drawing/PNG buffers.
        # Refuse an excessive single canvas before allocating it; silently
        # splitting or clipping here would violate the requested layout.
        if single_module_image and options.width * height > MAX_SINGLE_IMAGE_PIXELS:
            raise ValueError(f'模组单张图片过大（{options.width:,} × {height:,}），超过 {MAX_SINGLE_IMAGE_PIXELS:,} 像素上限。请改用分页排版或减少所选模组。')
        path = directory / f'{stem}_p{index:02d}.png'
        temporary = path.with_suffix('.png.tmp')
        image = None
        try:
            try:
                image = Image.new('RGB', (options.width, height), colors['canvas'])
            except MemoryError as error:
                if single_module_image:
                    raise ValueError('内存不足，无法生成模组单张长图。请改用分页排版或减少所选模组。') from error
                raise
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 0, options.width, layout.header_height), fill=colors['bar'])
            draw.text((margin, layout.chrome_padding), 'ARKNIGHTS / 本地资料',
                      font=layout.caption, fill=colors['bar_muted'], anchor='lt')
            if not lines or lines[0].kind != 'title':
                draw.line((0, layout.header_height - 2, options.width, layout.header_height - 2),
                          fill=colors['accent'], width=3)
            y = layout.header_height
            for line_index, line in enumerate(lines):
                if cancel:
                    cancel.check()
                bottom = y + line.height
                if line.kind == 'title':
                    draw.rectangle((0, y, options.width, bottom), fill=colors['bar'])
                    draw.text((margin, y + (line.height - layout.title.size) // 2), line.text,
                              font=layout.title, fill=colors['bar_ink'], anchor='lt')
                elif line.kind == 'title-end':
                    end = bottom - line.padding_bottom
                    draw.rectangle((0, y, options.width, end), fill=colors['bar'])
                    draw.line((0, end - 2, options.width, end - 2), fill=colors['accent'], width=3)
                elif line.kind == 'section':
                    text_y = y + line.padding_top + (layout.section_height - layout.section.size) // 2
                    draw.text((margin + 12, text_y), line.text, font=layout.section,
                              fill=colors['accent_dark'], anchor='lt')
                    draw.rectangle((margin, text_y, margin + 4, text_y + layout.section.size), fill=colors['accent'])
                    if line.last:
                        draw.line((margin, bottom - 4, right, bottom - 4), fill=colors['accent'], width=2)
                elif line.kind in {'heading','warning-heading'}:
                    is_warning = line.kind == 'warning-heading'
                    border = colors['warning_rule'] if is_warning else colors['rule']
                    draw.rectangle((margin, y, right, bottom),
                                   fill=colors['warning_bg'] if is_warning else colors['header'])
                    draw.line((margin, y, margin, bottom), fill=border)
                    draw.line((right, y, right, bottom), fill=border)
                    if line.first or line_index == 0:
                        draw.line((margin, y, right, y), fill=border)
                    if line.last:
                        draw.line((margin, bottom - 1, right, bottom - 1), fill=border)
                    text_y = _text_y(layout.heading, line.text, y + line.padding_top,
                                     line.height - line.padding_top - line.padding_bottom)
                    draw.text((margin + (line.inset or layout.padding), text_y), line.text, font=layout.heading,
                              fill=colors['warning_ink'] if is_warning else colors['header_ink'], anchor='lt')
                elif line.kind in {'table','table-header'}:
                    x = margin
                    for column_index,(cell,width) in enumerate(zip(line.cells,line.column_widths)):
                        is_h = line.kind == 'table-header'
                        cell_bg = colors['header'] if is_h else colors['table_alt'] if line.row_index % 2 else colors['paper']
                        draw.rectangle((x, y, x + width, bottom), fill=cell_bg)
                        draw.line((x, y, x, bottom), fill=colors['rule'])
                        draw.line((x + width, y, x + width, bottom), fill=colors['rule'])
                        if line.first or line_index == 0:
                            draw.line((x, y, x + width, y), fill=colors['rule'])
                        if line.last:
                            draw.line((x, bottom - 1, x + width, bottom - 1), fill=colors['rule'])
                        is_pot = line.column_labels[column_index] == '潜能'
                        if cell:
                            font = layout.table_heading if is_h else layout.body
                            draw.text((x + (line.inset or layout.padding), _text_y(font, cell, y, line.height)), cell,
                                      font=font,
                                      fill=colors['gold'] if is_pot else colors['header_ink'] if is_h else colors['ink'], anchor='lt')
                        x += width
                elif line.kind == 'card-end':
                    end = bottom - line.padding_bottom
                    warning = line.group == '草稿警告'
                    border = colors['warning_rule'] if warning else colors['rule']
                    draw.rectangle((margin, y, right, end), fill=colors['warning_bg'] if warning else colors['paper'])
                    draw.line((margin, y, margin, end), fill=border)
                    draw.line((right, y, right, end), fill=border)
                    draw.line((margin, end, right, end), fill=border)
                elif line.kind == 'separator':
                    draw.rectangle((margin, y, right, bottom), fill=colors['paper'])
                    draw.line((margin, y, margin, bottom), fill=colors['rule'])
                    draw.line((right, y, right, bottom), fill=colors['rule'])
                    draw.line((margin, y + line.height // 2, right, y + line.height // 2), fill=colors['rule'])
                else:
                    warning = line.group == '草稿警告'
                    border = colors['warning_rule'] if warning else colors['rule']
                    background = (colors['warning_bg'] if warning else colors['gold_bg'] if line.kind == 'potential'
                                  else colors['table_alt'] if line.row_index % 2 else colors['paper'])
                    draw.rectangle((margin, y, right, bottom), fill=background)
                    draw.line((margin, y, margin, bottom), fill=border)
                    draw.line((right, y, right, bottom), fill=border)
                    if line.first or line_index == 0:
                        draw.line((margin, y, right, y), fill=border)
                    if line.text:
                        draw.text((margin + (line.inset or layout.padding), _text_y(layout.body, line.text, y, line.height)), line.text,
                                  font=layout.body, fill=colors['warning_ink'] if warning else colors['gold']
                                  if line.kind == 'potential' else colors['ink'], anchor='lt')
                if line_index == len(lines) - 1 and line.kind in {'body', 'potential', 'table', 'table-header', 'heading', 'warning-heading'}:
                    draw.line((margin, bottom - 1, right, bottom - 1), fill=colors['rule'])
                y = bottom
            footer = f'第 {index} / {len(pages)} 页'
            full_footer = footer + ' · 本地数据快照'
            if layout.caption.getlength(full_footer) <= layout.width:
                footer = full_footer
            footer_y = height - layout.footer_height
            draw.line((margin, footer_y + 3, right, footer_y + 3), fill=colors['rule'])
            draw.text((margin, footer_y + layout.chrome_padding), footer,
                      font=layout.caption, fill=colors['muted'], anchor='lt')
            if cancel:
                cancel.check()
            info = PngInfo()
            info.add_text('report_theme', options.theme)
            info.add_text('report_style', style_version())
            image.save(temporary, format='PNG', optimize=False, pnginfo=info)
            if cancel:
                cancel.check()
            temporary.replace(path)
        finally:
            if image is not None:
                image.close()
            temporary.unlink(missing_ok=True)
        paths.append(path)
        if on_page:
            on_page(path, len(pages))
    return paths
