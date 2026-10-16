"""Bounded local PNG rendering for explicitly selected group commands."""
import asyncio
from bisect import bisect_right
from copy import deepcopy
from io import BytesIO
import unicodedata

DEFAULTS = {"enabled": False, "commands": []}
MAX_TEXT = 3500
MAX_PNG = 2 * 1024 * 1024
MAX_PAGES = 4


class RenderError(ValueError):
    pass


def command_key(value):
    key = " ".join(value.split()) if isinstance(value, str) else ""
    return {"help": "帮助", "/help": "帮助"}.get(key, key)


def validate(value):
    if not isinstance(value, dict) or value.keys() - DEFAULTS.keys():
        raise ValueError("图片回复设置包含未知字段")
    out = {**deepcopy(DEFAULTS), **value}
    if type(out['enabled']) is not bool:
        raise ValueError("图片回复开关必须是布尔值")
    commands = out['commands']
    if (not isinstance(commands, list) or len(commands) > 100
            or any(not isinstance(key, str) or not 1 <= len(key) <= 100 or key != command_key(key)
                   or any(unicodedata.category(char).startswith('C') for char in key) for key in commands)
            or len(commands) != len(set(commands))):
        raise ValueError("图片回复指令最多 100 个，需为不重复的单行指令名称；预设指令填写 执行 命令名")
    if out['enabled'] and not commands:
        raise ValueError("启用图片回复前请至少指定一个指令")
    return out


def validate_png(data):
    if not isinstance(data, bytes) or not data.startswith(b'\x89PNG\r\n\x1a\n') or not 8 < len(data) <= MAX_PNG:
        raise ValueError("回复图片必须为不超过 2 MiB 的 PNG")


def render_pages(text, title):
    from PIL import Image, ImageDraw, ImageFont
    from .reply_font import SUPPORTED_RANGES, font_data
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
        raise RenderError("回复内容需为 1–3500 个字符")
    if not isinstance(title, str) or not 1 <= len(title) <= 100:
        raise RenderError("图片标题无效")
    text = text.replace('\r\n', '\n').replace('\r', '\n').expandtabs(4)
    starts = [lo for lo, _hi in SUPPORTED_RANGES]
    for char in title + text:
        if char == '\n':
            continue
        point = ord(char); index = bisect_right(starts, point)-1
        if unicodedata.category(char).startswith('C') or index < 0 or point > SUPPORTED_RANGES[index][1]:
            raise RenderError("回复包含字体不支持的字符，请使用文字回复")
    small = ImageFont.truetype(BytesIO(font_data()), 21)
    heading = ImageFont.truetype(BytesIO(font_data()), 34)
    width, padding, step, per_page = 1080, 52, 46, 27
    # Advance widths are additive with BASIC layout; no HTML, URLs or CQ parsing.
    font = ImageFont.truetype(BytesIO(font_data()), 30, layout_engine=ImageFont.Layout.BASIC)
    lines = []
    for paragraph in text.split('\n'):
        line, length = '', 0
        for char in paragraph:
            advance = font.getlength(char)
            if line and length+advance > width-padding*2:
                lines.append(line); line, length = '', 0
            line += char; length += advance
        lines.append(line)
        if len(lines) > per_page*MAX_PAGES:
            raise RenderError("回复排版超过 4 页，请使用文字回复")
    pages = []
    for page, offset in enumerate(range(0, len(lines), per_page), 1):
        rows = lines[offset:offset+per_page]
        height = 224+max(1, len(rows))*step
        image = Image.new('RGB', (width, height), '#f5f5f4')
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((16, 16, width-16, height-16), radius=24, fill='white', outline='#dededb', width=2)
        draw.text((padding, 38), 'MYRINBOT / REPLY', font=small, fill='#777772')
        visible_title = title
        while heading.getlength(visible_title) > width-padding*2-40:
            visible_title = visible_title[:-1]
        if visible_title != title:
            visible_title += '…'
        draw.text((padding, 76), visible_title, font=heading, fill='#151515')
        draw.line((padding, 134, width-padding, 134), fill='#e5e5e2', width=2)
        for index, line in enumerate(rows):
            draw.text((padding, 156+index*step), line, font=font, fill='#262626')
        total = (len(lines)+per_page-1)//per_page
        draw.text((padding, height-54), f'Myrinbot · {page} / {total}', font=small, fill='#777772')
        output = BytesIO(); image.save(output, format='PNG')
        data = output.getvalue(); validate_png(data); pages.append(data)
    return pages


class ReplyRenderer:
    def __init__(self):
        self.slots = asyncio.Semaphore(2)

    async def render(self, text, title):
        if self.slots.locked():
            raise RenderError("图片渲染繁忙，请稍后重试")
        async with self.slots:
            return await asyncio.to_thread(render_pages, text, title)
