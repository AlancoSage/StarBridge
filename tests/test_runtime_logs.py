"""Isolated runtime-console capture, privacy, cursor and access checks."""
from copy import deepcopy
import json
import logging
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from urllib.parse import quote

from aiohttp.test_utils import TestClient, TestServer

from starbridge.app import STATE, create_app
from starbridge.runtime_logs import CAPACITY, MAX_MESSAGE, REDACTED, RuntimeLogs
from starbridge.storage import Store
from test_starbridge import config


class RuntimeLogTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.state = {"config": config(), "store": self.store}
        self.hub = RuntimeLogs(self.state)

    def tearDown(self):
        self.hub.close()
        self.store.close()

    def test_seed_is_ordered_bounded_and_once_then_observes_committed_audit(self):
        for index in range(205):
            self.store.audit("settings", "old-" + str(index))
        self.hub.start()
        self.hub.start()
        rows = self.hub.snapshot()["entries"]
        self.assertEqual(len(rows), 200)
        self.assertEqual(rows[0]["message"], "old-5")
        self.assertEqual(rows[-1]["message"], "old-204")
        self.store.audit("error", "new-error")
        row = self.hub.snapshot()["entries"][-1]
        self.assertEqual(row["source"], "audit.error")
        self.assertEqual(row["level"], "ERROR")
        self.assertEqual(row["time"], self.store.logs()[0]["time"])
        self.hub.close()
        self.hub.start()
        self.assertEqual(self.hub.snapshot()["cursor"], 201)

    def test_ring_capacity_length_initial_tail_and_lossless_incremental_batches(self):
        for index in range(CAPACITY + 5):
            self.hub.record_audit("command", str(index) + "x" * 10000)
        data = self.hub.snapshot()
        self.assertEqual(len(self.hub.entries), CAPACITY)
        self.assertEqual(len(data["entries"]), 500)
        self.assertEqual(data["cursor"], CAPACITY + 5)
        self.assertEqual(data["oldest_cursor"], 6)
        self.assertEqual(data["entries"][0]["id"], 506)
        self.assertTrue(all(len(row["message"]) <= MAX_MESSAGE for row in data["entries"]))
        batch = self.hub.snapshot(after=0, limit=200)
        self.assertTrue(batch["truncated"])
        self.assertFalse(batch["reset"])
        self.assertEqual(batch["cursor"], 205)
        collected = [row["id"] for row in batch["entries"]]
        while batch["entries"]:
            batch = self.hub.snapshot(after=batch["cursor"], limit=200)
            collected.extend(row["id"] for row in batch["entries"])
        self.assertEqual(collected, list(range(6, CAPACITY + 6)))
        self.assertEqual(batch["cursor"], CAPACITY + 5)

    def test_reset_epoch_future_cursor_and_clear_boundary(self):
        for index in range(700):
            self.hub.record_audit("relay", str(index))
        before_clear = self.hub.snapshot()
        self.assertEqual(before_clear["cursor"], 700)
        self.assertEqual(self.hub.snapshot(after=before_clear["cursor"])["entries"], [])
        self.hub.record_audit("relay", "after-clear")
        self.assertEqual([row["message"] for row in self.hub.snapshot(after=700)["entries"]], ["after-clear"])
        restarted = RuntimeLogs(self.state)
        restarted.record_audit("settings", "new-process")
        fresh = restarted.snapshot(after=700, instance=self.hub.instance_id)
        self.assertTrue(fresh["reset"])
        self.assertFalse(fresh["truncated"])
        self.assertEqual(fresh["cursor"], 1)
        self.assertEqual(fresh["entries"][0]["message"], "new-process")
        self.assertTrue(self.hub.snapshot(after=99999)["reset"])
        self.assertFalse(self.hub.snapshot(after=701, instance=self.hub.instance_id)["reset"])

    def test_capture_real_python_logs_and_traceback_without_changing_levels(self):
        root = logging.getLogger()
        previous_level, previous_handlers = root.level, list(root.handlers)
        try:
            root.setLevel(logging.INFO)
            self.hub.start()
            self.assertEqual(root.level, logging.INFO)
            logging.info("service-started")
            logger = logging.getLogger("starbridge.test_runtime")
            logger.warning("bridge %s", "disconnected")
            logging.getLogger("external.test_runtime").warning("unrelated-library")
            try:
                raise ValueError("password=unconfigured-unsafe-password")
            except ValueError:
                logger.exception("bridge failed")
            data = self.hub.snapshot()
            self.assertEqual(data["capture_level"], "INFO")
            self.assertEqual(len(data["entries"]), 3)
            self.assertEqual(data["entries"][0]["source"], "root")
            self.assertEqual(data["entries"][1]["level"], "WARNING")
            error = data["entries"][2]
            self.assertEqual(error["level"], "ERROR")
            self.assertIn("Traceback", error["message"])
            self.assertIn("ValueError", error["message"])
            self.assertNotIn("unconfigured-unsafe-password", error["message"])
            self.assertNotIn("unrelated-library", json.dumps(data))
            root.setLevel(logging.DEBUG)
            logger.debug("debug-already-enabled")
            self.assertEqual(self.hub.snapshot()["entries"][-1]["level"], "DEBUG")
            self.assertEqual(self.hub.snapshot()["capture_level"], "DEBUG")
        finally:
            self.hub.close()
            root.setLevel(previous_level)
        self.assertEqual(root.handlers, previous_handlers)

    def test_generic_credentials_nested_json_commands_url_cq_and_terminal_codes(self):
        cases = {
            "password=unknown-password": "unknown-password",
            "smtp_password: 'words with spaces'": "words with spaces",
            '{"payload":{"password":"nested-json-password"}}': "nested-json-password",
            "clientSecret=client-secret": "client-secret",
            "access_token=unknown-access-token&count=1": "unknown-access-token",
            "API_KEY: api-key-value": "api-key-value",
            "Authorization: Bearer auth-secret-value": "auth-secret-value",
            '{"Authorization": "QQBot qq-official-token"}': "qq-official-token",
            "sent Bearer bearer-secret-value now": "bearer-secret-value",
            "mysql://admin:database-password@database.local/app": "database-password",
            "/确认重置 opaque-challenge new-native-password": "new-native-password",
            "/login game-password": "game-password",
            "[CQ:image,file=https://external.test/private-image]": "private-image",
        }
        for text, hidden in cases.items():
            with self.subTest(text=text):
                self.hub.record_audit("command", text)
                sanitized = self.hub.snapshot()["entries"][-1]["message"]
                self.assertNotIn(hidden, sanitized)
        self.hub.record_audit("relay", "\x1b[31mred\x1b[0m\x00 <img src=x onerror=alert(1)>\nnext-line")
        sanitized = self.hub.snapshot()["entries"][-1]["message"]
        self.assertEqual(sanitized, "red <img src=x onerror=alert(1)>\nnext-line")

    def test_dynamic_config_registration_official_and_native_secret_redaction(self):
        self.state["registration"] = SimpleNamespace(settings={"api_token": "website-token", "smtp_password": "mail-special/+=pass"})
        self.state["native_passwords"] = SimpleNamespace(settings={}, requests={"job": {"password": "native-password"}}, code_proofs={"BIND1234": {}})
        self.state["onebot"] = SimpleNamespace(official=SimpleNamespace(cfg={"client_secret": "official-secret"}, access_token="official-access", session_id="session-secret"))
        self.state["config"]["mysql"] = {"password": "database-password"}
        values = [self.state["config"]["app"]["admin_token"], self.state["config"]["onebot"]["token"],
                  self.state["config"]["servers"][0]["token"], "website-token", "mail-special/+=pass",
                  quote("mail-special/+=pass", safe=""), "native-password", "BIND1234", "official-secret",
                  "official-access", "session-secret", "database-password"]
        self.hub.record(logging.ERROR, "starbridge." + values[0], " ".join(values))
        result = json.dumps(self.hub.snapshot(), ensure_ascii=False)
        for value in values:
            self.assertNotIn(value, result)
        self.assertIn(REDACTED, result)
        # An unlabelled value becomes secret after the original capture.
        self.hub.record_audit("settings", "newly-designated-secret")
        self.state["registration"].settings["smtp_password"] = "newly-designated-secret"
        self.assertNotIn("newly-designated-secret", json.dumps(self.hub.snapshot()))
        # Rotated credentials were already removed from the stored ring.
        self.state["config"]["app"]["admin_token"] = "replacement-admin-token"
        self.assertNotIn(values[0], json.dumps(self.hub.snapshot()))

    def test_nonrecursive_handler_and_failed_observer_never_disrupt_committed_business(self):
        committed = []

        def observer(kind, detail, created):
            committed.append(self.store.logs()[0]["detail"])
            raise RuntimeError("observer-only failure")

        self.store.audit_observer = observer
        self.store.audit("settings", "committed-setting")
        self.assertEqual(committed, ["committed-setting"])
        self.assertEqual(self.store.logs()[0]["detail"], "committed-setting")
        self.hub.start()
        handler = self.hub.handler
        handler.local.busy = True
        handler.emit(logging.LogRecord("root", logging.ERROR, __file__, 1, "recursive", (), None))
        self.assertFalse(any(row["message"] == "recursive" for row in self.hub.snapshot()["entries"]))
        handler.local.busy = False
        self.hub.close()
        count = self.hub.cursor
        self.store.audit("settings", "after-close")
        self.assertEqual(self.hub.cursor, count)
        self.assertIsNone(self.store.audit_observer)

    def test_observer_is_per_store_and_not_called_when_commit_fails(self):
        observer = Mock()
        other = Store(":memory:")
        try:
            self.store.audit_observer = observer
            other.audit("settings", "other-instance")
            observer.assert_not_called()
            self.store.db.execute("DROP TABLE audit")
            with self.assertRaises(sqlite3.Error):
                self.store.audit("settings", "not-committed")
            observer.assert_not_called()
        finally:
            other.close()


class RuntimeLogApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.cfg = config()
        self.client = TestClient(TestServer(create_app(self.cfg)))
        await self.client.start_server()
        self.state = self.client.app[STATE]
        self.hub = self.state["runtime_logs"]
        self.headers = {"Authorization": "Bearer " + self.cfg["app"]["admin_token"]}

    async def asyncTearDown(self):
        await self.client.close()

    async def get(self, query="", status=200, headers=None):
        response = await self.client.get("/api/logs" + query, headers=self.headers if headers is None else headers)
        self.assertEqual(response.status, status, await response.text())
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        return await response.json()

    async def test_api_incremental_polling_is_read_only_and_head_has_same_access(self):
        initial = await self.get()
        audit_count = self.state["store"].db.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
        cursor = initial["cursor"]
        self.state["store"].audit("settings", "real-business-record")
        data = await self.get(f"?after={cursor}&instance={initial['instance_id']}&limit=1")
        self.assertEqual(len(data["entries"]), 1)
        self.assertEqual(data["entries"][0]["message"], "real-business-record")
        self.assertEqual(data["cursor"], cursor + 1)
        self.assertEqual((await self.get(f"?after={data['cursor']}"))["entries"], [])
        self.assertEqual(self.state["store"].db.execute("SELECT COUNT(*) FROM audit").fetchone()[0], audit_count + 1)
        for headers, status in (({}, 401), (self.headers, 200)):
            response = await self.client.head("/api/logs", headers=headers)
            self.assertEqual(response.status, status)
            self.assertEqual(response.headers["Cache-Control"], "no-store")

    async def test_api_tail_snapshot_and_clear_boundary_do_not_replay_older_half(self):
        for index in range(1000):
            self.hub.record_audit("relay", str(index))
        snapshot = await self.get()
        self.assertEqual(len(snapshot["entries"]), 500)
        self.assertEqual(snapshot["entries"][-1]["message"], "999")
        self.assertEqual((await self.get(f"?after={snapshot['cursor']}"))["entries"], [])
        earliest = await self.get("?after=0&limit=10")
        self.assertEqual(len(earliest["entries"]), 10)
        self.assertEqual(earliest["cursor"], earliest["entries"][-1]["id"])

    async def test_owner_only_rechecked_after_revocation_without_scope_expansion(self):
        for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": "Bearer " + self.cfg["servers"][0]["token"]}):
            await self.get(status=401, headers=headers)
        response = await self.client.post("/api/admin-users", headers=self.headers,
            json={"username": "LogObserver", "password": "A-test-password-2026", "permissions": ["status.read", "monitoring.manage"]})
        self.assertEqual(response.status, 200, await response.text())
        user = (await response.json())["users"][0]
        session = self.state["admin_accounts"].session(user["id"], user["username"])
        team_headers = {"Authorization": "Bearer " + session["access_token"]}
        await self.get(status=403, headers=team_headers)
        response = await self.client.head("/api/logs", headers=team_headers)
        self.assertEqual(response.status, 403)
        with self.state["store"].db:
            self.state["store"].db.execute("DELETE FROM admin_sessions")
        await self.get(status=401, headers=team_headers)

    async def test_bad_queries_return_400_without_side_effect_or_secret_echo(self):
        initial = self.hub.cursor
        for query in ("?after=-1", "?after=1.5", "?after=01", "?after=", "?after=true", "?limit=0", "?limit=501",
                      "?limit=1&limit=2", "?after=0&after=1", "?instance=bad-secret", "?source=../../config.toml", "?after=" + "9" * 100):
            with self.subTest(query=query):
                data = await self.get(query, status=400)
                self.assertNotIn("bad-secret", json.dumps(data))
                self.assertEqual(self.hub.cursor, initial)

    async def test_live_credentials_redacted_in_api_and_cleanup_detaches_every_handler(self):
        self.state["registration"].settings["smtp_password"] = "test-only-smtp-secret"
        self.state["store"].audit("error", "smtp exploded test-only-smtp-secret")
        data = await self.get()
        self.assertNotIn("test-only-smtp-secret", json.dumps(data))
        handler = self.hub.handler
        self.assertIn(handler, logging.getLogger().handlers)
        await self.client.close()
        self.assertNotIn(handler, logging.getLogger().handlers)
        self.assertIsNone(self.state["store"].audit_observer)


if __name__ == "__main__":
    unittest.main()
