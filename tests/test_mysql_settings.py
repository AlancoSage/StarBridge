import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from starbridge.app import STATE, create_app, database_errors
from starbridge.config import load
from starbridge.mysql_settings import MYSQL_DEFAULTS, validate_mysql
from starbridge.settings import ConfigFile, serialize, validate
from test_settings import full_config


class MySQLConfigTests(unittest.TestCase):
    def test_optional_block_and_secret_round_trip(self):
        original = full_config()
        self.assertNotIn('mysql', validate(original))
        self.assertNotIn('[mysql]', serialize(original))
        cfg = deepcopy(original)
        cfg['mysql'] = {'password': ' quote" \\ percent% 密码\n', 'tls': True, 'ssl_ca': 'certs/ca.pem'}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.toml'
            path.write_text(serialize(validate(cfg)), encoding='utf-8')
            saved, _ = ConfigFile(path).read()
            self.assertEqual(saved['mysql'], validate_mysql(cfg['mysql']))
            self.assertEqual(load(path)['mysql']['ssl_ca'], str((path.parent / 'certs/ca.pem').resolve()))
            self.assertNotIn('mysql', original)

    def test_invalid_mysql_fields_never_echo_values(self):
        bad = [('enabled', 1), ('port', True), ('port', 65536), ('host', 'mysql://secret:password@localhost'),
               ('database', 'db;DROP TABLE'), ('user', 'user\nsecret'), ('password', 'secret\x00'),
               ('read_timeout', 31), ('write_timeout', 0), ('connect_timeout', '5'),
               ('tls', 'false'), ('ssl_ca', 'secret\nkey'), ('unsupported', 'secret')]
        for key, value in bad:
            with self.subTest(key=key), self.assertRaises(ValueError) as result:
                validate_mysql({key: value})
            self.assertNotIn('secret', str(result.exception))
        with self.assertRaises(ValueError):
            validate_mysql({'ssl_ca': 'cert.pem'})

    def test_legacy_supervisor_cannot_enable_remote_database(self):
        cfg = full_config(); cfg['mysql'] = {**MYSQL_DEFAULTS, 'enabled': True}
        with patch.dict('os.environ', {'STARBRIDGE_SUPERVISED':'1', 'MYRINBOT_MYSQL_SUPERVISOR':''}):
            with patch('starbridge.app.Store') as store, self.assertRaisesRegex(ValueError, '完全退出'):
                create_app(cfg)
            store.assert_not_called()


class MySQLSettingsAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'config.toml'
        self.path.write_text(serialize(full_config()), encoding='utf-8')
        self.client = TestClient(TestServer(create_app(load(self.path), self.path, asyncio.Event())))
        await self.client.start_server()
        self.state = self.client.app[STATE]
        self.headers = {'Authorization':'Bearer ' + full_config()['app']['admin_token']}

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    async def test_save_requires_restart_without_switching_live_connection(self):
        response = await self.client.get('/api/config', headers=self.headers)
        data = await response.json()
        data['config']['mysql'] = {**MYSQL_DEFAULTS, 'enabled': True, 'password':'test-only-secret'}
        result = await self.client.put('/api/config', headers=self.headers, json={'config':data['config'], 'revision':data['revision']})
        self.assertEqual(result.status, 200, await result.text())
        self.assertIn('mysql', (await result.json())['restart_required'])
        self.assertNotIn('mysql', self.state['config'])
        self.assertIsInstance(self.state['store'].db, sqlite3.Connection)
        status = await (await self.client.get('/api/database/status', headers=self.headers)).json()
        self.assertEqual(status['backend'], 'sqlite')
        self.assertNotIn('password', json.dumps(status))

    async def test_connection_test_checks_authorization_and_never_saves(self):
        prior = self.path.read_bytes()
        with patch('starbridge.database_api.MySQLConnection') as connection:
            denied = await self.client.post('/api/database/test', json={'mysql':MYSQL_DEFAULTS})
            self.assertEqual(denied.status, 401)
            connection.assert_not_called()
            response = await self.client.post('/api/database/test', headers=self.headers, json={'mysql':MYSQL_DEFAULTS})
            self.assertEqual((await response.json())['status'], 'ok')
            connection.return_value.close.assert_called_once()
        self.assertEqual(self.path.read_bytes(), prior)

    async def test_connection_errors_do_not_leak_driver_details(self):
        with patch('starbridge.database_api.MySQLConnection', side_effect=sqlite3.OperationalError('secret-sql-password')):
            response = await self.client.post('/api/database/test', headers=self.headers, json={'mysql':MYSQL_DEFAULTS})
        raw = await response.text()
        self.assertNotIn('secret-sql-password', raw)
        self.assertEqual(json.loads(raw)['status'], 'error')

    async def test_export_and_import_keep_local_credentials_and_database_target(self):
        cfg, revision = self.state['config_file'].read()
        cfg['mysql'] = {**MYSQL_DEFAULTS, 'password':'local-only-secret'}
        self.state['config_file'].save(cfg, revision)
        exported = self.state['deployment'].export()
        self.assertNotIn('local-only-secret', json.dumps(exported))
        exported['config']['mysql'].update(host='evil.example', password='external-secret', enabled=True)
        preview = self.state['deployment'].preview({'content':json.dumps(exported)})
        staged = self.state['deployment'].previews[preview['preview_id']]['config']
        self.assertEqual(staged['mysql'], cfg['mysql'])

    async def test_runtime_database_error_is_sanitized(self):
        async def failed(request):
            raise sqlite3.OperationalError('secret-password SQL details')
        response = await database_errors(None, failed)
        self.assertEqual(response.status, 503)
        self.assertNotIn('secret-password', response.text)
