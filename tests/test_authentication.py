import asyncio
from copy import deepcopy
import json
from pathlib import Path
import re
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import uuid

from aiohttp.test_utils import TestClient, TestServer

from starbridge.app import STATE, create_app
from starbridge.authentication import Authentication, DEFAULTS, validate_settings
from starbridge.passwords import check_password, hash_password, validate_password
from test_starbridge import config


PASSWORD = "Correct Horse 123"
DIGEST = hash_password(PASSWORD)


class PasswordTests(unittest.TestCase):
    def test_hash_is_salted_versioned_and_never_plaintext(self):
        second = hash_password(PASSWORD)
        self.assertNotEqual(second, DIGEST)
        self.assertTrue(check_password(PASSWORD, second))
        self.assertFalse(check_password("Incorrect Horse", second))
        self.assertNotIn(PASSWORD, second)
        self.assertFalse(check_password(PASSWORD, "not a password hash"))

    def test_password_and_authentication_settings_validation(self):
        for value in (None, 123, "short", "p" * 129, "password\n"):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(ValueError):
                validate_password(value)
        for changes in ({"enabled_servers": [[]]}, {"enabled_servers": ["a", "a"]}, {"enabled_servers": ["../x"]},
                        {"login_seconds": 29}, {"qq_seconds": True}, {"max_attempts": 11}, {"login_engine": "other"},
                        {"enabled_servers": ["survival"], "password_login": False, "qq_login": False}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_settings({**DEFAULTS, **changes})
        for engine in ("auto", "builtin", "authme", "nlogin", "loginsecurity", "librelogin"):
            self.assertEqual(validate_settings({"login_engine": engine})["login_engine"], engine)


class GameAuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.base = Path(self.tmp.name)
        self.cfg = config(str(self.base / "test.db"))
        self.client = TestClient(TestServer(create_app(self.cfg))); await self.client.start_server()
        self.state = self.client.app[STATE]; self.auth = self.state["authentication"]; self.store = self.state["store"]
        self.registration = self.state["registration"]
        self.admin = {"Authorization": "Bearer " + self.cfg["app"]["admin_token"]}
        self.bridge = {"Authorization": "Bearer " + self.cfg["servers"][0]["token"]}
        self.identity, self.nonce, self.account_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
        self.store.db.execute("INSERT INTO registration_accounts VALUES(?,?,?,?,?,?)", (self.account_id, "Steve", "steve", "123456789@qq.com", "123456789", time.time()))
        self.store.db.execute("INSERT INTO account_passwords VALUES(?,?,?)", (self.account_id, DIGEST, time.time()))
        self.store.db.commit()
        self.registration.settings.update(smtp_host="smtp.test", smtp_from="sender@example.com")
        self.sent = []
        self.mail = patch("starbridge.registration.send_verification", side_effect=lambda *args: self.sent.append(args)); self.mail.start()
        self.state["onebot"].ws = SimpleNamespace(closed=False, close=AsyncMock())
        self.state["onebot"].self_id = "100"
        self.state["onebot"].send_private = AsyncMock()
        self.state["onebot"].send_group = AsyncMock()
        await self.enable()

    async def asyncTearDown(self):
        await self.client.close(); self.mail.stop(); self.tmp.cleanup()

    async def enable(self, **changes):
        settings = {**deepcopy(DEFAULTS), "enabled_servers": ["survival"], **changes}
        await self.auth.save_settings(settings, self.auth.revision)

    def payload(self, action, **extra):
        return {"action": action, "uuid": self.identity, "nonce": self.nonce, "player": "Steve", "ip": "127.0.0.1", **extra}

    async def action(self, action, status=200, **extra):
        response = await self.client.post("/bridge/survival/auth", headers=self.bridge, json=self.payload(action, **extra))
        self.assertEqual(response.status, status, await response.text())
        return await response.json()

    async def heartbeat(self, payload=None):
        response = await self.client.post("/bridge/survival/tick", headers=self.bridge, json={"auth_sessions": [payload or self.payload("heartbeat")]})
        self.assertEqual(response.status, 200, await response.text())
        return await response.json()

    async def test_external_engine_settings_roundtrip_fences_sessions_and_reaches_bridge_policy(self):
        for engine in ("authme", "nlogin", "loginsecurity", "librelogin", "builtin", "auto"):
            with self.subTest(engine=engine):
                await self.action("join")
                self.assertTrue(self.auth.sessions)
                old_revision = self.auth.revision
                settings = {**deepcopy(self.auth.settings), "login_engine": engine}
                response = await self.client.put("/api/authentication/settings", headers=self.admin,
                                                 json={"settings": settings, "revision": old_revision})
                self.assertEqual(response.status, 200, await response.text())
                saved = await response.json()
                self.assertEqual(saved["settings"]["login_engine"], engine)
                self.assertNotEqual(saved["revision"], old_revision)
                self.assertFalse(self.auth.sessions)
                response = await self.client.get("/api/authentication/settings", headers=self.admin)
                self.assertEqual((await response.json())["settings"]["login_engine"], engine)
                self.assertEqual(json.loads(self.auth.path.read_text(encoding="utf-8"))["login_engine"], engine)
                heartbeat = await self.heartbeat()
                self.assertEqual(heartbeat["authentication"]["login_engine"], engine)
                self.assertTrue(heartbeat["authentication"]["required"])

    async def test_unknown_engine_rejection_preserves_live_sessions_and_revision(self):
        await self.action("join")
        old_revision, old_sessions = self.auth.revision, set(self.auth.sessions)
        response = await self.client.put("/api/authentication/settings", headers=self.admin,
                                         json={"settings": {**deepcopy(self.auth.settings), "login_engine": "unknown"},
                                               "revision": old_revision})
        self.assertEqual(response.status, 400)
        self.assertEqual(self.auth.revision, old_revision)
        self.assertEqual(set(self.auth.sessions), old_sessions)
        self.assertEqual(self.auth.settings["login_engine"], "auto")

    def bind(self, qq="123456789"):
        code = self.store.issue_code("survival", self.identity, "Steve")
        self.store.bind("survival", qq, code)

    def confirmation(self):
        message = self.state["onebot"].send_private.call_args.args[1]
        return re.search(r"/确认登录 ([A-Za-z0-9_-]+)", message)[1]

    async def test_defaults_are_disabled_and_authentication_requires_bridge_token(self):
        await self.enable(enabled_servers=[])
        data = await self.action("join")
        self.assertEqual(data["status"], "disabled")
        for headers in ({}, self.admin):
            response = await self.client.post("/bridge/survival/auth", headers=headers, json=self.payload("join"))
            self.assertEqual(response.status, 401)
        response = await self.client.get("/api/authentication/settings", headers=self.bridge)
        self.assertEqual(response.status, 401)

    async def test_password_login_gate_binding_nonce_and_uuid_link(self):
        self.assertEqual((await self.action("join"))["status"], "pending")
        response = await self.client.post("/bridge/survival/bind-code", headers=self.bridge, json=self.payload("bind"))
        self.assertEqual(response.status, 403)
        self.assertEqual((await self.action("password", password=PASSWORD))["status"], "authenticated")
        response = await self.client.post("/bridge/survival/bind-code", headers=self.bridge, json=self.payload("bind"))
        self.assertEqual(response.status, 200)
        response = await self.client.post("/bridge/survival/bind-code", headers=self.bridge, json=self.payload("bind", nonce=str(uuid.uuid4())))
        self.assertEqual(response.status, 403)
        self.assertEqual((await self.heartbeat())["authentication_results"][0]["status"], "authenticated")
        link = self.store.db.execute("SELECT * FROM account_game_links").fetchone()
        self.assertEqual(link["uuid"], self.identity)
        self.assertNotIn(PASSWORD, json.dumps(self.store.logs()))

    async def test_wrong_password_limits_survive_reconnection(self):
        await self.enable(max_attempts=2); await self.action("join")
        self.assertEqual((await self.action("password", password="Wrong Password"))["status"], "pending")
        self.assertEqual((await self.action("password", password="Wrong Password"))["status"], "denied")
        self.nonce = str(uuid.uuid4()); await self.action("join")
        await self.action("password", status=429, password=PASSWORD)

    async def test_registered_account_rejects_different_game_uuid_and_admin_can_reset(self):
        await self.action("join"); await self.action("password", password=PASSWORD)
        original_identity = self.identity
        self.identity, self.nonce = str(uuid.uuid4()), str(uuid.uuid4())
        await self.action("join"); await self.action("password", status=409, password=PASSWORD)
        response = await self.client.delete("/api/authentication/account-links/" + self.account_id, headers=self.admin)
        self.assertEqual(response.status, 200)
        self.assertFalse(self.auth.allowed("survival", original_identity))
        await self.action("join"); self.assertEqual((await self.action("password", password=PASSWORD))["status"], "authenticated")

    async def test_password_callback_cannot_authorize_reconnected_player(self):
        await self.action("join")
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed(*args):
            entered.set(); await release.wait(); return True
        with patch.object(self.registration.password_work, "run", side_effect=delayed):
            pending = asyncio.create_task(self.action("password", status=409, password=PASSWORD))
            await entered.wait(); self.nonce = str(uuid.uuid4()); await self.action("join"); release.set()
            await pending
        self.assertEqual((await self.heartbeat())["authentication_results"][0]["status"], "pending")

    async def test_qq_confirmation_is_private_owner_scoped_and_single_use(self):
        self.bind(); await self.action("join"); await self.action("qq")
        self.state["onebot"].send_private.assert_awaited_once()
        self.assertEqual(self.state["onebot"].send_private.call_args.args[0], "123456789")
        token = self.confirmation()
        with self.assertRaises(ValueError): self.auth.confirm("987654321", token, True)
        self.assertIn("已确认", self.auth.confirm("123456789", token, True))
        self.assertEqual((await self.heartbeat())["authentication_results"][0]["status"], "authenticated")
        with self.assertRaises(ValueError): self.auth.confirm("123456789", token, True)
        self.assertNotIn(token, json.dumps(self.store.logs()))

    async def test_qq_private_bot_event_works_group_event_cannot_approve(self):
        self.bind(); await self.action("join"); await self.action("qq"); token = self.confirmation()
        event = {"post_type": "message", "message_type": "group", "self_id": 100, "user_id": "123456789",
                 "group_id": "101", "message_id": "group-token", "message": "/确认登录 " + token}
        await self.state["bot"].handle_event(event)
        self.assertEqual((await self.heartbeat())["authentication_results"][0]["status"], "pending")
        event.update(message_type="private", message_id="private-token")
        await self.state["bot"].handle_event(event)
        self.assertEqual((await self.heartbeat())["authentication_results"][0]["status"], "authenticated")
        sent = self.state["onebot"].send_private.await_count
        await self.state["bot"].handle_event(event)
        self.assertEqual(self.state["onebot"].send_private.await_count, sent)

    async def test_qq_denial_disconnect_expiry_and_changed_binding(self):
        self.bind(); await self.action("join"); await self.action("qq"); token = self.confirmation()
        self.assertIn("已拒绝", self.auth.confirm("123456789", token, False))
        self.assertEqual((await self.heartbeat())["authentication_results"][0]["status"], "denied")
        await self.enable(qq_cooldown=15)
        with self.store.db: self.store.db.execute("DELETE FROM registration_limits")
        self.nonce = str(uuid.uuid4()); await self.action("join"); await self.action("qq"); token = self.confirmation()
        self.auth.sessions[("survival", self.identity)]["challenge"]["expires"] = time.time() - 1
        with self.assertRaises(ValueError): self.auth.confirm("123456789", token, True)
        with self.store.db: self.store.db.execute("DELETE FROM registration_limits")
        await self.action("qq"); token = self.confirmation(); self.store.unbind("survival", "123456789")
        with self.assertRaises(ValueError): self.auth.confirm("123456789", token, True)

    async def test_qq_reconnect_invalidates_old_confirmation_and_old_leave(self):
        self.bind(); await self.action("join"); await self.action("qq"); token = self.confirmation()
        old_nonce = self.nonce; self.nonce = str(uuid.uuid4()); await self.action("join")
        with self.assertRaises(ValueError): self.auth.confirm("123456789", token, True)
        await self.action("leave", status=409, nonce=old_nonce)
        self.assertEqual((await self.heartbeat())["authentication_results"][0]["status"], "pending")

    async def test_qq_delivery_failure_offline_and_no_binding_never_release_gate(self):
        await self.action("join"); await self.action("qq", status=403)
        self.bind(); self.state["onebot"].ws.closed = True
        await self.action("qq", status=503); self.state["onebot"].ws.closed = False
        self.state["onebot"].send_private.side_effect = RuntimeError("failure")
        await self.action("qq", status=502)
        self.assertEqual((await self.heartbeat())["authentication_results"][0]["status"], "pending")
        self.assertIsNone(self.auth.sessions[("survival", self.identity)]["challenge"])

    async def test_late_website_name_claim_cannot_take_over_bound_player(self):
        self.bind()
        with self.store.db: self.store.db.execute("UPDATE registration_accounts SET qq=NULL,email='other@example.com'")
        await self.action("join"); await self.action("password", status=409, password=PASSWORD)
        await self.action("qq"); self.auth.confirm("123456789", self.confirmation(), True)
        self.assertEqual((await self.heartbeat())["authentication_results"][0]["status"], "authenticated")
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM account_game_links").fetchone()[0], 0)

    async def test_settings_persist_conflict_write_failure_and_error_fail_closed(self):
        current = self.auth.config_response()
        await self.enable(login_seconds=45)
        response = await self.client.put("/api/authentication/settings", headers=self.admin, json=current)
        self.assertEqual(response.status, 409)
        current = self.auth.config_response(); before = self.auth.path.read_bytes()
        with patch("starbridge.authentication.atomic_json", side_effect=OSError("failure")):
            response = await self.client.put("/api/authentication/settings", headers=self.admin, json={**current, "settings": {**current["settings"], "login_seconds": 60}})
        self.assertEqual(response.status, 500); self.assertEqual(self.auth.path.read_bytes(), before)
        restored = Authentication(self.base, self.state["bot"], self.registration)
        self.assertEqual(restored.settings["login_seconds"], 45)
        self.auth.path.write_text('bad json', encoding='utf-8')
        broken = Authentication(self.base, self.state["bot"], self.registration)
        self.assertTrue(broken.policy("survival")["required"])
        self.assertFalse(broken.policy("survival")["available"])
        self.assertFalse(broken.allowed("survival", self.identity))
        self.assertEqual(self.auth.path.read_text(), 'bad json')

    async def test_expired_login_session_and_backend_restart_do_not_auto_login(self):
        await self.action("join")
        self.auth.sessions[("survival", self.identity)]["expires"] = time.time() - 1
        self.assertEqual((await self.heartbeat())["authentication_results"][0]["status"], "denied")
        self.nonce = str(uuid.uuid4()); await self.action("join"); await self.action("password", password=PASSWORD)
        self.auth.sessions.clear()
        self.assertEqual((await self.heartbeat())["authentication_results"][0]["status"], "missing")
        self.assertEqual((await self.action("join"))["status"], "pending")

    async def test_mail_password_reset_for_old_account_hashes_password_and_revokes_sessions(self):
        await self.action("join"); await self.action("password", password=PASSWORD)
        response = await self.client.post("/api/v1/account/password/request", json={"player": "Steve", "email": "123456789@qq.com"})
        self.assertEqual(response.status, 202); result = await response.json()
        self.assertEqual(self.sent[-1][5], "password")
        new_password = "New Correct Horse 456"
        response = await self.client.post("/api/v1/account/password/verify", json={"challenge_id": result["challenge_id"], "code": self.sent[-1][3], "password": new_password})
        self.assertEqual(response.status, 200, await response.text())
        self.assertFalse(self.auth.sessions)
        digest = self.store.db.execute("SELECT password_hash FROM account_passwords").fetchone()[0]
        self.assertTrue(check_password(new_password, digest)); self.assertFalse(check_password(PASSWORD, digest))
        self.assertNotIn(new_password, json.dumps(self.store.logs()))
        response = await self.client.post("/api/v1/account/password/verify", json={"challenge_id": result["challenge_id"], "code": self.sent[-1][3], "password": new_password})
        self.assertEqual(response.status, 400)

    async def test_password_reset_email_mismatch_and_wrong_code_do_not_change_credentials(self):
        response = await self.client.post("/api/v1/account/password/request", json={"player": "Steve", "email": "other@example.com"})
        self.assertEqual(response.status, 202); self.assertFalse(self.sent)
        response = await self.client.post("/api/v1/account/password/request", json={"player": "Steve", "email": "123456789@qq.com"})
        result = await response.json(); code = self.sent[-1][3]; wrong = "000000" if code != "000000" else "000001"
        for _ in range(5):
            response = await self.client.post("/api/v1/account/password/verify", json={"challenge_id": result["challenge_id"], "code": wrong, "password": "New Password"})
            self.assertEqual(response.status, 400)
        response = await self.client.post("/api/v1/account/password/verify", json={"challenge_id": result["challenge_id"], "code": code, "password": "New Password"})
        self.assertEqual(response.status, 429)
        self.assertEqual(self.store.db.execute("SELECT password_hash FROM account_passwords").fetchone()[0], DIGEST)

    async def test_registration_with_password_and_no_hashes_in_public_or_admin_accounts(self):
        self.registration.settings["enabled"] = True
        response = await self.client.post("/api/v1/registration/request", json={"player": "Alex", "email": "alex@example.com"})
        challenge = await response.json(); self.assertEqual(response.status, 202)
        response = await self.client.post("/api/v1/registration/verify", json={"challenge_id": challenge["challenge_id"], "code": self.sent[-1][3], "password": PASSWORD})
        self.assertEqual(response.status, 201); result = await response.json()
        self.assertTrue(result["account"]["has_password"])
        response = await self.client.get("/api/registration/accounts", headers=self.admin)
        text = await response.text(); self.assertNotIn("pbkdf2", text); self.assertNotIn(PASSWORD, text)
        self.assertNotIn("password_hash", json.dumps(result))

    async def test_authentication_api_cors_and_sensitive_operations_authorization(self):
        for method, url in (("get", "/api/authentication/settings"), ("put", "/api/authentication/settings"),
                            ("get", "/api/authentication/guide"),
                            ("delete", "/api/authentication/account-links/" + self.account_id)):
            response = await getattr(self.client, method)(url)
            self.assertEqual(response.status, 401)
        response = await self.client.get("/api/authentication/guide", headers=self.admin)
        self.assertEqual(response.status, 200)
        self.assertIn("Myrinbot-game-login.md", response.headers["Content-Disposition"])
        guide = await response.text()
        for provider in ("AuthMe", "nLogin", "LoginSecurity", "LibreLogin"):
            self.assertIn(provider, guide)
        response = await self.client.post("/api/v1/account/password/request", headers={"Origin": "https://unknown.example"}, json={"player": "Steve", "email": "123456789@qq.com"})
        self.assertEqual(response.status, 403); self.assertFalse(self.sent)
        response = await self.client.post("/api/v1/account/password/request", data="not json")
        self.assertEqual(response.status, 415)


class PrivateConfirmationWireTests(unittest.IsolatedAsyncioTestCase):
    async def test_onebot_private_segments_and_event_confirm_actual_bridge_connection(self):
        cfg = config(); client = TestClient(TestServer(create_app(cfg)))
        async with client:
            state = client.app[STATE]; auth = state["authentication"]
            await auth.save_settings({**DEFAULTS, "enabled_servers": ["survival"]}, auth.revision)
            identity, nonce = str(uuid.uuid4()), str(uuid.uuid4())
            code = state["store"].issue_code("survival", identity, "Steve"); state["store"].bind("survival", "123456789", code)
            headers = {"Authorization": "Bearer " + cfg["servers"][0]["token"]}
            payload = {"uuid": identity, "nonce": nonce, "player": "Steve", "action": "join"}
            await client.post("/bridge/survival/auth", headers=headers, json=payload)
            ws = await client.ws_connect("/onebot/ws", headers={"Authorization": "Bearer " + cfg["onebot"]["token"], "X-Self-ID": "100"})
            pending = asyncio.create_task(client.post("/bridge/survival/auth", headers=headers, json={**payload, "action": "qq"}))
            request = await ws.receive_json(timeout=3)
            self.assertEqual(request["action"], "send_private_msg"); self.assertEqual(request["params"]["user_id"], 123456789)
            self.assertEqual(request["params"]["message"][0]["type"], "text")
            token = re.search(r"/确认登录 ([A-Za-z0-9_-]+)", request["params"]["message"][0]["data"]["text"])[1]
            await ws.send_json({"status": "ok", "retcode": 0, "echo": request["echo"], "data": {}})
            self.assertEqual((await pending).status, 200)
            await ws.send_json({"post_type": "message", "message_type": "private", "self_id": 100, "user_id": 123456789,
                                "message_id": 55, "message": [{"type": "text", "data": {"text": "/确认登录 " + token}}]})
            confirmation = await ws.receive_json(timeout=3)
            self.assertIn("已确认", confirmation["params"]["message"][0]["data"]["text"])
            await ws.send_json({"status": "ok", "retcode": 0, "echo": confirmation["echo"], "data": {}})
            self.assertTrue(auth.allowed("survival", identity, nonce, "Steve"))
            await ws.close()
