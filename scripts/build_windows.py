"""Build a deployable Bot ZIP from a fixed list, excluding live data and credentials."""
import argparse
from pathlib import Path
import sys
import zipfile
import hashlib
import json

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from starbridge import __version__, __bridge_version__, __forge_version__
from scripts.update_runtime import managed


def build(output):
    names = ['README.md', 'config.example.toml', 'requirements.txt', 'requirements.lock.txt',
             '星桥.bat']
    extensions = {'starbridge': {'.py', '.js', '.css', '.html'}, 'scripts': {'.py'},
                  'docs': {'.md'}, 'examples': {'.json', '.js'}}
    for directory in extensions:
        names.extend(p.relative_to(ROOT).as_posix() for p in (ROOT / directory).rglob('*')
                     if p.is_file() and '__pycache__' not in p.parts
                     and p.suffix in extensions[directory] and not p.name.startswith('.'))
    # Ready-to-use optional downloads; do not bundle build tools, caches or website settings.
    for name in (f'bridge/target/StarBridge-{__bridge_version__}.jar',
                 f'bridge/target/StarBridge-Forge-1.20.1-{__forge_version__}.jar', 'dist/StarBridge-website.zip'):
        if (ROOT / name).is_file():
            names.append(name)
    manifest = {'format': 'starbridge-update-v1', 'protocol': 1, 'version': __version__,
                'files': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sorted(set(names)) if managed(name)}}
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(set(names)):
            path = ROOT / name
            if path.is_symlink() or not path.is_file():
                raise ValueError(f'Invalid deployment file: {name}')
            archive.write(path, f'StarBridge/{name}')
        archive.writestr('StarBridge/update.json', json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return len(set(names))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'dist' / f'StarBridge-Windows-{__version__}.zip')
    args = parser.parse_args()
    count = build(args.output)
    print(f'{args.output.resolve()} ({count} files)')
