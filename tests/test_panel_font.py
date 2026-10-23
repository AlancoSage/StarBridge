"""The public console font must remain local and survive existing updaters."""
import hashlib
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from aiohttp.test_utils import TestClient, TestServer

from scripts import build_windows
from scripts.update_runtime import managed, manifest_check
from starbridge.app import create_app
from starbridge.config import load
from starbridge.settings import serialize
from starbridge.updates import extract_package
from test_settings import full_config


ROOT = Path(__file__).resolve().parent.parent
FONT_MODULE = 'starbridge/panel_font.py'
LICENSE_FILE = 'docs/source-han-sans-license.md'
PINNED_SHA256 = 'f971e3bff46f76b49e1d5510556c2297c618ec4b491a295a4e741cdd38257799'


class PanelFontPackagingTests(unittest.TestCase):
    def test_font_is_unmodified_woff2_and_accepted_by_existing_updaters(self):
        from starbridge.panel_font import font_data, SHA256, FONT_URL

        data = font_data()
        self.assertEqual(SHA256, PINNED_SHA256)
        self.assertEqual(data[:4], b'wOF2')
        self.assertEqual(struct.unpack_from('>I', data, 8)[0], len(data))
        self.assertEqual(len(data), 7711988)
        self.assertEqual(hashlib.sha256(data).hexdigest(), SHA256)
        self.assertIn(SHA256[:16], FONT_URL)
        self.assertTrue(managed(FONT_MODULE))
        self.assertTrue(managed(LICENSE_FILE))
        self.assertLess((ROOT / FONT_MODULE).stat().st_size, 32 * 1024 * 1024)

    def test_font_and_full_license_survive_the_existing_deployment_protocol(self):
        license_data = (ROOT / LICENSE_FILE).read_bytes()
        self.assertIn(b'SIL OPEN FONT LICENSE Version 1.1', license_data)
        self.assertIn(b'Adobe', license_data)
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for name in ('README.md', 'config.example.toml', 'requirements.txt',
                         'requirements.lock.txt', '\u661f\u6865.bat'):
                (base / name).write_text('isolated fixture', encoding='utf-8')
            (base / 'starbridge').mkdir()
            for name in ('app.py', '__main__.py'):
                (base / 'starbridge' / name).write_text('pass\n', encoding='utf-8')
            (base / 'starbridge/__init__.py').write_text(
                f'__version__ = {build_windows.__version__!r}\n', encoding='utf-8')
            for name in (FONT_MODULE, LICENSE_FILE):
                target = base / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / name).read_bytes())
            output = base / 'font-deployment.zip'
            with patch.object(build_windows, 'ROOT', base):
                build_windows.build(output)
            with zipfile.ZipFile(output) as archive:
                for name in (FONT_MODULE, LICENSE_FILE):
                    self.assertEqual(archive.read('StarBridge/' + name), (ROOT / name).read_bytes())
            stage = base / 'extracted'
            manifest = extract_package(output, stage)
            manifest_check(manifest, stage)
            for name in (FONT_MODULE, LICENSE_FILE):
                self.assertEqual((stage / name).read_bytes(), (ROOT / name).read_bytes())
                self.assertEqual(manifest['files'][name], hashlib.sha256((ROOT / name).read_bytes()).hexdigest())


class PanelFontHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from starbridge.panel_font import font_data, SHA256, FONT_URL

        self.font_data = font_data()
        self.sha256 = SHA256
        self.url = FONT_URL
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'config.toml'
        self.path.write_text(serialize(full_config()), encoding='utf-8')
        self.client = TestClient(TestServer(create_app(load(self.path), self.path)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    async def test_get_and_head_work_before_login_with_immutable_cache_headers(self):
        response = await self.client.get('/api/config')
        self.assertEqual(response.status, 401)
        for method in ('get', 'head'):
            with self.subTest(method=method):
                response = await getattr(self.client, method)(self.url)
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers['Content-Type'], 'font/woff2')
                self.assertEqual(int(response.headers['Content-Length']), len(self.font_data))
                self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
                self.assertEqual(response.headers['ETag'], '"' + self.sha256 + '"')
                cache = {part.strip() for part in response.headers['Cache-Control'].split(',')}
                self.assertTrue({'public', 'max-age=31536000', 'immutable'} <= cache)
                data = await response.read()
                if method == 'head':
                    self.assertEqual(data, b'')
                else:
                    self.assertEqual(data, self.font_data)
                    self.assertEqual(hashlib.sha256(data).hexdigest(), self.sha256)

    async def test_cached_font_revalidates_without_resending_the_body(self):
        for value in ('"' + self.sha256 + '"', 'W/"' + self.sha256 + '"', '*'):
            with self.subTest(if_none_match=value):
                response = await self.client.get(self.url, headers={'If-None-Match': value})
                self.assertEqual(response.status, 304)
                self.assertEqual(response.headers['ETag'], '"' + self.sha256 + '"')
                self.assertIn('immutable', response.headers['Cache-Control'])
                self.assertEqual(await response.read(), b'')
        response = await self.client.get(self.url, headers={'If-None-Match': '"other-font"'})
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.read(), self.font_data)

    async def test_unknown_font_paths_do_not_expose_arbitrary_static_files(self):
        paths = (self.url.replace('.woff2', '-missing.woff2'),
                 self.url.replace('.woff2', '.py'),
                 self.url.rsplit('/', 1)[0] + '/config.toml')
        for url in paths:
            for method in ('get', 'head'):
                with self.subTest(url=url, method=method):
                    response = await getattr(self.client, method)(url)
                    self.assertEqual(response.status, 404)


if __name__ == '__main__':
    unittest.main()
