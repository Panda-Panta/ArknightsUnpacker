"""Selected font bytes shared by raster layout and self-contained HTML."""
from base64 import b64encode
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import struct


@dataclass(frozen=True)
class CustomFont:
    data: bytes
    format: str

    def at_size(self, size):
        from PIL import ImageFont

        try:
            return ImageFont.truetype(BytesIO(self.data), size)
        except (OSError, ValueError) as error:
            raise ValueError('无法加载所选字体，请选择有效的 TTF 或 OTF 字体文件。') from error

    def css(self):
        mime, format_name = ('font/otf', 'opentype') if self.format == 'otf' else ('font/ttf', 'truetype')
        encoded = b64encode(self.data).decode('ascii')
        return ('\n@font-face { font-family: "ArknightsCustomExport"; '
                f'src: url("data:{mime};base64,{encoded}") format("{format_name}"); '
                'font-style: normal; font-weight: normal; font-display: block; }\n'
                ':root { --body-family: "ArknightsCustomExport"; '
                '--heading-family: "ArknightsCustomExport"; '
                '--utility-family: "ArknightsCustomExport"; }\n'
                'html { font-synthesis: none; }\n')


def load_custom_font(font_path, font_index=0):
    if not font_path:
        return None
    if not isinstance(font_index, int) or isinstance(font_index, bool) or font_index < 0:
        raise ValueError('字体字形索引须为非负整数。')
    path = Path(font_path).expanduser()
    if path.suffix.lower() not in {'.ttf', '.otf', '.ttc', '.otc'}:
        raise ValueError('自定义字体仅支持 TTF、OTF 或 TTC 字体文件。')
    try:
        data = path.read_bytes()
    except OSError as error:
        raise ValueError(f'无法读取所选字体文件：{path}') from error
    if data.startswith(b'ttcf'):
        # Browsers consume the selected standalone face, not a TTC container.
        # Pillow receives those same bytes, so preview and HTML select one face.
        from fontTools.ttLib import TTFont, TTLibError
        try:
            with TTFont(BytesIO(data), fontNumber=font_index, lazy=True,
                        recalcBBoxes=False, recalcTimestamp=False) as face:
                output = BytesIO()
                face.save(output, reorderTables=False)
                data = output.getvalue()
        except (OSError, ValueError, IndexError, AssertionError, struct.error, TTLibError) as error:
            raise ValueError(f'无法读取所选字体字形（索引 {font_index}）：{path}') from error
    elif font_index:
        raise ValueError('所选字体文件不包含该字形索引。')
    if data[:4] not in {b'\x00\x01\x00\x00', b'true', b'OTTO'}:
        raise ValueError(f'所选文件不是有效的字体：{path}')
    font = CustomFont(data, 'otf' if data[:4] == b'OTTO' else 'ttf')
    font.at_size(16)
    return font
