"""Security contracts for bound-QQ native-password recovery."""
import asyncio
from copy import deepcopy
from pathlib import Path
import re
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
import uuid

from aiohttp.test_utils import TestClient, TestServer

from starbridge.app import STATE, create_app
from starbridge.native_passwords import NativePasswords, TARGETS, validate_settings
from test_starbridge import config


QQ = "123456789"
PASSWORD = "Native-Only-Secret-763!"
ACCOUNT = "a" * 64
RECREATED_ACCOUNT = "b" * 64
SETTINGS = {"servers": {"survival": {"platform": "bukkit", "engine": "authme"}}}


class NativePasswordSettingsTests(unittest.TestCase):
    def test_only_explicit_supported_platform_engine_pairs_are_accepted(self):
        self.assertEqual(validate_settings({"servers": {}}), {"servers": {}})
        for platform, engine in TARGETS:
            settings = {"servers": {"survival": {"platform": platform, "engine": engine}}}
            self.assertEqual(validate_settings(settings), settings)
        for value in (None, {}, {"servers": []}, {"servers": {}, "password": PASSWORD},
                      {"servers": {"../other": {"platform": "bukkit", "engine": "authme"}}},
                      {"servers": {"survival": {"platform": "fabric", "engine": "easyauth"}}},
                      {"servers": {"survival": {"platform": "bukkit", "engine": "limboauth"}}},
                      {"servers": {"survival": {"platform": "velocity", "engine": "authme"}}},
                      {"servers": {"survival": {"platform": "bukkit", "engine": "authme", "command": "op Steve"}}}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_settings(value)


class NativePasswordTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.cfg = config(str(self.base / "test.db"))
        self.app = create_app(self.cfg)
        self.state = self.app[STATE]
        self.store = self.state["store"]
        self.bot = self.state["bot"]
        self.recovery = self.state["native_passwords"]
        self.qq = self.state["onebot"]
        self.qq.ws = SimpleNamespace(closed=False, close=AsyncMock())
        self.qq.self_id = "100"
        self.qq.send_private = AsyncMock()
        self.qq.send_group = AsyncMock()
        self.identity, self.instance = str(uuid.uuid4()), str(uuid.uuid4())
        self.server = self.bot.servers["survival"]
        self.recovery.save(SETTINGS, self.recovery.revision)
        self.tick()

    async def asyncTearDown(self):
        await self.state["registration"].close()
        self.store.close()
        self.tmp.cleanup()

    def tick(self, **extra):
        return self.recovery.tick(self.server, {"instance": self.instance, "platform": "bukkit",
                                               "engine": "authme", "results": [], **extra})

    def bind(self, qq=QQ, identity=None, name="Steve", proof=True, account=ACCOUNT):
        identity = identity or self.identity
        code = self.store.issue_code("survival", identity, name)
        if proof:
            self.recovery.record_code("survival", identity, name, code, "bukkit", "authme", account)
            self.recovery.verify_binding(qq, "survival", code)
        else:
            self.store.bind("survival", qq, code)
        return code

    def challenge(self, qq=QQ):
        reply = self.recovery.private_command(qq, "/重置密码", "survival")
        return re.search(r"/确认重置 ([A-Za-z0-9_-]+) 新密码", reply)[1]

    def submit(self, token=None, qq=QQ, password=PASSWORD):
        token = token or self.challenge(qq)
        self.recovery.private_command(qq, "/确认重置", token + " " + password)
        return next(iter(self.recovery.requests))

    def claim(self, jid, **extra):
        return self.recovery.claim("survival", {"id": jid, "instance": self.instance,
                                                "platform": "bukkit", "engine": "authme", **extra})

    def database_text(self):
        return "\n".join(self.store.db.iterdump())

    def test_default_off_persisted_settings_and_revision_conflict(self):
        self.recovery.save({"servers": {}}, self.recovery.revision)
        self.assertEqual(NativePasswords(self.bot).settings, {"servers": {}})
        with self.assertRaises(ValueError):
            self.recovery.save(SETTINGS, "stale")
        self.assertEqual(self.recovery.settings, {"servers": {}})
        with self.assertRaises(ValueError):
            self.recovery.save({"servers": {"missing": SETTINGS["servers"]["survival"]}}, self.recovery.revision)

    def test_unbound_and_legacy_binding_cannot_reset_until_native_proof_is_renewed(self):
        with self.assertRaises(ValueError):
            self.challenge()
        self.bind(proof=False)
        with self.assertRaises(ValueError):
            self.challenge()
        code = self.store.issue_code("survival", self.identity, "Steve")
        self.recovery.record_code("survival", self.identity, "Steve", code, "bukkit", "authme", ACCOUNT)
        with self.assertRaises(ValueError):
            self.challenge()
        original = self.store.binding("survival", QQ)
        self.recovery.verify_binding(QQ, "survival", code)
        renewed = self.store.binding("survival", QQ)
        self.assertEqual(renewed["created"], original["created"])
        self.assertTrue(self.challenge())
        self.assertEqual(self.store.binding("survival", QQ)["uuid"], self.identity)

    async def test_native_qbind_alone_never_grants_a_legacy_attacker_qq_recovery(self):
        self.bind(proof=False)
        code = self.store.issue_code("survival", self.identity, "Steve")
        self.recovery.record_code("survival", self.identity, "Steve", code, "bukkit", "authme", ACCOUNT)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM native_password_proofs").fetchone()[0], 0)
        with self.assertRaises(ValueError):
            self.challenge()
        # A legitimate native owner using a different QQ cannot renew the old
        # binding. Its now-public failed code must not be usable by the old QQ.
        await self.bot.handle_event({"post_type": "message", "message_type": "private", "self_id": "100", "user_id": "987654321",
            "message_id": "native-code-wrong-qq", "message": "/验证绑定 survival " + code})
        self.assertIsNone(self.store.db.execute("SELECT code FROM codes WHERE code=?", (code,)).fetchone())
        self.assertNotIn(code, self.recovery.code_proofs)
        with self.assertRaises(ValueError): self.recovery.verify_binding(QQ, "survival", code)
        with self.assertRaises(ValueError):
            self.challenge()

    def test_recreated_native_account_needs_both_new_birth_proof_and_matching_qq_confirmation(self):
        self.bind()
        jid = self.submit()
        job = self.tick()["jobs"][0]
        self.assertEqual((job["id"], job["account"]), (jid, ACCOUNT))
        code = self.store.issue_code("survival", self.identity, "Steve")
        self.recovery.record_code("survival", self.identity, "Steve", code, "bukkit", "authme", RECREATED_ACCOUNT)
        # A new account birth revokes the previous QQ grant and its in-flight
        # request; it never automatically authorizes the old QQ for the new account.
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM native_password_proofs").fetchone()[0], 0)
        with self.assertRaises(ValueError): self.challenge()
        self.assertEqual(self.claim(jid), {"allowed": False})
        self.recovery.verify_binding(QQ, "survival", code)
        self.assertEqual(self.store.db.execute("SELECT account FROM native_password_proofs").fetchone()[0], RECREATED_ACCOUNT)
        self.store.db.execute("DELETE FROM registration_limits")
        new_id = self.submit()
        self.assertEqual(self.tick()["jobs"][0]["account"], RECREATED_ACCOUNT)
        self.assertEqual(self.claim(new_id), {"allowed": True})

    def test_untrusted_or_missing_native_account_fingerprint_does_not_grant_recovery(self):
        self.bind(proof=False)
        for account in (None, "", "short", "A" * 64, "g" * 64, "a" * 63, "a" * 65):
            code = self.store.issue_code("survival", self.identity, "Steve")
            self.recovery.record_code("survival", self.identity, "Steve", code, "bukkit", "authme", account)
            with self.subTest(account=account):
                self.assertNotIn(code, self.recovery.code_proofs)
                self.assertIsNone(self.recovery.renew("survival", QQ, code))
                with self.assertRaises(ValueError): self.challenge()

    def test_native_proof_cannot_cross_server_uuid_name_or_provider(self):
        self.bind()
        for column, value in (("uuid", str(uuid.uuid4())), ("name", "Alex"),
                              ("platform", "velocity"), ("engine", "librelogin"),
                              ("binding_created", 0)):
            old = self.store.db.execute("SELECT * FROM native_password_proofs").fetchone()[column]
            self.store.db.execute(f"UPDATE native_password_proofs SET {column}=?", (value,))
            with self.subTest(column=column), self.assertRaises(ValueError):
                self.challenge()
            self.store.db.execute(f"UPDATE native_password_proofs SET {column}=?", (old,))
        with self.assertRaises(ValueError):
            self.recovery.private_command(QQ, "/重置密码", "different")

    def test_expired_or_other_server_binding_code_does_not_grant_recovery(self):
        code = self.store.issue_code("survival", self.identity, "Steve")
        self.recovery.record_code("different", self.identity, "Steve", code, "bukkit", "authme", ACCOUNT)
        self.store.bind("survival", QQ, code)
        self.recovery.bound("survival", QQ, code)
        with self.assertRaises(ValueError):
            self.challenge()
        self.store.unbind("survival", QQ)
        code = self.store.issue_code("survival", self.identity, "Steve")
        self.recovery.record_code("survival", self.identity, "Steve", code, "bukkit", "authme", ACCOUNT)
        self.recovery.code_proofs[code]["expires"] = 0
        self.store.bind("survival", QQ, code)
        self.recovery.bound("survival", QQ, code)
        with self.assertRaises(ValueError):
            self.challenge()

    def test_confirm_requires_same_qq_single_use_token_and_safe_password(self):
        self.bind()
        token = self.challenge()
        for qq, password in (("987654321", PASSWORD), (QQ, "short"), (QQ, "has spaces 123"),
                             (QQ, "nonascii密码123"), (QQ, "x" * 65), (QQ, "line\nbreak123")):
            with self.subTest(qq=qq, password=password), self.assertRaises(ValueError):
                self.submit(token, qq, password)
        self.submit(token)
        with self.assertRaises(ValueError):
            self.submit(token)
        self.assertEqual(len(self.recovery.requests), 1)

    def test_expired_challenge_and_unbinding_between_request_and_confirm_are_rejected(self):
        self.bind()
        token = self.challenge()
        next(iter(self.recovery.challenges.values()))["expires"] = 0
        with self.assertRaises(ValueError):
            self.submit(token)
        token = self.challenge()
        self.store.unbind("survival", QQ)
        with self.assertRaises(ValueError):
            self.submit(token)

    def test_one_job_one_claim_and_one_result_no_password_persisted(self):
        self.bind()
        token = self.challenge()
        jid = self.submit(token)
        self.assertNotIn(PASSWORD, self.database_text())
        self.assertNotIn(token, self.database_text())
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0)
        response = self.tick()
        self.assertEqual(len(response["jobs"]), 1)
        job = response["jobs"][0]
        self.assertEqual((job["id"], job["uuid"], job["player"], job["password"]),
                         (jid, self.identity, "Steve", PASSWORD))
        self.assertEqual(job["account"], ACCOUNT)
        self.assertNotIn("password", self.recovery.requests[jid])
        self.assertEqual(self.tick()["jobs"], [])
        self.assertEqual(self.claim(jid), {"allowed": True})
        self.assertEqual(self.claim(jid), {"allowed": False})
        self.tick(results=[{"id": jid, "status": "success"}])
        self.assertNotIn(jid, self.recovery.requests)
        self.assertEqual(self.recovery.notifications.qsize(), 1)
        self.tick(results=[{"id": jid, "status": "success"}])
        self.assertEqual(self.recovery.notifications.qsize(), 1)
        self.assertNotIn(PASSWORD, self.database_text())
        self.assertNotIn(PASSWORD, repr(list(self.recovery.notifications._queue)))
        for file in self.base.glob("test.db*"):
            self.assertNotIn(PASSWORD.encode(), file.read_bytes())

    def test_claim_before_delivery_and_by_wrong_endpoint_never_consumes_request(self):
        self.bind()
        jid = self.submit()
        self.assertEqual(self.claim(jid), {"allowed": False})
        self.tick()
        for extra in ({"instance": str(uuid.uuid4())}, {"platform": "velocity"}, {"engine": "librelogin"}):
            with self.subTest(extra=extra):
                self.assertEqual(self.claim(jid, **extra), {"allowed": False})
        self.assertEqual(self.recovery.claim("different", {"id": jid, "instance": self.instance,
                                                           "platform": "bukkit", "engine": "authme"}), {"allowed": False})
        self.assertEqual(self.claim(jid), {"allowed": True})

    def test_final_claim_rechecks_all_authority_fences(self):
        for mutation in ("unbind", "rebind", "name", "proof", "account_birth", "settings", "token", "groups", "qq_generation", "self_id", "provider", "peer", "server_removed"):
            with self.subTest(mutation=mutation):
                self.recovery.requests.clear()
                self.recovery.challenges.clear()
                self.store.db.execute("DELETE FROM registration_limits")
                self.bot.servers["survival"] = self.server
                self.recovery.settings = deepcopy(SETTINGS)
                self.qq.official.cfg["enabled"] = False
                self.qq.generation = 0
                self.qq.self_id = "100"
                self.server["token"] = self.cfg["servers"][0]["token"]
                self.server["groups"] = ["101"]
                self.recovery.peers.clear()
                self.tick()
                self.store.db.execute("DELETE FROM bindings")
                self.store.db.execute("DELETE FROM native_password_proofs")
                self.bind()
                jid = self.submit()
                self.tick()
                if mutation == "unbind": self.store.unbind("survival", QQ)
                elif mutation == "rebind": self.store.db.execute("UPDATE bindings SET created=created+1")
                elif mutation == "name": self.store.db.execute("UPDATE bindings SET name='Alex'")
                elif mutation == "proof": self.store.db.execute("DELETE FROM native_password_proofs")
                elif mutation == "account_birth": self.store.db.execute("UPDATE native_password_proofs SET account=?", (RECREATED_ACCOUNT,))
                elif mutation == "settings": self.recovery.save({"servers": {}}, self.recovery.revision)
                elif mutation == "token": self.server["token"] = "changed-token"
                elif mutation == "groups": self.server["groups"] = ["other-group"]
                elif mutation == "qq_generation": self.qq.generation += 1
                elif mutation == "self_id": self.qq.self_id = "101"
                elif mutation == "provider": self.qq.official.cfg.update(enabled=True, app_id="123")
                elif mutation == "peer": self.tick(instance=str(uuid.uuid4()))
                elif mutation == "server_removed": self.bot.servers.pop("survival")
                self.assertEqual(self.claim(jid), {"allowed": False})
                self.assertNotIn(jid, self.recovery.requests)

    def test_saving_same_settings_still_revokes_not_started_requests(self):
        self.bind()
        jid = self.submit()
        self.tick()
        self.recovery.save(deepcopy(SETTINGS), self.recovery.revision)
        self.assertEqual(self.claim(jid), {"allowed": False})

    def test_request_expiry_removes_secret_and_no_delivery_replay(self):
        self.bind()
        jid = self.submit()
        request = self.recovery.requests[jid]
        request["expires"] = 0
        self.assertEqual(self.tick()["jobs"], [])
        self.assertNotIn("password", request)
        self.assertNotIn(jid, self.recovery.requests)
        self.assertEqual(self.claim(jid), {"allowed": False})

    def test_expiry_after_delivery_blocks_claim_without_reissuing_credentials(self):
        self.bind()
        jid = self.submit()
        self.assertEqual(len(self.tick()["jobs"]), 1)
        self.recovery.requests[jid]["expires"] = time.time() - 1
        self.assertEqual(self.claim(jid), {"allowed": False})
        self.assertEqual(self.tick()["jobs"], [])
        self.assertNotIn("password", self.recovery.requests[jid])

    def test_claimed_request_timeout_is_uncertain_and_never_replayed(self):
        self.bind()
        jid = self.submit()
        self.tick()
        self.assertEqual(self.claim(jid), {"allowed": True})
        self.recovery.requests[jid]["expires"] = time.time() - 46
        self.assertEqual(self.tick()["jobs"], [])
        self.assertNotIn(jid, self.recovery.requests)
        message = self.recovery.notifications.get_nowait()[-1]
        self.assertIn("不会重复提交", message)
        self.assertNotIn(PASSWORD, message)

    def test_fixed_native_precheck_failure_can_complete_without_claiming_password_write(self):
        self.bind()
        jid = self.submit()
        self.tick()
        self.tick(results=[{"id": jid, "status": "online"}])
        self.assertNotIn(jid, self.recovery.requests)
        self.assertIn("先完全退出游戏", self.recovery.notifications.get_nowait()[-1])
        self.assertEqual(self.claim(jid), {"allowed": False})
        self.assertEqual(self.tick()["jobs"], [])

    def test_stale_or_ambiguous_native_peer_cannot_start_reset(self):
        self.bind()
        self.recovery.peers[("survival", "bukkit", self.instance)]["seen"] = time.time() - 16
        with self.assertRaises(ValueError): self.challenge()
        self.tick()
        self.tick(instance=str(uuid.uuid4()))
        with self.assertRaises(ValueError): self.challenge()

    def test_wrong_result_peer_or_early_result_cannot_report_success(self):
        self.bind()
        jid = self.submit()
        self.tick(results=[{"id": jid, "status": "success"}])
        self.assertIn(jid, self.recovery.requests)
        self.assertEqual(self.recovery.notifications.qsize(), 0)
        self.assertEqual(self.claim(jid), {"allowed": True})
        other = {**self.server, "id": "other"}
        self.recovery.tick(other, {"instance": self.instance, "platform": "bukkit", "engine": "authme",
                                   "results": [{"id": jid, "status": "success"}]})
        self.assertIn(jid, self.recovery.requests)
        self.tick(results=[{"id": jid, "status": "identity_mismatch"}])
        self.assertNotIn(jid, self.recovery.requests)
        self.assertIn("原账号身份", self.recovery.notifications.get_nowait()[-1])

    def test_recovery_proof_persists_but_inflight_credential_does_not_survive_restart(self):
        self.bind()
        self.submit()
        restored = NativePasswords(self.bot)
        restored.tick(self.server, {"instance": self.instance, "platform": "bukkit", "engine": "authme"})
        self.assertEqual(restored.requests, {})
        self.assertTrue(restored.private_command(QQ, "/重置密码", "survival"))
        self.assertNotIn(PASSWORD, self.database_text())

    async def test_group_password_commands_are_never_relayed_or_echoed(self):
        self.bot.snapshots["survival"] = {"last_seen": time.time()}
        commands = ("/确认重置", "确认重置", "/重置密码", "重置密码",
                    "/确认重置\ttoken", "确认重置\u3000token", "/重置密码\ttoken", "重置密码\u3000token")
        for command in commands:
            event = {"post_type": "message", "message_type": "group", "self_id": "100", "user_id": QQ,
                     "group_id": "101", "message_id": str(uuid.uuid4()), "message": command + " token " + PASSWORD}
            await self.bot.handle_event(event)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0)
        self.assertEqual(self.qq.send_group.await_count, len(commands))
        self.assertNotIn(PASSWORD, repr(self.qq.send_group.await_args_list))
        self.assertNotIn(PASSWORD, self.database_text())

    async def test_group_binding_code_never_grants_reset_and_cannot_be_replayed_in_private(self):
        code = self.store.issue_code("survival", self.identity, "Steve")
        self.recovery.record_code("survival", self.identity, "Steve", code, "bukkit", "authme", ACCOUNT)
        await self.bot.handle_event({"post_type": "message", "message_type": "group", "self_id": "100", "user_id": QQ,
            "group_id": "101", "message_id": "native-code-posted-publicly", "message": "绑定 " + code})
        self.assertIsNotNone(self.store.binding("survival", QQ))
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM native_password_proofs").fetchone()[0], 0)
        self.assertNotIn(code, self.recovery.code_proofs)
        with self.assertRaises(ValueError): self.recovery.verify_binding(QQ, "survival", code)
        with self.assertRaises(ValueError): self.challenge()
        # Existing chat bindings also need a fresh private proof; publicly retrying
        # the old group command must not silently renew reset privileges.
        code = self.store.issue_code("survival", self.identity, "Steve")
        self.recovery.record_code("survival", self.identity, "Steve", code, "bukkit", "authme", ACCOUNT)
        await self.bot.handle_event({"post_type": "message", "message_type": "group", "self_id": "100", "user_id": QQ,
            "group_id": "101", "message_id": "native-code-public-existing-binding", "message": "绑定 " + code})
        self.assertNotIn(code, self.recovery.code_proofs)
        with self.assertRaises(ValueError): self.recovery.verify_binding(QQ, "survival", code)
        with self.assertRaises(ValueError): self.challenge()

    async def test_private_verification_command_posted_in_group_burns_the_exposed_code(self):
        self.bind(proof=False)
        code = self.store.issue_code("survival", self.identity, "Steve")
        self.recovery.record_code("survival", self.identity, "Steve", code, "bukkit", "authme", ACCOUNT)
        await self.bot.handle_event({"post_type": "message", "message_type": "group", "self_id": "100", "user_id": QQ,
            "group_id": "101", "message_id": "native-private-code-posted-in-group", "message": "/验证绑定 survival " + code})
        self.assertNotIn(code, self.recovery.code_proofs)
        self.assertIsNone(self.store.db.execute("SELECT code FROM codes WHERE code=?", (code,)).fetchone())
        with self.assertRaises(ValueError): self.recovery.verify_binding(QQ, "survival", code)
        self.assertNotIn(code, repr(self.qq.send_group.await_args_list))
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0)

    async def test_malformed_public_binding_commands_burn_receipts_without_forwarding(self):
        self.bind(proof=False)
        for index, template in enumerate(("/验证绑定\u200bsurvival{code}", "/验证绑定\tsurvival\t{code}", "绑定\u200b{code}", "/绑定 {code}")):
            code = self.store.issue_code("survival", self.identity, "Steve")
            self.recovery.record_code("survival", self.identity, "Steve", code, "bukkit", "authme", ACCOUNT)
            await self.bot.handle_event({"post_type": "message", "message_type": "group", "self_id": "100", "user_id": QQ,
                "group_id": "101", "message_id": "malformed-public-proof-" + str(index), "message": template.format(code=code)})
            self.assertNotIn(code, self.recovery.code_proofs)
            self.assertIsNone(self.store.db.execute("SELECT code FROM codes WHERE code=?", (code,)).fetchone())
            with self.assertRaises(ValueError): self.recovery.verify_binding(QQ, "survival", code)
            self.assertNotIn(code, repr(self.qq.send_group.await_args_list))
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0)

    async def test_private_confirmation_dedupes_message_and_never_echoes_password(self):
        self.bind()
        token = self.challenge()
        event = {"post_type": "message", "message_type": "private", "self_id": "100", "user_id": QQ,
                 "message_id": "reset-confirm-once", "message": "/确认重置 " + token + " " + PASSWORD}
        await self.bot.handle_event(event)
        await self.bot.handle_event(event)
        self.assertEqual(len(self.recovery.requests), 1)
        self.assertEqual(self.qq.send_private.await_count, 1)
        self.assertNotIn(PASSWORD, repr(self.qq.send_private.await_args_list))
        self.assertNotIn(PASSWORD, self.database_text())

    async def test_official_private_identity_cannot_take_over_group_or_numeric_binding(self):
        self.bind()
        self.qq.official.cfg.update(enabled=True, app_id="123", allow_active=False)
        for user in (QQ, "qug:123:member", "qup:123:member"):
            with self.subTest(user=user), self.assertRaises(ValueError):
                self.recovery.private_command(user, "/重置密码", "survival")
        event = {"post_type": "message", "message_type": "private", "self_id": self.qq.self_id,
                 "user_id": "qup:123:member", "message_id": "official-reset", "message": "/重置密码 survival"}
        await self.bot.handle_event(event)
        self.assertFalse(self.recovery.requests)
        self.assertIn("官机", self.qq.send_private.await_args.args[1])

    async def test_result_notification_does_not_cross_changed_qq_route(self):
        self.bind()
        jid = self.submit()
        self.tick()
        self.assertEqual(self.claim(jid), {"allowed": True})
        self.tick(results=[{"id": jid, "status": "success"}])
        self.qq.generation += 1
        worker = asyncio.create_task(self.recovery.worker())
        try:
            await asyncio.wait_for(self.recovery.notifications.join(), 2)
            self.qq.send_private.assert_not_awaited()
        finally:
            worker.cancel()
            with self.assertRaises(asyncio.CancelledError): await worker

    async def test_delivery_failure_logs_no_transport_exception_or_password_and_never_requeues(self):
        self.bind()
        jid = self.submit()
        self.tick()
        self.assertEqual(self.claim(jid), {"allowed": True})
        self.tick(results=[{"id": jid, "status": "success"}])
        self.qq.send_private.side_effect = RuntimeError(PASSWORD)
        worker = asyncio.create_task(self.recovery.worker())
        try:
            await asyncio.wait_for(self.recovery.notifications.join(), 2)
            self.assertEqual(self.qq.send_private.await_count, 1)
            self.assertFalse(self.recovery.requests)
            self.assertEqual(self.tick()["jobs"], [])
            self.assertNotIn(PASSWORD, self.database_text())
            self.assertTrue(any("投递失败" in row["detail"] for row in self.store.logs()))
        finally:
            worker.cancel()
            with self.assertRaises(asyncio.CancelledError): await worker


class NativePasswordApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = config(str(Path(self.tmp.name) / "test.db"))
        self.client = TestClient(TestServer(create_app(self.cfg)))
        await self.client.start_server()
        self.state = self.client.app[STATE]
        self.admin = {"Authorization": "Bearer " + self.cfg["app"]["admin_token"]}
        self.bridge = {"Authorization": "Bearer " + self.cfg["servers"][0]["token"]}
        self.instance = str(uuid.uuid4())

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    async def test_settings_and_native_transport_require_distinct_authorities(self):
        for method, path, payload in (("get", "/api/native-passwords/settings", None),
                                      ("put", "/api/native-passwords/settings", {}),
                                      ("post", "/bridge/survival/password-reset/tick", {}),
                                      ("post", "/bridge/survival/password-reset/claim", {})):
            response = await getattr(self.client, method)(path, json=payload)
            self.assertEqual(response.status, 401)
        response = await self.client.get("/api/native-passwords/settings", headers=self.bridge)
        self.assertEqual(response.status, 401)
        response = await self.client.post("/bridge/survival/password-reset/tick", headers=self.admin, json={})
        self.assertEqual(response.status, 401)
        response = await self.client.get("/api/native-passwords/settings", headers=self.admin)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        current = await response.json()
        self.assertEqual(current["settings"], {"servers": {}})
        response = await self.client.put("/api/native-passwords/settings", headers=self.admin,
                                         json={"settings": SETTINGS, "revision": current["revision"]})
        self.assertEqual(response.status, 200, await response.text())
        response = await self.client.put("/api/native-passwords/settings", headers=self.admin,
                                         json={"settings": {"servers": {}}, "revision": current["revision"]})
        self.assertEqual(response.status, 409)

    async def test_bind_code_extras_grant_proof_only_for_recognized_native_engine(self):
        qq = self.state["onebot"]
        qq.ws = SimpleNamespace(closed=False, close=AsyncMock())
        qq.self_id = "100"
        qq.send_private = AsyncMock()
        qq.send_group = AsyncMock()
        identity = str(uuid.uuid4())
        for engine in ("other", "authme"):
            response = await self.client.post("/bridge/survival/bind-code", headers=self.bridge,
                json={"uuid": identity, "player": "Steve", "password_reset_platform": "bukkit", "password_reset_engine": engine,
                      "password_reset_account": ACCOUNT})
            self.assertEqual(response.status, 200, await response.text())
            data = await response.json()
            self.assertNotIn("password_reset_verified", data)
            code = data["code"]
            self.assertEqual(code in self.state["native_passwords"].code_proofs, engine == "authme")
        self.state["store"].bind("survival", QQ, code)
        created = self.state["store"].binding("survival", QQ)["created"]
        response = await self.client.post("/bridge/survival/bind-code", headers=self.bridge,
            json={"uuid": identity, "player": "Steve", "password_reset_platform": "bukkit", "password_reset_engine": "authme",
                  "password_reset_account": ACCOUNT})
        self.assertEqual(response.status, 200, await response.text())
        data = await response.json()
        self.assertNotIn("password_reset_verified", data)
        self.assertEqual(self.state["store"].db.execute("SELECT COUNT(*) FROM native_password_proofs").fetchone()[0], 0)
        await self.state["bot"].handle_event({"post_type": "message", "message_type": "private", "self_id": "100", "user_id": QQ,
            "message_id": "native-existing-qq-renew", "message": "/验证绑定 survival " + data["code"]})
        self.assertEqual(self.state["store"].db.execute("SELECT COUNT(*) FROM native_password_proofs").fetchone()[0], 1)
        self.assertEqual(self.state["store"].binding("survival", QQ)["created"], created)

    async def test_binding_private_confirmation_native_claim_and_result_work_end_to_end(self):
        recovery, bot, qq = self.state["native_passwords"], self.state["bot"], self.state["onebot"]
        qq.ws = SimpleNamespace(closed=False, close=AsyncMock())
        qq.self_id = "100"
        qq.send_private = AsyncMock()
        qq.send_group = AsyncMock()
        response = await self.client.put("/api/native-passwords/settings", headers=self.admin,
            json={"settings": SETTINGS, "revision": recovery.revision})
        self.assertEqual(response.status, 200, await response.text())
        native_tick = {"instance": self.instance, "platform": "bukkit", "engine": "authme", "results": []}
        response = await self.client.post("/bridge/survival/password-reset/tick", headers=self.bridge, json=native_tick)
        self.assertEqual(response.status, 200, await response.text())
        identity = str(uuid.uuid4())
        response = await self.client.post("/bridge/survival/bind-code", headers=self.bridge,
            json={"uuid": identity, "player": "Steve", "password_reset_platform": "bukkit", "password_reset_engine": "authme",
                  "password_reset_account": ACCOUNT})
        self.assertEqual(response.status, 200, await response.text())
        code = (await response.json())["code"]
        await bot.handle_event({"post_type": "message", "message_type": "private", "self_id": "100", "user_id": QQ,
                               "message_id": "native-proof-bind", "message": "/验证绑定 survival " + code})
        event = {"post_type": "message", "message_type": "private", "self_id": "100", "user_id": QQ,
                 "message_id": "native-request", "message": "/重置密码 survival"}
        await bot.handle_event(event)
        token = re.search(r"/确认重置 ([A-Za-z0-9_-]+) 新密码", qq.send_private.await_args.args[1])[1]
        event.update(message_id="native-confirm", message="/确认重置 " + token + " " + PASSWORD)
        await bot.handle_event(event)
        response = await self.client.post("/bridge/survival/password-reset/tick", headers=self.bridge, json=native_tick)
        jobs = (await response.json())["jobs"]
        self.assertEqual(len(jobs), 1)
        self.assertEqual((jobs[0]["uuid"], jobs[0]["password"], jobs[0]["account"]), (identity, PASSWORD, ACCOUNT))
        claim = {"id": jobs[0]["id"], "instance": self.instance, "platform": "bukkit", "engine": "authme"}
        response = await self.client.post("/bridge/survival/password-reset/claim", headers=self.bridge, json=claim)
        self.assertEqual((await response.json())["allowed"], True)
        native_tick["results"] = [{"id": jobs[0]["id"], "status": "success"}]
        response = await self.client.post("/bridge/survival/password-reset/tick", headers=self.bridge, json=native_tick)
        self.assertEqual(response.status, 200, await response.text())
        await asyncio.wait_for(recovery.notifications.join(), 2)
        self.assertIn("密码已由原登录插件更新", qq.send_private.await_args.args[1])
        self.assertNotIn(PASSWORD, repr(qq.send_private.await_args_list))
        self.assertNotIn(PASSWORD, repr(qq.send_group.await_args_list))
        self.assertNotIn(PASSWORD, "\n".join(self.state["store"].db.iterdump()))
        response = await self.client.post("/bridge/survival/password-reset/claim", headers=self.bridge, json=claim)
        self.assertEqual((await response.json())["allowed"], False)

    async def test_tick_rejects_raw_exception_or_extra_secret_fields(self):
        valid = {"instance": self.instance, "platform": "bukkit", "engine": "authme", "results": []}
        malformed = ({**valid, "password": PASSWORD},
                     {**valid, "results": [{"id": str(uuid.uuid4()), "status": "success", "detail": PASSWORD}]},
                     {**valid, "results": [{"id": str(uuid.uuid4()), "status": PASSWORD}]},
                     {**valid, "instance": "invalid"}, {**valid, "engine": "limboauth"})
        for payload in malformed:
            response = await self.client.post("/bridge/survival/password-reset/tick", headers=self.bridge, json=payload)
            self.assertEqual(response.status, 400, await response.text())
            self.assertNotIn(PASSWORD, await response.text())
        response = await self.client.post("/bridge/survival/password-reset/tick", headers=self.bridge, json=valid)
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual((await response.json())["jobs"], [])
