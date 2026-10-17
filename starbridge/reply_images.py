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


def _label(image, xy, value, size=28, bold=False, fill='#f0f7f6'):
    from PIL import ImageDraw
    draw = ImageDraw.Draw(image)
    stroke = 1 if bold and size >= 42 else 0
    draw.text(xy, value, font=_font(size), fill=fill, stroke_width=stroke)


def _canvas(height):
    from PIL import Image, ImageFilter, ImageOps
    from .reply_backdrop import BACKDROP_JPEG
    with Image.open(BytesIO(BACKDROP_JPEG)) as source:
        image = ImageOps.fit(source.convert('RGB'), (1080, height), centering=(0.65, 0.4))
    image = image.filter(ImageFilter.GaussianBlur(3)).convert('RGBA')
    image.alpha_composite(Image.new('RGBA', image.size, (9, 31, 44, 148)))
    return image


def _cover(image, title, summary, number=None, caption=None):
    from PIL import Image, ImageDraw, ImageOps
    from .reply_backdrop import BACKDROP_JPEG
    draw = ImageDraw.Draw(image)
    _glass(image, (24, 18, 1056, 292), tint=12)
    with Image.open(BytesIO(BACKDROP_JPEG)) as source:
        art = ImageOps.fit(source.convert('RGB'), (520, 292), centering=(0.84, 0.22)).convert('RGBA')
    art.alpha_composite(Image.new('RGBA', art.size, (14, 32, 45, 44)))
    mask = Image.new('L', art.size)
    ImageDraw.Draw(mask).polygon([(130, 0), (520, 0), (520, 292), (0, 292)], fill=255)
    image.paste(art.convert('RGB'), (560, 0), mask)
    draw.line((560, 291, 690, 0), fill='#82caba', width=3)
    draw.rectangle((44, 33, 50, 53), fill='#8ed6be')
    _label(image, (64, 27), 'MYRINBOT  /  '+('群服简报' if number is not None else '指令回执'), 20,
           fill='#a8d9cb')
    _label(image, (42, 65), _fit(title, _font(44), 510), 44, True, fill='#f6f7f0')
    if number is not None:
        size = 88 if len(number) < 5 else 64
        _label(image, (40, 119), number, size, True, fill='#f6f7f0')
        x = 42+_font(size).getlength(number)+22
        _label(image, (x, 180), caption or '玩家在线', 23, fill='#a8d9cb')
    else:
        _label(image, (44, 154), '来自你的群服助手', 25, fill='#a8d9cb')
    _label(image, (44, 248), _fit(summary, _font(19), 510), 19, fill='#ced9dc')


def _glass(image, box, tint=27):
    from PIL import Image, ImageDraw, ImageFilter
    x1, y1, x2, y2 = box
    size = (x2-x1, y2-y1)
    pane = image.crop(box).filter(ImageFilter.GaussianBlur(15))
    pane.alpha_composite(Image.new('RGBA', size, (184, 225, 222, tint)))
    mask = Image.new('L', size)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0]-1, size[1]-1), radius=24, fill=255)
    image.paste(pane, (x1, y1), mask)
    rim = Image.new('RGBA', size)
    draw = ImageDraw.Draw(rim)
    draw.rounded_rectangle((0, 0, size[0]-1, size[1]-1), radius=24,
                           outline=(213, 245, 236, 100), width=2)
    draw.line((24, 1, size[0]-24, 1), fill=(228, 255, 247, 145), width=1)
    image.alpha_composite(rim, (x1, y1))


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
    from PIL import ImageDraw
    ImageDraw.Draw(image).line((44, image.height-53, 1036, image.height-53), fill='#577580', width=1)
    _label(image, (44, image.height-41), 'MYRINBOT  /  群服相连', 17, fill='#bbd4d7')
    _label(image, (964, image.height-41), f'{page:02} / {total:02}', 17, fill='#bbd4d7')


def _text_pages(text, title):
    lines = _wrap(text, _font(30), 960)
    per_page, step = 27, 42
    pages = []
    total = (len(lines)+per_page-1)//per_page
    for page, offset in enumerate(range(0, len(lines), per_page), 1):
        rows = lines[offset:offset+per_page]
        height = max(720, 424+len(rows)*step)
        image = _canvas(height)
        _cover(image, title, '生成于 '+time.strftime('%H:%M'))
        _glass(image, (32, 316, 1048, height-68))
        for index, line in enumerate(rows):
            _label(image, (60, 336+index*step), line, 30)
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
    # Local initials avoid sending player names or identities to avatar services.
    palette = ['#397767', '#807044', '#655f89', '#3c7389']
    color = palette[sum(map(ord, name)) % len(palette)]
    draw = ImageDraw.Draw(image)
    draw.ellipse((x, y+10, x+40, y+50), fill=color)
    draw.line((x+54, y+62, x+422, y+62), fill='#617e87', width=1)
    initial = name[0].upper()
    if len(initial) != 1:
        initial = name[0]
    left = x+20-_font(22).getlength(initial)/2
    _label(image, (left, y+12), initial, 22, True)
    _label(image, (x+54, y+10), _fit(name, _font(25), 367), 25)


def _server_card(image, y, server, players, continuation, index):
    from PIL import ImageDraw
    rows = (len(players)+1)//2
    height = 136+rows*72
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((56, y+26, 94, y+64), radius=9, fill='#315e61')
    number = f'{index:02}'
    _label(image, (75-_font(18).getlength(number)/2, y+29), number, 18, True, fill='#b2e8d7')
    name = server['name'] + (' · 续' if continuation else '')
    _label(image, (110, y+18), _fit(name, _font(32), 700), 32, True)
    draw.ellipse((900, y+40, 910, y+50), fill='#91e1bc' if server['online'] else '#efbd91')
    _label(image, (920, y+26), '已连接' if server['online'] else '离线', 22,
           fill='#b3ead5' if server['online'] else '#efc7a5')
    if not server['online']:
        detail = '等待游戏服务器连接'
    else:
        detail = (f"{len(server['players'])} / {server['max_players']} 位玩家" if server['max_players']
                  else f"{len(server['players'])} 位玩家")
        if server['version']:
            detail += '  ·  '+server['version']
        if not server['players']:
            detail += '  ·  暂无玩家在线'
    _label(image, (110, y+70), _fit(detail, _font(21), 880), 21, fill='#c7dcde')
    for index, name in enumerate(players):
        _player(image, 110+(index % 2)*464, y+116+(index//2)*72, name)
    return height


def _status_pages(view, title):
    servers = _status_view(view)
    batches, current, used = [], [], 0
    for number, server in enumerate(servers, 1):
        chunks = [server['players'][i:i+16] for i in range(0, len(server['players']), 16)] or [[]]
        for index, players in enumerate(chunks):
            height = 136+((len(players)+1)//2)*72
            if current and used+height+12 > 1050:
                batches.append(current); current, used = [], 0
            current.append((server, players, index > 0, number)); used += height+12
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
        body = sum(136+((len(players)+1)//2)*72+12 for _, players, _, _ in cards)
        height = max(760, 354+max(body, 136)+68)
        image = _canvas(height)
        number = str(count) if online else '—'
        heading = '此刻在线' if command_key(title) == '在线' else '运行概况'
        summary = f'{updated} 更新  ·  {online} / {len(servers)} 台连接  ·  {status}'
        _cover(image, heading, summary, number, '玩家在线' if online else '等待连接')
        _label(image, (44, 313), '服务器概览', 22, True)
        _label(image, (880, 316), f'{len(servers)} 台服务器', 19, fill='#c7dcde')
        _glass(image, (32, 354, 1048, height-68))
        y = 354
        if not cards:
            _label(image, (60, y+42), '暂无关联服务器', 28, fill='#c7dcde')
        for position, (server, players, continuation, index) in enumerate(cards):
            y += _server_card(image, y, server, players, continuation, index)+12
            if position < len(cards)-1:
                from PIL import ImageDraw
                ImageDraw.Draw(image).line((56, y-6, 1024, y-6), fill='#739199', width=1)
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
