from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch
import uuid

from aiohttp.test_utils import TestClient, TestServer

from starbridge.app import STATE, create_app
from starbridge.extensions import PluginManager, validate_plugin
from test_starbridge import config


def example():
    return {"api_version": 1, "id": "test_helper", "name": "测试助手", "version": "1.0.0",
            "settings": {"greeting": {"type": "string", "label": "内容", "default": "你好"},
                         "welcome": {"type": "boolean", "label": "入服通知", "default": False}},
            "rules": [{"event": "group_command", "command": "问候", "match": "prefix",
                       "reply": "{settings.greeting} {arg} {server_name} {player}", "cooldown": 3},
                      {"event": "player_join", "reply": "欢迎 {player} 来到 {server_name}", "when": "welcome"}]}


class PluginValidationTests(unittest.TestCase):
    def test_invalid_definitions(self):
        cases = [("id", "../unsafe"), ("api_version", True), ("api_version", 2), ("rules", []), ("settings", []), ("code", "print('no')")]
        for key, value in cases:
            with self.subTest(key=key):
                plugin = example(); plugin[key] = value
                with self.assertRaises(ValueError):
                    validate_plugin(plugin)
        for change in ({"command": "绑定"}, {"command": "带 空格"}, {"reply": "{settings.missing}"},
                       {"reply": "{unknown}"}, {"cooldown": 0}, {"cooldown": True}, {"when": []}, {"admin_only": "yes"}):
            plugin = example(); plugin["rules"][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_plugin(plugin)

    def test_all_settings_types_and_bounds(self):
        plugin = example()
        plugin["settings"].update({"count": {"type": "integer", "label": "数量", "default": 2, "min": 1, "max": 5},
                                   "hours": {"type": "number", "label": "时长", "default": 1.5},
                                   "mode": {"type": "select", "label": "模式", "default": "生存", "options": ["生存", "创造"]}})
        validate_plugin(plugin)
        for key, value in (("count", True), ("count", 6), ("hours", float('nan')), ("mode", "未知")):
            broken = deepcopy(plugin); broken["settings"][key]["default"] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_plugin(broken)

    def test_example_valid_independently_of_installed_plugins(self):
        base = Path(__file__).resolve().parent.parent
        sample = json.loads((base / "examples/community_helper.json").read_text(encoding="utf-8"))
        self.assertEqual(validate_plugin(sample)["id"], "community_helper")


class PluginApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.cfg = config(str(self.base / "db.sqlite"))
        self.client = TestClient(TestServer(create_app(self.cfg)))
        await self.client.start_server()
        self.state = self.client.app[STATE]
        self.manager = self.state["plugins"]
        self.headers = {"Authorization": "Bearer " + self.cfg["app"]["admin_token"]}
        self.state["onebot"].send_group = AsyncMock()
        self.bot = self.state["bot"]
        self.bot.snapshots["survival"] = {"last_seen": time.time(), "players": ["Steve"], "max_players": 20, "version": "test"}

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    async def get(self):
        response = await self.client.get("/api/extensions", headers=self.headers)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        return await response.json()

    async def install(self, plugin=None):
        data = await self.get()
        response = await self.client.post("/api/extensions/install", headers=self.headers,
                                          json={"revision": data["revision"], "plugin": plugin or example()})
        self.assertEqual(response.status, 200, await response.text())
        return await response.json()

    async def enable(self, settings=None):
        data = await self.get()
        payload = {"revision": data["revision"], "enabled": True}
        if settings is not None:
            payload["settings"] = settings
        response = await self.client.put("/api/extensions/test_helper", headers=self.headers, json=payload)
        self.assertEqual(response.status, 200, await response.text())
        return await response.json()

    async def message(self, text, user="201", group="101", mid=None):
        await self.bot.handle_event({"post_type": "message", "message_type": "group", "self_id": 100,
                                     "user_id": user, "group_id": group, "message_id": mid or uuid.uuid4().hex,
                                     "message": [{"type": "text", "data": {"text": text}}]})

    async def test_auth_on_all_endpoints(self):
        for method, route in (("get", "/api/extensions"), ("post", "/api/extensions/install"), ("post", "/api/extensions/scan"),
                              ("put", "/api/extensions/test_helper"), ("delete", "/api/extensions/test_helper"),
                              ("post", "/api/extensions/test_helper/reload"), ("get", "/api/extension-documents/guide")):
            response = await getattr(self.client, method)(route)
            self.assertEqual(response.status, 401)

    async def test_import_is_disabled_and_reinstall_stays_disabled(self):
        data = await self.install()
        self.assertFalse(next(p for p in data["plugins"] if p["id"] == "test_helper")["enabled"])
        await self.message("问候")
        self.state["onebot"].send_group.assert_not_awaited()
        await self.enable()
        data = await self.get()
        response = await self.client.delete("/api/extensions/test_helper", headers=self.headers, json={"revision": data["revision"]})
        self.assertEqual(response.status, 400)
        response = await self.client.put("/api/extensions/test_helper", headers=self.headers,
                                         json={"revision": data["revision"], "enabled": False})
        data = await response.json()
        response = await self.client.delete("/api/extensions/test_helper", headers=self.headers, json={"revision": data["revision"]})
        self.assertEqual(response.status, 200)
        self.assertEqual(len(list((self.base / "data/plugin-archive").glob("*.json"))), 1)
        self.assertFalse((self.base / "plugins/test_helper.json").exists())
        data = await self.install()
        self.assertFalse(next(p for p in data["plugins"] if p["id"] == "test_helper")["enabled"])

    async def test_prefix_template_consumes_message_and_deduplicates(self):
        await self.install(); await self.enable({"greeting": "欢迎 {arg}", "welcome": False})
        await self.message("问候 [CQ:at,qq=123]", mid="same")
        self.state["onebot"].send_group.assert_awaited_once_with("101", "欢迎 {arg} [CQ:at,qq=123] 生存服 未绑定")
        self.assertEqual(self.state["store"].poll("survival"), [])
        await self.message("问候 [CQ:at,qq=123]", mid="same")
        await self.message("问候 again")
        self.assertEqual(self.state["onebot"].send_group.await_count, 1)

    async def test_builtin_and_custom_reply_precedence(self):
        plugin = example(); plugin["rules"][0]["command"] = "官网"
        await self.install(plugin); await self.enable()
        await self.message("官网")
        self.state["onebot"].send_group.assert_awaited_with("101", "https://example.com")
        await self.message("帮助")
        self.assertIn("绑定", self.state["onebot"].send_group.call_args.args[1])

    async def test_permissions_and_foreign_group(self):
        plugin = example(); plugin["rules"][0].update(admin_only=True, bound_only=True)
        await self.install(plugin); await self.enable()
        await self.message("问候", user="202")
        self.assertIn("管理员", self.state["onebot"].send_group.call_args.args[1])
        await self.message("问候", user="201")
        self.assertIn("绑定", self.state["onebot"].send_group.call_args.args[1])
        self.state["onebot"].send_group.reset_mock()
        await self.message("问候", group="999")
        self.state["onebot"].send_group.assert_not_awaited()

    async def test_exact_matching_and_when_false_allows_normal_relay(self):
        plugin = example(); plugin["rules"][0].update(match="exact", when="welcome")
        await self.install(plugin); await self.enable()
        await self.message("问候")
        self.state["onebot"].send_group.assert_not_awaited()
        self.assertEqual(self.state["store"].poll("survival")[0]["kind"], "broadcast")
        await self.message("问候 参数")
        self.state["onebot"].send_group.assert_not_awaited()

    async def test_revision_conflict_and_validation_do_not_change_settings(self):
        data = await self.install()
        await self.enable()
        response = await self.client.put("/api/extensions/test_helper", headers=self.headers,
                                         json={"revision": data["revision"], "enabled": False})
        self.assertEqual(response.status, 409)
        current = await self.get()
        response = await self.client.put("/api/extensions/test_helper", headers=self.headers,
                                         json={"revision": current["revision"], "settings": {"welcome": "true"}})
        self.assertEqual(response.status, 400)
        self.assertEqual(await self.get(), current)

    async def test_settings_and_enabled_survive_restart(self):
        await self.install(); await self.enable({"greeting": "持久化", "welcome": True})
        manager = PluginManager(self.base, self.bot, self.state["store"])
        await manager.start()
        plugin = next(p for p in manager.listing()["plugins"] if p["id"] == "test_helper")
        self.assertEqual(plugin["status"], "running")
        self.assertEqual(plugin["settings"], {"greeting": "持久化", "welcome": True})

    async def test_reload_uses_updated_definition_and_scan_isolates_bad_json(self):
        await self.install(); await self.enable()
        updated = example(); updated["rules"][0]["reply"] = "修改后的规则"
        (self.base / "plugins/test_helper.json").write_text(json.dumps(updated), encoding="utf-8")
        data = await self.get()
        response = await self.client.post("/api/extensions/test_helper/reload", headers=self.headers, json={"revision": data["revision"]})
        self.assertEqual(response.status, 200)
        await self.message("问候")
        self.state["onebot"].send_group.assert_awaited_once_with("101", "修改后的规则")
        (self.base / "plugins/broken.json").write_text("not json", encoding="utf-8")
        data = await self.get()
        response = await self.client.post("/api/extensions/scan", headers=self.headers, json={"revision": data["revision"]})
        plugins = (await response.json())["plugins"]
        self.assertEqual([p["status"] for p in plugins if not p["builtin"]], ["error", "running"])

    async def test_game_event_when_enabled_and_original_relay_continues(self):
        await self.install(); await self.enable()
        self.bot.cfg["features"]["join_quit"] = False
        event = {"kind": "join", "player": "Steve", "uuid": str(uuid.uuid4())}
        await self.bot.relay_game(self.bot.servers["survival"], event)
        self.state["onebot"].send_group.assert_not_awaited()
        await self.enable({"greeting": "hi", "welcome": True})
        await self.bot.relay_game(self.bot.servers["survival"], event)
        self.state["onebot"].send_group.assert_awaited_once_with("101", "欢迎 Steve 来到 生存服")
        await self.bot.relay_game(self.bot.servers["survival"], event)
        self.assertEqual(self.state["onebot"].send_group.await_count, 1)
        self.bot.cfg["features"]["join_quit"] = True
        await self.bot.relay_game(self.bot.servers["survival"], event)
        self.assertIn("加入了游戏", self.state["onebot"].send_group.call_args.args[1])

    async def test_failed_state_file_never_overwritten(self):
        state = self.base / "data/plugin-state.json"
        state.parent.mkdir(parents=True, exist_ok=True); state.write_text('{"invalid": NaN}', encoding="utf-8")
        manager = PluginManager(self.base, self.bot, self.state["store"])
        await manager.start()
        self.assertTrue(manager.listing()["error"])
        with self.assertRaises(ValueError):
            await manager.install(example(), manager.revision)
        self.assertEqual(state.read_text(encoding="utf-8"), '{"invalid": NaN}')

    async def test_install_rejects_code_paths_and_duplicates(self):
        for change in ({"id": "../escape"}, {"code": "import os"}):
            plugin = example(); plugin.update(change)
            data = await self.get()
            response = await self.client.post("/api/extensions/install", headers=self.headers,
                                              json={"revision": data["revision"], "plugin": plugin})
            self.assertEqual(response.status, 400)
        await self.install()
        data = await self.get()
        response = await self.client.post("/api/extensions/install", headers=self.headers,
                                          json={"revision": data["revision"], "plugin": example()})
        self.assertEqual(response.status, 400)

    async def test_write_failure_preserves_running_state(self):
        await self.install(); data = await self.get()
        with patch("starbridge.extensions.atomic_json", side_effect=OSError("disk full")):
            response = await self.client.put("/api/extensions/test_helper", headers=self.headers,
                                             json={"revision": data["revision"], "enabled": True})
        self.assertEqual(response.status, 500)
        self.assertEqual(await self.get(), data)

    async def test_downloads_are_valid(self):
        for document in ("guide", "example"):
            response = await self.client.get("/api/extension-documents/"+document, headers=self.headers)
            self.assertEqual(response.status, 200)
            self.assertIn("attachment", response.headers["Content-Disposition"])
            text = await response.text()
            if document == "example":
                validate_plugin(json.loads(text))
            else:
                self.assertIn("模板变量", text)

    async def test_memory_database_instance_does_not_load_workspace_plugins(self):
        app = create_app(config())
        async with TestClient(TestServer(app)) as client:
            root = app[STATE]["plugins"].root
            self.assertNotEqual(root, Path(__file__).resolve().parent.parent / "plugins")
            response = await client.get("/api/extensions", headers=self.headers)
            self.assertEqual([p["id"] for p in (await response.json())["plugins"]], ["keyword_replies", "scheduled_tasks"])
        self.assertFalse(root.parent.exists())

    async def keywords(self, **payload):
        data = await self.get()
        return await self.client.put("/api/extensions/keyword_replies", headers=self.headers,
                                     json={"revision": data["revision"], **payload})

    async def test_keywords_migrate_once_and_keep_disabled_empty_settings_on_restart(self):
        plugin = (await self.get())["plugins"][0]
        self.assertEqual(plugin["id"], "keyword_replies")
        self.assertTrue(plugin["builtin"])
        self.assertTrue(plugin["enabled"])
        self.assertEqual(plugin["settings"]["replies"], self.cfg["replies"])
        response = await self.keywords(enabled=False, settings={"replies": {}})
        self.assertEqual(response.status, 200)
        for _ in range(2):
            manager = PluginManager(self.base, self.bot, self.state["store"])
            await manager.start()
            plugin = manager.listing()["plugins"][0]
            self.assertFalse(plugin["enabled"])
            self.assertEqual(plugin["settings"], {"replies": {}})
            await manager.scan(manager.revision)
            self.assertEqual(manager.listing()["plugins"][0], plugin)
        self.assertEqual(self.cfg["replies"], {"官网": "https://example.com"})

    async def test_keywords_live_edit_literal_long_text_and_exact_matching(self):
        reply = "{server_name} [CQ:at,qq=123]\n" + "星" * 3400
        response = await self.keywords(settings={"replies": {"带 空格": reply, "帮助": "不能覆盖帮助"}})
        self.assertEqual(response.status, 200)
        await self.message("带 空格")
        self.state["onebot"].send_group.assert_awaited_once_with("101", reply)
        self.assertEqual(self.state["store"].poll("survival"), [])
        await self.message("带 空格 参数")
        self.assertEqual(self.state["onebot"].send_group.await_count, 1)
        self.assertEqual(self.state["store"].poll("survival")[0]["kind"], "broadcast")
        await self.message("帮助")
        self.assertIn("绑定", self.state["onebot"].send_group.call_args.args[1])

    async def test_keywords_disabled_never_falls_back_to_legacy_config(self):
        response = await self.keywords(enabled=False)
        self.assertEqual(response.status, 200)
        await self.message("官网")
        self.state["onebot"].send_group.assert_not_awaited()
        self.assertEqual(self.state["store"].poll("survival")[0]["kind"], "broadcast")
        plugin = example(); plugin["rules"][0]["command"] = "官网"
        await self.install(plugin); await self.enable()
        await self.message("官网")
        self.assertIn("你好", self.state["onebot"].send_group.call_args.args[1])

    async def test_keywords_validation_conflict_and_write_failure_preserve_values(self):
        current = await self.get()
        cases = [[], {"": "empty"}, {"a": ""}, {"a" * 81: "x"}, {"a": "x" * 3501},
                 {"a": 5}, {str(i): "x" for i in range(201)}, {"a\0": "x"}]
        for replies in cases:
            with self.subTest(replies_type=type(replies).__name__):
                response = await self.keywords(settings={"replies": replies})
                self.assertEqual(response.status, 400)
                self.assertEqual(await self.get(), current)
        response = await self.keywords(settings={"replies": {"新版": "已保存"}})
        self.assertEqual(response.status, 200)
        response = await self.client.put("/api/extensions/keyword_replies", headers=self.headers,
                                        json={"revision": current["revision"], "enabled": False})
        self.assertEqual(response.status, 409)
        before = self.manager.state_path.read_bytes()
        current = await self.get()
        with patch("starbridge.extensions.os.replace", side_effect=OSError("write failed")):
            response = await self.keywords(settings={"replies": {"失败": "不生效"}})
        self.assertEqual(response.status, 500)
        self.assertEqual(await self.get(), current)
        self.assertEqual(self.manager.state_path.read_bytes(), before)

    async def test_keywords_large_legacy_map_preserves_existing_limits(self):
        self.manager.state_path.unlink()
        self.bot.cfg["replies"] = {f"关键词 {i}": "文" * 3500 for i in range(200)}
        manager = PluginManager(self.base, self.bot, self.state["store"])
        await manager.start()
        self.assertEqual(manager.listing()["plugins"][0]["settings"]["replies"], self.bot.cfg["replies"])
        self.assertGreater(manager.state_path.stat().st_size, 128 * 1024)
        reloaded = PluginManager(self.base, self.bot, self.state["store"])
        await reloaded.start()
        self.assertEqual(reloaded.listing(), manager.listing())

    async def test_keywords_reserved_id_and_builtin_removal(self):
        plugin = example(); plugin["id"] = "keyword_replies"
        data = await self.get()
        response = await self.client.post("/api/extensions/install", headers=self.headers,
                                         json={"revision": data["revision"], "plugin": plugin})
        self.assertEqual(response.status, 400)
        response = await self.keywords(enabled=False)
        self.assertEqual(response.status, 200)
        data = await self.get()
        response = await self.client.delete("/api/extensions/keyword_replies", headers=self.headers,
                                           json={"revision": data["revision"]})
        self.assertEqual(response.status, 400)
        self.assertFalse((self.base / "plugins/keyword_replies.json").exists())

    async def test_keywords_migration_failure_keeps_legacy_and_retry_works(self):
        self.manager.state_path.unlink()
        manager = PluginManager(self.base, self.bot, self.state["store"])
        with patch("starbridge.extensions.os.replace", side_effect=OSError("write failed")):
            await manager.start()
        self.assertTrue(manager.listing()["error"])
        self.assertFalse(manager.listing()["plugins"][0]["enabled"])
        self.assertEqual(self.bot.cfg["replies"], {"官网": "https://example.com"})
        self.assertFalse(manager.state_path.exists())
        manager = PluginManager(self.base, self.bot, self.state["store"])
        await manager.start()
        self.assertTrue(manager.listing()["plugins"][0]["enabled"])
