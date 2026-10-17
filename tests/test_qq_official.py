import asyncio
from base64 import b64decode
from copy import deepcopy
import json
from io import BytesIO
from pathlib import Path
import struct
import tempfile
import time
import unittest
import zlib
from unittest.mock import patch
from unittest.mock import AsyncMock

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from starbridge.app import create_app, STATE
from starbridge.bot import Bot
from starbridge.qq_connection import QQConnection
from starbridge.qq_identity import official_id, official_parts
from starbridge.qq_official import QQOfficial
from starbridge.settings import validate, runtime_config, serialize, ConfigFile
from starbridge.storage import Store
from starbridge.reply_images import MAX_PNG, render_pages
from test_settings import full_config


APP = "102001"
GROUP = "GROUP_OPEN_ID"
USER = "MEMBER_OPEN_ID"
PRIVATE = "PRIVATE_OPEN_ID"


def official_config():
    cfg = full_config()
    cfg["qq_official"] = {"enabled": True, "app_id": APP, "client_secret": "fixture-private-secret",
                          "admins": [official_id("qug", APP, USER)], "allow_active": False}
    cfg["servers"][0]["groups"] = [official_id("qg", APP, GROUP)]
    return validate(cfg)


class OfficialConfigTests(unittest.TestCase):
    def test_legacy_and_official_round_trip_and_admin_scope(self):
        legacy = full_config()
        self.assertNotIn("qq_official", validate(legacy))
        cfg = official_config()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"config.toml"; path.write_text(serialize(cfg), encoding="utf-8")
            self.assertEqual(ConfigFile(path).read()[0], cfg)
            runtime = runtime_config(cfg, path)
            self.assertEqual(runtime["onebot"]["admins"], cfg["qq_official"]["admins"])
            self.assertEqual(cfg["onebot"]["admins"], legacy["onebot"]["admins"])

    def test_invalid_official_credentials_and_cross_app_admins(self):
        for key, value in [("enabled", 1), ("app_id", "invalid"), ("client_secret", ""),
                           ("client_secret", "line\nsecret"), ("allow_active", "true"),
                           ("admins", ["201"]), ("admins", [official_id("qug", "102002", USER)]),
                           ("admins", [{}]), ("admins", [official_id("qg", APP, GROUP)])]:
            cfg = official_config(); cfg["qq_official"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate(cfg)

    def test_group_namespace_and_identity_shapes(self):
        for bad in ["OPENID", "qg:102001:bad/path", "qug:102001:MEMBER", "qg:102001:bad space"]:
            cfg = official_config(); cfg["servers"][0]["groups"] = [bad]
            with self.subTest(bad=bad), self.assertRaises(ValueError): validate(cfg)
        for bad in [None, 123, {}, "", "bad/path"]:
            with self.assertRaises(ValueError): official_id("qug", APP, bad)
        self.assertNotEqual(official_id("qug", APP, USER), official_id("qup", APP, USER))
        self.assertIsNone(official_parts("201", ("qug",)))

    def test_gateway_only_official_tls_hosts(self):
        for url in ["wss://api.bot.qq.com/websocket/", "wss://api.sgroup.qq.com/websocket"]:
            self.assertTrue(QQOfficial.valid_gateway(url))
        for url in ["ws://api.bot.qq.com/", "wss://evil.invalid/", "wss://api.bot.qq.com.evil.invalid/", "wss://secret@api.bot.qq.com/", "wss://api.bot.qq.com:8443/", None]:
            self.assertFalse(QQOfficial.valid_gateway(url))


class OfficialTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = Store(":memory:"); self.events = asyncio.Queue(maxsize=256)
        self.tokens = []; self.messages = []; self.identify = asyncio.Queue(); self.sockets = []
        self.vendor_error = None
        self.uploads = []; self.file_info = 'fixture-file-info'
        self.media_error = None
        self.heartbeat_interval = 10000
        # A 2 MiB PNG grows to nearly 2.8 MiB inside JSON base64.
        app = web.Application(client_max_size=4 * 1024 * 1024)
        app.router.add_post("/app/getAppAccessToken", self.issue_token)
        app.router.add_get("/gateway", self.gateway)
        app.router.add_get("/socket", self.socket)
        app.router.add_post("/v2/{kind:groups|users}/{openid}/messages", self.message)
        app.router.add_post('/v2/groups/{openid}/files', self.upload)
        self.server = TestServer(app); await self.server.start_server()
        self.base = str(self.server.make_url("/")).rstrip("/")
        self.api_patch = patch.object(QQOfficial, "API_BASE", self.base); self.api_patch.start()
        self.url_patch = patch.object(QQOfficial, "valid_gateway", staticmethod(lambda url: url == str(self.server.make_url("/socket")).replace("http://", "ws://"))); self.url_patch.start()
        self.transport = QQOfficial(official_config()["qq_official"], self.store, self.events)
        await self.transport.start()
        await asyncio.wait_for(self.wait_connected(), 3)

    async def asyncTearDown(self):
        await self.transport.close(); await self.server.close(); self.url_patch.stop(); self.api_patch.stop(); self.store.close()

    async def wait_connected(self):
        while not self.transport.connected: await asyncio.sleep(.01)

    async def issue_token(self, request):
        data = await request.json(); self.tokens.append(data)
        if self.vendor_error: return web.json_response(self.vendor_error)
        return web.json_response({"access_token": "fixture-access-token", "expires_in": "7200"})

    async def gateway(self, request):
        self.assertEqual(request.headers["Authorization"], "QQBot fixture-access-token")
        return web.json_response({"url": str(self.server.make_url("/socket")).replace("http://", "ws://")})

    async def socket(self, request):
        ws = web.WebSocketResponse(); await ws.prepare(request); self.sockets.append(ws)
        await ws.send_json({"op":10,"d":{"heartbeat_interval":self.heartbeat_interval}})
        identify = await ws.receive_json(); await self.identify.put(identify)
        if identify["op"] == 6:
            await ws.send_json({"op":0,"s":4,"t":"RESUMED","d":""})
        else:
            await ws.send_json({"op":0,"s":1,"t":"READY","d":{"session_id":"fixture-session","user":{"id":"900"}}})
        async for frame in ws:
            if frame.type == web.WSMsgType.TEXT and json.loads(frame.data).get("op") == 1:
                await ws.send_json({"op":11})
        return ws

    async def message(self, request):
        self.assertEqual(request.headers["Authorization"], "QQBot fixture-access-token")
        body = await request.json()
        self.messages.append({"kind":request.match_info["kind"],"openid":request.match_info["openid"],"body":body})
        if body.get('msg_type') == 7 and self.media_error:
            if self.media_error == 'invalid': return web.Response(text='invalid response')
            return web.json_response({'code':40034090}, status=self.media_error)
        return web.json_response({"id":"fixture-outgoing"})

    async def upload(self, request):
        self.assertEqual(request.headers['Authorization'], 'QQBot fixture-access-token')
        data = await request.json(); self.uploads.append(data)
        self.assertEqual(data['file_type'], 1); self.assertIs(data['srv_send_msg'], False)
        self.assertNotIn('url', data)
        self.assertTrue(b64decode(data['file_data']).startswith(b'\x89PNG\r\n\x1a\n'))
        return web.json_response({'file_info':self.file_info, 'ttl':3600})

    async def test_group_image_upload_and_quoted_media_share_message_sequence(self):
        self.transport.dispatch(*self.event('在线', mid='image1'))
        png = render_pages('服务器在线', '在线')[0]
        await self.transport.send_group_image(official_id('qg', APP, GROUP), png)
        body = self.messages[-1]['body']
        self.assertEqual(body, {'content':'', 'msg_type':7, 'media':{'file_info':'fixture-file-info'}, 'msg_id':'image1', 'msg_seq':1})
        self.assertEqual(b64decode(self.uploads[0]['file_data']), png)
        await self.transport.send_group(official_id('qg', APP, GROUP), '继续文字')
        self.assertEqual(self.messages[-1]['body']['msg_seq'], 2)

    async def test_maximum_png_upload_survives_base64_expansion_and_larger_files_are_rejected(self):
        output = BytesIO()
        Image.new('RGB', (1, 1), 'black').save(output, 'PNG')
        png = output.getvalue()
        # Add a valid ancillary text chunk before IEND to reach the precise upload boundary.
        content = b'padding\x00' + b'x' * (MAX_PNG - len(png) - 20)
        chunk = b'tEXt' + content
        png = png[:-12] + struct.pack('>I', len(content)) + chunk + struct.pack('>I', zlib.crc32(chunk)) + png[-12:]
        self.assertEqual(len(png), MAX_PNG)
        with Image.open(BytesIO(png)) as image:
            image.verify()
        self.transport.dispatch(*self.event('在线', mid='maximum-image'))
        await self.transport.send_group_image(official_id('qg', APP, GROUP), png)
        self.assertEqual(b64decode(self.uploads[0]['file_data']), png)
        self.assertGreater(len(json.dumps(self.uploads[0]).encode()), 1024 * 1024)
        self.assertEqual(self.messages[-1]['body']['msg_type'], 7)
        with self.assertRaises(ValueError):
            await self.transport.send_group_image(official_id('qg', APP, GROUP), png + b'x')
        self.assertEqual(len(self.uploads), 1)
        self.assertEqual(len(self.messages), 1)

    async def test_image_upload_requires_matching_app_reply_context_and_valid_file_info(self):
        png = render_pages('服务器在线', '在线')[0]
        with self.assertRaises(RuntimeError): await self.transport.send_group_image(official_id('qg', APP, GROUP), png)
        with self.assertRaises(ConnectionError): await self.transport.send_group_image(official_id('qg', '102002', GROUP), png)
        self.assertEqual(self.uploads, [])
        self.transport.dispatch(*self.event('在线')); self.file_info = None
        with self.assertRaises(RuntimeError): await self.transport.send_group_image(official_id('qg', APP, GROUP), png)
        self.assertEqual(self.messages, [])

    async def test_config_change_after_image_upload_does_not_send_media(self):
        self.transport.dispatch(*self.event('在线'))
        request = self.transport._json
        async def changed(method, path, payload=None, authenticated=True):
            data = await request(method, path, payload, authenticated)
            if path.endswith('/files'): self.transport.generation += 1
            return data
        with patch.object(self.transport, '_json', new=changed):
            with self.assertRaises(ConnectionError):
                await self.transport.send_group_image(official_id('qg', APP, GROUP), render_pages('服务器在线', '在线')[0])
        self.assertEqual(len(self.uploads), 1); self.assertEqual(self.messages, [])

    async def test_uncertain_media_response_does_not_repeat_text(self):
        cfg = official_config(); cfg['reply_images'] = {'enabled':True, 'commands':['在线']}
        connection = QQConnection(cfg, self.store); connection.official = self.transport
        for error in [500, 408, 'invalid']:
            self.media_error = error; self.transport.dispatch(*self.event('在线', mid=str(error)))
            with self.subTest(error=error), self.assertRaises(ConnectionError):
                await connection.send_reply(official_id('qg', APP, GROUP), '服务器在线', '在线')
        self.assertEqual(len(self.messages), 3)
        self.assertTrue(all(message['body']['msg_type'] == 7 for message in self.messages))

    async def test_explicit_media_rejection_falls_back_to_text(self):
        cfg = official_config(); cfg['reply_images'] = {'enabled':True, 'commands':['在线']}
        connection = QQConnection(cfg, self.store); connection.official = self.transport
        self.media_error = 200; self.transport.dispatch(*self.event('在线'))
        await connection.send_reply(official_id('qg', APP, GROUP), '服务器在线', '在线')
        self.assertEqual([message['body']['msg_type'] for message in self.messages], [7, 0])
        self.assertEqual(self.messages[-1]['body']['content'], '服务器在线')

    def event(self, content="在线", private=False, mid="m1"):
        data = {"id":mid,"content":content,"author":{"user_openid" if private else "member_openid":PRIVATE if private else USER}}
        if not private: data["group_openid"] = GROUP
        return "C2C_MESSAGE_CREATE" if private else "GROUP_AT_MESSAGE_CREATE", data

    async def test_token_identify_and_heartbeats_use_current_contract(self):
        identify = await asyncio.wait_for(self.identify.get(), 1)
        self.assertEqual(identify["op"], 2); self.assertEqual(identify["d"]["intents"], 1 << 25)
        self.assertEqual(identify["d"]["token"], "QQBot fixture-access-token")
        self.assertEqual(self.tokens, [{"appId":APP,"clientSecret":"fixture-private-secret"}])
        self.assertEqual(await asyncio.gather(*(self.transport.token() for _ in range(8))), ["fixture-access-token"]*8)
        self.assertEqual(len(self.tokens),1)
        # Reconnect with an explicit short interval for this heartbeat test;
        # image-rendering tests should not depend on a 100 ms fake gateway clock.
        self.heartbeat_interval = 1000
        await self.sockets[-1].send_json({"op": 7})
        resume = await asyncio.wait_for(self.identify.get(), 3)
        self.assertEqual(resume["op"], 6)
        self.transport.token_expires = 0
        async def refreshed():
            while len(self.tokens) < 2 or not self.transport.connected:
                await asyncio.sleep(.02)
        await asyncio.wait_for(refreshed(), 5)
        self.assertGreaterEqual(len(self.tokens),2); self.assertTrue(self.transport.connected)

    async def test_event_normalization_and_reply_message_reference(self):
        kind, data = self.event("<@!900> 在线")
        self.transport.dispatch(kind, data); event = await self.events.get(); self.events.task_done()
        self.assertEqual(event["user_id"], official_id("qug",APP,USER)); self.assertEqual(event["group_id"],official_id("qg",APP,GROUP))
        self.assertEqual(event["message"][0]["data"]["text"],"在线")
        await self.transport.send_group(event["group_id"],"first"); await self.transport.send_group(event["group_id"],"second")
        self.assertEqual(self.messages[0]["body"],{"content":"first","msg_type":0,"msg_id":"m1","msg_seq":1})
        self.assertEqual(self.messages[1]["body"]["msg_seq"],2)
        kind, data = self.event("接入信息", private=True, mid="private1"); self.transport.dispatch(kind,data)
        event = await self.events.get(); self.events.task_done(); await self.transport.send_private(event["user_id"],"private")
        self.assertEqual(self.messages[-1]["kind"],"users"); self.assertEqual(self.messages[-1]["openid"],PRIVATE)

    async def test_cross_app_scope_and_passive_send_restrictions(self):
        for target in ["101", official_id("qg","102002",GROUP), official_id("qug",APP,USER)]:
            with self.assertRaises(ConnectionError): await self.transport.send_group(target,"no")
        with self.assertRaises(RuntimeError): await self.transport.send_group(official_id("qg",APP,GROUP),"no")
        self.assertEqual(self.messages,[])
        self.transport.cfg["allow_active"] = True
        await self.transport.send_group(official_id("qg",APP,GROUP),"active")
        self.assertNotIn("msg_id",self.messages[-1]["body"])

    async def test_missing_openid_ignored_and_duplicate_does_not_reset_sequence(self):
        kind, data=self.event(); data["author"]={}; self.transport.dispatch(kind,data); self.assertTrue(self.events.empty())
        kind,data=self.event(); self.transport.dispatch(kind,data); await self.transport.send_group(official_id("qg",APP,GROUP),"first")
        self.transport.dispatch(kind,data); await self.transport.send_group(official_id("qg",APP,GROUP),"second")
        self.assertEqual(self.messages[-1]["body"]["msg_seq"],2)

    async def test_config_generation_cancels_waiting_send(self):
        self.transport.dispatch(*self.event()); await self.transport.send_lock.acquire()
        pending=asyncio.create_task(self.transport.send_group(official_id("qg",APP,GROUP),"obsolete")); await asyncio.sleep(0)
        self.transport.generation+=1; self.transport.cfg["app_id"]="102002"; self.transport.send_lock.release()
        with self.assertRaises(ConnectionError): await pending
        self.assertEqual(self.messages,[])

    async def test_vendor_auth_error_is_checked_even_on_http_200_and_secret_hidden(self):
        self.vendor_error={"code":100016,"message":"fixture-private-secret fixture-access-token"}; self.transport.token_expires=0
        with self.assertRaises(RuntimeError) as caught: await self.transport.token()
        self.assertIn("100016",str(caught.exception)); self.assertNotIn("fixture-private-secret",str(caught.exception)); self.assertNotIn("fixture-access-token",str(caught.exception))

    async def test_gateway_resume_retains_last_processed_sequence(self):
        await self.identify.get(); await self.sockets[-1].send_json({"op":0,"s":3,"t":"GROUP_AT_MESSAGE_CREATE","d":self.event()[1]})
        event=await asyncio.wait_for(self.events.get(),1); self.events.task_done(); self.assertEqual(event["message_id"],"m1")
        await self.sockets[-1].send_json({"op":7})
        resume=await asyncio.wait_for(self.identify.get(),3)
        self.assertEqual(resume["op"],6); self.assertEqual(resume["d"]["seq"],3)

    async def test_close_during_heartbeat_cleanup_preserves_parent_cancellation_and_never_reconnects(self):
        await self.transport.close()
        self.transport = QQOfficial(official_config()["qq_official"], self.store, self.events)
        heartbeat_started, cleanup_entered, cleanup_release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def controlled_heartbeat(ws, interval):
            heartbeat_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleanup_entered.set()
                await cleanup_release.wait()

        with patch.object(self.transport, "heartbeat", new=controlled_heartbeat):
            await self.transport.start()
            await asyncio.wait_for(self.wait_connected(), 3)
            await asyncio.wait_for(heartbeat_started.wait(), 1)
            await self.sockets[-1].send_json({"op": 7})
            await asyncio.wait_for(cleanup_entered.wait(), 1)
            # The connection is now awaiting a cancelled child heartbeat. Its own
            # cancellation through close must not be mistaken for that child.
            connections = len(self.sockets)
            close_task = asyncio.create_task(self.transport.close())
            try:
                done, _ = await asyncio.wait({close_task}, timeout=2)
                self.assertIn(close_task, done, "QQ close swallowed parent cancellation and kept reconnecting")
                await close_task
                self.assertIsNone(self.transport.task)
                self.assertFalse(self.transport.connected)
                await asyncio.sleep(1.1)
                self.assertEqual(len(self.sockets), connections)
            finally:
                cleanup_release.set()
                if not close_task.done():
                    # Ensure a failed regression assertion cannot leave a reconnect
                    # loop alive and hang unittest's event-loop shutdown.
                    with patch.object(self.transport, "connect", new=AsyncMock(side_effect=asyncio.CancelledError)):
                        close_task.cancel()
                        await asyncio.wait_for(close_task, 3)

    async def test_binding_and_admin_commands_use_namespaced_identity(self):
        cfg=official_config(); cfg["app"]["database"]=":memory:"; cfg["onebot"]["admins"]=list(cfg["qq_official"]["admins"])
        connection=QQConnection(cfg,self.store); connection.official=self.transport
        bot=Bot(cfg,self.store,connection)
        sid=cfg["servers"][0]["id"]; uid="01234567-89ab-cdef-0123-456789abcdef"
        code=self.store.issue_code(sid,uid,"Steve")
        bot.snapshots[sid]={"last_seen":time.time(),"players":["Steve"],"max_players":20,"version":"test"}
        self.transport.dispatch(*self.event("绑定 "+code)); event=await self.events.get(); self.events.task_done(); await bot.handle_event(event)
        user=official_id("qug",APP,USER); self.assertEqual(self.store.binding(sid,user)["name"],"Steve"); self.assertIsNone(self.store.binding(sid,"201"))
        self.transport.dispatch(*self.event("执行 在线检查",mid="command1")); event=await self.events.get(); self.events.task_done(); await bot.handle_event(event)
        job=self.store.poll(sid)[0]; self.assertEqual(job["command"],"list")
        self.assertEqual(job["reply_group"],official_id("qg",APP,GROUP))

    async def test_unassociated_group_can_discover_identity_without_privilege(self):
        cfg=official_config(); cfg["servers"]=[]; connection=QQConnection(cfg,self.store); connection.official=self.transport
        bot=Bot(cfg,self.store,connection); self.transport.dispatch(*self.event("接入信息"))
        event=await self.events.get(); self.events.task_done(); await bot.handle_event(event)
        self.assertIn(official_id("qg",APP,GROUP),self.messages[-1]["body"]["content"])
        self.assertIn(official_id("qug",APP,USER),self.messages[-1]["body"]["content"])

    async def test_official_help_describes_only_at_messages(self):
        cfg = official_config()
        connection = QQConnection(cfg, self.store); connection.official = self.transport
        bot = Bot(cfg, self.store, connection)
        self.transport.dispatch(*self.event("帮助"))
        event = await self.events.get(); self.events.task_done(); await bot.handle_event(event)
        reply = self.messages[-1]["body"]["content"]
        self.assertIn("@机器人群消息会同步到游戏", reply)
        self.assertNotIn("普通群消息会同步到游戏", reply)
        self.assertIn("注册请使用社区注册网页", reply)


class OfficialConfigApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.path=Path(self.tmp.name)/"config.toml"
        cfg=official_config(); cfg["qq_official"]["enabled"]=False
        self.path.write_text(serialize(cfg),encoding="utf-8")
        self.client=TestClient(TestServer(create_app(runtime_config(cfg,self.path),self.path)))
        await self.client.start_server(); self.state=self.client.app[STATE]
        self.headers={"Authorization":"Bearer "+cfg["app"]["admin_token"]}

    async def asyncTearDown(self):
        await self.client.close(); self.tmp.cleanup()

    async def current(self):
        response=await self.client.get("/api/config",headers=self.headers)
        self.assertEqual(response.status,200); return await response.json()

    async def test_export_redacts_secret_and_import_preserves_local_official_credentials(self):
        response=await self.client.get("/api/deployment/export",headers=self.headers)
        exported=await response.json(); self.assertNotIn("fixture-private-secret",json.dumps(exported))
        exported["config"]["qq_official"].update(app_id="102002",client_secret="foreign-private-secret",admins=[])
        response=await self.client.post("/api/deployment/preview",headers=self.headers,json={"content":json.dumps(exported)})
        self.assertEqual(response.status,200); result=await response.json()
        preview=self.state["deployment"].previews[result["preview_id"]]["config"]
        self.assertEqual(preview["qq_official"],(await self.current())["config"]["qq_official"])
        self.assertNotIn("fixture-private-secret",json.dumps(result))

    async def test_bad_config_is_atomic_and_switch_revokes_old_remote_jobs(self):
        data=await self.current(); before=self.path.read_bytes()
        bad=deepcopy(data); bad["config"]["qq_official"].update(enabled=True,client_secret="")
        response=await self.client.put("/api/config",headers=self.headers,json=bad)
        self.assertEqual(response.status,400); self.assertEqual(self.path.read_bytes(),before)
        self.state["store"].enqueue("survival",{"kind":"command","command":"list","reply_group":"101"})
        data["config"]["qq_official"]["enabled"]=True
        with patch.object(QQOfficial,"start",new=AsyncMock()):
            response=await self.client.put("/api/config",headers=self.headers,json=data)
        self.assertEqual(response.status,200); self.assertTrue((await response.json())["onebot_reconnect"])
        self.assertEqual(self.state["store"].poll("survival"),[])
        self.assertEqual(self.state["onebot"].provider,"official")
        self.assertFalse(self.state["onebot"].valid_user("201"))
        self.assertTrue(self.state["onebot"].valid_user(official_id("qug",APP,USER)))
        self.assertEqual(self.state["bot"].cfg["onebot"]["admins"],[official_id("qug",APP,USER)])

    async def test_non_owner_cannot_read_official_secret_or_change_transport(self):
        accounts=self.state["admin_accounts"]
        await accounts.save({"username":"Observer","password":"fixture-observer-password","permissions":["status.read"]})
        response=await self.client.post("/api/admin-auth/login",json={"username":"Observer","password":"fixture-observer-password"})
        self.assertEqual(response.status,200); token=(await response.json())["access_token"]
        headers={"Authorization":"Bearer "+token}
        for path in ["/api/config","/api/deployment/export"]:
            response=await self.client.get(path,headers=headers); self.assertEqual(response.status,403)
            self.assertNotIn("fixture-private-secret",await response.text())
        response=await self.client.get("/api/status",headers=headers); self.assertEqual(response.status,200)
        self.assertNotIn("fixture-private-secret",await response.text())

    async def test_monitoring_preserves_official_group_id_and_rejects_user_id(self):
        current = self.state["runtime"].config("monitoring")
        settings = {**current["settings"], "notify_groups": True, "groups": [official_id("qg", APP, GROUP)]}
        result = self.state["runtime"].save("monitoring", settings, current["revision"])
        self.assertEqual(result["settings"]["groups"], settings["groups"])
        with self.assertRaises(ValueError):
            # RegistrationError follows the existing runtime-settings API contract.
            self.state["runtime"].save("monitoring", {**settings, "groups": [official_id("qug", APP, USER)]}, result["revision"])


if __name__ == "__main__":
    unittest.main()
