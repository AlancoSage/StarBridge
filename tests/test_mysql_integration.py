"""Real MySQL contracts, opt in with MYRINBOT_TEST_MYSQL_CONFIG.

The JSON file contains either the MySQL settings or {"mysql": settings}.
Only a disposable database named myrinbot_it_* is accepted. Its tables are
removed before each test. No database or driver is mocked by these tests.
"""
import importlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid

from starbridge.mysql_settings import validate_mysql
from starbridge.storage import Store


_CONFIG = os.environ.get("MYRINBOT_TEST_MYSQL_CONFIG", "")


def mysql_settings():
    value = json.loads(Path(_CONFIG).read_text(encoding="utf-8"))
    result = validate_mysql(value.get("mysql", value))
    if not result["enabled"] or not re.fullmatch(r"myrinbot_it_[A-Za-z0-9_]+", result["database"]):
        raise ValueError("Integration tests require a disposable myrinbot_it_* database")
    return result


def clear_database():
    import pymysql
    cfg = mysql_settings()
    options = {key: cfg[key] for key in ("host", "port", "database", "user", "password", "connect_timeout")}
    if cfg["tls"]:
        options.update(ssl_ca=cfg["ssl_ca"] or None, ssl_verify_cert=True, ssl_verify_identity=True)
    else:
        options["ssl_disabled"] = True
    with pymysql.connect(**options, autocommit=True) as db, db.cursor() as cursor:
        cursor.execute("SHOW TABLES")
        tables = [row[0] for row in cursor.fetchall()]
        if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table) for table in tables):
            raise ValueError("Unexpected identifier in disposable integration database")
        for table in tables:
            cursor.execute("DROP TABLE `" + table + "`")


def _contract_case(name, module_name, class_name, factory="config", selected=None, excluded=(), methods=None):
    """Run existing security contracts unchanged against the real backend."""
    module = importlib.import_module(module_name)
    base = getattr(module, class_name)
    original = getattr(module, factory)

    def configured(*args, **kwargs):
        cfg = original(*args, **kwargs)
        cfg["mysql"] = mysql_settings()
        return cfg

    async def set_up(self):
        clear_database()
        configuration = patch.object(module, factory, configured)
        configuration.start()
        self.addCleanup(configuration.stop)
        await base.asyncSetUp(self)
        self.assertEqual(self.state["store"].db.dialect, "mysql")

    namespace = {"__module__": __name__, "asyncSetUp": set_up}
    for method in dir(base):
        if method.startswith("test_") and (method in excluded or (selected is not None and method not in selected)):
            namespace[method] = None
    namespace.update(methods or {})
    return unittest.skipUnless(_CONFIG, "Set MYRINBOT_TEST_MYSQL_CONFIG for real MySQL integration tests")(type(name, (base,), namespace))


MySQLAuthenticationTests = _contract_case("MySQLAuthenticationTests", "test_authentication", "GameAuthenticationTests")
MySQLOwnerAccountTests = _contract_case("MySQLOwnerAccountTests", "test_admin_accounts", "OwnerAccountTests", factory="full_config",
    excluded={"test_existing_team_deployment_migrates_without_replacing_credentials_or_sessions"})
MySQLCatalogTests = _contract_case("MySQLCatalogTests", "tests.test_catalog", "CatalogTests",
    excluded={"test_catalog_persists_on_reopen"})


def _native_database_text(self):
    db = self.store.db
    return "\n".join(repr(tuple(row)) for table in sorted(db.tables()) for row in db.execute('SELECT * FROM `' + table + '`'))


async def _native_api_roundtrip(self):
    # The original security assertion uses SQLite's diagnostic iterdump API.
    # Project MySQL through the real portable backup format for that assertion.
    db = self.state["store"].db

    def portable_dump():
        with tempfile.TemporaryDirectory() as folder:
            snapshot = Path(folder) / "native-password-proof.sqlite3"
            db.export_sqlite(snapshot)
            connection = sqlite3.connect(snapshot)
            try:
                yield from connection.iterdump()
            finally:
                connection.close()

    db.iterdump = portable_dump
    try:
        original = importlib.import_module("test_native_passwords").NativePasswordApiTests
        await original.test_binding_private_confirmation_native_claim_and_result_work_end_to_end(self)
    finally:
        del db.iterdump


MySQLNativePasswordTests = _contract_case("MySQLNativePasswordTests", "test_native_passwords", "NativePasswordTests",
    methods={"database_text": _native_database_text})
MySQLNativePasswordApiTests = _contract_case("MySQLNativePasswordApiTests", "test_native_passwords", "NativePasswordApiTests",
    methods={"test_binding_private_confirmation_native_claim_and_result_work_end_to_end": _native_api_roundtrip})
MySQLRegistrationTests = _contract_case("MySQLRegistrationTests", "test_registration", "RegistrationApiTests", selected={
    "test_apply_verify_account_token_and_one_time_code", "test_case_insensitive_names_and_no_pending_takeover",
    "test_email_failure_rolls_back_pending_and_creates_no_account", "test_codes_and_accounts_survive_restart_limits_persist",
})
MySQLOperationsTests = _contract_case("MySQLOperationsTests", "test_operations", "OperationsTests", factory="full_config", selected={
    "test_admin_routes_and_optimistic_revisions", "test_game_command_submitted_then_confirmed_once",
    "test_group_application_sender_scope_and_duplicate_protection", "test_whitelist_approval_ack_and_stale_repeated_review",
})
MySQLBackupTests = _contract_case("MySQLBackupTests", "test_backups", "BackupTests", factory="full_config", selected={
    "test_online_snapshot_preview_preserves_wal_data_and_hides_credentials",
    "test_native_password_restore_preserves_policy_but_requires_fresh_native_binding_proof",
    "test_old_backup_without_native_recovery_tables_restores_with_recovery_disabled",
    "test_native_password_policy_change_invalidates_existing_restore_preview",
    "test_website_settings_restore_and_preview_fence",
    "test_retention_keeps_manual_safety_and_newest_scheduled_backup",
    "test_backup_owner_validation_rejects_reserved_team_id_and_username_collision",
    "test_stale_expired_or_changed_preview_does_not_restore",
    "test_unauthorized_upload_download_restore_and_delete_are_rejected",
    "test_bad_zip_paths_duplicates_corruption_and_schema_are_rejected",
})


@unittest.skipUnless(_CONFIG, "Set MYRINBOT_TEST_MYSQL_CONFIG for real MySQL integration tests")
class MySQLStoreTests(unittest.TestCase):
    def setUp(self):
        clear_database()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = str(Path(self.temporary.name) / "must-not-fallback.sqlite3")
        self.mysql = mysql_settings()
        self.store = Store(self.path, self.mysql)
        self.addCleanup(self.store.close)

    def test_json_jobs_unicode_literals_binding_and_reopen(self):
        identity = str(uuid.uuid4())
        code = self.store.issue_code("survival", identity, "Steve")
        self.store.bind("survival", "123456789", code)
        with self.assertRaises(ValueError):
            self.store.bind("survival", "987654321", code)
        payload = {"kind": "player_action", "uuid": identity, "detail": "中文🙂 O'Reilly \\ 50% ?", "nested": {"null": None}}
        jid = self.store.enqueue("survival", payload)
        self.assertEqual(self.store.job("survival", jid), payload)
        self.assertEqual(self.store.poll("other"), [])
        self.assertEqual(self.store.poll("survival")[0]["detail"], payload["detail"])
        self.assertEqual(self.store.poll("survival"), [])
        self.store.close()
        self.store = Store(self.path, self.mysql)
        self.addCleanup(self.store.close)
        self.assertEqual(self.store.binding("survival", "123456789")["uuid"], identity)
        self.store.ack("other", [jid])
        self.assertIsNotNone(self.store.job("survival", jid))
        self.store.ack("survival", [jid])
        self.assertIsNone(self.store.job("survival", jid))
        self.assertFalse(Path(self.path).exists())

    def test_exact_identity_case_and_trailing_spaces_are_not_merged(self):
        for key in ("Event", "event", "event "):
            self.assertFalse(self.store.seen(key))
            self.assertTrue(self.store.seen(key))
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM seen").fetchone()[0], 3)
        for index, sid in enumerate(("Server", "server", "server ")):
            code = self.store.issue_code(sid, str(uuid.uuid4()), "Steve")
            self.store.bind(sid, "123456789", code)
        self.assertEqual(len(self.store.bindings()), 3)

    def test_transaction_failure_rolls_back_all_writes(self):
        code = self.store.issue_code("survival", str(uuid.uuid4()), "Steve")
        with self.assertRaisesRegex(RuntimeError, "abort test transaction"):
            with self.store.db:
                self.store.db.execute("DELETE FROM codes WHERE code=?", (code,))
                self.store.db.execute("INSERT INTO seen VALUES(?,?)", ("must-roll-back", time.time() + 30))
                raise RuntimeError("abort test transaction")
        self.assertIsNotNone(self.store.db.execute("SELECT code FROM codes WHERE code=?", (code,)).fetchone())
        self.assertIsNone(self.store.db.execute("SELECT id FROM seen WHERE id=?", ("must-roll-back",)).fetchone())

    def test_real_second_connection_never_observes_uncommitted_writes(self):
        second = Store(self.path, self.mysql)
        self.addCleanup(second.close)
        with self.store.db:
            self.store.db.execute("INSERT INTO seen VALUES(?,?)", ("private", time.time() + 30))
            self.assertIsNone(second.db.execute("SELECT id FROM seen WHERE id=?", ("private",)).fetchone())
        self.assertIsNotNone(second.db.execute("SELECT id FROM seen WHERE id=?", ("private",)).fetchone())

    def test_secondary_unique_collision_never_overwrites_another_account(self):
        sql = "INSERT INTO admin_users VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET username=excluded.username,password_hash=excluded.password_hash,permissions=excluded.permissions,enabled=excluded.enabled,revision=excluded.revision"
        with self.store.db:
            self.store.db.execute(sql, ("first", "Original", "original-hash", "[]", 1, 1, time.time()))
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.db:
                self.store.db.execute(sql, ("other", "Original", "attacker-hash", "[]", 1, 2, time.time()))
        row = self.store.db.execute("SELECT id,password_hash FROM admin_users").fetchone()
        self.assertEqual(tuple(row), ("first", "original-hash"))
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM admin_users").fetchone()[0], 1)

    def test_binding_code_is_consumed_once_across_real_connections(self):
        code = self.store.issue_code("survival", str(uuid.uuid4()), "Steve")
        barrier = threading.Barrier(2)
        results = []

        def attempt(qq):
            # Each thread owns its own driver connection, just as independent
            # application processes do; the database enforces the unique claim.
            connection = Store(self.path, self.mysql)
            try:
                barrier.wait(timeout=10)
                try:
                    connection.bind("survival", qq, code)
                    results.append("bound")
                except (ValueError, sqlite3.IntegrityError, sqlite3.OperationalError):
                    results.append("rejected")
            finally:
                connection.close()

        workers = [threading.Thread(target=attempt, args=(qq,), daemon=True) for qq in ("123456789", "987654321")]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(15)
            self.assertFalse(worker.is_alive())
        self.assertEqual(sorted(results), ["bound", "rejected"])
        self.assertEqual(len(self.store.bindings()), 1)
        self.assertIsNone(self.store.db.execute("SELECT code FROM codes WHERE code=?", (code,)).fetchone())

    def test_json_extract_delete_and_retention_queries(self):
        identity = str(uuid.uuid4())
        first = self.store.enqueue("survival", {"kind": "player_action", "uuid": identity})
        second = self.store.enqueue("survival", {"kind": "text", "uuid": identity})
        with self.store.db:
            self.store.db.execute("DELETE FROM jobs WHERE json_extract(payload,'$.kind')='player_action' AND json_extract(payload,'$.uuid')=?", (identity,))
        self.assertIsNone(self.store.job("survival", first))
        self.assertIsNotNone(self.store.job("survival", second))
        for index in range(4):
            self.store.audit("test", "record " + str(index))
        self.assertEqual(len(self.store.logs()), 4)
        self.store.create_player_action("action", "survival", identity, "Steve", "kick", "test")
        self.assertTrue(self.store.complete_player_action("survival", "action", True, "ok"))


if __name__ == "__main__":
    unittest.main()
