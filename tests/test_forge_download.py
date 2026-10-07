from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from aiohttp.test_utils import TestClient, TestServer
from starbridge.app import create_app
from starbridge.game_bridges import bridge_catalog
from test_starbridge import config


class ForgeDownloadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.cfg = config()
        self.client = TestClient(TestServer(create_app(self.cfg)))
        await self.client.start_server()
        self.headers = {'Authorization': 'Bearer ' + self.cfg['app']['admin_token']}
        (self.root / 'bridge/target').mkdir(parents=True)
        (self.root / 'bridge/target/StarBridge-0.5.0.jar').write_bytes(b'bukkit-fixture')
        for item in bridge_catalog():
            (self.root / 'bridge/target' / item['filename']).write_bytes(item['filename'].encode())

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    async def test_platform_selection_authentication_and_unknown_platform(self):
        with patch('starbridge.app.Path', return_value=self.root / 'starbridge/app.py'):
            for platform, expected in (('bukkit', b'bukkit-fixture'), ('forge', b'StarBridge-Forge-1.20.1-0.1.0.jar')):
                response = await self.client.get('/api/plugin?platform=' + platform, headers=self.headers)
                self.assertEqual(response.status, 200)
                self.assertEqual(await response.read(), expected)
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                self.assertIn('attachment;', response.headers['Content-Disposition'])
            response = await self.client.get('/api/plugin?platform=forge')
            self.assertEqual(response.status, 401)
            response = await self.client.get('/api/plugin?platform=../../config.toml', headers=self.headers)
            self.assertEqual(response.status, 400)
            # FileResponse closes its file in a background executor; Windows may
            # still hold the downloaded file here. Use a separate absent root.
            with patch('starbridge.app.Path', return_value=self.root / 'missing/starbridge/app.py'):
                response = await self.client.get('/api/plugin?platform=forge', headers=self.headers)
                self.assertEqual(response.status, 404)

    async def test_all_native_versions_and_catalog_use_fixed_paths(self):
        self.assertEqual((await self.client.get('/api/plugin/catalog')).status, 401)
        with patch('starbridge.app.Path', return_value=self.root / 'starbridge/app.py'):
            response = await self.client.get('/api/plugin/catalog', headers=self.headers)
            catalog = (await response.json())['bridges']
            self.assertEqual(len(catalog), 7)
            self.assertTrue(all(item['available'] for item in catalog))
            for item in catalog:
                response = await self.client.get('/api/plugin', params={key: item[key] for key in ('platform', 'version')}, headers=self.headers)
                self.assertEqual(response.status, 200)
                self.assertEqual(await response.read(), item['filename'].encode())
            for platform, version in [('forge', '../../config.toml'), ('forge', '1.21.1'), ('neoforge', '1.20.1'), ('bukkit', '1.12.2'), ('forge', '')]:
                response = await self.client.get('/api/plugin', params={'platform': platform, 'version': version}, headers=self.headers)
                self.assertEqual(response.status, 400)
            with patch('starbridge.app.Path', return_value=self.root / 'missing/starbridge/app.py'):
                catalog = await (await self.client.get('/api/plugin/catalog', headers=self.headers)).json()
                self.assertTrue(all(not item['available'] for item in catalog['bridges']))
                response = await self.client.get('/api/plugin?platform=neoforge', headers=self.headers)
                self.assertEqual(response.status, 404)

    async def test_native_guide_platforms_and_panel_module(self):
        for platform in ('forge', 'neoforge'):
            response = await self.client.get('/api/authentication/guide?platform='+platform, headers=self.headers)
            self.assertEqual(response.status, 200)
            self.assertIn(b'1.7.10', await response.read())
        response = await self.client.get('/api/authentication/guide?platform=fabric', headers=self.headers)
        self.assertEqual(response.status, 400)
        response = await self.client.get('/mod-bridge-panel.js')
        self.assertEqual(response.status, 200)
        self.assertIn(b'/api/plugin/catalog', await response.read())
