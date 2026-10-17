"""MySQL recovery tests; integration cases use an explicit disposable instance."""
import asyncio
from contextlib import closing
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import uuid
import zipfile

from aiohttp.test_utils import TestClient, TestServer
from scripts import mysql_runtime, update_runtime
from scripts.migrate_database import MigrationError, migrate
from starbridge.app import STATE, create_app
from starbridge.backups import (BackupError, apply_pending_restore, check_database,
                               Backups, finish_restore, preserve_database_settings, snapshot_database)
from starbridge.config import load
from starbridge.database import connect
from starbridge.mysql_settings import MYSQL_DEFAULTS
from starbridge.settings import ConfigFile, runtime_config, serialize
from test_settings import full_config


class MySQLRecoveryGuards(unittest.TestCase):
    def test_relative_mysql_ca_uses_the_same_runtime_target_when_restoring(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            cfg = full_config()
            cfg["mysql"] = {**MYSQL_DEFAULTS, "enabled": True, "tls": True, "ssl_ca": "certificates/ca.pem"}
            running = runtime_config(cfg, path)
            backups = Backups({"config_file": ConfigFile(path), "config": running})
            backups.check_local(cfg)
            changed = deepcopy(cfg)
            changed["mysql"]["host"] = "another.example.invalid"
            with self.assertRaises(BackupError):
                backups.check_local(changed)

    def test_code_rollback_cannot_change_database_backends(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            current = base / "config.toml"
            captured = base / "captured.toml"
            cfg = full_config()
            current.write_text(serialize(cfg), encoding="utf-8")
            other = deepcopy(cfg)
            other["mysql"] = {**MYSQL_DEFAULTS, "enabled": True}
            captured.write_text(serialize(other), encoding="utf-8")
            self.assertFalse(mysql_runtime.same_database_target(current, captured))
            source = base / "rollback"
            (source / "state").mkdir(parents=True)
            shutil.copyfile(captured, source / "state/config.toml")
            with self.assertRaises(ValueError):
                mysql_runtime.restore_capture(base, current, source)

    def test_archive_cannot_redirect_the_current_database(self):
        current = {"mysql": {"enabled": True, "host": "current", "password": "local-only"}}
        incoming = {"mysql": {"enabled": True, "host": "archive", "password": "untrusted"}}
        preserve_database_settings(incoming, current)
        self.assertEqual(incoming["mysql"], current["mysql"])
        incoming["mysql"]["host"] = "edited"
        self.assertEqual(current["mysql"]["host"], "current")
        preserve_database_settings(incoming, {})
        self.assertNotIn("mysql", incoming)

    def test_wrapper_preserves_protected_supervisor_and_restores_hooks(self):
        original = update_runtime.capture
        original_apply = update_runtime.apply_pending
        before = os.environ.get(mysql_runtime.CAPABILITY)
        with mysql_runtime.database_hooks():
            self.assertIs(update_runtime.capture, mysql_runtime.capture)
            self.assertEqual(os.environ[mysql_runtime.CAPABILITY], "1")
            self.assertFalse(update_runtime.managed("scripts/update_runtime.py"))
        self.assertIs(update_runtime.capture, original)
        self.assertIs(update_runtime.apply_pending, original_apply)
        self.assertEqual(os.environ.get(mysql_runtime.CAPABILITY), before)

    def test_mysql_snapshot_does_not_read_the_sqlite_fallback(self):
        class Database:
            def export_sqlite(self, path, max_bytes):
                self.path = path
            def close(self):
                pass
        db = Database()
        cfg = {"app": {"database": "never-read.sqlite3"}, "mysql": {"enabled": True}}
        with patch("starbridge.database.connect", return_value=db), patch("starbridge.backups.check_database") as check:
            with patch("starbridge.backups.copy_database", side_effect=AssertionError("SQLite fallback was used")):
                snapshot_database(cfg, "snapshot.sqlite3")
        self.assertEqual(db.path, "snapshot.sqlite3")
        check.assert_called_once_with("snapshot.sqlite3")


class UpdateDatabaseFences(unittest.IsolatedAsyncioTestCase):
    async def test_pending_mysql_settings_reject_update_before_preparation(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            cfg = full_config()
            config.write_text(serialize(cfg), encoding="utf-8")
            app = create_app(load(config), config_path=config, restart_event=asyncio.Event())
            state = app[STATE]
            try:
                cfg["mysql"] = {**MYSQL_DEFAULTS, "enabled": True}
                config.write_text(serialize(cfg), encoding="utf-8")
                with patch.dict(os.environ, {"STARBRIDGE_SUPERVISED": "1", mysql_runtime.CAPABILITY: "1"}):
                    with self.assertRaises(BackupError) as caught:
                        await state["updates"].apply({"id": "a" * 32})
                self.assertEqual(caught.exception.status, 409)
                self.assertFalse(state.get("maintenance", False))
            finally:
                state["store"].close()


@unittest.skipUnless(os.environ.get("MYRINBOT_MYSQL_TEST_INSTANCE"), "requires an explicitly selected disposable MySQL instance")
class MySQLBackupIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import pymysql
        metadata = json.loads(Path(os.environ["MYRINBOT_MYSQL_TEST_INSTANCE"]).read_text(encoding="utf-8"))
        self.mysql = deepcopy(metadata["mysql"])
        self.mysql["database"] = "myrinbot_it_backups_" + uuid.uuid4().hex[:12]
        self.mysql["enabled"] = True
        self.root_connection = pymysql.connect(host=self.mysql["host"], port=self.mysql["port"], user="root",
                                               password=metadata["root_password"], autocommit=True)
        self.addAsyncCleanup(self.asyncTearDown)
        with self.root_connection.cursor() as cursor:
            cursor.execute("CREATE DATABASE `" + self.mysql["database"] + "` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin")
            cursor.execute("SELECT Host FROM mysql.user WHERE User=%s", (self.mysql["user"],))
            for (host,) in cursor.fetchall():
                cursor.execute("GRANT ALL ON `" + self.mysql["database"] + "`.* TO %s@%s", (self.mysql["user"], host))
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.config = self.base / "config.toml"
        self.cfg = full_config()
        self.cfg["mysql"] = self.mysql
        self.config.write_text(serialize(self.cfg), encoding="utf-8")
        self.client = TestClient(TestServer(create_app(load(self.config), config_path=self.config,
                                                      restart_event=asyncio.Event())))
        try:
            await self.client.start_server()
        except Exception:
            await self.asyncTearDown()
            raise
        self.state = self.client.app[STATE]
        self.admin = {"Authorization": "Bearer " + self.cfg["app"]["admin_token"]}
        self.player = str(uuid.uuid4())
        self.state["catalog"].create({"uuid": self.player, "name": "Steve", "ip": "127.0.0.1", "region": "测试", "notes": "original"})

    async def asyncTearDown(self):
        if hasattr(self, "client"):
            await self.client.close()
        if hasattr(self, "root_connection") and self.root_connection.open:
            with self.root_connection.cursor() as cursor:
                cursor.execute("DROP DATABASE IF EXISTS `" + self.mysql["database"] + "`")
            self.root_connection.close()
        if hasattr(self, "tmp"):
            self.tmp.cleanup()

    async def prepare_restore(self, rewrite_mysql=False):
        response = await self.client.post("/api/backups", headers=self.admin)
        self.assertEqual(response.status, 200, await response.text())
        entry = await response.json()
        response = await self.client.get("/api/backups/" + entry["id"], headers=self.admin)
        payload = await response.read()
        with zipfile.ZipFile(io.BytesIO(payload)) as source:
            values = {name: source.read(name) for name in source.namelist()}
        portable = self.base / "portable.sqlite3"
        portable.write_bytes(values["database.sqlite3"])
        self.assertEqual(check_database(portable)["players"], 1)
        if rewrite_mysql:
            malicious = deepcopy(self.cfg)
            malicious["mysql"].update(host="archive.example.invalid", database="wrong_target", password="archive-password")
            values["config.toml"] = serialize(malicious).encode("utf-8")
            manifest = json.loads(values["manifest.json"])
            manifest["files"]["config.toml"] = {"size": len(values["config.toml"]),
                                                   "sha256": hashlib.sha256(values["config.toml"]).hexdigest()}
            values["manifest.json"] = json.dumps(manifest).encode()
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w") as target:
                for name, content in values.items():
                    target.writestr(name, content)
            payload = output.getvalue()
        with self.state["store"].db:
            self.state["store"].db.execute("UPDATE player_profiles SET notes='before-restore'")
        response = await self.client.post("/api/backups/preview", headers={**self.admin, "Content-Type": "application/zip"}, data=payload)
        self.assertEqual(response.status, 200, await response.text())
        preview = await response.json()
        response = await self.client.post("/api/backups/restore", headers=self.admin, json={"preview_id": preview["preview_id"]})
        self.assertEqual(response.status, 200, await response.text())
        await self.client.close()

    def notes(self):
        with closing(connect("unused", mysql=self.mysql)) as db:
            return db.execute("SELECT notes FROM player_profiles WHERE uuid=?", (self.player,)).fetchone()[0]

    async def test_portable_backup_restore_keeps_local_mysql_target(self):
        await self.prepare_restore(rewrite_mysql=True)
        self.assertTrue(await asyncio.to_thread(apply_pending_restore, self.config))
        self.assertEqual(self.notes(), "original")
        self.assertEqual(load(self.config)["mysql"]["host"], self.mysql["host"])
        self.assertEqual(load(self.config)["mysql"]["database"], self.mysql["database"])
        self.assertFalse(Path(load(self.config)["app"]["database"]).exists())
        finish_restore(self.config)

    async def test_interrupted_mysql_restore_uses_the_journal_to_rollback(self):
        await self.prepare_restore()
        self.assertTrue(await asyncio.to_thread(apply_pending_restore, self.config))
        self.assertEqual(self.notes(), "original")
        self.assertFalse(await asyncio.to_thread(apply_pending_restore, self.config))
        self.assertEqual(self.notes(), "before-restore")
        self.assertEqual(json.loads((self.base / "data/last-restore.json").read_text())["status"], "rolled_back")

    async def test_offline_migration_roundtrip_preserves_rows_and_revokes_sessions(self):
        with self.state["store"].db:
            self.state["store"].db.execute("INSERT INTO admin_sessions VALUES(?,?,?)", ("a" * 64, "owner", 9999999999.0))
        await self.client.close()
        folder = await asyncio.to_thread(migrate, self.config, "sqlite", False, self.base)
        self.assertTrue((folder / "source.sqlite3").is_file())
        cfg = load(self.config)
        self.assertFalse(cfg["mysql"]["enabled"])
        with closing(sqlite3.connect(cfg["app"]["database"])) as db:
            self.assertEqual(db.execute("SELECT notes FROM player_profiles").fetchone()[0], "original")
            self.assertEqual(db.execute("SELECT count(*) FROM admin_sessions").fetchone()[0], 0)
        with self.assertRaises(MigrationError):
            await asyncio.to_thread(migrate, self.config, "mysql", False, self.base)
        folder = await asyncio.to_thread(migrate, self.config, "mysql", True, self.base)
        self.assertTrue(load(self.config)["mysql"]["enabled"])
        self.assertTrue((folder / "target-before.sqlite3").is_file())
        self.assertEqual(self.notes(), "original")
        with closing(connect("unused", mysql=self.mysql)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM admin_sessions").fetchone()[0], 0)

    async def test_update_wrapper_captures_and_restores_mysql_with_its_active_python(self):
        with self.state["store"].db:
            self.state["store"].db.execute("INSERT INTO admin_sessions VALUES(?,?,?)", ("b" * 64, "owner", 9999999999.0))
        await self.client.close()
        fixture = self.base / "runtime-fixture"
        project = Path(__file__).resolve().parent.parent
        for name in ("starbridge", "scripts"):
            target = fixture / name
            target.mkdir(parents=True)
            files = (project / name).glob("*.py") if name == "starbridge" else (
                project / "scripts/mysql_runtime.py", project / "scripts/update_runtime.py")
            for source in files:
                shutil.copyfile(source, target / source.name)
        capture = self.base / "update-rollback"
        await asyncio.to_thread(mysql_runtime.capture, fixture, self.config, capture)
        self.assertTrue((capture / "state/database.sqlite3").is_file())
        self.assertFalse((capture / "code/scripts/update_runtime.py").exists())
        with closing(connect("unused", mysql=self.mysql)) as db, db:
            db.execute("UPDATE player_profiles SET notes='new-version-wrote-this'")
        await asyncio.to_thread(mysql_runtime.restore_capture, fixture, self.config, capture)
        self.assertEqual(self.notes(), "original")
        self.assertTrue(load(self.config)["mysql"]["enabled"])
        with closing(connect("unused", mysql=self.mysql)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM admin_sessions").fetchone()[0], 0)

    async def test_migration_config_write_failure_restores_the_existing_mysql_target(self):
        await self.client.close()
        await asyncio.to_thread(migrate, self.config, "sqlite", False, self.base)
        with closing(connect("unused", mysql=self.mysql)) as db, db:
            db.execute("UPDATE player_profiles SET notes='remote-before'")
        original_atomic = update_runtime.atomic
        def fail_config(path, content):
            if Path(path) == self.config:
                raise OSError("simulated config write failure")
            return original_atomic(path, content)
        with patch.object(update_runtime, "atomic", side_effect=fail_config), self.assertRaises(MigrationError):
            await asyncio.to_thread(migrate, self.config, "mysql", True, self.base)
        self.assertFalse(load(self.config)["mysql"]["enabled"])
        self.assertEqual(self.notes(), "remote-before")


if __name__ == "__main__":
    unittest.main()
