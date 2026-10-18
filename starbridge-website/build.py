"""Build the independent VexBot website without reading any Bot files."""
import argparse
import json
from pathlib import Path
import zipfile

from serve import api_base

ROOT = Path(__file__).resolve().parent
FILES = ('index.html', 'site.css', 'site.js', 'config.json', 'mark.png', 'mark.svg',
         'README.md', 'LICENSE', 'nginx.example.conf', 'serve.py', 'build.py', 'start.ps1', '.gitignore',
         'sdk/starbridge.js', 'docs/website-deployment.md', 'docs/account-api.md', 'docs/community-operations.md')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-base', help='API address for config.json in the archive only')
    parser.add_argument('--output', type=Path, default=ROOT/'dist/VexBot-website.zip')
    args = parser.parse_args()
    try:
        address = api_base(args.api_base if args.api_base is not None else json.loads((ROOT/'config.json').read_text(encoding='utf-8'))['apiBase'])
        for name in FILES:
            if not (ROOT/name).is_file():
                raise ValueError('Missing project file: '+name)
    except (ValueError, KeyError, OSError, TypeError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix('.zip.tmp')
    try:
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name in FILES:
                if name == 'config.json':
                    archive.writestr(name, json.dumps({'apiBase':address}, ensure_ascii=False)+'\n')
                else:
                    archive.write(ROOT/name, name)
        temporary.replace(args.output)
    finally:
        temporary.unlink(missing_ok=True)
    print(f'Built: {args.output.resolve()} ({args.output.stat().st_size} bytes)')


if __name__ == '__main__':
    main()
