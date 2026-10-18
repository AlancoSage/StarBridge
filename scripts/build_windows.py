"""Build the VexBot deployment, preserving installed supervisors' legacy paths."""
import argparse
from pathlib import Path
import sys
import zipfile
import hashlib
import json

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from starbridge import __version__, __bridge_version__, __velocity_version__
from starbridge.branding import ARTIFACT_PREFIX, artifact_path
from starbridge.game_bridges import bridge_catalog
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
    files = {name: ROOT / name for name in names}
    # The deployed supervisor accepts these legacy paths. Use current artifacts as
    # their contents without changing the existing update protocol or ZIP root.
    downloads = [f'bridge/target/{ARTIFACT_PREFIX}-{__bridge_version__}.jar',
                 f'bridge/target/{ARTIFACT_PREFIX}-Velocity-{__velocity_version__}.jar',
                 *(f'bridge/target/{item["filename"]}' for item in bridge_catalog()),
                 f'dist/{ARTIFACT_PREFIX}-website.zip']
    for name in downloads:
        current = Path(name)
        legacy_name = current.with_name(
            'StarBridge-' + current.name.removeprefix(ARTIFACT_PREFIX + '-')).as_posix()
        path = artifact_path(ROOT / current.parent, current.name)
        if path.is_file():
            files[legacy_name] = path
    # Keep legal documents in the docs directory accepted by existing update runtimes.
    for name in ('LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md', 'CONTRIBUTING.md', 'SECURITY.md'):
        path = ROOT / name
        if path.is_file():
            files['docs/' + (name if path.suffix == '.md' else name + '.md')] = path
    manifest = {'format': 'starbridge-update-v1', 'protocol': 1, 'version': __version__,
                'files': {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sorted(files.items()) if managed(name)}}
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, path in sorted(files.items()):
            if path.is_symlink() or not path.is_file():
                raise ValueError(f'Invalid deployment file: {name}')
            archive.write(path, f'StarBridge/{name}')
        archive.writestr('StarBridge/update.json', json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return len(files)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'dist' / f'{ARTIFACT_PREFIX}-Windows-{__version__}.zip')
    args = parser.parse_args()
    count = build(args.output)
    print(f'{args.output.resolve()} ({count} files)')
