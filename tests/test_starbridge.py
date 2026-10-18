import asyncio
from copy import deepcopy
from pathlib import Path
import tempfile
import time
import unittest
import uuid

from aiohttp import WSMsgType, WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer

from starbridge.app import STATE, create_app
from starbridge.bot import plain_message
from starbridge.config import initialize, load
from starbridge.storage import Store


def config(database=":memory:"):
    return {
        "app": {"database": database, "admin_token": "admin-" + "a" * 32},
        "onebot": {"token": "bot-" + "b" * 32, "self_id": "100", "admins": ["201"]},
        "features": {"qq_to_mc": True, "mc_to_qq": True, "join_quit": True, "unbind_on_leave": True},
        "servers": [{"id": "survival", "name": "生存服", "token": "game-" + "c" * 32,
                     "groups": ["101"], "commands": {"在线检查": "list"}}],
        "replies": {"官网": "https://example.com"},
    }


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")

    def tearDown(self):
        self.store.close()

    def test_binding_code_scope_unique_and_single_use(self):
        code = self.store.issue_code("one", "uuid1", "Steve")
        with self.assertRaises(ValueError):
            self.store.bind("two", "111", code)
        self.store.bind("one", "111", code)
        with self.assertRaises(ValueError):
            self.store.bind("one", "222", code)
        next_code = self.store.issue_code("one", "uuid1", "Steve")
        with self.assertRaises(ValueError):
            self.store.bind("one", "222", next_code)
        self.assertTrue(self.store.unbind("one", "111"))
        self.store.bind("one", "222", next_code)
        self.assertEqual(self.store.binding("one", "222")["name"], "Steve")

    def test_expiry_and_code_rotation(self):
        old = self.store.issue_code("one", "uuid1", "Steve")
        code = self.store.issue_code("one", "uuid1", "Steve")
        with self.assertRaises(ValueError):
            self.store.bind("one", "111", old)
        with self.store.db:
            self.store.db.execute("UPDATE codes SET expires=0")
        with self.assertRaises(ValueError):
            self.store.bind("one", "111", code)

    def test_job_lease_retry_ack_and_scope(self):
        jid = self.store.enqueue("one", {"kind": "broadcast", "text": "hello"})
        self.assertEqual(self.store.poll("two"), [])
        self.assertEqual(self.store.poll("one")[0]["id"], jid)
        self.assertEqual(self.store.poll("one"), [])
        self.store.ack("two", [jid])
        with self.store.db:
            self.store.db.execute("UPDATE jobs SET lease=0")
        self.assertEqual(self.store.poll("one")[0]["id"], jid)
        self.store.ack("one", [jid])
        self.assertIsNone(self.store.job("one", jid))

    def test_expired_jobs_and_dedupe(self):
        self.store.enqueue("one", {"kind": "broadcast", "text": "hello"})
        with self.store.db:
            self.store.db.execute("UPDATE jobs SET expires=0")
        self.assertEqual(self.store.poll("one"), [])
        self.assertFalse(self.store.seen("event1"))
        self.assertTrue(self.store.seen("event1"))

    def test_restart_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "db.sqlite")
            db = Store(path)
            code = db.issue_code("one", "uuid1", "Steve")
            db.bind("one", "111", code)
            db.close()
            db = Store(path)
            self.assertEqual(db.binding("one", "111")["name"], "Steve")
            db.close()

    def test_configuration_generates_independent_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            initialize(path)
            cfg = load(path)
            self.assertNotEqual(cfg["onebot"]["token"], cfg["servers"][0]["token"])
            with self.assertRaises(ValueError):
                initialize(path)

    def test_message_formats_and_literal_cq(self):
        self.assertEqual(plain_message("hello[CQ:at,qq=1]&#91;CQ:at,qq=2&#93;"), "hello[CQ:at,qq=2]")
        self.assertEqual(plain_message([{"type": "text", "data": {"text": "hello"}}, {"type": "image", "data": {}}, None]), "hello[图片]")
        self.assertEqual(plain_message([{"type": "text", "data": None}]), "")


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.cfg = config()
        self.client = TestClient(TestServer(create_app(self.cfg)))
        await self.client.start_server()
        self.state = self.client.app[STATE]
        self.bridge_headers = {"Authorization": "Bearer " + self.cfg["servers"][0]["token"]}
        self.admin_headers = {"Authorization": "Bearer " + self.cfg["app"]["admin_token"]}
        self.ws_headers = {"Authorization": "Bearer " + self.cfg["onebot"]["token"], "X-Self-ID": "100"}
        self.ws = await self.client.ws_connect("/onebot/ws", headers=self.ws_headers)
        self.actions = asyncio.Queue()
        self.reader = asyncio.create_task(self.read_actions())
        self.message_id = 0

    async def asyncTearDown(self):
        await self.ws.close()
        await self.reader
        await self.client.close()

    async def read_actions(self):
        async for msg in self.ws:
            if msg.type == WSMsgType.TEXT:
                data = msg.json()
                await self.actions.put(data)
                await self.ws.send_json({"status": "ok", "retcode": 0, "data": {"message_id": 1000}, "echo": data["echo"]})

    async def event(self, text, qq=200, group=101, **extra):
        self.message_id += 1
        event = {"post_type": "message", "self_id": 100, "message_type": "group", "group_id": group,
                 "message_id": self.message_id, "user_id": qq, "message": [{"type": "text", "data": {"text": text}}],
                 "sender": {"nickname": "QQ用户"}, **extra}
        await self.ws.send_json(event)
        return event

    async def reply(self):
        action = await asyncio.wait_for(self.actions.get(), 2)
        self.assertEqual(action["action"], "send_group_msg")
        return action["params"]["message"][0]["data"]["text"]

    async def tick(self, **extra):
        data = {"players": ["Steve"], "max_players": 20, "version": "1.20.4", "events": [], "results": [], **extra}
        r = await self.client.post("/bridge/survival/tick", headers=self.bridge_headers, json=data)
        self.assertEqual(r.status, 200, await r.text())
        return await r.json()

    async def settle(self):
        await asyncio.sleep(0.05)
        await asyncio.wait_for(self.state["onebot"].events.join(), 2)

    async def test_health_panel_and_auth_isolation(self):
        self.assertEqual((await self.client.get("/health")).status, 200)
        self.assertIn("VexBot", await (await self.client.get("/")).text())
        icon = await self.client.get("/mark.png")
        self.assertEqual(icon.status, 200)
        self.assertEqual(icon.content_type, "image/png")
        self.assertTrue((await icon.read()).startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual((await self.client.get("/api/status")).status, 401)
        self.assertEqual((await self.client.get("/api/status", headers=self.bridge_headers)).status, 401)
        r = await self.client.get("/api/status", headers=self.admin_headers)
        status = await r.json()
        self.assertTrue(status["onebot"])
        self.assertNotIn(self.cfg["onebot"]["token"], str(status))
        self.assertEqual((await self.client.post("/bridge/survival/tick", json={}, headers=self.admin_headers)).status, 401)

    async def test_ws_rejects_bad_token_identity_and_second_connection(self):
        for headers, expected in [({}, 401), ({**self.ws_headers, "X-Self-ID": "999"}, 403), (self.ws_headers, 409)]:
            with self.assertRaises(WSServerHandshakeError) as caught:
                await self.client.ws_connect("/onebot/ws", headers=headers)
            self.assertEqual(caught.exception.status, expected)

    async def test_qq_commands_binding_and_unbinding(self):
        await self.event("帮助")
        self.assertIn("/qbind", await self.reply())
        r = await self.client.post("/bridge/survival/bind-code", headers=self.bridge_headers,
                                   json={"uuid": str(uuid.uuid4()), "player": "Steve"})
        code = (await r.json())["code"]
        await self.event("绑定 " + code)
        self.assertIn("绑定成功", await self.reply())
        await self.event("绑定 " + code, qq=202)
        self.assertIn("无效", await self.reply())
        await self.event("我的绑定")
        self.assertIn("Steve", await self.reply())
        await self.event("解绑")
        self.assertIn("已解除", await self.reply())

    async def test_bidirectional_relay_deduplication_and_ack(self):
        await self.tick()
        original = await self.event("你好 Minecraft")
        await self.ws.send_json(original)
        await self.settle()
        jobs = (await self.tick())["jobs"]
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["text"], "[QQ] QQ用户: 你好 Minecraft")
        await self.tick(results=[{"id": jobs[0]["id"], "ok": True, "detail": "done"}])
        self.assertIsNone(self.state["store"].job("survival", jobs[0]["id"]))
        game_event = {"id": "chat1", "kind": "chat", "player": "Steve", "text": "你好 QQ"}
        await self.tick(events=[game_event])
        self.assertIn("Steve: 你好 QQ", await self.reply())
        await self.tick(events=[game_event])
        await self.settle()
        self.assertTrue(self.actions.empty())

    async def test_admin_command_allowlist_and_result(self):
        await self.tick()
        await self.event("执行 在线检查")
        self.assertIn("权限不足", await self.reply())
        await self.event("执行 op Steve", qq=201)
        self.assertIn("可用命令", await self.reply())
        self.assertEqual((await self.tick())["jobs"], [])
        await self.event("执行 在线检查", qq=201)
        self.assertIn("已提交", await self.reply())
        jobs = (await self.tick())["jobs"]
        self.assertEqual(jobs[0]["command"], "list")
        await self.tick(results=[{"id": jobs[0]["id"], "ok": True, "detail": "1/20: Steve"}])
        self.assertIn("1/20: Steve", await self.reply())

    async def test_offline_status_no_queueing_and_online_players(self):
        await self.event("执行 在线检查", qq=201)
        self.assertIn("未提交", await self.reply())
        await self.event("状态")
        self.assertIn("离线", await self.reply())
        await self.tick()
        await self.event("在线")
        self.assertIn("Steve", await self.reply())
        self.state["bot"].snapshots["survival"]["last_seen"] = 0
        await self.event("hello")
        await self.settle()
        self.assertEqual(self.state["store"].poll("survival"), [])

    async def test_untrusted_events_do_not_relay(self):
        await self.tick()
        await self.event("hello", group=999)
        await self.event("hello", qq=100)
        await self.event("hello", anonymous={"name": "匿名"})
        await self.event("hello", self_id=999)
        await self.settle()
        self.assertEqual((await self.tick())["jobs"], [])

    async def test_group_leave_unbind_and_custom_reply(self):
        store = self.state["store"]
        code = store.issue_code("survival", "uuid1", "Steve")
        store.bind("survival", "200", code)
        await self.ws.send_json({"post_type": "notice", "notice_type": "group_decrease", "self_id": 100, "group_id": 101, "user_id": 200})
        await self.settle()
        self.assertIsNone(store.binding("survival", "200"))
        await self.event("官网")
        self.assertEqual(await self.reply(), "https://example.com")

    async def test_bad_bridge_input_and_code_rate_limit(self):
        r = await self.client.post("/bridge/survival/tick", headers=self.bridge_headers, json={"events": [None]})
        self.assertEqual(r.status, 400)
        r = await self.client.post("/bridge/survival/bind-code", headers=self.bridge_headers, json={"uuid": "bad", "player": "Steve"})
        self.assertEqual(r.status, 400)
        payload = {"uuid": str(uuid.uuid4()), "player": "Steve"}
        for _ in range(3):
            self.assertEqual((await self.client.post("/bridge/survival/bind-code", headers=self.bridge_headers, json=payload)).status, 200)
        self.assertEqual((await self.client.post("/bridge/survival/bind-code", headers=self.bridge_headers, json=payload)).status, 429)

    async def test_result_cannot_override_group_or_event_kind(self):
        await self.tick()
        jid = self.state["store"].enqueue("survival", {"kind": "command", "command": "list", "reply_group": "101"})
        await self.tick(results=[{"id": jid, "ok": True, "detail": "done", "group": "999", "kind": "chat"}])
        action = await asyncio.wait_for(self.actions.get(), 2)
        self.assertEqual(action["params"]["group_id"], 101)
        self.assertIn("已执行", action["params"]["message"][0]["data"]["text"])


if __name__ == "__main__":
    unittest.main()
