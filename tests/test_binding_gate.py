"""Admission must use real, current, server-scoped QQ bindings, never login proofs."""
import asyncio
from contextlib import closing
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid
import zipfile

from aiohttp.test_utils import TestClient, TestServer

from scripts import update_runtime
from starbridge.app import STATE, create_app
from starbridge.backups import (FILES, apply_pending_restore, finish_restore,
                                unpack_archive)
from starbridge.binding_gate import BindingGate, DEFAULTS, MAX_SETTINGS, validate_settings
from starbridge.config import load
from starbridge.extensions import atomic_json
from starbridge.registration import RegistrationError
from starbridge.settings import serialize
from test_settings import full_config


class BindingGateSettingsTests(unittest.TestCase):
    def test_validates_servers_message_controls_and_unknown_fields(self):
        for value in (None, [], {"other": True}, {"enabled_servers": "a"},
                      {"enabled_servers": ["a", "a"]}, {"enabled_servers": [[]]},
                      {"enabled_servers": ["../a"]}, {"enabled_servers": ["a"] * 101},
                      {"message": ""}, {"message": " "}, {"message": "x" * 301},
                      {"message": "hello\nthere"}, {"message": "a\x7f"}, {"message": "a\u202e"},
                      {"message": 1}):
            with self.subTest(value=value), self.assertRaises(RegistrationError):
                validate_settings({**DEFAULTS, **value} if isinstance(value, dict) else value)
        for incomplete in ({}, {"enabled_servers": []}, {"message": "missing server list"}):
            with self.assertRaises(RegistrationError):
                validate_settings(incomplete)
        self.assertEqual(validate_settings(DEFAULTS), DEFAULTS)
        self.assertEqual(validate_settings({**DEFAULTS, "enabled_servers": ["b", "a"]})["enabled_servers"], ["a", "b"])
        self.assertEqual(len(validate_settings({**DEFAULTS, "message": "中" * 300})["message"]), 300)

    def test_supervisor_capture_and_restore_preserve_gate_and_old_capture_disables_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config.toml"
            config.write_text('[app]\ndatabase="data/test.db"\n', encoding="utf-8")
            target = root / "data/binding-gate-settings.json"
            atomic_json(target, {**DEFAULTS, "enabled_servers": ["survival"]})
            database = root / "data/test.db"
            with closing(sqlite3.connect(database)) as db, db:
                db.execute("CREATE TABLE sample (value TEXT)")
            capture = root / "capture"
            update_runtime.capture(root, config, capture)
            self.assertIn("data/binding-gate-settings.json", update_runtime.read_json(capture / "capture.json")["state"])
            atomic_json(target, DEFAULTS)
            update_runtime.restore_capture(root, config, capture)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["enabled_servers"], ["survival"])
            # A deliberate rollback to a capture predating the feature restores its absence.
            info = update_runtime.read_json(capture / "capture.json")
            info["state"].remove("data/binding-gate-settings.json")
            update_runtime.write_json(capture / "capture.json", info)
            update_runtime.restore_capture(root, config, capture)
            self.assertFalse(target.exists())


class BindingGateFixture(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.path = self.base / "config.toml"
        self.cfg = full_config()
        other = {**deepcopy(self.cfg["servers"][0]), "id": "creative", "name": "创造服",
                 "token": "creative-" + "c" * 32, "groups": ["102"]}
        self.cfg["servers"].append(other)
        self.path.write_text(serialize(self.cfg), encoding="utf-8")
        self.client = TestClient(TestServer(create_app(load(self.path), self.path, asyncio.Event())))
        await self.client.start_server()
        self.state = self.client.app[STATE]
        self.gate = self.state["binding_gate"]
        self.store = self.state["store"]
        self.root = {"Authorization": "Bearer " + self.cfg["app"]["admin_token"]}
        self.bridge = {"Authorization": "Bearer " + self.cfg["servers"][0]["token"]}
        self.other_bridge = {"Authorization": "Bearer " + other["token"]}
        self.identity = str(uuid.uuid4())

    async def asyncTearDown(self):
        await self.client.close()
        self.temporary.cleanup()

    def ready(self, sid="survival", capabilities=None):
        self.state["bot"].snapshots[sid] = {"last_seen": time.time(),
            "capabilities": ["binding_gate"] if capabilities is None else capabilities}

    async def settings(self):
        response = await self.client.get("/api/binding-gate/settings", headers=self.root)
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        return await response.json()

    async def save(self, settings, revision=None, status=200):
        response = await self.client.put("/api/binding-gate/settings", headers=self.root,
            json={"settings": settings, "revision": self.gate.revision if revision is None else revision})
        self.assertEqual(response.status, status, await response.text())
        return await response.json()

    async def enable(self, *servers):
        for sid in servers or ("survival",):
            self.ready(sid)
        return await self.save({**DEFAULTS, "enabled_servers": list(servers or ("survival",))})

    async def check(self, data=None, sid="survival", headers=None, status=200):
        response = await self.client.post(f"/bridge/{sid}/binding-check",
            headers=self.bridge if headers is None else headers,
            json={"uuid": self.identity, "player": "Steve", **(data or {})})
        self.assertEqual(response.status, status, await response.text())
        return await response.json() if status == 200 else await response.text()

    def bind(self, sid="survival", qq="123456789", identity=None, name="Steve"):
        code = self.store.issue_code(sid, identity or self.identity, name)
        return self.store.bind(sid, qq, code)


class BindingGateApiTests(BindingGateFixture):
    async def test_default_off_allows_without_binding_or_side_effects(self):
        result = await self.check()
        self.assertEqual(set(result), {"required", "available", "allowed", "message", "revision"})
        self.assertFalse(result["required"])
        self.assertTrue(result["available"] and result["allowed"])
        self.assertFalse(self.gate.path.exists())
        for table in ("bindings", "codes", "account_game_links", "registration_accounts"):
            self.assertEqual(self.store.db.execute("SELECT count(*) FROM " + table).fetchone()[0], 0)

    async def test_current_uuid_and_server_scope_with_immediate_unbind_and_rename(self):
        await self.enable("survival", "creative")
        self.assertFalse((await self.check())["allowed"])
        self.bind("creative")
        self.assertFalse((await self.check())["allowed"])
        self.bind(identity=str(uuid.uuid4()), qq="987654321")
        self.assertFalse((await self.check())["allowed"], "Identical names must not bypass UUID binding")
        self.bind()
        self.assertTrue((await self.check({"player": "RenamedPlayer"}))["allowed"])
        self.store.unbind("survival", "123456789")
        self.assertFalse((await self.check())["allowed"])
        self.assertTrue((await self.check(sid="creative", headers=self.other_bridge))["allowed"])

    async def test_official_namespaced_user_id_is_preserved_and_never_returned(self):
        await self.enable()
        for qq in ("qug:123456789:Abc_Official-ID", "qup:987654321:AnotherOpenID"):
            self.bind(qq=qq)
            result = await self.check({"nonce": str(uuid.uuid4())})
            self.assertTrue(result["allowed"])
            self.assertNotIn(qq, json.dumps(result))
            self.assertEqual(self.store.binding("survival", qq)["qq"], qq)
            self.store.unbind("survival", qq)
        with self.store.db:
            self.store.db.execute("INSERT INTO bindings VALUES(?,?,?,?,?)", ("survival", "qg:123:group", self.identity, "Steve", time.time()))
        self.assertFalse((await self.check())["allowed"], "Group IDs are not user identities")

    async def test_bridge_tokens_are_isolated_and_admin_token_is_not_bridge_token(self):
        for header in ({}, {"Authorization": "Bearer invalid"}, self.root, self.other_bridge):
            response = await self.client.post("/bridge/survival/binding-check", headers=header,
                json={"uuid": self.identity, "player": "Steve"})
            self.assertEqual(response.status, 401)
        await self.check(sid="creative", headers=self.bridge, status=401)
        await self.check(sid="absent", status=404)

    async def test_request_identity_format_rejects_relaxed_uuid_names_nonce_and_unknown_fields(self):
        for change in ({"uuid": self.identity.replace("-", "")}, {"uuid": "{" + self.identity + "}"},
                       {"uuid": "not-uuid"}, {"uuid": 123}, {"player": "Steve.other"},
                       {"player": "x" * 17}, {"player": ""}, {"player": 1},
                       {"nonce": "incorrect"}, {"nonce": None}, {"ip": "127.0.0.1"}):
            with self.subTest(change=change):
                await self.check(change, status=400)
        self.assertTrue((await self.check({"uuid": self.identity.upper()}))["allowed"])

    async def test_only_owner_may_read_or_save_even_all_permissions_team_member(self):
        from starbridge.admin_accounts import PERMISSIONS
        response = await self.client.post("/api/admin-users", headers=self.root,
            json={"username": "TeamAdmin", "password": "Team-password-2026", "permissions": list(PERMISSIONS)})
        self.assertEqual(response.status, 200, await response.text())
        response = await self.client.post("/api/admin-auth/login",
            json={"username": "TeamAdmin", "password": "Team-password-2026"})
        team = {"Authorization": "Bearer " + (await response.json())["access_token"]}
        for headers, status in (({}, 401), (self.bridge, 401), (team, 403)):
            for method in (self.client.get, self.client.put):
                response = await method("/api/binding-gate/settings", headers=headers)
                self.assertEqual(response.status, status, await response.text())
        self.assertFalse(self.gate.path.exists())

    async def test_owner_account_session_can_save_without_exposing_management_token(self):
        response = await self.client.post("/api/admin-auth/setup", headers=self.root,
            json={"username": "Owner", "password": "Owner-password-2026"})
        self.assertEqual(response.status, 200, await response.text())
        headers = {"Authorization": "Bearer " + (await response.json())["access_token"]}
        response = await self.client.get("/api/binding-gate/settings", headers=headers)
        current = await response.json()
        self.assertEqual(response.status, 200)
        response = await self.client.put("/api/binding-gate/settings", headers=headers,
            json={"settings": {**DEFAULTS, "message": "请先绑定游戏账号"}, "revision": current["revision"]})
        self.assertEqual(response.status, 200, await response.text())
        self.assertNotIn(self.cfg["app"]["admin_token"], await response.text())
        self.assertEqual((await response.json())["settings"]["message"], "请先绑定游戏账号")

    async def test_invalid_request_shapes_and_unknown_settings_fields_are_rejected_without_changes(self):
        await self.enable()
        revision, content = self.gate.revision, self.gate.path.read_bytes()
        for value in ([], None, "text", {"settings": DEFAULTS, "revision": revision, "unknown": 1},
                      {"settings": {"message": "incomplete"}, "revision": revision},
                      {"settings": {**DEFAULTS, "unknown": True}, "revision": revision}):
            response = await self.client.put("/api/binding-gate/settings", headers=self.root, json=value)
            self.assertEqual(response.status, 400, await response.text())
        response = await self.client.post("/bridge/survival/binding-check", headers=self.bridge, json=[])
        self.assertEqual(response.status, 400, await response.text())
        self.assertEqual(self.gate.path.read_bytes(), content)
        self.assertEqual(self.gate.revision, revision)

    async def test_new_enable_requires_existing_fresh_supporting_bridge(self):
        for sid in ("missing", "survival"):
            await self.save({**DEFAULTS, "enabled_servers": [sid]}, status=400)
        self.ready(capabilities=["player_management"])
        await self.save({**DEFAULTS, "enabled_servers": ["survival"]}, status=400)
        self.ready()
        self.state["bot"].snapshots["survival"]["last_seen"] = time.time() - 16
        await self.save({**DEFAULTS, "enabled_servers": ["survival"]}, status=400)
        self.assertFalse(self.gate.path.exists())
        await self.enable()
        self.assertEqual(json.loads(self.gate.path.read_text(encoding="utf-8"))["enabled_servers"], ["survival"])

    async def test_enabled_offline_or_removed_servers_remain_visible_and_can_be_disabled(self):
        await self.enable()
        del self.state["bot"].snapshots["survival"]
        result = await self.settings()
        self.assertFalse(next(s for s in result["servers"] if s["id"] == "survival")["online"])
        await self.save({**DEFAULTS, "enabled_servers": ["survival"], "message": "先完成绑定"})
        del self.state["bot"].servers["survival"]
        result = await self.settings()
        missing = next(s for s in result["servers"] if s["id"] == "survival")
        self.assertTrue(missing["missing"])
        self.assertFalse(missing["supported"] or missing["online"])
        self.assertEqual(result["settings"]["enabled_servers"], ["survival"])
        await self.save(DEFAULTS)
        self.assertEqual((await self.settings())["settings"]["enabled_servers"], [])

    async def test_stale_revision_and_concurrent_save_do_not_overwrite(self):
        old = (await self.settings())["revision"]
        await self.save({**DEFAULTS, "message": "先绑定再进入"})
        await self.save(DEFAULTS, revision=old, status=409)
        revision = self.gate.revision
        results = await asyncio.gather(*(self.gate.save({**DEFAULTS, "message": text}, revision)
                                        for text in ("第一条提示", "第二条提示")), return_exceptions=True)
        self.assertEqual(sum(isinstance(result, RegistrationError) and result.status == 409 for result in results), 1)
        self.assertEqual((await self.settings())["settings"]["message"], "第一条提示")

    async def test_disk_corruption_missing_file_and_recovery_fail_closed(self):
        await self.enable()
        self.bind()
        for content in (b"{invalid", b"x" * (MAX_SETTINGS + 1), b'{"enabled_servers":null}', b'{"message":"missing server list"}'):
            self.gate.path.write_bytes(content)
            self.assertFalse((await self.check())["allowed"])
            self.assertFalse((await self.check())["available"])
            self.assertTrue((await self.check(sid="creative", headers=self.other_bridge))["required"])
            result = await self.settings()
            self.assertTrue(result["error"])
            self.assertEqual(result["settings"]["enabled_servers"], ["survival"])
            await self.save({**DEFAULTS, "enabled_servers": ["survival"]})
            self.assertTrue((await self.check())["allowed"])
        self.gate.path.unlink()
        self.assertFalse((await self.check())["allowed"])
        await self.save(DEFAULTS)
        self.assertTrue((await self.check())["allowed"])

    async def test_corrupt_startup_is_not_treated_as_default_off(self):
        self.gate.path.parent.mkdir(parents=True, exist_ok=True)
        self.gate.path.write_text("not JSON", encoding="utf-8")
        gate = BindingGate(self.base, self.state["bot"])
        result = gate.check("survival", {"uuid": self.identity, "player": "Steve"})
        self.assertTrue(result["required"])
        self.assertFalse(result["available"] or result["allowed"])
        await gate.save(DEFAULTS, gate.revision)
        self.assertTrue(gate.check("survival", {"uuid": self.identity, "player": "Steve"})["allowed"])

    async def test_disk_save_failure_preserves_previous_policy_and_revision(self):
        await self.enable()
        revision = self.gate.revision
        content = self.gate.path.read_bytes()
        with patch("starbridge.binding_gate.atomic_json", side_effect=OSError("disk private details")):
            result = await self.save(DEFAULTS, status=503)
        self.assertNotIn("private details", str(result))
        self.assertEqual(self.gate.path.read_bytes(), content)
        self.assertEqual(self.gate.revision, revision)
        self.assertFalse((await self.check())["allowed"])

    async def test_database_failure_fails_closed_without_raw_details(self):
        await self.enable()
        failed = SimpleNamespace(execute=lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("private secret")))
        original_store = self.gate.store
        self.gate.store = SimpleNamespace(db=failed)
        try:
            result = await self.check()
            self.assertFalse(result["available"] or result["allowed"])
            self.assertNotIn("private", str(result))
        finally:
            self.gate.store = original_store

    async def test_prelogin_check_does_not_create_binding_proofs_or_authenticate_player(self):
        await self.enable()
        self.bind()
        auth = self.state["authentication"]
        await auth.save_settings({**auth.settings, "enabled_servers": ["survival"]}, auth.revision)
        account = str(uuid.uuid4())
        with self.store.db:
            self.store.db.execute("INSERT INTO registration_accounts VALUES(?,?,?,?,?,?)",
                (account, "Steve", "steve", "123456789@qq.com", "123456789", time.time()))
        result = await self.check({"nonce": str(uuid.uuid4())})
        self.assertTrue(result["allowed"])
        self.assertFalse(auth.allowed("survival", self.identity, str(uuid.uuid4()), "Steve"))
        self.assertFalse(auth.sessions)
        for table in ("codes", "account_game_links", "native_password_proofs", "password_challenges"):
            self.assertEqual(self.store.db.execute("SELECT count(*) FROM " + table).fetchone()[0], 0)

    async def test_tick_advertises_current_policy_and_settings_report_capability(self):
        response = await self.client.post("/bridge/survival/tick", headers=self.bridge,
            json={"capabilities": ["binding_gate"]})
        self.assertEqual(response.status, 200, await response.text())
        self.assertFalse((await response.json())["binding_policy"]["required"])
        self.assertTrue(next(s for s in (await self.settings())["servers"] if s["id"] == "survival")["supported"])
        await self.enable()
        response = await self.client.post("/bridge/survival/tick", headers=self.bridge,
            json={"capabilities": ["binding_gate"]})
        result = await response.json()
        self.assertTrue(result["binding_policy"]["required"])
        self.assertEqual(result["binding_policy"], self.gate.policy("survival"))
        self.assertIn("authentication", result)

    async def test_settings_persist_without_new_database_schema(self):
        tables = self.store.db.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name").fetchall()
        await self.enable()
        restored = BindingGate(self.base, self.state["bot"])
        self.assertEqual(restored.config()["settings"], self.gate.config()["settings"])
        self.assertEqual(restored.revision, self.gate.revision)
        self.assertFalse(restored.check("survival", {"uuid": self.identity, "player": "Steve"})["allowed"])
        self.assertEqual(tables, self.store.db.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name").fetchall())


class BindingGateBackupTests(BindingGateFixture):
    async def archive(self):
        entry = await self.state["backups"].create("manual")
        return self.state["backups"].path(entry["id"]).read_bytes()

    def rewrite(self, payload, update):
        with zipfile.ZipFile(io.BytesIO(payload)) as source:
            values = {name: source.read(name) for name in source.namelist()}
        update(values)
        manifest = json.loads(values.pop("manifest.json"))
        manifest["files"] = {name: {"size": len(value), "sha256": hashlib.sha256(value).hexdigest()} for name, value in values.items()}
        values["manifest.json"] = json.dumps(manifest).encode()
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            for name, value in values.items():
                archive.writestr(name, value)
        return output.getvalue()

    async def restore(self, payload):
        manager = self.state["backups"]
        response = await self.client.post("/api/backups/preview", headers={**self.root, "Content-Type": "application/zip"}, data=payload)
        self.assertEqual(response.status, 200, await response.text())
        preview = await response.json()
        await manager.restore(preview["preview_id"])
        # Offline restore owns the database; close the isolated HTTP service first.
        await self.client.close()
        self.assertTrue(apply_pending_restore(self.path))
        finish_restore(self.path)
        gate = BindingGate(self.base, self.state["bot"])
        return gate

    async def test_backup_includes_gate_and_rejects_invalid_or_oversize_settings(self):
        await self.enable()
        payload = await self.archive()
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            self.assertEqual(json.loads(archive.read("data/binding-gate-settings.json"))["enabled_servers"], ["survival"])
        self.assertEqual(FILES["data/binding-gate-settings.json"], MAX_SETTINGS)
        for content in (b'{"message":""}', b" " * (MAX_SETTINGS + 1)):
            invalid = self.rewrite(payload, lambda values: values.update({"data/binding-gate-settings.json": content}))
            target = self.base / ("invalid-" + uuid.uuid4().hex + ".zip")
            target.write_bytes(invalid)
            with self.assertRaises(ValueError):
                unpack_archive(target, self.base / ("unpacked-" + uuid.uuid4().hex))

    async def test_restore_restores_saved_gate_policy(self):
        await self.enable()
        payload = await self.archive()
        await self.save(DEFAULTS)
        gate = await self.restore(payload)
        self.assertTrue(gate.policy("survival")["required"])
        self.assertTrue(gate.policy("survival")["available"])

    async def test_explicit_old_backup_restore_defaults_gate_off(self):
        await self.enable()
        payload = self.rewrite(await self.archive(), lambda values: values.pop("data/binding-gate-settings.json"))
        gate = await self.restore(payload)
        self.assertFalse(gate.path.exists())
        self.assertFalse(gate.policy("survival")["required"])


if os.environ.get("MYRINBOT_TEST_MYSQL_CONFIG"):
    from test_mysql_integration import _contract_case
    MySQLBindingGateApiTests = _contract_case("MySQLBindingGateApiTests", "test_binding_gate", "BindingGateApiTests",
        factory="full_config", excluded={"test_settings_persist_without_new_database_schema"})


if __name__ == "__main__":
    unittest.main()
