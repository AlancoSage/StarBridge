import asyncio
from copy import deepcopy
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

import aiohttp
from aiohttp.test_utils import TestClient, TestServer

from starbridge.__main__ import serve
from starbridge.app import STATE, create_app
from starbridge.config import load
from starbridge.settings import ConfigFile, serialize, validate
from test_starbridge import config


def full_config():
    cfg = config("data/test.db")
    cfg["app"].update(host="127.0.0.1", port=8088)
    return validate(cfg)


class ConfigValidationTests(unittest.TestCase):
    def test_all_settings_toml_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "config.toml"
            cfg = full_config()
            cfg["replies"] = {'中文"关键词': '第一行\n第二行 "引用" \\ [CQ:text]'}
            cfg["app"]["database"] = "数据/my database.db"
            file.write_text(serialize(cfg), encoding="utf-8")
            self.assertEqual(ConfigFile(file).read()[0], cfg)
            self.assertEqual(load(file)["app"]["database"], str((file.parent / cfg["app"]["database"]).resolve()))

    def test_invalid_structures_do_not_raise_internal_errors(self):
        for section in ("app", "onebot", "features", "servers", "replies"):
            cfg = full_config(); cfg[section] = None
            with self.subTest(section=section), self.assertRaises(ValueError):
                validate(cfg)
        for value in (None, [], "config"):
            with self.assertRaises(ValueError):
                validate(value)

    def test_invalid_values(self):
        cases = [("app", "port", True), ("app", "port", 70000), ("app", "host", "http://host"),
                 ("app", "database", ":memory:"), ("onebot", "admins", [123]),
                 ("onebot", "admins", ["123", "123"]), ("onebot", "self_id", "１２３"),
                 ("features", "qq_to_mc", "false"), ("onebot", "token", "short")]
        for section, key, value in cases:
            cfg = full_config(); cfg[section][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate(cfg)


class ConfigApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "config.toml"
        self.path.write_text(serialize(full_config()), encoding="utf-8")
        self.restart = asyncio.Event()
        self.client = TestClient(TestServer(create_app(load(self.path), self.path, self.restart)))
        await self.client.start_server()
        self.state = self.client.app[STATE]
        self.headers = {"Authorization": "Bearer " + full_config()["app"]["admin_token"]}

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    async def read(self):
        response = await self.client.get("/api/config", headers=self.headers)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        return await response.json()

    async def save(self, payload, expected=200):
        response = await self.client.put("/api/config", headers=self.headers,
                                         json={"config": payload["config"], "revision": payload["revision"]})
        self.assertEqual(response.status, expected, await response.text())
        return await response.json()

    async def test_admin_auth_on_read_write_and_restart(self):
        for method, url in [("get", "/api/config"), ("put", "/api/config"), ("post", "/api/restart")]:
            for headers in ({}, {"Authorization": "Bearer " + full_config()["servers"][0]["token"]}):
                response = await getattr(self.client, method)(url, headers=headers, json={})
                self.assertEqual(response.status, 401)
        self.assertFalse(self.restart.is_set())

    async def test_save_all_sections_persist_and_apply_without_restart(self):
        previous = self.path.read_bytes()
        data = await self.read()
        cfg = data["config"]
        cfg["onebot"]["admins"] = ["300"]
        cfg["features"]["qq_to_mc"] = False
        cfg["servers"][0]["name"] = "新生存服"
        cfg["servers"][0]["groups"] = ["555"]
        cfg["servers"][0]["commands"] = {"时间": "time query daytime"}
        result = await self.save(data)
        self.assertEqual(result["restart_required"], [])
        self.assertEqual(load(self.path)["replies"], cfg["replies"])
        self.assertEqual(self.path.with_suffix(".toml.bak").read_bytes(), previous)
        self.assertEqual(self.state["bot"].cfg["onebot"]["admins"], ["300"])
        self.assertIn("555", self.state["bot"].groups)
        self.assertNotIn("101", self.state["bot"].groups)
        headers = {"Authorization": "Bearer " + cfg["servers"][0]["token"]}
        response = await self.client.post("/bridge/survival/tick", headers=headers, json={})
        self.assertEqual((await response.json())["allowed_commands"], ["time query daytime"])

    async def test_live_reply_uses_saved_plugin_settings(self):
        data = await self.read()
        response = await self.client.get("/api/extensions", headers=self.headers)
        plugins = await response.json()
        response = await self.client.put("/api/extensions/keyword_replies", headers=self.headers,
                                        json={"revision": plugins["revision"], "settings": {"replies": {"测试": "新回复"}}})
        self.assertEqual(response.status, 200)
        ws = await self.client.ws_connect("/onebot/ws", headers={"Authorization": "Bearer " + data["config"]["onebot"]["token"], "X-Self-ID": "100"})
        await ws.send_json({"post_type": "message", "self_id": 100, "message_type": "group", "group_id": 101, "user_id": 200, "message_id": 1, "message": "测试"})
        reply = await ws.receive_json(timeout=2)
        self.assertEqual(reply["params"]["message"][0]["data"]["text"], "新回复")
        await ws.send_json({"status": "ok", "retcode": 0, "echo": reply["echo"], "data": {}})
        await ws.close()

    async def test_invalid_and_stale_save_preserve_file_and_runtime(self):
        data = await self.read(); previous = self.path.read_bytes()
        invalid = deepcopy(data); invalid["config"]["app"]["port"] = -1
        await self.save(invalid, 400)
        self.assertEqual(self.path.read_bytes(), previous)
        data["config"]["features"]["qq_to_mc"] = False
        await self.save(data)
        await self.save(data, 409)
        self.assertEqual(self.state["config"]["app"]["port"], 8088)

    async def test_write_failure_does_not_change_runtime(self):
        data = await self.read(); previous = self.path.read_bytes()
        data["config"]["features"]["qq_to_mc"] = False
        with patch("starbridge.settings.os.replace", side_effect=OSError("test failure")):
            await self.save(data, 500)
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertTrue(self.state["bot"].cfg["features"]["qq_to_mc"])

    async def test_config_reply_changes_rejected_without_overwriting_plugin(self):
        data = await self.read(); before = self.path.read_bytes()
        data["config"]["replies"] = {"旧入口": "不生效"}
        result = await self.save(data, 400)
        self.assertIn("关键词回复已移至插件", result["error"])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.state["plugins"].entries["keyword_replies"]["settings"]["replies"], {"官网": "https://example.com"})

    async def test_network_and_database_settings_are_staged(self):
        data = await self.read(); original_db = self.state["config"]["app"]["database"]
        data["config"]["app"].update(host="0.0.0.0", port=9999, database="data/other.db")
        result = await self.save(data)
        self.assertEqual(set(result["restart_required"]), {"host", "port", "database"})
        self.assertEqual(self.state["config"]["app"]["port"], 8088)
        self.assertEqual(self.state["config"]["app"]["database"], original_db)
        self.assertEqual(load(self.path)["app"]["port"], 9999)

    async def test_rotation_invalidates_old_admin_and_bridge_tokens(self):
        data = await self.read(); old = data["config"]["servers"][0]["token"]
        data["config"]["app"]["admin_token"] = "new-admin-" + "z" * 32
        data["config"]["servers"][0]["token"] = "new-game-" + "y" * 32
        await self.save(data)
        self.assertEqual((await self.client.get("/api/config", headers=self.headers)).status, 401)
        self.headers = {"Authorization": "Bearer " + data["config"]["app"]["admin_token"]}
        await self.read()
        response = await self.client.post("/bridge/survival/tick", headers={"Authorization": "Bearer " + old}, json={})
        self.assertEqual(response.status, 401)

    async def test_onebot_rotation_disconnects_active_socket(self):
        data = await self.read()
        ws = await self.client.ws_connect("/onebot/ws", headers={"Authorization": "Bearer " + data["config"]["onebot"]["token"], "X-Self-ID": "100"})
        data["config"]["onebot"]["token"] = "new-bot-" + "x" * 32
        task = asyncio.create_task(self.save(data))
        await ws.receive(timeout=2)
        result = await task
        self.assertTrue(result["onebot_reconnect"])
        self.assertFalse(self.state["onebot"].connected)
        await ws.close()

    async def test_remove_server_revokes_pending_jobs_and_keeps_bindings(self):
        store = self.state["store"]
        code = store.issue_code("survival", "uuid1", "Steve"); store.bind("survival", "200", code)
        store.enqueue("survival", {"kind": "command", "command": "list", "reply_group": "101"})
        data = await self.read()
        data["config"]["servers"][0]["id"] = "creative"
        await self.save(data)
        self.assertEqual(store.poll("survival"), [])
        self.assertEqual(store.binding("survival", "200")["name"], "Steve")
        self.assertEqual((await self.client.post("/bridge/survival/tick", json={})).status, 404)

    async def test_remove_last_server_persists_and_can_add_again(self):
        store = self.state['store']
        code = store.issue_code('survival', 'uuid1', 'Steve'); store.bind('survival', '200', code)
        store.enqueue('survival', {'kind': 'command', 'command': 'list', 'reply_group': '101'})
        data = await self.read()
        original = deepcopy(data['config']['servers'][0])
        data['config']['servers'] = []
        result = await self.save(data)
        self.assertEqual(result['restart_required'], [])
        self.assertEqual(load(self.path)['servers'], [])
        self.assertEqual(ConfigFile(self.path).read()[0]['servers'], [])
        self.assertEqual(self.state['bot'].servers, {})
        self.assertEqual(self.state['bot'].groups, {})
        self.assertEqual(store.poll('survival'), [])
        self.assertEqual(store.binding('survival', '200')['name'], 'Steve')
        response = await self.client.get('/api/status', headers=self.headers)
        self.assertEqual((await response.json())['servers'], [])
        self.assertEqual((await self.client.post('/bridge/survival/tick', json={})).status, 404)
        data = await self.read(); data['config']['servers'] = [original]
        await self.save(data)
        self.assertIn('survival', load(self.path)['servers'][0]['id'])
        self.assertIn('survival', self.state['bot'].servers)

    async def test_restart_event_after_response(self):
        response = await self.client.post("/api/restart", headers=self.headers)
        self.assertEqual(response.status, 200)
        await asyncio.wait_for(self.restart.wait(), 2)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class SupervisorTests(unittest.IsolatedAsyncioTestCase):
    async def wait_ready(self, session, origin, headers, predicate=lambda d: True):
        for _ in range(100):
            try:
                async with session.get(origin + "/api/config", headers=headers) as response:
                    data = await response.json()
                    if response.status == 200 and predicate(data):
                        return data
            except (aiohttp.ClientError, OSError):
                pass
            await asyncio.sleep(0.05)
        self.fail("服务未在预期时间就绪")

    async def test_restart_new_port_database_and_failed_restart_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            cfg = full_config(); cfg["app"]["port"] = free_port()
            path.write_text(serialize(cfg), encoding="utf-8")
            origin = f"http://127.0.0.1:{cfg['app']['port']}"
            headers = {"Authorization": "Bearer " + cfg["app"]["admin_token"]}
            task = asyncio.create_task(serve(path))
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=1)) as session:
                    data = await self.wait_ready(session, origin, headers)
                    port = free_port(); data["config"]["app"].update(port=port, database="data/new.db")
                    async with session.put(origin + "/api/config", headers=headers, json=data) as response:
                        self.assertEqual(response.status, 200)
                    async with session.post(origin + "/api/restart", headers=headers) as response:
                        self.assertEqual(response.status, 200)
                    new_origin = f"http://127.0.0.1:{port}"
                    data = await self.wait_ready(session, new_origin, headers)
                    self.assertEqual(data["restart_required"], [])
                    self.assertTrue((path.parent / "data/new.db").exists())
                    # A directory cannot be opened as a SQLite file. Keep the old service accessible.
                    data["config"]["app"]["database"] = "data"
                    async with session.put(new_origin + "/api/config", headers=headers, json=data) as response:
                        self.assertEqual(response.status, 200)
                    async with session.post(new_origin + "/api/restart", headers=headers) as response:
                        self.assertEqual(response.status, 200)
                    recovered = await self.wait_ready(session, new_origin, headers, lambda d: bool(d["restart_error"]))
                    self.assertEqual(recovered["restart_required"], ["database"])
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
