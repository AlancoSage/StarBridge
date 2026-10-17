"""Bounded local PNG rendering for explicitly selected group commands."""
import asyncio
from bisect import bisect_right
from copy import deepcopy
from io import BytesIO
import math
from threading import local
import time
import unicodedata

DEFAULTS = {"enabled": False, "commands": []}
MAX_TEXT = 3500
MAX_PNG = 2 * 1024 * 1024
MAX_PAGES = 4
_fonts = local()


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


def _check_characters(value):
    from .reply_font import SUPPORTED_RANGES
    starts = [lo for lo, _hi in SUPPORTED_RANGES]
    for char in value:
        if char == '\n':
            continue
        point = ord(char); index = bisect_right(starts, point)-1
        if unicodedata.category(char).startswith('C') or index < 0 or point > SUPPORTED_RANGES[index][1]:
            raise RenderError("回复包含字体不支持的字符，请使用文字回复")


def _font(size):
    from PIL import ImageFont
    from .reply_font import font_data
    cache = getattr(_fonts, 'current', None)
    if cache is not None and size in cache:
        return cache[size]
    font = ImageFont.truetype(BytesIO(font_data()), size, layout_engine=ImageFont.Layout.BASIC)
    if cache is not None:
        cache[size] = font
    return font


def _wrap(text, font, width):
    # Literal text only: no HTML, URLs, CQ codes or external image requests.
    lines = []
    for paragraph in text.split('\n'):
        line, length = '', 0
        for char in paragraph:
            advance = font.getlength(char)
            if line and length+advance > width:
                lines.append(line); line, length = '', 0
            line += char; length += advance
        lines.append(line)
        if len(lines) > 27*MAX_PAGES:
            raise RenderError("回复排版超过 4 页，请使用文字回复")
    return lines


def _fit(value, font, width):
    if font.getlength(value) <= width:
        return value
    while value and font.getlength(value+'…') > width:
        value = value[:-1]
    return value+'…'


def _label(image, xy, value, size=28, bold=False, fill='white'):
    from PIL import ImageDraw
    draw = ImageDraw.Draw(image)
    x, y = xy
    stroke = 1 if bold else 0
    draw.text((x+1, y+2), value, font=_font(size), fill=(9, 18, 35, 210), stroke_width=stroke)
    draw.text((x, y), value, font=_font(size), fill=fill, stroke_width=stroke)


def _canvas(height):
    from PIL import Image, ImageOps
    from .reply_backdrop import BACKDROP_JPEG
    with Image.open(BytesIO(BACKDROP_JPEG)) as source:
        image = ImageOps.fit(source.convert('RGB'), (1080, height), centering=(0.55, 0.40)).convert('RGBA')
    image.alpha_composite(Image.new('RGBA', image.size, (12, 24, 45, 102)))
    return image


def _glass(image, box, radius=26, tint=24):
    from PIL import Image, ImageDraw, ImageFilter
    x1, y1, x2, y2 = box
    size = (x2-x1, y2-y1)
    pane = image.crop(box).filter(ImageFilter.GaussianBlur(12))
    pane.alpha_composite(Image.new('RGBA', size, (235, 244, 255, tint)))
    mask = Image.new('L', size)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0]-1, size[1]-1), radius=radius, fill=255)
    image.paste(pane, (x1, y1), mask)
    ImageDraw.Draw(image).rounded_rectangle((x1, y1, x2-1, y2-1), radius=radius,
                                            outline=(244, 249, 255, 108), width=2)


def _encode(image):
    image = image.convert('RGB')
    output = BytesIO(); image.save(output, format='PNG', compress_level=3)
    if output.tell() > MAX_PNG:
        # Bound transport size while keeping the public PNG in RGB mode.
        output = BytesIO()
        image.quantize(colors=256).convert('RGB').save(output, format='PNG', compress_level=3)
    data = output.getvalue(); validate_png(data)
    return data


def _footer(image, page, total):
    _label(image, (44, image.height-46), f'MYRINBOT  ·  {page} / {total}', 19,
           fill=(233, 242, 255, 225))


def _text_pages(text, title):
    lines = _wrap(text, _font(30), 904)
    per_page, step = 27, 44
    pages = []
    total = (len(lines)+per_page-1)//per_page
    for page, offset in enumerate(range(0, len(lines), per_page), 1):
        rows = lines[offset:offset+per_page]
        height = max(720, 350+len(rows)*step)
        image = _canvas(height)
        _label(image, (44, 40), 'MYRINBOT / REPLY', 23, fill=(215, 238, 255, 255))
        _label(image, (44, 90), _fit(title, _font(58), 990), 58, True)
        _label(image, (46, 176), '指令回复  ·  '+time.strftime('%H:%M'), 22)
        _glass(image, (42, 234, 1038, height-68))
        for index, line in enumerate(rows):
            _label(image, (86, 254+index*step), line, 30)
        _footer(image, page, total)
        pages.append(_encode(image))
    return pages


def _status_view(view):
    if (not isinstance(view, dict) or view.get('type') != 'server_status'
            or not isinstance(view.get('servers'), list) or len(view['servers']) > 100
            or type(view.get('updated')) not in (int, float) or not math.isfinite(view['updated'])
            or not 0 <= view['updated'] <= 253402214400):
        raise RenderError('服务器图片数据无效')
    servers = []
    for value in view['servers']:
        if (not isinstance(value, dict) or type(value.get('online')) is not bool
                or not isinstance(value.get('name'), str) or not 1 <= len(value['name']) <= 100
                or not isinstance(value.get('players'), list) or len(value['players']) > 1000
                or any(not isinstance(p, str) or not 1 <= len(p) <= 100 for p in value['players'])
                or type(value.get('max_players')) is not int or not 0 <= value['max_players'] <= 1000000
                or not isinstance(value.get('version'), str) or len(value['version']) > 100):
            raise RenderError('服务器图片数据无效')
        _check_characters(value['name'] + ''.join(value['players']) + value['version'])
        if any('\n' in item or '\r' in item for item in [value['name'], value['version'], *value['players']]):
            raise RenderError('服务器名称与玩家名称需为单行文字')
        servers.append({**value, 'players': list(value['players']) if value['online'] else [],
                        'max_players': value['max_players'] if value['online'] else 0,
                        'version': value['version'] if value['online'] else ''})
    return servers


def _player(image, x, y, name):
    from PIL import ImageDraw
    _glass(image, (x, y, x+450, y+78), radius=19, tint=34)
    # Local initials avoid sending player names or identities to avatar services.
    palette = [(75, 133, 179), (116, 106, 167), (57, 135, 139), (128, 112, 151)]
    color = palette[sum(map(ord, name)) % len(palette)]
    ImageDraw.Draw(image).rounded_rectangle((x+10, y+10, x+68, y+68), radius=13, fill=color)
    initial = name[0].upper()
    if len(initial) != 1:
        initial = name[0]
    left = x+39-_font(30).getlength(initial)/2
    _label(image, (left, y+15), initial, 30, True)
    _label(image, (x+84, y+19), _fit(name, _font(25), 352), 25, True)


def _server_card(image, y, server, players, continuation):
    rows = (len(players)+1)//2
    height = 136+rows*94
    _glass(image, (42, y, 1038, y+height), radius=28)
    name = server['name'] + (' · 续' if continuation else '')
    _label(image, (66, y+22), _fit(name, _font(35), 710), 35, True)
    badge = f"{len(server['players'])} 人在线" if server['online'] else '桥接离线'
    _glass(image, (824, y+24, 1014, y+78), radius=12, tint=10)
    _label(image, (842, y+32), badge, 23, True)
    if not server['online']:
        detail = '等待游戏服务器连接'
    else:
        detail = (f"{len(server['players'])} / {server['max_players']} 位玩家" if server['max_players']
                  else f"{len(server['players'])} 位玩家")
        if server['version']:
            detail += '  ·  '+server['version']
        if not server['players']:
            detail += '  ·  暂无玩家在线'
    _label(image, (68, y+82), _fit(detail, _font(22), 925), 22, fill=(228, 239, 255, 255))
    for index, name in enumerate(players):
        _player(image, 66+(index % 2)*474, y+124+(index//2)*94, name)
    return height


def _status_pages(view, title):
    servers = _status_view(view)
    batches, current, used = [], [], 0
    for server in servers:
        chunks = [server['players'][i:i+16] for i in range(0, len(server['players']), 16)] or [[]]
        for index, players in enumerate(chunks):
            height = 136+((len(players)+1)//2)*94
            if current and used+height+18 > 1090:
                batches.append(current); current, used = [], 0
            current.append((server, players, index > 0)); used += height+18
    if current or not batches:
        batches.append(current)
    if len(batches) > MAX_PAGES:
        raise RenderError('服务器列表超过 4 页，请使用文字回复')
    count = sum(len(s['players']) for s in servers)
    online = sum(s['online'] for s in servers)
    status = '正常' if servers and online == len(servers) else '部分离线' if online else '桥接离线'
    if not servers:
        status = '暂无服务器'
    try:
        updated = time.strftime('%H:%M', time.localtime(view['updated']))
    except (ValueError, OverflowError, OSError) as exc:
        raise RenderError('更新时间无效') from exc
    pages = []
    for page, cards in enumerate(batches, 1):
        body = sum(136+((len(players)+1)//2)*94+18 for _, players, _ in cards)
        height = max(900, 354+body+50)
        image = _canvas(height)
        _label(image, (44, 40), 'MYRINBOT / SERVER', 23, fill=(215, 238, 255, 255))
        heading = '服务器在线列表' if command_key(title) == '在线' else '服务器运行状态'
        _label(image, (44, 100), heading, 57, True)
        _glass(image, (864, 34, 1038, 204), radius=32, tint=26)
        _label(image, (914, 50), '在线', 25, True)
        number = str(count) if online else '—'
        size = 65 if len(number) <= 3 else 46
        _label(image, (951-_font(size).getlength(number)/2, 90), number, size, True)
        for index, (label, value) in enumerate([('服务器', str(len(servers))), ('更新时间', updated), ('状态', status)]):
            x = 42+index*338
            _glass(image, (x, 230, x+320, 332), radius=23, tint=18)
            _label(image, (x+22, 243), label, 23)
            _label(image, (x+22, 275), value, 32, True)
        y = 354
        if not cards:
            _glass(image, (42, y, 1038, y+136))
            _label(image, (68, y+44), '暂无关联服务器', 30)
        for server, players, continuation in cards:
            y += _server_card(image, y, server, players, continuation)+18
        _footer(image, page, len(batches))
        pages.append(_encode(image))
    return pages


def render_pages(text, title, view=None):
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
        raise RenderError('回复内容需为 1–3500 个字符')
    if not isinstance(title, str) or not 1 <= len(title) <= 100:
        raise RenderError('图片标题无效')
    text = text.replace('\r\n', '\n').replace('\r', '\n').expandtabs(4)
    _check_characters(title+text)
    # Each worker owns its FreeType faces; retain only immutable source font bytes.
    previous = getattr(_fonts, 'current', None)
    _fonts.current = {}
    try:
        if view is not None:
            return _status_pages(view, title)
        return _text_pages(text, title)
    finally:
        if previous is None:
            del _fonts.current
        else:
            _fonts.current = previous


class ReplyRenderer:
    def __init__(self):
        self.slots = asyncio.Semaphore(2)

    async def render(self, text, title, view=None):
        if self.slots.locked():
            raise RenderError("图片渲染繁忙，请稍后重试")
        async with self.slots:
            if view is None:
                return await asyncio.to_thread(render_pages, text, title)
            return await asyncio.to_thread(render_pages, text, title, view)
