"""Render the code-native VexBot robot monogram for the panel and website."""
from base64 import b64encode
from io import BytesIO
from pathlib import Path
import textwrap

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
POINTS = ((60, 64), (100, 64), (128, 142), (156, 64), (196, 64), (144, 190), (112, 190))
EYES = ((88, 94, 102, 108), (154, 94, 168, 108))


def build():
    scale = 4
    image = Image.new('RGBA', (256*scale, 256*scale))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(tuple(n*scale for n in (16, 16, 240, 240)), radius=48*scale, fill='black')
    draw.polygon([(x*scale, y*scale) for x, y in POINTS], fill='white')
    for box in EYES:
        draw.rectangle(tuple(n*scale for n in box), fill='black')
    image = image.resize((256, 256), Image.Resampling.LANCZOS)
    output = BytesIO(); image.save(output, format='PNG', optimize=True)
    data = output.getvalue()
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">'
           '<rect x="16" y="16" width="224" height="224" rx="48" fill="#000"/>'
           '<polygon points="' + ' '.join(f'{x},{y}' for x, y in POINTS) + '" fill="#fff"/>'
           + ''.join(f'<rect x="{x1}" y="{y1}" width="{x2-x1}" height="{y2-y1}" fill="#000"/>'
                     for x1, y1, x2, y2 in EYES) + '</svg>\n')
    (ROOT / 'assets/vexbot-icon.png').write_bytes(data)
    (ROOT / 'assets/vexbot-icon.svg').write_text(svg, encoding='utf-8')
    (ROOT / 'starbridge-website/mark.png').write_bytes(data)
    (ROOT / 'starbridge-website/mark.svg').write_text(svg, encoding='utf-8')
    encoded = '\n'.join('    ' + repr(line) for line in textwrap.wrap(b64encode(data).decode('ascii'), 100))
    module = ('"""VexBot PNG icon, embedded for compatibility with existing update runtimes."""\n'
              'from base64 import b64decode\n\n\nICON_PNG = b64decode(\n' + encoded + '\n)\n')
    (ROOT / 'starbridge/brand_icon.py').write_text(module, encoding='utf-8')
    print('Built VexBot SVG, PNG and embedded panel icon')


if __name__ == '__main__':
    build()
