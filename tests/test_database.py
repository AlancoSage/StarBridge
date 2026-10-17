"""Dialect/security tests plus opt-in tests against an actual MySQL server.

Set MYRINBOT_MYSQL_TEST_CONFIG to a JSON file naming a disposable, empty
database. Integration tests remove all project tables in that database.
"""
from copy import deepcopy
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from starbridge.database import (Cursor, MySQLConnection, Row, _create_table,
                                _default_matches, _dialect, _render, _tokens, connect)


class DialectTests(unittest.TestCase):
    def test_sqlite_is_the_native_default_and_keeps_row_api(self):
        with closing(connect(":memory:")) as database:
            self.assertIsInstance(database, sqlite3.Connection)
            row = database.execute("SELECT 7 AS value").fetchone()
            self.assertEqual(row[0], 7)
            self.assertEqual(dict(row), {"value": 7})

    def test_lexing_never_substitutes_literal_or_commented_parameters(self):
        sql = "SELECT '? key % -- text', \"key\", ? /* ? key */ FROM runtime_settings WHERE key=? -- ?\n"
        translated = _render(_dialect(_tokens(sql)))
        self.assertEqual(translated.count("%s"), 2)
        self.assertIn("'? key %% -- text'", translated)
        self.assertIn('"key"', translated)
        self.assertIn("`key` = %s", translated)
        self.assertNotIn("/*", translated)

    def test_ddl_uses_complete_bounded_keys_and_lossless_payloads(self):
        sql = "CREATE TABLE IF NOT EXISTS demo (id TEXT PRIMARY KEY, email TEXT UNIQUE, payload TEXT NOT NULL DEFAULT '', count REAL, revision INTEGER)"
        translated = _render(_create_table(_tokens(sql)))
        self.assertIn("id VARCHAR(768) PRIMARY KEY", translated)
        self.assertIn("email VARCHAR(254) UNIQUE", translated)
        self.assertIn("payload LONGTEXT NOT NULL DEFAULT ( '' )", translated)
        self.assertIn("count DOUBLE", translated)
        self.assertIn("revision BIGINT", translated)
        self.assertIn("utf8mb4_0900_bin", translated)
        self.assertNotIn("PRIMARY `KEY`", translated)

    def test_scalar_and_aggregate_max_have_distinct_meanings(self):
        translated = _render(_dialect(_tokens("SELECT MAX(id), MAX(last_seen,?), MIN(last_seen,?) FROM audit")))
        self.assertIn("MAX ( id )", translated)
        self.assertIn("GREATEST ( last_seen , %s )", translated)
        self.assertIn("LEAST ( last_seen , %s )", translated)

    def test_cleanup_derived_table_limit_and_stats_integer_division(self):
        translated = _render(_dialect(_tokens("DELETE FROM audit WHERE id IN (SELECT id FROM audit ORDER BY id DESC LIMIT -1 OFFSET 20)")))
        self.assertIn("SELECT * FROM ( SELECT id FROM audit", translated)
        self.assertIn("LIMIT 18446744073709551615 OFFSET 20", translated)
        translated = _render(_dialect(_tokens("SELECT period FROM (SELECT (bucket / ?) * ? AS period FROM server_samples GROUP BY period) GROUP BY period")))
        self.assertIn("bucket DIV %s", translated)
        self.assertIn(") AS _sb_derived GROUP", translated)

    def test_json_null_and_literal_null_are_distinguished(self):
        translated = _render(_dialect(_tokens("SELECT json_extract(payload,'$.reply_group') FROM jobs")))
        self.assertIn("JSON_TYPE", translated)
        self.assertIn("THEN NULL ELSE JSON_UNQUOTE", translated)

    def test_default_metadata_only_accepts_the_original_constant(self):
        self.assertTrue(_default_matches("(_utf8mb4\\'\\')", ""))
        self.assertTrue(_default_matches("(_utf8mb4\\'{}\\')", "{}"))
        self.assertTrue(_default_matches("0", 0))
        self.assertFalse(_default_matches("999", 0))
        self.assertFalse(_default_matches("UUID()", ""))
        self.assertFalse(_default_matches("NULL", None))

    def test_row_can_be_read_as_a_sequence_or_dict(self):
        row = Row(("ID", "name"), (42, "测试"))
        self.assertEqual(row[0], 42)
        self.assertEqual(row["id"], 42)
        self.assertEqual(tuple(row), (42, "测试"))
        self.assertEqual(dict(row), {"ID": 42, "name": "测试"})
        cursor = Cursor([(1,), (2,)], ["n"], 2, 7)
        self.assertEqual(cursor.fetchone()["n"], 1)
        self.assertEqual([tuple(value) for value in cursor.fetchall()], [(2,)])
        self.assertIsNone(cursor.fetchone())


MYSQL_CONFIG = os.environ.get("MYRINBOT_MYSQL_TEST_CONFIG")


@unittest.skipUnless(MYSQL_CONFIG, "requires disposable MySQL test database")
class MySQLIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = json.loads(Path(MYSQL_CONFIG).read_text(encoding="utf-8-sig"))
        cls.settings["enabled"] = True
        cls.settings.pop("_comment", None)
        cls.connection = MySQLConnection(cls.settings)
        if cls.connection.tables():
            raise RuntimeError("MySQL integration database must initially be empty")

    @classmethod
    def tearDownClass(cls):
        cls.connection.rollback()
        expected = {entry[1] for entry in cls.connection._canonical() if entry[0] == "table" and not entry[1].startswith("sqlite_")}
        for table in cls.connection.tables():
            if table not in expected and table != "adapter_probe":
                continue
            cls.connection.execute("DROP TABLE `" + table + "`")
        cls.connection.close()

    def setUp(self):
        from starbridge.storage import Store
        from starbridge.catalog import Catalog
        from starbridge.registration import Registration
        from starbridge.authentication import Authentication
        from starbridge.native_passwords import NativePasswords
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "must-not-exist.sqlite3"), mysql=self.settings)
        self.db = self.store.db
        self.catalog = Catalog(self.store)
        self.registration = Registration(self.temp.name, self.store)
        Authentication(self.temp.name, None, self.registration)
        NativePasswords(SimpleNamespace(store=self.store))
        self.db.rollback()
        with self.db:
            for table in self.db.tables():
                self.db.execute("DELETE FROM `" + table + "`")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_native_storage_full_schema_binding_jobs_unicode_and_no_mirror(self):
        self.assertFalse((Path(self.temp.name) / "must-not-exist.sqlite3").exists())
        identity = str(uuid.uuid4())
        code = self.store.issue_code("main", identity, "Steve")
        bound = self.store.bind("main", "qug:123:" + "X" * 200, code)
        self.assertEqual(bound["uuid"], identity)
        self.assertEqual(self.store.binding("main", "qug:123:" + "X" * 200)["name"], "Steve")
        self.assertFalse(self.store.seen("X" * 700))
        self.assertTrue(self.store.seen("X" * 700))
        job = self.store.enqueue("main", {"kind": "broadcast", "text": "中文 🎮 ' % \\ ?"})
        self.assertEqual(self.store.job("main", job)["text"], "中文 🎮 ' % \\ ?")
        self.assertEqual(self.store.poll("main")[0]["id"], job)
        self.assertEqual(self.store.poll("main"), [])
        self.store.ack("main", [job])
        self.assertIsNone(self.store.job("main", job))

    def test_index_keys_case_trailing_spaces_and_long_email_remain_distinct(self):
        with self.db:
            for identity in ("Case", "case", "case "):
                self.db.execute("INSERT INTO seen VALUES(?,?)", (identity, 123))
            self.db.execute("INSERT INTO registration_accounts VALUES(?,?,?,?,?,?)", ("a", "Player", "player", "a" * 240 + "@example.com", None, 123))
        self.assertEqual(self.db.execute("SELECT count(*) FROM seen").fetchone()[0], 3)
        self.assertEqual(len(self.db.execute("SELECT email FROM registration_accounts").fetchone()[0]), 252)
        self.assertEqual(self.db.execute("SELECT player FROM registration_accounts WHERE player LIKE ? ESCAPE '\\'", ("%PLAYER%",)).fetchone()[0], "Player")

    def test_upsert_preserves_explicit_conflict_target_and_atomic_rollback(self):
        insert = "INSERT INTO admin_users VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET username=excluded.username,password_hash=excluded.password_hash,permissions=excluded.permissions,enabled=excluded.enabled,revision=excluded.revision"
        with self.db:
            self.db.execute(insert, ("one", "alice", "hash1", "[]", 1, 1, 1))
            self.db.execute(insert, ("two", "bob", "hash2", "[]", 1, 1, 1))
            self.db.execute(insert, ("one", "alicia", "hash3", "[]", 1, 2, 1))
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db:
                self.db.execute(insert, ("three", "bob", "hacked", "[]", 1, 1, 1))
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db:
                self.db.execute("INSERT INTO seen VALUES('rollback',1)")
                self.db.execute(insert, ("one", "bob", "hacked", "[]", 1, 3, 1))
        self.assertIsNone(self.db.execute("SELECT 1 FROM seen WHERE id='rollback'").fetchone())
        self.assertEqual(self.db.execute("SELECT password_hash FROM admin_users WHERE id='two'").fetchone()[0], "hash2")
        self.assertEqual(self.db.execute("SELECT username FROM admin_users WHERE id='one'").fetchone()[0], "alicia")

    def test_ignore_rejects_truncation_check_and_not_null_errors(self):
        with self.db:
            self.db.execute("INSERT INTO seen VALUES('duplicate',1)")
            self.assertEqual(self.db.execute("INSERT OR IGNORE INTO seen VALUES('duplicate',2)").rowcount, 0)
        for sql, values in (("INSERT OR IGNORE INTO seen VALUES(?,?)", ("x" * 769, 1)),
                            ("INSERT OR IGNORE INTO admin_owner VALUES(?,?,?,?,?)", ("intruder", "abc", "secret-value", 1, 1)),
                            ("INSERT OR IGNORE INTO admin_users VALUES(?,?,?,?,?,?,?)", ("id", None, "secret-value", "[]", 1, 1, 1))):
            with self.assertRaises(sqlite3.Error) as caught:
                with self.db:
                    self.db.execute(sql, values)
            self.assertNotIn("secret-value", str(caught.exception))

    def test_json_null_pruning_and_unchanged_update_rowcount(self):
        with self.db:
            for index, value in enumerate((None, "null", "broadcast", "other")):
                self.db.execute("INSERT INTO jobs(id,server,payload,created,expires) VALUES(?,?,?,?,?)", (str(index), "main", json.dumps({"kind": value}), index, 100))
            self.db.execute("DELETE FROM jobs WHERE json_extract(payload,'$.kind') IS NULL")
            self.db.execute("DELETE FROM jobs WHERE json_extract(payload,'$.kind')='broadcast'")
            self.assertEqual(self.db.execute("UPDATE jobs SET server='main' WHERE id='1'").rowcount, 1)
            self.db.execute("DELETE FROM jobs WHERE id IN (SELECT id FROM jobs ORDER BY created DESC LIMIT -1 OFFSET 1)")
        self.assertEqual(self.db.execute("SELECT id FROM jobs").fetchone()[0], "3")
        with self.db:
            self.db.executemany("INSERT INTO audit(time,kind,detail) VALUES(?,?,?)", ((1, "test", str(index)) for index in range(1005)))
            self.db.execute("DELETE FROM audit WHERE id < (SELECT COALESCE(MAX(id),0)-1000 FROM audit)")
        self.assertEqual(self.db.execute("SELECT count(*) FROM audit").fetchone()[0], 1001)

    def test_catalog_observation_upsert_search_and_time_bucket_statistics(self):
        identity = str(uuid.uuid4())
        record = {"uuid": identity, "name": "Steve", "online": True, "ip": "127.0.0.1"}
        self.catalog.observe({"id": "main", "name": "主服"}, [record])
        self.catalog.observe({"id": "main", "name": "主服"}, [{**record, "ip": "127.0.0.2"}])
        row = self.db.execute("SELECT ip FROM player_profiles WHERE uuid=?", (identity,)).fetchone()
        self.assertEqual(row[0], "127.0.0.2")
        with self.db:
            self.db.executemany("INSERT INTO server_samples VALUES(?,?,?,?,?)", (("main", 301, 1, 3, 20), ("main", 302, 1, 5, 20), ("other", 302, 1, 10, 20)))
        query = "SELECT period,sum(online_count),sum(connected) FROM (SELECT (bucket / ?) * ? AS period,server,avg(online_count) AS online_count,max(connected) AS connected FROM server_samples WHERE bucket>=? GROUP BY period,server) GROUP BY period ORDER BY period"
        row = self.db.execute(query, (300, 300, 0)).fetchone()
        self.assertEqual(tuple(row), (300, 14, 2))

    def test_snapshot_roundtrip_and_failed_restore_rolls_back(self):
        snapshot = Path(self.temp.name) / "snapshot.sqlite3"
        with self.db:
            self.db.execute("INSERT INTO bindings VALUES(?,?,?,?,?)", ("main", "12345", str(uuid.uuid4()), "Player", 123.5))
            self.db.execute("INSERT INTO runtime_settings VALUES(?,?,?)", ("statistics", '{"enabled": false}', 1))
            self.db.execute("INSERT INTO audit(id,time,kind,detail) VALUES(50000,0,'test','')")
            self.db.execute("DELETE FROM audit")
            self.db.execute("INSERT INTO player_profiles(id,uuid,name) VALUES(50000,?,?)", (str(uuid.uuid4()), "Sequence"))
            self.db.execute("DELETE FROM player_profiles")
        # The full archive validator expects exact feature settings; this
        # row is intentionally removed so the test isolates storage transport.
        with self.db:
            self.db.execute("DELETE FROM runtime_settings")
        self.db.export_sqlite(snapshot)
        from starbridge.backups import check_database
        counts = check_database(snapshot)
        self.assertTrue(snapshot.exists())
        # Restore into an entirely empty database, rather than one whose
        # preexisting AUTO_INCREMENT counter could mask sequence loss.
        for table in self.db.tables():
            self.db.execute("DROP TABLE `" + table + "`")
        self.db.restore_sqlite(snapshot)
        self.assertEqual(self.store.bindings()[0]["name"], "Player")
        with self.db:
            self.assertGreater(self.db.execute("INSERT INTO audit(time,kind,detail) VALUES(0,'test','')").lastrowid, 50000)
            self.assertGreater(self.db.execute("INSERT INTO player_profiles(uuid,name) VALUES(?,?)", (str(uuid.uuid4()), "Sequence")).lastrowid, 50000)
        # Canonical SQLite accepts arbitrarily long keys; MySQL must reject
        # one rather than truncate it, and retain the complete previous DB.
        with closing(sqlite3.connect(snapshot)) as incoming, incoming:
            incoming.execute("INSERT INTO seen VALUES(?,?)", ("bad" * 300, 1))
        with self.assertRaises(sqlite3.Error):
            self.db.restore_sqlite(snapshot)
        self.assertEqual(len(self.store.bindings()), 1)

    def test_connection_drop_never_replays_a_write_and_next_transaction_recovers(self):
        from pymysql import OperationalError
        self.db.execute("BEGIN IMMEDIATE")
        with patch.object(self.db._raw, "cursor", side_effect=OperationalError(2013, "password secret-value")):
            with self.assertRaises(sqlite3.OperationalError) as caught:
                self.db.execute("INSERT INTO seen VALUES('not-replayed',1)")
        self.assertNotIn("secret-value", str(caught.exception))
        with self.assertRaises(sqlite3.OperationalError):
            self.db.execute("SELECT 1")
        self.db.rollback()
        with self.db:
            self.db.execute("INSERT INTO seen VALUES('recovered',1)")
        self.assertIsNone(self.db.execute("SELECT 1 FROM seen WHERE id='not-replayed'").fetchone())
        self.assertIsNotNone(self.db.execute("SELECT 1 FROM seen WHERE id='recovered'").fetchone())

    def test_connection_preflight_refuses_foreign_objects_engine_and_missing_unique_constraint(self):
        cases = (("CREATE TABLE adapter_probe (id BIGINT)", "DROP TABLE adapter_probe"),
                 ("CREATE VIEW adapter_probe AS SELECT id FROM seen", "DROP VIEW adapter_probe"),
                 ("ALTER TABLE audit ENGINE=MyISAM", "ALTER TABLE audit ENGINE=InnoDB"),
                 ("ALTER TABLE jobs ALTER COLUMN lease SET DEFAULT 999", "ALTER TABLE jobs ALTER COLUMN lease SET DEFAULT 0"),
                 ("ALTER TABLE account_game_links ADD CONSTRAINT adapter_foreign FOREIGN KEY(account_id) REFERENCES account_passwords(account_id) ON DELETE CASCADE", "ALTER TABLE account_game_links DROP FOREIGN KEY adapter_foreign"),
                 ("ALTER TABLE registration_accounts DROP INDEX email", "ALTER TABLE registration_accounts ADD UNIQUE(email)"))
        for change, restore in cases:
            with self.subTest(change=change):
                self.db._run(_tokens(change))
                try:
                    with self.assertRaises(ValueError):
                        MySQLConnection(self.settings)
                finally:
                    self.db._run(_tokens(restore))

    def test_partial_initialization_can_reopen_before_catalog_adds_secondary_index(self):
        self.db._run(_tokens("DROP INDEX binding_uuid ON bindings"))
        try:
            reopened = MySQLConnection(self.settings)
            reopened.close()
        finally:
            self.db._run(_tokens("CREATE INDEX binding_uuid ON bindings(uuid)"))


if __name__ == "__main__":
    unittest.main()
