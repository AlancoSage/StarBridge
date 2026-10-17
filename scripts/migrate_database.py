"""Explicit, offline SQLite/MySQL migration with local portable safety copies."""
import argparse
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sqlite3
import sys
import tomllib
import uuid

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import update_runtime as runtime
from starbridge.backups import (check_database, replace_database, safe_path,
                                snapshot_database, trusted_schema, revoke_transient, copy_database)
from starbridge.database import connect
from starbridge.settings import runtime_config, serialize, validate


class MigrationError(ValueError):
    pass


def has_data(config):
    path, mysql = config["app"]["database"], config.get("mysql", {})
    if not mysql.get("enabled") and not Path(path).exists():
        return False
    with closing(connect(path, mysql=mysql)) as db:
        if hasattr(db, "has_data"):
            return db.has_data()
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        known = {entry[1] for entry in trusted_schema() if entry[0] == "table"}
        if set(tables) - known:
            raise MigrationError("目标 SQLite 含有非本项目数据，请使用专用数据库路径")
        return any(db.execute('SELECT 1 FROM "' + table + '" LIMIT 1').fetchone() for table in tables)


def empty_snapshot(source, destination):
    with closing(sqlite3.connect(source)) as original, closing(sqlite3.connect(destination)) as db:
        original.backup(db)
        with db:
            for (table,) in db.execute("SELECT name FROM sqlite_schema WHERE type='table'").fetchall():
                db.execute('DELETE FROM "' + table + '"')


def migrate(config_path, destination, replace=False, root=None):
    config_path = Path(config_path).resolve()
    root = Path(root or Path(__file__).resolve().parent.parent).resolve()
    lock = runtime.supervisor_lock(root)
    try:
        original = config_path.read_bytes()
        cfg = validate(tomllib.loads(original.decode("utf-8")))
        source_mysql = cfg.get("mysql", {}).get("enabled", False)
        if source_mysql == (destination == "mysql"):
            raise MigrationError("当前已使用目标数据库，无需迁移")
        target = deepcopy(cfg)
        target.setdefault("mysql", {})["enabled"] = destination == "mysql"
        target = validate(target)
        source_runtime, target_runtime = runtime_config(cfg, config_path), runtime_config(target, config_path)
        if not source_mysql and not Path(source_runtime["app"]["database"]).is_file():
            raise MigrationError("源 SQLite 文件不存在，未创建或切换数据库")
        occupied = has_data(target_runtime)
        if occupied and not replace:
            raise MigrationError("目标数据库已有数据；默认不覆盖。确认需要替换后使用 --replace，工具会先保存目标安全副本")
        base = config_path.parent
        backup_root = safe_path(base, "data/database-migrations")
        backup_root.mkdir(parents=True, exist_ok=True)
        identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:12]
        folder = safe_path(backup_root, identifier)
        folder.mkdir()
        runtime.atomic(folder / "config-before.toml", original)
        source = folder / "source.sqlite3"
        snapshot_database(source_runtime, source)
        check_database(source)
        incoming = folder / "incoming.sqlite3"
        copy_database(source, incoming)
        revoke_transient(incoming)
        baseline = folder / "target-before.sqlite3"
        if occupied:
            snapshot_database(target_runtime, baseline)
            check_database(baseline)
        else:
            empty_snapshot(source, baseline)
        journal = {"format": "myrinbot-database-migration-v1", "source": "mysql" if source_mysql else "sqlite",
                   "target": destination, "phase": "prepared", "config_sha256": hashlib.sha256(original).hexdigest()}
        runtime.write_json(folder / "migration.json", journal)
        if config_path.read_bytes() != original:
            raise MigrationError("配置在迁移准备期间发生变化，未切换数据库")
        switched = False
        try:
            journal["phase"] = "copying"; runtime.write_json(folder / "migration.json", journal)
            replace_database(incoming, target_runtime["app"]["database"], target_runtime.get("mysql"))
            verified = folder / "target-verified.sqlite3"
            snapshot_database(target_runtime, verified)
            check_database(verified)
            # Compare logical rows, not SQLite pages or schema-internal sequence state.
            with closing(sqlite3.connect(incoming)) as left, closing(sqlite3.connect(verified)) as right:
                present = {row[0] for row in left.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
                for kind, name, _, _ in trusted_schema():
                    if kind != "table" or name == "sqlite_sequence":
                        continue
                    a = sorted(left.execute('SELECT * FROM "' + name + '"').fetchall(), key=repr) if name in present else []
                    b = sorted(right.execute('SELECT * FROM "' + name + '"').fetchall(), key=repr)
                    if a != b:
                        raise MigrationError("迁移后的数据核对失败，未切换配置")
            if config_path.read_bytes() != original:
                raise MigrationError("配置在迁移期间发生变化，未切换数据库")
            journal["phase"] = "verified"; runtime.write_json(folder / "migration.json", journal)
            runtime.atomic(config_path, serialize(target).encode("utf-8"))
            switched = True
            journal["phase"] = "complete"; runtime.write_json(folder / "migration.json", journal)
        except Exception as exc:
            if switched:
                # The checked target is already selected. A journal cleanup
                # failure must never put an empty baseline behind that config.
                return folder
            # If a crash occurred, the portable baseline and journal remain for
            # explicit operator recovery. Never fall back to another live store.
            try:
                replace_database(baseline, target_runtime["app"]["database"], target_runtime.get("mysql"))
                journal["phase"] = "rolled_back"
            except Exception:
                journal["phase"] = "recovery_required"
            runtime.write_json(folder / "migration.json", journal)
            raise MigrationError("迁移未完成，源数据库保持不变。请保留安全副本与迁移记录：" + str(folder)) from exc
        return folder
    finally:
        lock.close()


def main():
    parser = argparse.ArgumentParser(description="停止软件后，将 Myrinbot 数据完整迁移至 SQLite 或 MySQL")
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument("--to", choices=("mysql", "sqlite"), required=True)
    parser.add_argument("--replace", action="store_true", help="允许替换目标现有数据，替换前保存完整安全副本")
    args = parser.parse_args()
    try:
        folder = migrate(args.config, args.to, args.replace)
    except (OSError, ValueError, sqlite3.Error) as exc:
        message = str(exc) if isinstance(exc, MigrationError) else "迁移失败，请检查数据库配置、权限与连接；原配置未自动切换"
        parser.exit(1, message + "\n")
    print("迁移与逐表核对完成，已切换配置至 " + args.to + "；旧验证码、登录会话与待执行操作已撤销，定时任务已暂停。请重新启动软件。安全副本：" + str(folder))


if __name__ == "__main__":
    main()
