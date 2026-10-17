"""Bounded local PNG rendering for explicitly selected group commands."""
import asyncio
from bisect import bisect_right
from copy import deepcopy
import hashlib
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


def _font(size, bold=False):
    from PIL import ImageFont
    if bold:
        from .reply_bold_font import font_data
    else:
        from .reply_font import font_data
    cache = getattr(_fonts, 'current', None)
    key = (size, bold)
    if cache is not None and key in cache:
        return cache[key]
    font = ImageFont.truetype(BytesIO(font_data()), size, layout_engine=ImageFont.Layout.BASIC)
    if cache is not None:
        cache[key] = font
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
    from PIL import Image, ImageDraw, ImageFilter
    font = _font(size, bold)
    x, y = xy
    box = font.getbbox(value, anchor='lt')
    shadow = Image.new('RGBA', (max(1, math.ceil(font.getlength(value))+16), max(1, box[3]-box[1]+20)))
    ImageDraw.Draw(shadow).text((8, 10), value, font=font, fill=(0, 0, 0, 105), anchor='lt')
    image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(2)), (int(x)-8, int(y)-8))
    ImageDraw.Draw(image).text(xy, value, font=font, fill=fill, anchor='lt')


def _canvas(height):
    from PIL import Image, ImageOps
    from .reply_backdrop import BACKDROP_JPEG
    with Image.open(BytesIO(BACKDROP_JPEG)) as source:
        image = ImageOps.fit(source.convert('RGB'), (1080, height), centering=(0.5, 0)).convert('RGBA')
    image.alpha_composite(Image.new('RGBA', image.size, (10, 15, 25, 112)))
    return image


def _glass(image, box, radius=30, tint=14, border=62, shade=0):
    from PIL import Image, ImageDraw, ImageFilter
    x1, y1, x2, y2 = box
    size = (x2-x1, y2-y1)
    pane = image.crop(box).filter(ImageFilter.GaussianBlur(1.4))
    pane.alpha_composite(Image.new('RGBA', size, (255, 255, 255, tint)))
    if shade:
        pane.alpha_composite(Image.new('RGBA', size, (0, 0, 0, shade)))
    mask = Image.new('L', size)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0]-1, size[1]-1), radius=radius, fill=255)
    image.paste(pane, (x1, y1), mask)
    rim = Image.new('RGBA', size)
    draw = ImageDraw.Draw(rim)
    draw.rounded_rectangle((0, 0, size[0]-1, size[1]-1), radius=radius,
                           outline=(255, 255, 255, border), width=1)
    draw.rounded_rectangle((2, 2, size[0]-3, size[1]-3), radius=max(1, radius-2),
                           outline=(255, 255, 255, border//4), width=1)
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
    if total > 1:
        _label(image, (44, image.height-30), f'{page} / {total}', 17)


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
        _label(image, (44, 90), _fit(title, _font(58, True), 990), 58, True)
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


def _avatar(name):
    """Local voxel-style placeholder, never presented as a fetched player skin."""
    from PIL import Image, ImageDraw
    seed = hashlib.sha256(name.encode('utf-8')).digest()
    palettes = [('#ba9678', '#674631', '#e3d4bc', '#6662a2'),
                ('#a87956', '#4b3024', '#ddd0b6', '#4565a4'),
                ('#9cbdc8', '#083d59', '#d8f2f6', '#00b7dc')]
    skin, hair, eyes, iris = palettes[seed[0] % len(palettes)]
    image = Image.new('RGB', (8, 8), skin); draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 7, 1), fill=hair)
    draw.rectangle((0, 2, seed[1] % 3, 2), fill=hair)
    draw.rectangle((7, 2, 7, 3), fill=hair)
    draw.rectangle((1, 4, 2, 4), fill=eyes); draw.rectangle((5, 4, 6, 4), fill=eyes)
    draw.point((2, 4), fill=iris); draw.point((5, 4), fill=iris)
    draw.rectangle((3, 5, 4, 5), fill=hair)
    draw.rectangle((2, 7, 5, 7), fill=hair)
    return image.resize((50, 50), Image.Resampling.NEAREST)


def _player(image, x, y, name, height=72):
    from PIL import Image, ImageDraw
    _glass(image, (x, y, x+308, y+height), radius=17, tint=56, border=110)
    avatar_size = height-22
    mask = Image.new('L', (avatar_size, avatar_size))
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, avatar_size-1, avatar_size-1), radius=7, fill=255)
    image.paste(_avatar(name).resize((avatar_size, avatar_size), Image.Resampling.NEAREST), (x+10, y+10), mask)
    _label(image, (x+avatar_size+23, y+(height-22)//2), _fit(name, _font(23, True), 274-avatar_size), 23, True)


def _card_height(players, details, columns=3, player_height=72):
    rows = (len(players)+columns-1)//columns
    return 106+(32 if details else 0)+(rows*(player_height+8)-8 if rows else 0)


def _server_card(image, y, server, players, continuation, details, left=42, width=996, columns=3, player_height=72):
    height = _card_height(players, details, columns, player_height)
    right = left+width
    _glass(image, (left, y, right, y+height), radius=30)
    name = server['name'] + (' · 续' if continuation else '')
    badge = f"{len(server['players'])} 人在线" if server['online'] else '离线'
    badge_font = _font(20, True)
    badge_width = max(111, math.ceil(badge_font.getlength(badge))+28)
    badge_left = right-24-badge_width
    _label(image, (left+24, y+30), _fit(name, _font(32, True), badge_left-left-48), 32, True)
    _glass(image, (badge_left, y+22, right-24, y+67), radius=8, tint=0, border=70, shade=36)
    _label(image, (badge_left+(badge_width-badge_font.getlength(badge))/2, y+35), badge, 20, True)
    if details:
        detail = '等待游戏服务器连接'
        if server['online']:
            detail = (f"{len(server['players'])} / {server['max_players']} 位玩家" if server['max_players']
                      else f"{len(server['players'])} 位玩家")
            if server['version']:
                detail += '  ·  '+server['version']
        _label(image, (left+24, y+76), _fit(detail, _font(20), width-51), 20)
    for index, name in enumerate(players):
        _player(image, left+24+(index % columns)*324,
                y+84+(32 if details else 0)+(index//columns)*(player_height+8), name, player_height)
    return height


def _online_summary(image, count, online, servers, updated, status):
    _glass(image, (42, 44, 334, image.height-44), radius=30)
    _label(image, (66, 70), 'Myrinbot', 21, True, fill='#d6f3ee')
    _label(image, (66, 112), '服务器', 38, True)
    _label(image, (66, 160), '在线列表', 46, True)
    _glass(image, (62, 226, 314, 346), radius=24, tint=14)
    _label(image, (82, 244), '当前在线', 20, True)
    number = str(count) if online else '—'
    size = 54 if len(number) <= 5 else 42
    _label(image, (82, 278), number, size, True)
    for index, (label, value) in enumerate([('服务器', str(servers)), ('更新时间', updated), ('状态', status)]):
        y = 366+index*76
        _glass(image, (62, y, 314, y+62), radius=18, tint=12)
        _label(image, (82, y+23), label, 20, True)
        _label(image, (294-_font(28, True).getlength(value), y+17), value, 28, True)


def _status_pages(view, title):
    servers = _status_view(view)
    details = command_key(title) != '在线'
    columns, player_height = (3, 72) if details else (2, 68)
    body_limit = 1228 if details else 1512
    batches, current, used = [], [], 0
    for server in servers:
        chunks = [server['players'][i:i+36] for i in range(0, len(server['players']), 36)] or [[]]
        for index, players in enumerate(chunks):
            height = _card_height(players, details, columns, player_height)
            if current and used+height+19 > body_limit:
                batches.append(current); current, used = [], 0
            if current:
                used += 19
            current.append((server, players, index > 0)); used += height
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
        body = sum(_card_height(players, details, columns, player_height) for _, players, _ in cards)+max(0, len(cards)-1)*19
        if not details:
            image = _canvas(max(648, 44+max(body, 106)+44))
            _online_summary(image, count, online, len(servers), updated, status)
            y = 44
            if not cards:
                _glass(image, (358, y, 1038, y+106))
                _label(image, (382, y+38), '暂无关联服务器', 28)
            for server, players, continuation in cards:
                y += _server_card(image, y, server, players, continuation, False,
                                  left=358, width=680, columns=columns, player_height=player_height)+19
            _footer(image, page, len(batches))
            pages.append(_encode(image))
            continue
        height = max(560, 328+max(body, 106)+44)
        image = _canvas(height)
        _label(image, (42, 79), 'Myrinbot', 21, True, fill='#d6f3ee')
        heading = '服务器在线列表' if command_key(title) == '在线' else '服务器运行状态'
        _label(image, (42, 121), heading, 60, True)
        _glass(image, (878, 44, 1038, 178), radius=32, tint=14)
        _label(image, (958-_font(21, True).getlength('在线')/2, 64), '在线', 21, True)
        number = str(count) if online else '—'
        size = 64 if len(number) <= 3 else 44
        _label(image, (958-_font(size, True).getlength(number)/2, 113), number, size, True)
        for index, (label, value) in enumerate([('服务器', str(len(servers))), ('更新时间', updated), ('状态', status)]):
            x = (42, 380, 716)[index]
            _glass(image, (x, 205, x+322, 304), radius=24, tint=12)
            _label(image, (x+20, 228), label, 20, True)
            _label(image, (x+20, 257), value, 32, True)
        y = 328
        if not cards:
            _glass(image, (42, y, 1038, y+106))
            _label(image, (66, y+38), '暂无关联服务器', 28)
        for server, players, continuation in cards:
            y += _server_card(image, y, server, players, continuation, details)+19
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
