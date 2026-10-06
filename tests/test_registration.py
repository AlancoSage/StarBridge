import asyncio
from copy import deepcopy
import json
from pathlib import Path
import smtplib
import tempfile
import threading
import time
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer

from starbridge.app import STATE, create_app
from starbridge.registration import DEFAULTS, Registration, RegistrationError, send_verification, validate_settings
from test_starbridge import config


class RegistrationSettingsTests(unittest.TestCase):
    def test_invalid_settings(self):
        for changes in ({"enabled": True}, {"smtp_security": "plain"}, {"smtp_port": True},
                        {"code_minutes": 0}, {"smtp_from": "x\r\nBcc: evil"}, {"allowed_origins": ["*"]},
                        {"allowed_origins": ["https://example.com/path"]}, {"smtp_password": "secret"},
                        {"api_token": "short"}, {"website_url": "javascript:alert(1)"}, {"unknown": True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_settings({**deepcopy(DEFAULTS), **changes})
        value = validate_settings({**deepcopy(DEFAULTS), "allowed_origins": ["https://example.com/"]})
        self.assertEqual(value["allowed_origins"], ["https://example.com"])


class MailTransportTests(unittest.TestCase):
    def test_ssl_message_and_certificate_validation(self):
        settings = {**DEFAULTS, "smtp_host": "smtp.example", "smtp_from": "sender@example.com", "smtp_username": "user", "smtp_password": "secret"}
        with patch("starbridge.registration.smtplib.SMTP_SSL") as constructor:
            client = constructor.return_value
            client.send_message.return_value = {}
            send_verification(settings, "person@example.com", "Steve", "000007", "ticket-" * 5, "web")
            self.assertEqual(constructor.call_args.kwargs["timeout"], 10)
            self.assertTrue(constructor.call_args.kwargs["context"].check_hostname)
            client.login.assert_called_once_with("user", "secret")
            message = client.send_message.call_args.args[0]
            self.assertIn("000007", message.get_content())
            self.assertIn("申请编号", message.get_content())
            self.assertNotIn("secret", message.get_content())

    def test_starttls_before_login_and_group_instructions(self):
        settings = {**DEFAULTS, "smtp_host": "smtp.example", "smtp_port": 587, "smtp_security": "starttls", "smtp_from": "sender@example.com", "smtp_username": "user", "smtp_password": "secret"}
        with patch("starbridge.registration.smtplib.SMTP") as constructor:
            client = constructor.return_value
            client.send_message.return_value = {}
            send_verification(settings, "123456789@qq.com", "Steve", "000007", "ticket-" * 5, "group")
            self.assertEqual([call[0] for call in client.method_calls][:4], ["ehlo", "starttls", "ehlo", "login"])
            self.assertIn("/注册 000007", client.send_message.call_args.args[0].get_content())

    def test_rejected_recipient_is_not_success(self):
        with patch("starbridge.registration.smtplib.SMTP_SSL") as constructor:
            constructor.return_value.send_message.return_value = {"person@example.com": (550, "refused")}
            with self.assertRaises(smtplib.SMTPException):
                send_verification({**DEFAULTS, "smtp_host": "smtp.example", "smtp_from": "sender@example.com"}, "person@example.com", "Steve", "000007", "ticket-" * 5, "web")


class RegistrationApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.base = Path(self.tmp.name)
        self.cfg = config(str(self.base / "test.db"))
        self.client = TestClient(TestServer(create_app(self.cfg)))
        await self.client.start_server()
        self.state = self.client.app[STATE]; self.service = self.state["registration"]
        self.headers = {"Authorization": "Bearer " + self.cfg["app"]["admin_token"]}
        self.sent = []
        self.mail_patch = patch("starbridge.registration.send_verification", side_effect=lambda *args: self.sent.append(args))
        self.mail_patch.start()
        self.state["onebot"].send_group = AsyncMock()

    async def asyncTearDown(self):
        await self.client.close(); self.mail_patch.stop(); self.tmp.cleanup()

    async def settings(self):
        response = await self.client.get("/api/registration/settings", headers=self.headers)
        self.assertEqual(response.status, 200)
        return await response.json()

    async def enable(self, **changes):
        value = await self.settings()
        value["settings"].update(enabled=True, smtp_host="smtp.test.example", smtp_from="sender@example.com")
        value["settings"].update(changes)
        response = await self.client.put("/api/registration/settings", headers=self.headers, json=value)
        self.assertEqual(response.status, 200, await response.text())
        return await response.json()

    async def apply(self, player="Steve", email="123456789@qq.com"):
        response = await self.client.post("/api/v1/registration/request", json={"player": player, "email": email})
        self.assertEqual(response.status, 202, await response.text())
        return await response.json()

    def code(self):
        return self.sent[-1][3]

    async def verify(self, challenge_id, code=None):
        return await self.client.post("/api/v1/registration/verify", json={"challenge_id": challenge_id, "code": code or self.code()})

    async def test_defaults_disabled_and_no_secret_in_public_info(self):
        response = await self.client.get("/api/v1/registration/info")
        data = await response.json()
        self.assertFalse(data["enabled"]); self.assertNotIn("smtp_password", data); self.assertNotIn("api_token", data)
        response = await self.client.post("/api/v1/registration/request", json={"player": "Steve", "email": "x@example.com"})
        self.assertEqual(response.status, 503); self.assertFalse(self.sent)

    async def test_apply_verify_account_token_and_one_time_code(self):
        await self.enable(); challenge = await self.apply()
        self.assertNotIn("code", challenge)
        row = self.service.store.db.execute("SELECT * FROM registration_challenges").fetchone()
        self.assertEqual(len(row["code_hash"]), 64); self.assertNotEqual(row["code_hash"], self.code())
        response = await self.verify(challenge["challenge_id"])
        self.assertEqual(response.status, 201); result = await response.json()
        self.assertEqual(result["account"]["qq"], "123456789")
        response = await self.client.get("/api/v1/account", headers={"Authorization": "Bearer " + result["access_token"]})
        self.assertEqual((await response.json())["account"], result["account"])
        self.assertEqual((await self.verify(challenge["challenge_id"])).status, 409)
        response = await self.client.get("/api/registration/accounts", headers=self.headers)
        self.assertEqual((await response.json())["total"], 1)
        session = self.service.store.db.execute("SELECT * FROM registration_sessions").fetchone()
        self.assertNotEqual(session["token_hash"], result["access_token"])

    async def test_email_failure_rolls_back_pending_and_creates_no_account(self):
        await self.enable()
        with patch("starbridge.registration.send_verification", side_effect=smtplib.SMTPException("secret provider message")):
            response = await self.client.post("/api/v1/registration/request", json={"player": "Steve", "email": "x@example.com"})
        self.assertEqual(response.status, 502); self.assertNotIn("secret provider message", await response.text())
        self.assertEqual(self.service.store.db.execute("SELECT count(*) FROM registration_challenges").fetchone()[0], 0)
        self.assertEqual(self.service.list_accounts()["total"], 0)

    async def test_attempt_lock_and_expiration(self):
        await self.enable(); challenge = await self.apply()
        incorrect = "111111" if self.code() != "111111" else "222222"
        for _ in range(5):
            self.assertEqual((await self.verify(challenge["challenge_id"], incorrect)).status, 400)
        self.assertEqual((await self.verify(challenge["challenge_id"])).status, 429)
        with self.service.store.db:
            self.service.store.db.execute("UPDATE registration_challenges SET expires=?", (time.time() - 1,))
        self.assertEqual((await self.verify(challenge["challenge_id"])).status, 410)

    async def test_resend_requires_ticket_and_replaces_old_code(self):
        await self.enable(); challenge = await self.apply(); old_code = self.code()
        response = await self.client.post("/api/v1/registration/resend", json={"challenge_id": challenge["challenge_id"]})
        self.assertEqual(response.status, 429)
        with self.service.store.db:
            self.service.store.db.execute("UPDATE registration_limits SET time=time-61")
        response = await self.client.post("/api/v1/registration/resend", json={"challenge_id": challenge["challenge_id"]})
        self.assertEqual(response.status, 202); replacement = await response.json()
        self.assertNotEqual(replacement["challenge_id"], challenge["challenge_id"])
        self.assertEqual((await self.verify(challenge["challenge_id"], old_code)).status, 404)
        self.assertEqual((await self.verify(replacement["challenge_id"])).status, 201)

    async def test_case_insensitive_names_and_no_pending_takeover(self):
        await self.enable(); await self.apply()
        response = await self.client.post("/api/v1/registration/request", json={"player": "sTEVE", "email": "other@example.com"})
        self.assertEqual(response.status, 409); self.assertEqual(len(self.sent), 1)

    async def test_group_format_identity_scope_and_success(self):
        await self.enable(); bot = self.state["bot"]
        async def message(text, user="123456789", group="101"):
            await bot.handle_event({"post_type": "message", "message_type": "group", "self_id": 100,
                                    "user_id": user, "group_id": group, "message_id": time.time_ns(), "message": text})
        await message("/申请")
        self.assertIn("格式错误", self.state["onebot"].send_group.call_args.args[1])
        await message("/申请 Steve 999999999")
        self.assertIn("本人", self.state["onebot"].send_group.call_args.args[1]); self.assertFalse(self.sent)
        await message("/申请 Steve 123456789")
        self.assertIn("验证码已发送", self.state["onebot"].send_group.call_args.args[1])
        self.assertNotIn(self.code(), self.state["onebot"].send_group.call_args.args[1])
        await message("/注册 " + self.code(), user="999999999")
        self.assertIn("还没有注册申请", self.state["onebot"].send_group.call_args.args[1])
        await message("/注册 " + self.code())
        self.assertIn("注册成功", self.state["onebot"].send_group.call_args.args[1])
        self.assertEqual(self.service.list_accounts()["total"], 1)

    async def test_public_cannot_confirm_group_challenge(self):
        await self.enable()
        challenge = await self.service.request_code("Steve", "123456789@qq.com", "group", "survival:101:123456789")
        self.assertEqual((await self.verify(challenge["challenge_id"])).status, 404)
        with self.assertRaises(RegistrationError):
            self.service.verify(challenge["challenge_id"], self.code(), "group", "survival:999:123456789")

    async def test_cors_allowlist_preflight_and_failure_headers(self):
        await self.enable(allowed_origins=["https://website.example"])
        response = await self.client.options("/api/v1/registration/request", headers={"Origin": "https://website.example"})
        self.assertEqual(response.status, 204); self.assertEqual(response.headers["Access-Control-Allow-Origin"], "https://website.example")
        response = await self.client.get("/api/v1/registration/info", headers={"Origin": "https://evil.example"})
        self.assertEqual(response.status, 403); self.assertNotIn("Access-Control-Allow-Origin", response.headers)
        response = await self.client.post("/api/v1/registration/request", headers={"Origin": "https://website.example"}, json={"player": "x", "email": "bad"})
        self.assertEqual(response.status, 400); self.assertIn("Access-Control-Allow-Origin", response.headers)

    async def test_separate_api_key_only_reads_accounts(self):
        await self.enable(api_token="website-" + "z" * 40)
        challenge = await self.apply(); result = await (await self.verify(challenge["challenge_id"])).json()
        url = "/api/v1/accounts/" + result["account"]["id"]
        self.assertEqual((await self.client.get(url, headers=self.headers)).status, 401)
        key = {"Authorization": "Bearer website-" + "z" * 40}
        response = await self.client.get(url, headers=key)
        self.assertEqual((await response.json())["account"], result["account"])
        self.assertEqual((await self.client.get("/api/registration/settings", headers=key)).status, 401)
        await self.enable(api_token="replacement-" + "q" * 40)
        self.assertEqual((await self.client.get(url, headers=key)).status, 401)

    async def test_admin_auth_revision_write_failure_and_token_reuse(self):
        self.assertEqual((await self.client.get("/api/registration/settings")).status, 401)
        initial = await self.settings(); await self.enable()
        response = await self.client.put("/api/registration/settings", headers=self.headers, json=initial)
        self.assertEqual(response.status, 409)
        current = await self.settings()
        current["settings"]["api_token"] = self.cfg["app"]["admin_token"]
        response = await self.client.put("/api/registration/settings", headers=self.headers, json=current)
        self.assertEqual(response.status, 400)
        current = await self.settings(); current["settings"]["site_name"] = "不会写入"
        with patch("starbridge.registration.atomic_json", side_effect=OSError("disk")):
            response = await self.client.put("/api/registration/settings", headers=self.headers, json=current)
        self.assertEqual(response.status, 500); self.assertNotEqual(self.service.settings["site_name"], "不会写入")

    async def test_codes_and_accounts_survive_restart_limits_persist(self):
        await self.enable(); challenge = await self.apply()
        replacement = Registration(self.base, self.state["store"])
        self.assertTrue(replacement.settings["enabled"])
        with self.assertRaises(RegistrationError):
            await replacement.request_code("Alex", "123456789@qq.com")
        result = replacement.verify(challenge["challenge_id"], self.code())
        self.assertEqual(result["account"]["player"], "Steve")

    async def test_settings_change_during_mail_does_not_enable_stale_code(self):
        await self.enable(); started = threading.Event(); finish = threading.Event()
        def slow_mail(*args):
            self.sent.append(args); started.set(); finish.wait(3)
        with patch("starbridge.registration.send_verification", side_effect=slow_mail):
            task = asyncio.create_task(self.service.request_code("Steve", "x@example.com"))
            try:
                for _ in range(50):
                    if started.is_set(): break
                    await asyncio.sleep(.01)
                self.assertTrue(started.is_set())
                await self.enable(site_name="修改后的社区")
            finally:
                finish.set()
            with self.assertRaises(RegistrationError) as result:
                await task
            self.assertEqual(result.exception.code, "settings_changed")
        self.assertEqual(self.service.store.db.execute("SELECT count(*) FROM registration_challenges").fetchone()[0], 0)

    async def test_no_longer_than_two_smtp_threads(self):
        await self.enable(); started = []; finish = threading.Event()
        def slow_mail(*args):
            started.append(args); finish.wait(3)
        with patch("starbridge.registration.send_verification", side_effect=slow_mail):
            tasks = [asyncio.create_task(self.service.request_code("User" + str(i), f"u{i}@example.com", remote=str(i))) for i in range(3)]
            try:
                await asyncio.sleep(.12)
                self.assertEqual(len(started), 2)
            finally:
                finish.set()
            await asyncio.gather(*tasks)
            self.assertEqual(len(started), 3)

    async def test_cancelled_request_releases_no_early_smtp_slot(self):
        await self.enable(); started = []; finish = threading.Event()
        def slow_mail(*args):
            started.append(args); finish.wait(3)
        with patch("starbridge.registration.send_verification", side_effect=slow_mail):
            first = asyncio.create_task(self.service.request_code("User0", "u0@example.com", remote="0"))
            for _ in range(50):
                if started: break
                await asyncio.sleep(.01)
            first.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await first
            rest = [asyncio.create_task(self.service.request_code("User" + str(i), f"u{i}@example.com", remote=str(i))) for i in (1, 2)]
            try:
                await asyncio.sleep(.1)
                self.assertEqual(len(started), 2)
            finally:
                finish.set()
            await asyncio.gather(*rest)
        self.assertIsNone(self.service.store.db.execute("SELECT 1 FROM registration_challenges WHERE email='u0@example.com'").fetchone())

    async def test_invalid_input_content_type_and_invalid_tokens(self):
        await self.enable()
        for value in ({"player": "a", "email": "bad"}, {"player": "Valid", "email": "x@example.com", "qq": "999999"}):
            response = await self.client.post("/api/v1/registration/request", json=value)
            self.assertEqual(response.status, 400)
        response = await self.client.post("/api/v1/registration/request", data="not json")
        self.assertEqual(response.status, 415)
        self.assertEqual((await self.client.get("/api/v1/account")).status, 401)
        self.assertEqual((await self.client.get("/api/v1/account", headers=self.headers)).status, 401)

    async def test_sessions_expire_and_no_passwords_or_secrets_in_logs(self):
        await self.enable(smtp_password="private-password", smtp_username="sender")
        challenge = await self.apply(); result = await (await self.verify(challenge["challenge_id"])).json()
        text = json.dumps(self.state["store"].logs())
        self.assertNotIn(self.code(), text); self.assertNotIn(result["access_token"], text); self.assertNotIn("private-password", text)
        with self.service.store.db:
            self.service.store.db.execute("UPDATE registration_sessions SET expires=?", (time.time() - 1,))
        response = await self.client.get("/api/v1/account", headers={"Authorization": "Bearer " + result["access_token"]})
        self.assertEqual(response.status, 401)

    async def test_pages_downloads_and_account_search(self):
        for path in ("/register", "/register.js", "/registration-panel.js"):
            self.assertEqual((await self.client.get(path)).status, 200)
        for kind in ("guide", "example"):
            response = await self.client.get("/api/registration/" + kind, headers=self.headers)
            self.assertEqual(response.status, 200); self.assertIn("attachment", response.headers["Content-Disposition"])
        await self.enable(); challenge = await self.apply(); await self.verify(challenge["challenge_id"])
        response = await self.client.get("/api/registration/accounts?q=steve", headers=self.headers)
        self.assertEqual((await response.json())["total"], 1)
        response = await self.client.get("/api/registration/accounts?q=%", headers=self.headers)
        self.assertEqual((await response.json())["total"], 0)

    async def test_corrupt_settings_fail_closed_without_overwrite(self):
        path = self.base / "data/registration-settings.json"
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text("broken", encoding="utf-8")
        service = Registration(self.base, self.state["store"])
        self.assertFalse(service.settings["enabled"]); self.assertTrue(service.error)
        with self.assertRaises(RegistrationError):
            await service.save_settings(DEFAULTS, service.revision)
        self.assertEqual(path.read_text(encoding="utf-8"), "broken")
