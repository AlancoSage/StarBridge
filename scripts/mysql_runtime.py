"""MySQL-aware database hooks around the unchanged, protected update supervisor.

The supervisor keeps its original package protocol and journal. Database work runs
in the active application environment so an older supervisor does not have to
import a newly installed PyMySQL dependency or a replacement application module.
"""
import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import update_runtime as runtime

CAPABILITY = "MYRINBOT_MYSQL_SUPERVISOR"
_original_capture = runtime.capture
_original_restore = runtime.restore_capture
_original_apply = runtime.apply_pending


def mysql_enabled(config):
    return tomllib.loads(Path(config).read_text(encoding="utf-8")).get("mysql", {}).get("enabled", False) is True


def supports_mysql(source):
    """Pre-MySQL releases cannot safely run with a MySQL-enabled local config."""
    source = Path(source)
    return (source / "starbridge/database.py").is_file() and (source / "scripts/mysql_runtime.py").is_file()


def same_database_target(config, archived_config):
    """A historical code rollback must not silently select another live store."""
    config = Path(config).resolve()
    def identity(path):
        cfg = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        mysql = cfg.get("mysql", {})
        if not mysql.get("enabled", False):
            return ("sqlite", str((config.parent / cfg["app"]["database"]).resolve()))
        ca = mysql.get("ssl_ca", "")
        if ca:
            ca = str((config.parent / ca).resolve())
        return ("mysql", mysql.get("host", "127.0.0.1"), mysql.get("port", 3306),
                mysql.get("database", "myrinbot"), mysql.get("user", "myrinbot"),
                mysql.get("password", ""), mysql.get("tls", False), ca)
    return identity(config) == identity(archived_config)


def database_tool(root, config, operation, snapshot):
    helper = runtime.safe(root, "scripts/mysql_runtime.py")
    result = subprocess.run([runtime.runtime_python(root), str(helper), operation,
                             "--config", str(config), "--snapshot", str(snapshot)],
                            cwd=root, capture_output=True, timeout=180)
    if result.returncode:
        # Database drivers can include connection details in their exceptions.
        # Keep stdout/stderr private, including when an update error is audited.
        raise ValueError("MySQL 数据库快照操作失败，请检查连接、权限和数据库结构；未继续切换版本")


def capture(root, config, destination):
    if not mysql_enabled(config):
        return _original_capture(root, config, destination)
    names = runtime.managed_files(root)
    for name in names:
        runtime.atomic(runtime.safe(destination / "code", name), runtime.safe(root, name).read_bytes())
    settings = {name: path for name, path in runtime.state_files(config).items() if path.exists()}
    for name, path in settings.items():
        runtime.atomic(runtime.safe(destination / "state", name), path.read_bytes())
    database_tool(root, config, "export", destination / "state/database.sqlite3")
    runtime.write_json(destination / "capture.json", {"files": names, "state": list(settings),
                                                      "database_backend": "mysql"})


def restore_capture(root, config, source):
    archived_config = runtime.safe(source / "state", "config.toml")
    if not same_database_target(config, archived_config):
        raise ValueError("数据库目标已变化；为避免覆盖其他数据库，请先离线核对并迁移，再回退历史版本")
    if not mysql_enabled(archived_config):
        return _original_restore(root, config, source)
    if not supports_mysql(source / "code"):
        raise ValueError("此回退副本缺少 MySQL 支持；请先离线迁移至 SQLite 再回退")
    info = runtime.read_json(source / "capture.json")
    original = info["files"]
    if any(not runtime.managed(name) for name in original):
        raise ValueError("代码回退清单错误")
    for name in set(runtime.managed_files(root)) - set(original):
        runtime.safe(root, name).unlink()
    for name in original:
        runtime.atomic(runtime.safe(root, name), runtime.safe(source / "code", name).read_bytes())
    current = runtime.state_files(config)
    existing = info["state"]
    for name in existing:
        if name not in current and not (name.startswith("plugins/") and Path(name).suffix == ".json"):
            raise ValueError("数据回退路径错误")
        current.setdefault(name, runtime.safe(Path(config).resolve().parent, name))
    for name, target in current.items():
        if name in existing:
            runtime.atomic(target, runtime.safe(source / "state", name).read_bytes())
        elif target.exists():
            target.unlink()
    runtime.clear_caches(root)
    database_tool(root, config, "import", source / "state/database.sqlite3")


def apply_pending(root, config):
    journal = runtime.job_path(root)
    if journal.exists() and mysql_enabled(config):
        job = runtime.read_json(journal)
        if job.get("phase") == "pending":
            stage = runtime.folder(root, job["id"])
            source = stage / "package" if job.get("mode") == "update" else runtime.folder(root, job["source"]) / "rollback/code"
            if not supports_mysql(source):
                raise ValueError("目标版本不支持 MySQL；请先离线迁移至 SQLite 再切换版本")
    if journal.exists():
        job = runtime.read_json(journal)
        if job.get("phase") == "pending" and job.get("mode") == "rollback":
            archived = runtime.folder(root, job["source"]) / "rollback/state/config.toml"
            if not same_database_target(config, archived):
                raise ValueError("历史回退副本使用不同数据库目标；请先离线核对并迁移")
    return _original_apply(root, config)


@contextmanager
def database_hooks():
    old_capture, old_restore, old_apply = runtime.capture, runtime.restore_capture, runtime.apply_pending
    old_marker = os.environ.get(CAPABILITY)
    runtime.capture, runtime.restore_capture = capture, restore_capture
    runtime.apply_pending = apply_pending
    os.environ[CAPABILITY] = "1"
    try:
        yield
    finally:
        runtime.capture, runtime.restore_capture = old_capture, old_restore
        runtime.apply_pending = old_apply
        if old_marker is None:
            os.environ.pop(CAPABILITY, None)
        else:
            os.environ[CAPABILITY] = old_marker


def supervise(config, root=None):
    with database_hooks():
        return runtime.supervise(config, root)


def main():
    parser = argparse.ArgumentParser(description="Myrinbot 内部离线数据库快照工具")
    parser.add_argument("operation", choices=("export", "import"))
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--snapshot", required=True, type=Path)
    args = parser.parse_args()
    from starbridge.config import load
    from starbridge.backups import snapshot_database, replace_database, copy_database, revoke_transient
    cfg = load(args.config)
    if args.operation == "export":
        args.snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot_database(cfg, args.snapshot)
    else:
        with tempfile.TemporaryDirectory(prefix=".mysql-restore-", dir=args.snapshot.parent) as temporary:
            incoming = Path(temporary) / "incoming.sqlite3"
            copy_database(args.snapshot, incoming)
            revoke_transient(incoming)
            replace_database(incoming, cfg["app"]["database"], cfg.get("mysql"))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("数据库快照操作失败，请检查连接、权限与数据库结构", file=sys.stderr)
        raise SystemExit(1)
