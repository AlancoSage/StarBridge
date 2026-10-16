import asyncio
from base64 import b64decode
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock

from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from starbridge.app import create_app, STATE
from starbridge.qq_connection import QQConnection
from starbridge.reply_images import command_key, render_pages, RenderError, validate
from starbridge.settings import ConfigFile, runtime_config, serialize, validate as validate_config
from starbridge.storage import Store
from starbridge.onebot import OneBotActionError
from scripts.update_runtime import managed
from test_settings import full_config


class RenderingTests(unittest.TestCase):
    def test_legacy_config_and_new_config_roundtrip(self):
        cfg = full_config()
        self.assertNotIn('reply_images', validate_config(cfg))
        cfg['reply_images'] = {'enabled': True, 'commands': ['在线', '执行 在线检查']}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'config.toml'; path.write_text(serialize(cfg), encoding='utf-8')
            self.assertEqual(ConfigFile(path).read()[0], cfg)
        self.assertEqual(command_key('/help'), '帮助')
        self.assertEqual(command_key(' 执行   在线检查 '), '执行 在线检查')

    def test_invalid_settings(self):
        for value in [None, {'enabled': 1}, {'unknown': True}, {'enabled': True},
                      {'commands': '在线'}, {'commands': [{}]}, {'commands': ['在线', '在线']},
                      {'commands': [' 执行 在线检查']}, {'commands': ['help']}, {'commands': ['a\nb']}]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate(value)

    def test_chinese_png_and_literal_untrusted_text(self):
        pages = render_pages('生存服 · 在线\n玩家：2/20\n版本：1.21.11\n<CQ:image> [CQ:image,file=http://example.invalid]\n<script>literal</script>', '在线')
        self.assertEqual(len(pages), 1)
        with Image.open(BytesIO(pages[0])) as image:
            self.assertEqual(image.format, 'PNG'); self.assertEqual(image.mode, 'RGB')
            self.assertEqual(image.width, 1080)
            self.assertLess(image.height, 1600)
            self.assertLess(min(image.crop((52, 156, 900, 300)).convert('L').getextrema()), 100)

    def test_pagination_and_bounded_input(self):
        pages = render_pages('中'*3000, '状态')
        self.assertGreater(len(pages), 1); self.assertLessEqual(len(pages), 4)
        for page in pages:
            with Image.open(BytesIO(page)) as image:
                self.assertLessEqual(image.height, 1600)
        for text in ['', '中'*3501, '\n'*120, '\x00secret', '\U0001f600']:
            with self.subTest(text=text[:20]), self.assertRaises(RenderError):
                render_pages(text, '在线')

    def test_font_is_pinned_and_compatible_with_existing_updater(self):
        from starbridge.reply_font import font_data, SHA256
        self.assertEqual(hashlib.sha256(font_data()).hexdigest(), SHA256)
        self.assertTrue(managed('starbridge/reply_font.py'))
        self.assertIn(b'N\x00o\x00t\x00o', font_data())
        self.assertTrue((Path(__file__).resolve().parent.parent/'docs/noto-font-license.md').is_file())


class ReplySelectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = Store(':memory:')
        self.cfg = full_config(); self.cfg['reply_images'] = {'enabled': True, 'commands': ['在线', '帮助']}
        self.connection = QQConnection(self.cfg, self.store)
        self.connection.legacy.send_group = AsyncMock()
        self.connection.legacy.send_private = AsyncMock()
        self.connection.legacy.send_group_image = AsyncMock()

    async def asyncTearDown(self):
        await self.connection.close(); self.store.close()

    async def test_only_selected_replies_render_and_other_messages_stay_text(self):
        await self.connection.send_reply('101', '服务器在线', '在线')
        self.connection.legacy.send_group_image.assert_awaited_once()
        await self.connection.send_reply('101', '服务器状态', '状态')
        await self.connection.send_group('101', '普通游戏聊天')
        await self.connection.send_private('201', '私聊登录确认')
        self.assertEqual(self.connection.legacy.send_group.await_count, 2)
        self.connection.legacy.send_private.assert_awaited_once_with('201', '私聊登录确认')

    async def test_render_failure_and_explicit_rejection_fall_back_once(self):
        self.connection.renderer.render = AsyncMock(side_effect=RenderError('SECRET-REPLY'))
        await self.connection.send_reply('101', '正文', '在线')
        self.connection.legacy.send_group.assert_awaited_once_with('101', '正文')
        self.assertNotIn('SECRET-REPLY', json.dumps(self.store.logs()))
        self.connection.renderer.render = AsyncMock(return_value=[b'fixture-png'])
        self.connection.legacy.send_group_image.side_effect = RuntimeError('vendor secret')
        await self.connection.send_reply('101', '正文2', '在线')
        self.assertEqual(self.connection.legacy.send_group.await_count, 2)
        self.assertNotIn('vendor secret', json.dumps(self.store.logs()))

    async def test_unknown_send_result_and_partial_pages_are_not_replayed(self):
        self.connection.renderer.render = AsyncMock(return_value=[b'png1', b'png2'])
        self.connection.legacy.send_group_image.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError): await self.connection.send_reply('101', '正文', '在线')
        self.connection.legacy.send_group.assert_not_awaited()
        self.connection.legacy.send_group_image.side_effect = [None, RuntimeError('rejected')]
        with self.assertRaises(RuntimeError): await self.connection.send_reply('101', '正文', '在线')
        self.connection.legacy.send_group.assert_not_awaited()

    async def test_transport_change_cancels_waiting_render(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed(*args):
            entered.set(); await release.wait(); return [b'png']
        self.connection.renderer.render = delayed
        task = asyncio.create_task(self.connection.send_reply('101', '旧回复', '在线'))
        await entered.wait(); await self.connection.reconfigure(self.cfg, True); release.set()
        with self.assertRaises(ConnectionError): await task
        self.connection.legacy.send_group.assert_not_awaited()
        self.connection.legacy.send_group_image.assert_not_awaited()

    async def test_onebot_async_acceptance_does_not_trigger_text_fallback(self):
        self.connection.legacy.send_group_image = type(self.connection.legacy).send_group_image.__get__(self.connection.legacy)
        self.connection.legacy.call = AsyncMock(side_effect=OneBotActionError('send_group_msg', {'status':'async','retcode':1}))
        with self.assertRaises(ConnectionError): await self.connection.send_reply('101', '正文', '在线')
        self.connection.legacy.send_group.assert_not_awaited()

    async def test_disabling_images_during_render_sends_text(self):
        async def disable(*args):
            cfg = deepcopy(self.cfg); cfg['reply_images']['enabled'] = False
            await self.connection.reconfigure(cfg, False)
            return [b'png']
        self.connection.renderer.render = disable
        await self.connection.send_reply('101', '正文', '在线')
        self.connection.legacy.send_group.assert_awaited_once_with('101', '正文')
        self.connection.legacy.send_group_image.assert_not_awaited()

    async def test_disabling_after_first_page_does_not_send_remaining_pages_or_repeat_text(self):
        self.connection.renderer.render = AsyncMock(return_value=[b'png1', b'png2'])
        async def disable(*args):
            cfg = deepcopy(self.cfg); cfg['reply_images']['enabled'] = False
            await self.connection.reconfigure(cfg, False)
        self.connection.legacy.send_group_image.side_effect = disable
        with self.assertRaises(ConnectionError): await self.connection.send_reply('101', '正文', '在线')
        self.connection.legacy.send_group_image.assert_awaited_once()
        self.connection.legacy.send_group.assert_not_awaited()


class ImageReplyApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.path = Path(self.tmp.name)/'config.toml'
        cfg = full_config(); cfg['reply_images'] = {'enabled': True, 'commands': ['在线', '执行 在线检查', '官网']}
        self.path.write_text(serialize(cfg), encoding='utf-8')
        self.client = TestClient(TestServer(create_app(runtime_config(cfg, self.path), self.path)))
        await self.client.start_server(); self.state = self.client.app[STATE]
        self.headers = {'Authorization': 'Bearer '+cfg['app']['admin_token']}
        self.state['bot'].snapshots['survival'] = {'last_seen':time.time(), 'players':['Steve'], 'max_players':20, 'version':'test'}
        self.ws = None

    async def asyncTearDown(self):
        if self.ws: await self.ws.close()
        await self.client.close(); self.tmp.cleanup()

    async def receive_reply(self, text, mid):
        await self.ws.send_json({'post_type':'message', 'message_type':'group', 'group_id':101, 'user_id':201,
                                 'self_id':100, 'message_id':mid, 'message':text})
        return await asyncio.wait_for(self.ws.receive_json(), 5)

    async def acknowledge(self, reply):
        await self.ws.send_json({'status':'ok','retcode':0,'echo':reply['echo'],'data':{'message_id':1}})

    async def test_onebot_selected_builtin_keyword_and_async_command_result(self):
        self.ws = await self.client.ws_connect('/onebot/ws', headers={'Authorization':'Bearer '+self.state['config']['onebot']['token'], 'X-Self-ID':'100'})
        for index, (command, kind) in enumerate([('在线','image'), ('状态','text'), ('官网','image'), ('执行 在线检查','image')]):
            reply = await self.receive_reply(command, index)
            self.assertEqual(reply['action'], 'send_group_msg')
            segment = reply['params']['message'][0]; self.assertEqual(segment['type'], kind)
            if kind == 'image':
                self.assertTrue(segment['data']['file'].startswith('base64://'))
                with Image.open(BytesIO(b64decode(segment['data']['file'][9:]))) as image:
                    self.assertEqual(image.format, 'PNG')
            await self.acknowledge(reply)
        await self.state['onebot'].events.join()
        job = self.state['store'].poll('survival')[0]
        self.assertEqual(job['reply_command'], '执行 在线检查')
        response = await self.client.post('/bridge/survival/tick', headers={'Authorization':'Bearer '+self.state['bot'].servers['survival']['token']},
                                         json={'players':[], 'max_players':20, 'events':[], 'results':[{'id':job['id'],'ok':True,'detail':'在线玩家：Steve'}]})
        self.assertEqual(response.status, 200)
        result = await asyncio.wait_for(self.ws.receive_json(), 5)
        self.assertEqual(result['params']['message'][0]['type'], 'image')
        await self.acknowledge(result)

    async def test_owner_preview_produces_png_without_config_or_job_writes(self):
        before = self.path.read_bytes()
        response = await self.client.post('/api/reply-images/preview', headers=self.headers, json={'command':'在线','text':'生存服 · 在线\n玩家：2/20'})
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        data = await response.json(); self.assertEqual(len(data['pages']), 1)
        with Image.open(BytesIO(b64decode(data['pages'][0].split(',', 1)[1]))) as image:
            self.assertEqual(image.format, 'PNG')
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.state['store'].poll('survival'), [])

    async def test_preview_rejects_bad_input_and_invalid_save_is_atomic(self):
        for payload in [{'command':'在线','text':'x'*3501}, {'command':'在线','text':{}}, {'command':'','text':'x'}, {'command':'在线','text':'x','url':'http://invalid'}]:
            response = await self.client.post('/api/reply-images/preview', headers=self.headers, json=payload)
            self.assertEqual(response.status, 400)
        before = self.path.read_bytes()
        config = await (await self.client.get('/api/config', headers=self.headers)).json()
        config['config']['reply_images'] = {'enabled':True, 'commands':[]}
        response = await self.client.put('/api/config', headers=self.headers, json=config)
        self.assertEqual(response.status, 400); self.assertEqual(self.path.read_bytes(), before)

    async def test_preview_requires_owner(self):
        response = await self.client.post('/api/reply-images/preview', json={'command':'在线','text':'x'})
        self.assertEqual(response.status, 401)
        await self.state['admin_accounts'].save({'username':'Observer','password':'fixture-observer-password','permissions':['status.read','plugins.manage']})
        login = await self.client.post('/api/admin-auth/login', json={'username':'Observer','password':'fixture-observer-password'})
        token = (await login.json())['access_token']
        response = await self.client.post('/api/reply-images/preview', headers={'Authorization':'Bearer '+token}, json={'command':'在线','text':'x'})
        self.assertEqual(response.status, 403)


if __name__ == '__main__': unittest.main()
