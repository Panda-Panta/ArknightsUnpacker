"""Pillow CJK renderer: no Qt application or main-thread requirement."""
from dataclasses import dataclass, field
from pathlib import Path
import math
import os

from PIL import Image, ImageDraw, ImageFont

from ..contracts import ReportDocument, CancelToken, null_progress
from .model import semantic_blocks

MAX_SINGLE_IMAGE_PIXELS = 80_000_000


@dataclass
class DrawLine:
    text: str
    height: int
    kind: str = 'body'
    continued: bool = False
    cells: list[str] = field(default_factory=list)
    column_labels: list[str] = field(default_factory=list)


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
            if current and font.getlength(candidate) > width:
                lines.append(current)
                current = character
            else:
                current = candidate
        if current:
            lines.append(current)
    return lines


def layout_pages(document: ReportDocument, *, cancel: CancelToken | None = None, emit=null_progress) -> list[list[DrawLine]]:
    options = document.options
    single_module_image = bool(document.modules) and not document.operators and options.module_image_layout == 'single'
    body_font = _font(options.font_size)
    heading_font = _font(round(options.font_size * 1.12), True)
    margin = min(48, options.width // 14)
    content_width = options.width - 2 * margin
    line_height = math.ceil(options.font_size * 1.48)
    heading_height = math.ceil(options.font_size * 1.85)
    # Reserve a complete title and page footer on every page.
    page_height = min(options.max_page_height, 20_000_000 // options.width)
    capacity = None if single_module_image else page_height - margin * 2 - heading_height * 2
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
        current.append(line)
        used += line.height

    blocks = semantic_blocks(document)
    for block_index, block in enumerate(blocks, 1):
        if cancel:
            cancel.check()
        emit({'kind':'progress','stage':'report_layout','current':block_index,'total':len(blocks),'message':block.title})
        heading = wrap_text(block.title, heading_font, content_width - 16, cancel=cancel)
        # Keep a section heading with at least its first content line when feasible.
        required = len(heading) * heading_height + line_height
        if capacity is not None and current and used + required > capacity:
            pages.append(current)
            current, used = [], 0
        for text in heading:
            add(DrawLine(text, heading_height, 'warning-heading' if block.group == '草稿警告' else 'heading'))
        for key, value in block.rows:
            lines = wrap_text(f'{key}：{value}', body_font, content_width - 12, cancel=cancel)
            for index, text in enumerate(lines):
                add(DrawLine(text, line_height, 'potential' if '潜能' in key else 'body', index > 0))
        if block.columns:
            if content_width >= (len(block.columns) * 3 + 4) * options.font_size:
                weights = [1.6] + [1] * (len(block.columns)-1)
                widths = [int(content_width * weight / sum(weights)) for weight in weights]
                for row_index,row in enumerate([block.columns,*block.cells]):
                    wrapped = [wrap_text(value,body_font,width-16,cancel=cancel) for value,width in zip(row,widths)]
                    for line_index in range(max(map(len,wrapped),default=1)):
                        cells = [values[line_index] if line_index < len(values) else '' for values in wrapped]
                        add(DrawLine(' | '.join(cells),line_height,'table-header' if row_index==0 else 'table',
                                     cells=cells,column_labels=block.columns))
                add(DrawLine('', max(8,line_height//2)))
                continue
            # A narrow image uses labeled rows instead of unreadably narrow columns.
            for row in block.cells:
                for key, value in zip(block.columns, row):
                    for index, text in enumerate(wrap_text(f'{key}：{value}', body_font, content_width - 12, cancel=cancel)):
                        add(DrawLine(text, line_height, 'potential' if key == '潜能' else 'body', index > 0))
                add(DrawLine('', max(8, line_height // 3), 'separator'))
        add(DrawLine('', max(8, line_height // 2)))
    if current:
        pages.append(current)
    return pages


def render_png(document: ReportDocument, directory: Path, stem: str, *, cancel: CancelToken | None = None,
               emit=null_progress, on_page=None) -> list[Path]:
    options = document.options
    single_module_image = bool(document.modules) and not document.operators and options.module_image_layout == 'single'
    pages = layout_pages(document, cancel=cancel, emit=emit)
    dark = options.theme == 'dark'
    colors = dict(bg='#20252b' if dark else '#ffffff', fg='#f1f3f5' if dark else '#20252b',
                  header='#343d48' if dark else '#eef0f2', muted='#aeb9c7' if dark else '#5c6875',
                  accent='#ffd187' if dark else '#895300', border='#586574' if dark else '#c8ced5')
    margin = min(48, options.width // 14)
    body = _font(options.font_size)
    heading = _font(round(options.font_size * 1.12), True)
    small = _font(max(12, round(options.font_size * .7)))
    heading_height = math.ceil(options.font_size * 1.85)
    paths = []
    for index, lines in enumerate(pages, 1):
        if cancel:
            cancel.check()
        emit({'kind':'progress','stage':'report_png','current':index,'total':len(pages),'message':f'{document.title} · 第{index}页'})
        if cancel:
            cancel.check()
        full_height = margin * 2 + heading_height * 2 + sum(line.height for line in lines)
        height = full_height if single_module_image else min(options.max_page_height, full_height)
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
                image = Image.new('RGB', (options.width, height), colors['bg'])
            except MemoryError as error:
                if single_module_image:
                    raise ValueError('内存不足，无法生成模组单张长图。请改用分页排版或减少所选模组。') from error
                raise
            draw = ImageDraw.Draw(image)
            # A short repeated title cannot run beyond the right edge.
            title = wrap_text(document.title, heading, options.width - margin * 2, cancel=cancel)[0]
            if title != document.title:
                title = title[:-1] + '…'
            draw.text((margin, margin), title, font=heading, fill=colors['fg'])
            y = margin + heading_height
            for line in lines:
                if cancel:
                    cancel.check()
                if line.kind in {'heading','warning-heading'}:
                    draw.rectangle((margin - 8, y, options.width - margin + 8, y + line.height - 4),
                                   fill='#6b3b23' if line.kind == 'warning-heading' else colors['header'])
                    draw.text((margin, y + 3), line.text, font=heading, fill=colors['fg'])
                elif line.kind in {'table','table-header'}:
                    weights = [1.6] + [1] * (len(line.cells)-1)
                    widths = [int((options.width-margin*2) * weight / sum(weights)) for weight in weights]
                    x=margin
                    for column_index,(cell,width) in enumerate(zip(line.cells,widths)):
                        draw.rectangle((x,y,x+width,y+line.height),fill=colors['header'] if line.kind=='table-header' else colors['bg'],outline=colors['border'])
                        draw.text((x+6,y+3),cell,font=body,fill=colors['accent'] if line.column_labels[column_index]=='潜能' else colors['fg'])
                        x+=width
                elif line.kind == 'separator':
                    draw.line((margin, y + line.height // 2, options.width - margin, y + line.height // 2), fill=colors['border'])
                else:
                    draw.text((margin + 6, y + 3), line.text, font=body,
                              fill=colors['accent'] if line.kind == 'potential' else colors['fg'])
                y += line.height
            footer = f'第 {index} / {len(pages)} 页 · 本地数据快照 · 模板 {document.metadata.get("template_version", "")} '
            draw.text((margin, height - margin - options.font_size), footer, font=small, fill=colors['muted'])
            if cancel:
                cancel.check()
            image.save(temporary, format='PNG', optimize=False)
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
