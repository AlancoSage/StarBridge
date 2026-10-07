from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from aiohttp.test_utils import TestClient, TestServer
from starbridge.app import create_app
from test_starbridge import config


class ForgeDownloadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = config()
        self.client = TestClient(TestServer(create_app(self.cfg)))
        await self.client.start_server()
        self.headers = {'Authorization': 'Bearer ' + self.cfg['app']['admin_token']}
        (self.root / 'bridge/target').mkdir(parents=True)
        (self.root / 'bridge/target/StarBridge-0.5.0.jar').write_bytes(b'bukkit-fixture')
        (self.root / 'bridge/target/StarBridge-Forge-1.20.1-0.1.0.jar').write_bytes(b'forge-fixture')

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    async def test_platform_selection_authentication_and_unknown_platform(self):
        with patch('starbridge.app.Path', return_value=self.root / 'starbridge/app.py'):
            for platform, expected in (('bukkit', b'bukkit-fixture'), ('forge', b'forge-fixture')):
                response = await self.client.get('/api/plugin?platform=' + platform, headers=self.headers)
                self.assertEqual(response.status, 200)
                self.assertEqual(await response.read(), expected)
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                self.assertIn('attachment;', response.headers['Content-Disposition'])
            response = await self.client.get('/api/plugin?platform=forge')
            self.assertEqual(response.status, 401)
            response = await self.client.get('/api/plugin?platform=../../config.toml', headers=self.headers)
            self.assertEqual(response.status, 400)
            (self.root / 'bridge/target/StarBridge-Forge-1.20.1-0.1.0.jar').unlink()
            response = await self.client.get('/api/plugin?platform=forge', headers=self.headers)
            self.assertEqual(response.status, 404)
