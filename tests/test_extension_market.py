"""Isolated API and execution checks for the bundled VexBot plugin market."""
from copy import deepcopy
import asyncio
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch
import uuid

from aiohttp.test_utils import TestClient, TestServer

from starbridge import extension_market as market
from starbridge.app import STATE, create_app
from starbridge.extensions import BUILTINS, MAX_PLUGINS, encode, validate_plugin
from test_starbridge import config


def official(plugin_id="community_rules"):
    return deepcopy(next(item["definition"] for item in market.CATALOG if item["definition"]["id"] == plugin_id))


def future_catalog(plugin_id="community_rules"):
    items = deepcopy(market.CATALOG)
    row = next(item for item in items if item["definition"]["id"] == plugin_id)
    old = deepcopy(row["definition"])
    row["previous_definitions"] = (old,)
    row["definition"]["version"] = "1.1.0"
    row["definition"]["changelog"] = "测试夹具模拟随软件发布的新版本"
    row["definition"]["settings"]["new_note"] = {"type": "string", "label": "新增说明", "default": "新版本默认值"}
    return items


class MarketCatalogTests(unittest.TestCase):
    def test_all_packages_validate_and_use_distinct_non_builtin_commands(self):
        rows = market.catalog()
        self.assertEqual(len(rows), 6)
        self.assertEqual(len({item["definition"]["id"] for item in rows}), 6)
        commands = []
        for row in rows:
            definition = validate_plugin(row["definition"])
            self.assertEqual(definition["author"], "VexBot")
            self.assertLess(len(encode(definition)), 64 * 1024)
            self.assertEqual(row["sha256"], market.digest(definition))
            self.assertTrue(row["readme"])
            self.assertEqual(row["previous_definitions"], ())
            commands.extend(rule["command"] for rule in definition["rules"] if rule["event"] == "group_command")
        self.assertEqual(len(set(commands)), len(commands))
        self.assertFalse(set(commands) & BUILTINS)

    def test_release_comparison_accepts_only_unambiguous_release_triplets(self):
        self.assertGreater(market.release_version("1.10.0"), market.release_version("1.9.9"))
        for value in ("v1.0.0", "1.0", "01.0.0", "1.0.0-beta", "1.0.0+build", "2", None, True, []):
            with self.subTest(value=value):
                self.assertIsNone(market.release_version(value))


class MarketApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.cfg = config(str(self.base / "db.sqlite"))
        self.cfg["features"]["qq_to_mc"] = False
        self.client = TestClient(TestServer(create_app(self.cfg)))
        await self.client.start_server()
        self.state = self.client.app[STATE]
        self.manager = self.state["plugins"]
        self.bot = self.state["bot"]
        self.headers = {"Authorization": "Bearer " + self.cfg["app"]["admin_token"]}
        self.state["onebot"].send_group = AsyncMock()
        self.bot.snapshots["survival"] = {"last_seen": time.time(), "players": ["Steve", "Alex"], "max_players": 20}

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    async def get(self, headers=None):
        response = await self.client.get("/api/extension-market", headers=headers or self.headers)
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        return await response.json()

    def payload(self, listing, plugin_id):
        row = next(row for row in listing["plugins"] if row["id"] == plugin_id)
        return {"revision": listing["revision"], "catalog_revision": listing["catalog_revision"], "sha256": row["sha256"]}

    async def operation(self, plugin_id="community_rules", action="install", payload=None, status=200, headers=None):
        payload = self.payload(await self.get(), plugin_id) if payload is None else payload
        response = await self.client.post(f"/api/extension-market/{plugin_id}/{action}",
                                          headers=headers or self.headers, json=payload)
        self.assertEqual(response.status, status, await response.text())
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        return await response.json()

    async def message(self, text, user="201"):
        await self.bot.handle_event({"post_type": "message", "message_type": "group", "self_id": 100,
                                     "user_id": user, "group_id": "101", "message_id": uuid.uuid4().hex,
                                     "message": [{"type": "text", "data": {"text": text}}]})

    async def test_listing_does_not_install_and_discloses_no_runtime_config(self):
        before = self.manager.revision
        data = await self.get()
        self.assertEqual(data["revision"], before)
        self.assertEqual(data["error"], "")
        self.assertEqual(len(data["plugins"]), 6)
        self.assertEqual(len(list(self.manager.root.glob("*.json"))), 0)
        for row in data["plugins"]:
            self.assertEqual(row["status"], "available")
            self.assertIsNone(row["installed_version"])
            self.assertIsInstance(row["readme"], str)
            self.assertIsInstance(row["changelog"], str)
            self.assertTrue(row["capabilities"])
            self.assertGreater(row["settings_count"], 0)
        serialized = json.dumps(data)
        self.assertNotIn(self.cfg["app"]["admin_token"], serialized)
        self.assertNotIn(str(self.base), serialized)

    async def test_unauthorized_cannot_list_install_or_upgrade(self):
        for route in ("/api/extension-market", "/api/extension-market/community_rules/install", "/api/extension-market/community_rules/upgrade"):
            for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": "Bearer " + self.cfg["servers"][0]["token"]}):
                request = self.client.get if route == "/api/extension-market" else self.client.post
                response = await request(route, headers=headers)
                self.assertEqual(response.status, 401)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertFalse((self.manager.root / "community_rules.json").exists())

    async def test_market_honors_plugin_manager_team_permission(self):
        response = await self.client.post("/api/admin-users", headers=self.headers,
            json={"username": "Observer", "password": "A-test-password-2026", "permissions": ["status.read"]})
        self.assertEqual(response.status, 200, await response.text())
        user = (await response.json())["users"][0]
        session = self.state["admin_accounts"].session(user["id"], user["username"])
        team_headers = {"Authorization": "Bearer " + session["access_token"]}
        for method, route in (("get", "/api/extension-market"), ("post", "/api/extension-market/community_rules/install"),
                              ("post", "/api/extension-market/community_rules/upgrade")):
            response = await getattr(self.client, method)(route, headers=team_headers)
            self.assertEqual(response.status, 403)
        with self.state["store"].db:
            self.state["store"].db.execute("UPDATE admin_users SET permissions=? WHERE id=?",
                                         (json.dumps(["status.read", "plugins.manage"]), user["id"]))
        data = await self.get(team_headers)
        await self.operation(payload=self.payload(data, "community_rules"), headers=team_headers)

    async def test_install_is_real_disabled_and_executes_only_after_enable(self):
        data = await self.operation()
        row = next(row for row in data["plugins"] if row["id"] == "community_rules")
        self.assertEqual(row["status"], "installed")
        self.assertEqual(row["installed_version"], "1.0.0")
        path = self.manager.root / "community_rules.json"
        self.assertEqual(validate_plugin(json.loads(path.read_text(encoding="utf-8"))), official())
        self.assertFalse(self.manager.entries["community_rules"]["enabled"])
        await self.message("群规")
        self.state["onebot"].send_group.assert_not_awaited()
        await self.manager.update("community_rules", {"revision": self.manager.revision, "enabled": True,
                                 "settings": {"title": "测试社区", "content": "请不要破坏他人建筑"}})
        await self.message("群规")
        self.state["onebot"].send_group.assert_awaited_once_with("101", "测试社区\n请不要破坏他人建筑")

    async def test_all_six_packages_execute_real_commands_and_game_events(self):
        code = self.state["store"].issue_code("survival", "uuid-steve", "Steve")
        self.state["store"].bind("survival", "201", code)
        for item in market.catalog():
            definition = item["definition"]
            plugin_id = definition["id"]
            await self.operation(plugin_id)
            await self.manager.update(plugin_id, {"revision": self.manager.revision, "enabled": True})
            command = next(rule["command"] for rule in definition["rules"] if rule["event"] == "group_command")
            self.state["onebot"].send_group.reset_mock()
            await self.message(command)
            self.state["onebot"].send_group.assert_awaited_once()
            reply = self.state["onebot"].send_group.call_args.args[1]
            self.assertTrue(reply)
            if plugin_id == "online_digest":
                self.assertIn("2 人", reply)
                self.assertIn("Steve、Alex", reply)
            if plugin_id == "binding_card":
                self.assertIn("Steve", reply)
            if plugin_id == "join_quit_notice":
                self.state["onebot"].send_group.reset_mock()
                for kind in ("join", "quit"):
                    await self.manager.game_event(self.bot.servers["survival"], {"kind": kind, "player": "Alex", "uuid": "uuid-alex"})
                self.assertEqual(self.state["onebot"].send_group.await_count, 2)
                self.assertIn("Alex", self.state["onebot"].send_group.call_args.args[1])
            self.bot.limits.clear()

    async def test_stale_revision_catalog_and_digest_are_conflicts_without_writes(self):
        data = await self.get()
        payload = self.payload(data, "community_rules")
        before = self.manager.revision
        for field in ("revision", "catalog_revision", "sha256"):
            with self.subTest(field=field):
                await self.operation(payload={**payload, field: "0" * 64}, status=409)
                self.assertEqual(self.manager.revision, before)
                self.assertFalse((self.manager.root / "community_rules.json").exists())
        await self.operation()
        await self.operation("server_address", payload=self.payload(data, "server_address"), status=409)

    async def test_unknown_fields_urls_definitions_and_invalid_payloads_are_rejected(self):
        payload = self.payload(await self.get(), "community_rules")
        for extra in ({"url": "https://example.invalid/plugin.json"}, {"plugin": official()}, {"enabled": True}):
            await self.operation(payload={**payload, **extra}, status=400)
        for broken in ([], None, {}, {**payload, "sha256": "short"}, {**payload, "revision": True}):
            # operation(None) intentionally means auto payload, so issue this request directly.
            response = await self.client.post("/api/extension-market/community_rules/install", headers=self.headers, json=broken)
            self.assertEqual(response.status, 400, await response.text())
        response = await self.client.post("/api/extension-market/unknown/install", headers=self.headers, json=payload)
        self.assertEqual(response.status, 404)
        self.assertFalse((self.manager.root / "community_rules.json").exists())

    async def test_reinstall_and_same_version_upgrade_cannot_overwrite_enabled_plugin(self):
        await self.operation()
        await self.manager.update("community_rules", {"revision": self.manager.revision, "enabled": True})
        before = self.manager.revision
        await self.operation(status=409)
        await self.operation(action="upgrade", status=409)
        self.assertEqual(before, self.manager.revision)
        self.assertTrue(self.manager.entries["community_rules"]["enabled"])

    async def test_same_version_local_customization_is_protected(self):
        definition = official()
        definition["rules"][0]["reply"] = "本地定制内容"
        await self.manager.install(definition, self.manager.revision)
        row = next(row for row in (await self.get())["plugins"] if row["id"] == definition["id"])
        self.assertEqual(row["status"], "custom")
        await self.operation(action="upgrade", status=409)
        self.assertEqual(self.manager.entries[definition["id"]]["definition"], definition)

    async def test_unloaded_same_id_file_and_unscanned_disk_edits_are_protected(self):
        path = self.manager.root / "community_rules.json"
        path.write_text(json.dumps(official(), ensure_ascii=False), encoding="utf-8")
        row = next(row for row in (await self.get())["plugins"] if row["id"] == "community_rules")
        self.assertEqual(row["status"], "custom")
        await self.operation(status=409)
        await self.manager.scan(self.manager.revision)
        data = await self.get()
        definition = official()
        definition["description"] = "尚未重新扫描的磁盘修改"
        content = encode(definition)
        path.write_bytes(content)
        row = next(row for row in (await self.get())["plugins"] if row["id"] == "community_rules")
        self.assertEqual(row["status"], "custom")
        await self.operation(payload=self.payload(data, "community_rules"), action="upgrade", status=409)
        self.assertEqual(path.read_bytes(), content)

    async def test_unknown_lower_newer_and_nonstandard_local_versions_never_offer_updates(self):
        for version in ("0.0.1", "9.0.0", "1.0.0-beta", "v1.0.0"):
            definition = official()
            definition["version"] = version
            path = self.manager.root / "community_rules.json"
            path.write_bytes(encode(definition))
            await self.manager.scan(self.manager.revision)
            row = next(row for row in (await self.get())["plugins"] if row["id"] == "community_rules")
            self.assertEqual(row["status"], "custom", version)
            await self.operation(action="upgrade", status=409)
            self.assertEqual(json.loads(path.read_bytes())["version"], version)

    async def test_trusted_future_upgrade_preserves_settings_permissions_history_and_can_rollback(self):
        original_definition = official()
        await self.operation()
        policy = {"groups": ["101"], "user_mode": "admins", "read_bindings": False}
        await self.manager.update("community_rules", {"revision": self.manager.revision, "enabled": True,
            "settings": {"title": "我的标题", "content": "我的规则"}, "permissions": policy})
        original_permissions = deepcopy(self.manager.entries["community_rules"]["permissions"])
        with patch.object(market, "CATALOG", future_catalog()):
            row = next(row for row in (await self.get())["plugins"] if row["id"] == "community_rules")
            self.assertEqual(row["status"], "update")
            await self.operation(action="upgrade")
            entry = self.manager.entries["community_rules"]
            self.assertFalse(entry["enabled"])
            self.assertEqual(entry["definition"]["version"], "1.1.0")
            self.assertEqual(entry["settings"], {"title": "我的标题", "content": "我的规则", "new_note": "新版本默认值"})
            self.assertEqual(entry["permissions"], original_permissions)
            history = self.manager.versions("community_rules")["versions"]
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["version"], "1.0.0")
            await self.manager.upgrade("community_rules", self.manager.revision, history[0]["id"])
            entry = self.manager.entries["community_rules"]
            self.assertFalse(entry["enabled"])
            self.assertEqual(entry["settings"], {"title": "我的标题", "content": "我的规则"})
            self.assertEqual(entry["permissions"], original_permissions)
            self.assertEqual(entry["definition"], original_definition)

    async def test_concurrent_install_uses_one_revision_and_only_one_succeeds(self):
        payload = self.payload(await self.get(), "community_rules")

        async def post_once():
            return await self.client.post("/api/extension-market/community_rules/install", headers=self.headers, json=payload)

        responses = await asyncio.gather(post_once(), post_once())
        self.assertEqual(sorted(response.status for response in responses), [200, 409])
        for response in responses:
            await response.read()
        self.assertEqual(len(list(self.manager.root.glob("*.json"))), 1)
        self.assertFalse(self.manager.entries["community_rules"]["enabled"])

    async def test_mutated_known_previous_package_cannot_be_upgraded(self):
        definition = official()
        definition["description"] = "本地修改旧包"
        await self.manager.install(definition, self.manager.revision)
        with patch.object(market, "CATALOG", future_catalog()):
            row = next(row for row in (await self.get())["plugins"] if row["id"] == "community_rules")
            self.assertEqual(row["status"], "custom")
            await self.operation(action="upgrade", status=409)
        self.assertEqual(self.manager.entries["community_rules"]["definition"], definition)

    async def test_read_only_state_and_invalid_local_package_are_not_overwritten(self):
        self.manager.state_error = "插件状态读取失败，已暂停写入。"
        data = await self.get()
        self.assertEqual(data["error"], self.manager.state_error)
        await self.operation(status=400)
        self.assertFalse((self.manager.root / "community_rules.json").exists())
        self.manager.state_error = ""
        path = self.manager.root / "community_rules.json"
        path.write_text("not json", encoding="utf-8")
        await self.manager.scan(self.manager.revision)
        row = next(row for row in (await self.get())["plugins"] if row["id"] == "community_rules")
        self.assertEqual(row["status"], "error")
        await self.operation(status=409)
        self.assertEqual(path.read_text(encoding="utf-8"), "not json")

    async def test_full_capacity_is_rejected_by_real_manager(self):
        for index in range(MAX_PLUGINS):
            definition = official()
            definition["id"] = f"capacity_{index}"
            (self.manager.root / f"capacity_{index}.json").write_bytes(encode(definition))
        await self.manager.scan(self.manager.revision)
        await self.operation(status=400)
        self.assertFalse((self.manager.root / "community_rules.json").exists())

    async def test_write_errors_are_generic_and_never_expose_paths(self):
        with patch("starbridge.extensions.atomic_json", side_effect=OSError("denied " + str(self.base))):
            result = await self.operation(status=500)
        self.assertNotIn(str(self.base), json.dumps(result))
        self.assertNotIn("denied", json.dumps(result))
        self.assertFalse((self.manager.root / "community_rules.json").exists())


if __name__ == "__main__":
    unittest.main()
