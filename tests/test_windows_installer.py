"""Runtime checks and packaging boundaries for the Windows deployment."""
import importlib.util
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


runtime = module('windows_runtime')
builder = module('build_windows')


class WindowsInstallerTests(unittest.TestCase):
    def test_wildcard_bind_addresses_have_usable_browser_urls(self):
        self.assertEqual(runtime.panel_url({'host':'0.0.0.0','port':8088}), 'http://127.0.0.1:8088/')
        self.assertEqual(runtime.panel_url({'host':'::','port':8088}), 'http://[::1]:8088/')
        self.assertEqual(runtime.panel_url({'host':'::1','port':8088}), 'http://[::1]:8088/')

    def test_port_conflict_does_not_stop_or_change_existing_listener(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0))
            listener.listen()
            app={'host':'127.0.0.1','port':listener.getsockname()[1]}
            with self.assertRaises(OSError):
                runtime.check_port(app)
            with socket.create_connection(('127.0.0.1',app['port']),timeout=1):
                pass
        runtime.check_port(app)

    def test_configuration_info_does_not_expose_login_token(self):
        with tempfile.TemporaryDirectory() as directory:
            from starbridge.config import initialize
            root=Path(directory)
            initialize(root/'config.toml')
            with patch.object(runtime,'ROOT',root):
                info={'panel_url':runtime.panel_url(runtime.configuration())}
            self.assertEqual(set(info),{'panel_url'})
            self.assertNotIn('admin_token',json.dumps(info))

    def test_deployment_archive_excludes_live_configuration_keys_and_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ['README.md','config.example.toml','requirements.txt','requirements.lock.txt',
                         '星桥.bat']:
                (root/name).write_text('deployment file',encoding='utf-8')
            private=['config.toml','data/player.db','.runtime/python.exe','scripts/local.env',
                     'install.ps1','start.cmd','stop.ps1',
                     'starbridge/private.key','starbridge/__pycache__/cached.py']
            public=['starbridge/app.py','scripts/windows_runtime.py','docs/install.md','examples/helper.json']
            for name in private+public:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text('PRIVATE' if name in private else 'source',encoding='utf-8')
            output=root/'dist/package.zip'
            with patch.object(builder,'ROOT',root):
                builder.build(output)
            with zipfile.ZipFile(output) as archive:
                names=archive.namelist()
                self.assertEqual([name for name in names if name.count('/') == 1
                                  and name.endswith(('.bat','.cmd','.ps1'))], ['StarBridge/星桥.bat'])
                for name in private:
                    self.assertNotIn('StarBridge/'+name,names)
                for name in public:
                    self.assertIn('StarBridge/'+name,names)
                self.assertFalse(any(b'PRIVATE' in archive.read(name) for name in names))

    def test_licenses_survive_the_existing_update_protocol(self):
        from starbridge.updates import extract_package
        from scripts.update_runtime import manifest_check
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('README.md', 'config.example.toml', 'requirements.txt',
                         'requirements.lock.txt', '星桥.bat'):
                (root / name).write_text('deployment', encoding='utf-8')
            (root / 'starbridge').mkdir()
            for name in ('app.py', '__main__.py'):
                (root / 'starbridge' / name).write_text('pass\n', encoding='utf-8')
            (root / 'starbridge/__init__.py').write_text(
                f'__version__ = {builder.__version__!r}\n', encoding='utf-8')
            legal = {'LICENSE': 'AGPL text', 'NOTICE': 'project copyright',
                     'THIRD_PARTY_NOTICES.md': 'third party licenses',
                     'CONTRIBUTING.md': 'contributions', 'SECURITY.md': 'private reports'}
            for name, content in legal.items():
                (root / name).write_text(content, encoding='utf-8')
            output = root / 'package.zip'
            with patch.object(builder, 'ROOT', root):
                builder.build(output)
            stage = root / 'extracted'
            manifest = extract_package(output, stage)
            manifest_check(manifest, stage)
            for name, content in legal.items():
                target = stage / 'docs' / (name if name.endswith('.md') else name + '.md')
                self.assertEqual(target.read_text('utf-8'), content)


if __name__ == '__main__':
    unittest.main()
