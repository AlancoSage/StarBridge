"""Embed the cleaned reference backdrop for existing update runtimes."""
import base64
import hashlib
from io import BytesIO
from pathlib import Path
import textwrap

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent


def build():
    source = ROOT / 'assets/reply-glass-background-v2.png'
    output = ROOT / 'starbridge/reply_backdrop.py'
    with Image.open(source) as image:
        buffer = BytesIO()
        image.convert('RGB').save(buffer, format='JPEG', quality=90, optimize=True)
    lines = ['"""Cleaned user-reference illustration; source and edit prompt in assets/reply-glass-background-v2.json."""',
             'from base64 import b64decode', '', f'SOURCE_ASSET = {source.relative_to(ROOT).as_posix()!r}',
             f'SOURCE_SHA256 = {hashlib.sha256(source.read_bytes()).hexdigest()!r}',
             '', 'BACKDROP_JPEG = b64decode(']
    lines += ['    '+repr(line) for line in textwrap.wrap(base64.b64encode(buffer.getvalue()).decode('ascii'), 100)]
    lines += [')', '']
    output.write_text('\n'.join(lines), encoding='utf-8')
    print(f'Embedded reply background: {len(buffer.getvalue())} JPEG bytes')


if __name__ == '__main__': build()
