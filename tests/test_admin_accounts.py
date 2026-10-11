import asyncio
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from starbridge.app import STATE, create_app
from starbridge.admin_accounts import PERMISSIONS, PRESETS
from starbridge.config import load
from starbridge.passwords import check_password
from starbridge.settings import ConfigFile, serialize
from test_settings import full_config


class OwnerAccountTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.path = self.base / 'config.toml'
        self.cfg = full_config()
        self.path.write_text(serialize(self.cfg), encoding='utf-8')
        self.restart = asyncio.Event()
        await self.start()
        self.root = {'Authorization': 'Bearer ' + self.cfg['app']['admin_token']}
        self.account = {'username': 'admin', 'password': 'Owner-password-2026'}

    async def start(self):
        self.client = TestClient(TestServer(create_app(load(self.path), self.path, self.restart)))
        await self.client.start_server()
        self.state = self.client.app[STATE]
        self.db = self.state['store'].db

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    async def setup_owner(self):
        response = await self.client.post('/api/admin-auth/setup', headers=self.root, json=self.account)
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        result = await response.json()
        return result, {'Authorization': 'Bearer ' + result['access_token']}

    async def team(self, username='Observer', scope=PRESETS['observer']):
        response = await self.client.post('/api/admin-users', headers=self.root,
            json={'username': username, 'password': 'Team-password-2026', 'permissions': scope})
        self.assertEqual(response.status, 200, await response.text())
        users = (await response.json())['users']
        user = next(row for row in users if row['username'] == username)
        response = await self.client.post('/api/admin-auth/login',
            json={'username': username, 'password': 'Team-password-2026'})
        self.assertEqual(response.status, 200, await response.text())
        return user, {'Authorization': 'Bearer ' + (await response.json())['access_token']}

    async def test_setup_status_is_public_and_bootstrap_requires_exact_current_token(self):
        response = await self.client.get('/api/admin-auth/setup')
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.json(), {'required': True})
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        _, team = await self.team()
        with patch.object(self.state['registration'].password_work, 'run') as work:
            for headers in ({}, {'Authorization': 'Bearer wrong'}, team,
                            {'Authorization': 'Bearer ' + self.cfg['servers'][0]['token']}):
                response = await self.client.post('/api/admin-auth/setup', headers=headers, json=self.account)
                self.assertEqual(response.status, 401, await response.text())
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
            work.assert_not_called()
        self.assertEqual(self.db.execute('SELECT count(*) FROM admin_owner').fetchone()[0], 0)
        result, headers = await self.setup_owner()
        self.assertEqual((await self.client.get('/api/admin-auth/setup')).status, 200)
        self.assertEqual(await (await self.client.get('/api/admin-auth/setup')).json(), {'required': False})
        self.assertEqual(result['identity']['username'], 'admin')
        self.assertTrue(result['identity']['owner'])
        self.assertEqual((await self.client.post('/api/admin-auth/setup', headers=headers, json=self.account)).status, 401)
        duplicate = await self.client.post('/api/admin-auth/setup', headers=self.root,
                                          json={'username': 'Other', 'password': 'Other-password-2026'})
        self.assertEqual(duplicate.status, 409)
        self.assertEqual(self.db.execute('SELECT username FROM admin_owner').fetchone()[0], 'admin')

    async def test_setup_validates_credentials_without_storing_plaintext_or_exposing_hashes(self):
        invalid = ({'username': 'ab'}, {'username': '用户名'}, {'username': 'a' * 33},
                   {'password': 'short'}, {'password': 'x' * 129}, {'password': 'x' * 10 + '\x7f'},
                   {'password': None}, {'permissions': ['owner']})
        for change in invalid:
            response = await self.client.post('/api/admin-auth/setup', headers=self.root, json=self.account | change)
            self.assertEqual(response.status, 400, await response.text())
        result, headers = await self.setup_owner()
        row = self.db.execute('SELECT * FROM admin_owner').fetchone()
        self.assertNotEqual(row['password_hash'], self.account['password'])
        self.assertTrue(check_password(self.account['password'], row['password_hash']))
        stored = self.db.execute('SELECT * FROM admin_sessions').fetchone()
        self.assertEqual(stored['token_hash'], hashlib.sha256(result['access_token'].encode()).hexdigest())
        self.assertNotEqual(result['access_token'], self.cfg['app']['admin_token'])
        self.assertEqual(stored['user_id'], 'owner')
        self.assertEqual(result['expires_in'], 28800)
        session = await (await self.client.get('/api/session', headers=headers)).json()
        listing = await (await self.client.get('/api/admin-users', headers=headers)).json()
        public = await (await self.client.get('/api/admin-auth/setup')).json()
        for value in (result, session, listing, public):
            serialized = json.dumps(value)
            self.assertNotIn(row['password_hash'], serialized)
            self.assertNotIn(self.account['password'], serialized)
        self.assertEqual(listing['users'], [])

    async def test_owner_session_has_full_read_and_write_authority_and_no_game_identity(self):
        result, headers = await self.setup_owner()
        self.assertEqual(set(result['identity']['permissions']), set(PERMISSIONS))
        paths = ('/api/config', '/api/admin-users', '/api/status', '/api/registration/settings',
                 '/api/authentication/settings', '/api/website/settings', '/api/player-profiles',
                 '/api/extensions', '/api/schedules', '/api/monitoring', '/api/statistics',
                 '/api/backups', '/api/updates', '/api/community-features')
        for path in paths:
            with self.subTest(path=path):
                root = await self.client.get(path, headers=self.root)
                response = await self.client.get(path, headers=headers)
                self.assertEqual(root.status, 200, await root.text())
                self.assertEqual(response.status, root.status)
                self.assertNotIn(response.status, (401, 403))
        payload = await (await self.client.get('/api/config', headers=headers)).json()
        payload['config']['servers'][0]['name'] = 'Owner changed server'
        response = await self.client.put('/api/config', headers=headers, json=payload)
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual(ConfigFile(self.path).read()[0]['servers'][0]['name'], 'Owner changed server')
        response = await self.client.post('/api/admin-users', headers=headers,
            json={'username': 'Helper', 'password': 'Helper-password-2026', 'permissions': PRESETS['admin']})
        self.assertEqual(response.status, 200, await response.text())
        backup = await self.client.post('/api/backups', headers=headers)
        self.assertEqual(backup.status, 200, await backup.text())
        self.assertEqual((await self.client.get('/api/backups/' + (await backup.json())['id'], headers=headers)).status, 200)
        for path in ('/bridge/survival/tick', '/bridge/survival/auth'):
            self.assertEqual((await self.client.post(path, headers=headers, json={})).status, 401)
        self.assertEqual((await self.client.get('/api/v1/me/services', headers=headers)).status, 401)
        self.assertEqual((await self.client.post('/api/restart', headers=headers)).status, 200)
        await asyncio.wait_for(self.restart.wait(), 2)

    async def test_team_admin_preset_keeps_owner_boundaries_and_cannot_bootstrap(self):
        _, headers = await self.team('TeamAdmin', PRESETS['admin'])
        self.assertEqual((await self.client.get('/api/statistics', headers=headers)).status, 200)
        identity = await (await self.client.get('/api/session', headers=headers)).json()
        self.assertFalse(identity['owner'])
        for method, path in (('get', '/api/config'), ('get', '/api/admin-users'), ('post', '/api/restart'),
                             ('get', '/api/registration/settings'), ('get', '/api/authentication/settings'),
                             ('get', '/api/updates'), ('post', '/api/backups/restore')):
            with self.subTest(path=path):
                self.assertEqual((await getattr(self.client, method)(path, headers=headers, json={})).status, 403)
        self.assertEqual((await self.client.post('/api/admin-auth/setup', headers=headers, json=self.account)).status, 401)
        self.assertEqual(self.db.execute('SELECT count(*) FROM admin_owner').fetchone()[0], 0)
        await self.setup_owner()
        self.assertEqual((await self.client.get('/api/config', headers=headers)).status, 403)

    async def test_owner_login_is_case_insensitive_and_bad_password_is_generic(self):
        await self.setup_owner()
        response = await self.client.post('/api/admin-auth/login', json=self.account | {'username': 'ADMIN'})
        self.assertEqual(response.status, 200, await response.text())
        result = await response.json()
        self.assertEqual(result['identity']['username'], 'admin')
        self.assertTrue(result['identity']['owner'])
        failures = []
        for username in ('admin', 'Missing'):
            response = await self.client.post('/api/admin-auth/login',
                json={'username': username, 'password': 'Incorrect-password-2026'})
            self.assertEqual(response.status, 401)
            failures.append(await response.json())
        self.assertEqual(failures[0], failures[1])
        self.assertEqual((await self.client.post('/api/admin-auth/login',
            json=self.account | {'password': 'Invalid-password\x7f'})).status, 401)

    async def test_owner_logout_expiry_and_session_limit_revoke_without_changing_legacy_token(self):
        _, first = await self.setup_owner()
        response = await self.client.post('/api/admin-auth/logout', headers=first)
        self.assertEqual(response.status, 200)
        self.assertEqual((await self.client.get('/api/session', headers=first)).status, 401)
        tokens = []
        for _ in range(6):
            response = await self.client.post('/api/admin-auth/login', json=self.account)
            self.assertEqual(response.status, 200, await response.text())
            tokens.append((await response.json())['access_token'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM admin_sessions WHERE user_id=?', ('owner',)).fetchone()[0], 5)
        self.assertEqual((await self.client.get('/api/session', headers={'Authorization': 'Bearer ' + tokens[0]})).status, 401)
        newest = {'Authorization': 'Bearer ' + tokens[-1]}
        with self.db:
            self.db.execute('UPDATE admin_sessions SET expires=? WHERE token_hash=?',
                            (time.time() - 1, hashlib.sha256(tokens[-1].encode()).hexdigest()))
        self.assertEqual((await self.client.get('/api/config', headers=newest)).status, 401)
        self.assertEqual((await self.client.get('/api/config', headers=self.root)).status, 200)

    async def test_existing_team_deployment_migrates_without_replacing_credentials_or_sessions(self):
        _, headers = await self.team()
        old_hash = self.db.execute('SELECT password_hash FROM admin_users').fetchone()[0]
        database = self.state['config']['app']['database']
        await self.client.close()
        with closing(sqlite3.connect(database)) as db:
            with db:
                db.execute('DROP TABLE admin_owner')
        await self.start()
        self.assertEqual(await (await self.client.get('/api/admin-auth/setup')).json(), {'required': True})
        self.assertEqual(self.db.execute('SELECT password_hash FROM admin_users').fetchone()[0], old_hash)
        self.assertEqual((await self.client.get('/api/session', headers=headers)).status, 200)
        await self.setup_owner()
        self.assertEqual((await self.client.get('/api/session', headers=headers)).status, 200)
        await self.client.close()
        await self.start()
        response = await self.client.post('/api/admin-auth/login', json=self.account)
        self.assertEqual(response.status, 200, await response.text())
        self.assertTrue((await response.json())['identity']['owner'])

    async def test_usernames_cannot_collide_with_team_before_or_after_setup(self):
        user, headers = await self.team('ADMIN')
        response = await self.client.post('/api/admin-auth/setup', headers=self.root, json=self.account)
        self.assertEqual(response.status, 409)
        self.assertEqual(self.db.execute('SELECT count(*) FROM admin_owner').fetchone()[0], 0)
        self.account['username'] = 'HostOwner'
        _, owner = await self.setup_owner()
        for method, path, payload in (
            ('post', '/api/admin-users', {'username': 'hostowner', 'password': 'Team-password-2026'}),
            ('put', '/api/admin-users/' + user['id'], {'username': 'HOSTOWNER', 'revision': user['revision']})):
            response = await getattr(self.client, method)(path, headers=owner, json=payload)
            self.assertEqual(response.status, 409, await response.text())
        self.assertEqual((await self.client.get('/api/session', headers=headers)).status, 200)

    async def test_concurrent_setup_only_creates_one_owner_without_overwrite(self):
        responses = await asyncio.gather(*[
            self.client.post('/api/admin-auth/setup', headers=self.root,
                             json=self.account | {'username': name}) for name in ('FirstOwner', 'SecondOwner')])
        self.assertEqual(sorted(response.status for response in responses), [200, 409])
        result = await next(response for response in responses if response.status == 200).json()
        self.assertEqual(self.db.execute('SELECT count(*) FROM admin_owner').fetchone()[0], 1)
        self.assertEqual(self.db.execute('SELECT username FROM admin_owner').fetchone()[0], result['identity']['username'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM admin_sessions').fetchone()[0], 1)

    async def test_concurrent_setup_and_team_creation_cannot_share_a_username(self):
        responses = await asyncio.gather(
            self.client.post('/api/admin-auth/setup', headers=self.root, json=self.account),
            self.client.post('/api/admin-users', headers=self.root,
                             json={'username': 'ADMIN', 'password': 'Team-password-2026'}))
        self.assertEqual(sorted(response.status for response in responses), [200, 409])
        self.assertEqual(self.db.execute('SELECT count(*) FROM admin_owner').fetchone()[0] +
                         self.db.execute('SELECT count(*) FROM admin_users').fetchone()[0], 1)

    async def test_rotated_bootstrap_token_cannot_finish_setup_after_password_hashing(self):
        work = self.state['registration'].password_work
        original = work.run
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed(*args):
            result = await original(*args)
            entered.set()
            await release.wait()
            return result
        with patch.object(work, 'run', side_effect=delayed):
            task = asyncio.create_task(self.client.post('/api/admin-auth/setup', headers=self.root, json=self.account))
            await asyncio.wait_for(entered.wait(), 5)
            self.state['config']['app']['admin_token'] = 'rotated-admin-token-2026'
            release.set()
            response = await task
        self.assertEqual(response.status, 401)
        self.assertEqual(self.db.execute('SELECT count(*) FROM admin_owner').fetchone()[0], 0)

    async def test_revoked_owner_session_cannot_commit_waiting_config_write(self):
        _, headers = await self.setup_owner()
        payload = await (await self.client.get('/api/config', headers=headers)).json()
        original = self.path.read_bytes()
        payload['config']['servers'][0]['name'] = 'Must not commit'
        lock = self.state['settings_lock']
        await lock.acquire()
        try:
            task = asyncio.create_task(self.client.put('/api/config', headers=headers, json=payload))
            for _ in range(100):
                if lock._waiters:
                    break
                await asyncio.sleep(0.01)
            self.assertTrue(lock._waiters)
            self.assertEqual((await self.client.post('/api/admin-auth/logout', headers=headers)).status, 200)
        finally:
            lock.release()
        response = await task
        self.assertEqual(response.status, 401, await response.text())
        self.assertEqual(self.path.read_bytes(), original)

    async def test_revoked_owner_session_cannot_commit_team_creation_after_hashing(self):
        _, headers = await self.setup_owner()
        work = self.state['registration'].password_work
        original = work.run
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed(*args):
            result = await original(*args)
            entered.set()
            await release.wait()
            return result
        with patch.object(work, 'run', side_effect=delayed):
            task = asyncio.create_task(self.client.post('/api/admin-users', headers=headers,
                json={'username': 'NewTeam', 'password': 'Team-password-2026'}))
            await asyncio.wait_for(entered.wait(), 5)
            self.assertEqual((await self.client.post('/api/admin-auth/logout', headers=headers)).status, 200)
            release.set()
            response = await task
        self.assertEqual(response.status, 401)
        self.assertEqual(self.db.execute('SELECT count(*) FROM admin_users').fetchone()[0], 0)

    async def test_malformed_team_id_cannot_become_an_owner_session(self):
        user, _ = await self.team()
        await self.setup_owner()
        with self.db:
            self.db.execute("UPDATE admin_users SET id='owner' WHERE id=?", (user['id'],))
        response = await self.client.post('/api/admin-auth/login',
            json={'username': 'Observer', 'password': 'Team-password-2026'})
        self.assertEqual(response.status, 401)
