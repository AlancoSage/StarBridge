from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from aiohttp.test_utils import TestClient, TestServer
from starbridge.app import create_app
from starbridge.game_bridges import bridge_catalog, bridge_filename
from starbridge import __bridge_version__, __forge_version__
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
        (self.root / 'bridge/target' / f'StarBridge-{__bridge_version__}.jar').write_bytes(b'bukkit-fixture')
        for item in bridge_catalog():
            (self.root / 'bridge/target' / item['filename']).write_bytes(item['filename'].encode())

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    async def test_platform_selection_authentication_and_unknown_platform(self):
        with patch('starbridge.app.Path', return_value=self.root / 'starbridge/app.py'):
            for platform, expected in (('bukkit', b'bukkit-fixture'),
                                      ('forge', f'VexBot-Forge-1.20.1-{__forge_version__}.jar'.encode()),
                                      ('fabric', f'VexBot-Fabric-1.20.1-{__forge_version__}.jar'.encode())):
                response = await self.client.get('/api/plugin?platform=' + platform, headers=self.headers)
                self.assertEqual(response.status, 200)
                self.assertEqual(await response.read(), expected)
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                self.assertIn('attachment;', response.headers['Content-Disposition'])
                if platform == 'bukkit':
                    self.assertIn(f'VexBot-{__bridge_version__}.jar', response.headers['Content-Disposition'])
            for platform in ('forge', 'fabric'):
                response = await self.client.get('/api/plugin?platform='+platform)
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
            self.assertEqual(len(catalog), 24)
            self.assertEqual(len({item['filename'] for item in catalog}), 24)
            neoforge = [item for item in catalog if item['platform'] == 'neoforge']
            self.assertEqual([item['version'] for item in neoforge], ['1.20.4', '1.20.6', '1.21.1', '1.21.4', '1.21.8', '1.21.11', '26.1.2', '26.2'])
            self.assertEqual([item['java'] for item in neoforge], [17, 21, 21, 21, 21, 21, 25, 25])
            self.assertEqual([item['config'] for item in neoforge], ['properties', 'properties', 'toml', 'properties', 'properties', 'properties', 'properties', 'properties'])
            self.assertTrue(all(item['label'].startswith('NeoForge ') for item in neoforge))
            fabric = [item for item in catalog if item['platform'] == 'fabric']
            self.assertEqual([item['version'] for item in fabric], ['1.16.5', '1.18.2', '1.19.2', '1.20.1', '1.21.1', '1.21.8', '1.21.11', '26.1', '26.2', '26.3'])
            self.assertEqual([item['java'] for item in fabric], [8, 17, 17, 17, 21, 21, 21, 25, 25, 25])
            self.assertTrue(all(item['config'] == 'properties' and item['label'].startswith('Fabric ') for item in fabric))
            self.assertTrue(all(item['available'] for item in catalog))
            for item in catalog:
                response = await self.client.get('/api/plugin', params={key: item[key] for key in ('platform', 'version')}, headers=self.headers)
                self.assertEqual(response.status, 200)
                self.assertEqual(await response.read(), item['filename'].encode())
            for platform, version in [('forge', '../../config.toml'), ('forge', '1.21.1'), ('neoforge', '1.20.1'), ('bukkit', '1.12.2'), ('forge', ''),
                                      ('fabric', '../../config.toml'), ('fabric', '..\\config.toml'), ('fabric', '1.12.2'), ('fabric', ''),
                                      ('fabric', '1.20.1/../../config.toml'), ('neoforge', '26.1'), ('neoforge', '26.3'), ('neoforge', '1.21.11-beta')]:
                response = await self.client.get('/api/plugin', params={'platform': platform, 'version': version}, headers=self.headers)
                self.assertEqual(response.status, 400)
            with patch('starbridge.app.Path', return_value=self.root / 'missing/starbridge/app.py'):
                catalog = await (await self.client.get('/api/plugin/catalog', headers=self.headers)).json()
                self.assertTrue(all(not item['available'] for item in catalog['bridges']))
                for platform in ('neoforge', 'fabric'):
                    response = await self.client.get('/api/plugin?platform='+platform, headers=self.headers)
                    self.assertEqual(response.status, 404)

    async def test_catalog_rejects_unknown_versions_before_constructing_paths(self):
        for platform, version in (('fabric', '../secret'), ('fabric/..', '1.20.1'), ('fabric', '1.20.1.jar'), ('fabric', '1.20.1\\secret')):
            with self.assertRaises(ValueError):
                bridge_filename(platform, version)

    async def test_existing_deployment_artifact_is_downloadable_and_new_build_takes_precedence(self):
        directory = self.root / 'bridge/target'
        filename = bridge_filename('fabric', '1.20.1')
        (directory / filename).unlink()
        (directory / filename.replace('VexBot-', 'StarBridge-', 1)).write_bytes(b'legacy-build')
        with patch('starbridge.app.Path', return_value=self.root / 'starbridge/app.py'):
            catalog = await (await self.client.get('/api/plugin/catalog', headers=self.headers)).json()
            self.assertTrue(next(row for row in catalog['bridges'] if row['filename'] == filename)['available'])
            response = await self.client.get('/api/plugin?platform=fabric&version=1.20.1', headers=self.headers)
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.read(), b'legacy-build')
            self.assertIn(filename, response.headers['Content-Disposition'])
            (directory / filename.replace('VexBot-', 'AetherBot-', 1)).write_bytes(b'aetherbot-build')
            response = await self.client.get('/api/plugin?platform=fabric&version=1.20.1', headers=self.headers)
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.read(), b'aetherbot-build')
            (directory / filename.replace('VexBot-', 'Myrinbot-', 1)).write_bytes(b'myrinbot-build')
            response = await self.client.get('/api/plugin?platform=fabric&version=1.20.1', headers=self.headers)
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.read(), b'myrinbot-build')
            (directory / filename).write_bytes(b'current-build')
            response = await self.client.get('/api/plugin?platform=fabric&version=1.20.1', headers=self.headers)
            self.assertEqual(await response.read(), b'current-build')

    async def test_native_guide_platforms_and_panel_module(self):
        for platform in ('forge', 'neoforge', 'fabric'):
            response = await self.client.get('/api/authentication/guide?platform='+platform, headers=self.headers)
            self.assertEqual(response.status, 200)
            self.assertIn(b'1.16.5' if platform == 'fabric' else b'1.7.10', await response.read())
            self.assertIn('VexBot-fabric-game-ends.md' if platform == 'fabric' else 'VexBot-mod-game-ends.md', response.headers['Content-Disposition'])
        response = await self.client.get('/api/authentication/guide?platform=quilt', headers=self.headers)
        self.assertEqual(response.status, 400)
        response = await self.client.get('/mod-bridge-panel.js')
        self.assertEqual(response.status, 200)
        self.assertIn(b'/api/plugin/catalog', await response.read())
