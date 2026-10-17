import asyncio
from base64 import b64decode
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from aiohttp.test_utils import TestClient, TestServer

from starbridge.app import STATE, create_app
from starbridge.bot import Bot
from starbridge.qq_connection import QQConnection
from starbridge.reply_images import RenderError
from starbridge.settings import runtime_config, serialize
from starbridge.storage import Store
from test_settings import full_config


def two_servers():
    cfg = full_config()
    cfg['reply_images'] = {'enabled': True, 'commands': ['在线', '状态', '帮助']}
    other = deepcopy(cfg['servers'][0])
    other.update(id='private', name='另一台服务器', groups=['102'], token='game-' + 'd' * 32)
    cfg['servers'].append(other)
    return cfg


def snapshots(bot):
    bot.snapshots.update({
        'survival': {'last_seen': time.time(), 'players': ['Steve'], 'max_players': 20,
                     'version': '1.21.11', 'player_records': [{'ip': '192.0.2.1', 'notes': 'private'}]},
        'private': {'last_seen': time.time(), 'players': ['OtherPlayer'], 'max_players': 50,
                    'version': 'private-version', 'ip': '192.0.2.2'},
    })


class ReplyViewTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = Store(':memory:')
        self.cfg = two_servers()
        self.connection = QQConnection(self.cfg, self.store)
        self.connection.renderer.render = AsyncMock(return_value=[b'png-fixture'])
        self.connection.legacy.send_group = AsyncMock()
        self.connection.legacy.send_group_image = AsyncMock()
        self.bot = Bot(self.cfg, self.store, self.connection)
        snapshots(self.bot)

    async def asyncTearDown(self):
        await self.connection.close()
        self.store.close()

    async def test_status_and_online_context_are_scoped_to_the_current_group(self):
        for index, command in enumerate(('在线', '状态')):
            await self.bot.handle_event({'post_type': 'message', 'message_type': 'group',
                                         'self_id': '100', 'user_id': '201', 'group_id': '101',
                                         'message_id': index, 'message': command})
            args = self.connection.renderer.render.await_args.args
            self.assertEqual(args[1], command)
            view = args[2]
            self.assertEqual(view['type'], 'server_status')
            self.assertLess(abs(time.time() - view['updated']), 2)
            self.assertEqual(view['servers'], [{'id': 'survival', 'name': '生存服', 'online': True,
                                                'players': ['Steve'], 'max_players': 20,
                                                'version': '1.21.11'}])
            serialized = json.dumps(view)
            for value in ('OtherPlayer', 'private-version', 'player_records', '192.0.2', 'notes', 'token'):
                self.assertNotIn(value, serialized)
        self.assertEqual(self.connection.legacy.send_group_image.await_count, 2)

    async def test_other_group_gets_only_its_own_server_and_snapshot_is_detached(self):
        await self.bot.reply('102', '状态正文', '状态')
        view = self.connection.renderer.render.await_args.args[2]
        self.assertEqual([server['id'] for server in view['servers']], ['private'])
        self.assertEqual(view['servers'][0]['players'], ['OtherPlayer'])
        self.bot.snapshots['private']['players'].append('LaterPlayer')
        self.assertEqual(view['servers'][0]['players'], ['OtherPlayer'])

    async def test_offline_context_drops_stale_player_capacity_and_version(self):
        self.bot.snapshots['survival']['last_seen'] = time.time() - 16
        await self.bot.reply('101', '桥接离线', '在线')
        server = self.connection.renderer.render.await_args.args[2]['servers'][0]
        self.assertEqual(server, {'id': 'survival', 'name': '生存服', 'online': False,
                                 'players': [], 'max_players': 0, 'version': ''})

    async def test_missing_snapshot_does_not_invent_online_players(self):
        self.bot.snapshots.clear()
        server = self.bot.status_view(self.bot.servers['survival'])['servers'][0]
        self.assertFalse(server['online'])
        self.assertEqual(server['players'], [])

    async def test_unknown_group_and_no_configured_servers_do_not_select_a_default(self):
        await self.bot.reply('999', '原文', '在线')
        self.connection.renderer.render.assert_awaited_once_with('原文', '在线')
        cfg = deepcopy(self.cfg); cfg['servers'] = []
        empty = Bot(cfg, self.store, self.connection)
        self.connection.renderer.render.reset_mock()
        await empty.handle_event({'post_type': 'message', 'message_type': 'group', 'group_id': '101',
                                  'self_id': '100', 'user_id': '201', 'message_id': 'empty', 'message': '在线'})
        self.connection.renderer.render.assert_not_awaited()

    async def test_other_commands_preserve_the_legacy_send_reply_signature(self):
        calls = []
        async def legacy_reply(group, text, command):
            calls.append((group, text, command))
        bot = Bot(self.cfg, self.store, SimpleNamespace(send_reply=legacy_reply))
        await bot.reply('101', '帮助正文', '帮助')
        await bot.reply('999', '在线正文', '在线')
        self.assertEqual(calls, [('101', '帮助正文', '帮助'), ('999', '在线正文', '在线')])

    async def test_legacy_text_transport_remains_supported(self):
        transport = SimpleNamespace(send_group=AsyncMock())
        bot = Bot(self.cfg, self.store, transport)
        await bot.reply('101', '原文', '在线')
        transport.send_group.assert_awaited_once_with('101', '原文')

    async def test_none_view_preserves_two_argument_renderer(self):
        calls = []
        async def legacy_render(text, title):
            calls.append((text, title))
            return [b'png-fixture']
        self.connection.renderer.render = legacy_render
        await self.connection.send_reply('101', '帮助正文', '帮助')
        self.assertEqual(calls, [('帮助正文', '帮助')])

    async def test_unselected_status_reply_keeps_original_text(self):
        self.connection.image_config['commands'] = ['帮助']
        await self.bot.reply('101', '原文', '在线')
        self.connection.renderer.render.assert_not_awaited()
        self.connection.legacy.send_group.assert_awaited_once_with('101', '原文')

    async def test_group_reassignment_cancels_old_server_images_without_reconnecting_qq(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed(text, title, view):
            self.assertEqual(view['servers'][0]['id'], 'survival')
            entered.set()
            await release.wait()
            return [b'png-fixture']
        self.connection.renderer.render = delayed
        self.connection.official.close = AsyncMock()
        task = asyncio.create_task(self.bot.reply('101', '旧服状态', '在线'))
        await entered.wait()
        cfg = deepcopy(self.cfg)
        cfg['servers'][0]['groups'] = []
        cfg['servers'][1]['groups'] = ['101', '102']
        self.bot.groups = {group: server for server in cfg['servers'] for group in server['groups']}
        await self.connection.reconfigure(cfg, False)
        release.set()
        with self.assertRaises(ConnectionError):
            await task
        self.connection.legacy.send_group_image.assert_not_awaited()
        self.connection.legacy.send_group.assert_not_awaited()
        self.connection.official.close.assert_not_awaited()

    async def test_failed_render_does_not_fall_back_to_old_server_text_after_route_changes(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed_failure(text, title, view):
            entered.set()
            await release.wait()
            raise RenderError('fixture rendering failure')
        self.connection.renderer.render = delayed_failure
        task = asyncio.create_task(self.bot.reply('101', '旧服私密状态', '在线'))
        await entered.wait()
        cfg = deepcopy(self.cfg)
        cfg['servers'][0]['groups'] = []
        await self.connection.reconfigure(cfg, False)
        release.set()
        with self.assertRaises(ConnectionError):
            await task
        self.connection.legacy.send_group_image.assert_not_awaited()
        self.connection.legacy.send_group.assert_not_awaited()

    async def test_route_signature_tracks_server_identity_and_token_without_caching_raw_tokens(self):
        initial = self.connection.generation
        cfg = deepcopy(self.cfg)
        cfg['servers'][0]['name'] = '改名'
        cfg['servers'][0]['groups'].reverse()
        await self.connection.reconfigure(cfg, False)
        self.assertEqual(self.connection.generation, initial)
        cfg['servers'][0]['token'] = 'new-' + 'e' * 32
        await self.connection.reconfigure(cfg, False)
        self.assertEqual(self.connection.generation, initial + 1)
        self.assertNotIn(cfg['servers'][0]['token'], repr(self.connection.routes))
        cfg['servers'][0]['id'] = 'renamed-server'
        await self.connection.reconfigure(cfg, False)
        self.assertEqual(self.connection.generation, initial + 2)
        cfg['servers'] = []
        await self.connection.reconfigure(cfg, False)
        self.assertEqual(self.connection.routes, frozenset())

    async def test_missing_servers_config_keeps_existing_connection_compatibility(self):
        cfg = deepcopy(self.cfg)
        cfg.pop('servers')
        other = QQConnection(cfg, self.store)
        self.assertEqual(other.routes, frozenset())
        await other.reconfigure(cfg, False)
        self.assertEqual(other.generation, 0)
        await other.close()


class ReplyViewApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'config.toml'
        self.cfg = two_servers()
        self.path.write_text(serialize(self.cfg), encoding='utf-8')
        self.client = TestClient(TestServer(create_app(runtime_config(self.cfg, self.path), self.path)))
        await self.client.start_server()
        self.state = self.client.app[STATE]
        snapshots(self.state['bot'])
        self.renderer = self.state['onebot'].renderer.render = AsyncMock(return_value=[b'png-fixture'])
        self.headers = {'Authorization': 'Bearer ' + self.cfg['app']['admin_token']}

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    async def preview(self, payload):
        return await self.client.post('/api/reply-images/preview', headers=self.headers, json=payload)

    async def test_selected_server_uses_current_real_context_and_keeps_base64_response(self):
        before = self.path.read_bytes()
        response = await self.preview({'command': '在线', 'text': '预览文字', 'server': 'survival'})
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        data = await response.json()
        self.assertEqual(b64decode(data['pages'][0].split(',', 1)[1]), b'png-fixture')
        args = self.renderer.await_args.args
        self.assertEqual(args[:2], ('预览文字', '在线'))
        self.assertEqual(args[2]['servers'][0]['players'], ['Steve'])
        self.assertEqual(len(args[2]['servers']), 1)
        self.assertNotIn('OtherPlayer', json.dumps(args[2]))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.state['store'].poll('survival'), [])

    async def test_status_preview_drops_offline_snapshot(self):
        self.state['bot'].snapshots['survival']['last_seen'] = 0
        response = await self.preview({'command': '状态', 'text': '原文', 'server': 'survival'})
        self.assertEqual(response.status, 200)
        view = self.renderer.await_args.args[2]
        self.assertFalse(view['servers'][0]['online'])
        self.assertEqual(view['servers'][0]['players'], [])
        self.assertEqual(view['servers'][0]['max_players'], 0)
        self.assertEqual(view['servers'][0]['version'], '')

    async def test_absent_empty_server_and_other_commands_preserve_old_preview(self):
        for extra in ({}, {'server': ''}, {'server': 'survival'}):
            command = '帮助' if extra.get('server') else '在线'
            response = await self.preview({'command': command, 'text': '原文', **extra})
            self.assertEqual(response.status, 200)
            self.assertEqual(self.renderer.await_args.args, ('原文', command))

    async def test_invalid_or_unknown_server_never_falls_back_to_first_server(self):
        for server in (None, 1, True, [], {}, 'missing', ' survival', 'SURVIVAL', ' '):
            with self.subTest(server=server):
                response = await self.preview({'command': '在线', 'text': '原文', 'server': server})
                self.assertEqual(response.status, 400)
        self.renderer.assert_not_awaited()

    async def test_empty_server_list_supports_text_preview_but_rejects_unknown_selection(self):
        self.state['bot'].servers.clear()
        response = await self.preview({'command': '在线', 'text': '原文'})
        self.assertEqual(response.status, 200)
        self.assertEqual(self.renderer.await_args.args, ('原文', '在线'))
        response = await self.preview({'command': '在线', 'text': '原文', 'server': 'survival'})
        self.assertEqual(response.status, 400)

    async def test_preview_context_requires_owner_even_with_status_read_permission(self):
        payload = {'command': '在线', 'text': '原文', 'server': 'survival'}
        response = await self.client.post('/api/reply-images/preview', json=payload)
        self.assertEqual(response.status, 401)
        await self.state['admin_accounts'].save({'username': 'Observer', 'password': 'fixture-observer-password',
                                                'permissions': ['status.read']})
        login = await self.client.post('/api/admin-auth/login', json={'username': 'Observer',
                                                                    'password': 'fixture-observer-password'})
        token = (await login.json())['access_token']
        response = await self.client.post('/api/reply-images/preview',
                                          headers={'Authorization': 'Bearer ' + token}, json=payload)
        self.assertEqual(response.status, 403)
        self.renderer.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
