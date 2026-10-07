"""Bounded ZIP snapshots and journaled, offline restoration of trusted application data."""
import asyncio
from contextlib import closing, suppress
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile
import time
import tomllib
import uuid
import zipfile
import zlib

from . import __version__
from .authentication import Authentication, validate_settings as validate_auth
from .catalog import Catalog
from .extensions import (atomic_json, encode, invalid_constant, validate_plugin, setting_value,
                         IDENTIFIER, BUILTIN_PLUGINS, MAX_PLUGINS, MAX_FILE, MAX_STATE, permission_value)
from .operations import task_definition, whitelist_settings
from .registration import Registration, validate_settings as validate_registration
from .website import validate_settings as validate_website
from .settings import ConfigFile, runtime_config, serialize, validate
from .storage import Store

MIB = 1024 * 1024
MAX_ARCHIVE, MAX_DATABASE, MAX_TOTAL = 64 * MIB, 128 * MIB, 144 * MIB
ID = re.compile(r"[0-9]{8}T[0-9]{6}Z-[a-f0-9]{12}")
JOB_ID = re.compile(r"[a-f0-9]{32}")
FILES = {"config.toml": 256 * 1024, "database.sqlite3": MAX_DATABASE,
         "data/registration-settings.json": 32 * 1024,
         "data/authentication-settings.json": 32 * 1024, "data/plugin-state.json": MAX_STATE,
         "data/website-settings.json": 32 * 1024}
REQUIRED = {"config.toml", "database.sqlite3"}
TRANSIENT = ("codes", "jobs", "seen", "registration_challenges", "registration_sessions", "password_challenges")


class BackupError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message); self.status = status


def file_limit(name):
    if name in FILES:
        return FILES[name]
    if re.fullmatch(r"plugins/[a-z][a-z0-9_]{0,39}\.json", name):
        return MAX_FILE
    raise BackupError("备份包含不支持的文件或路径")


def safe_path(root, name):
    path = Path(root) / name
    if path.is_symlink() or not path.resolve().is_relative_to(Path(root).resolve()):
        raise BackupError("备份目录不允许符号链接或跳转到其他位置")
    return path


def remove_stage(root, folder):
    if folder.parent == root and JOB_ID.fullmatch(folder.name) and folder.resolve().is_relative_to(root.resolve()):
        shutil.rmtree(folder)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=invalid_constant)


def hash_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(MIB), b""): digest.update(chunk)
    return digest.hexdigest()


def write_archive(files, database, destination, reason):
    manifest = {"format": "starbridge-backup", "version": 1, "app_version": __version__,
                "created_at": datetime.now(timezone.utc).isoformat(), "reason": reason, "files": {}}
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for name, content in files.items():
            manifest["files"][name] = {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
            archive.writestr(name, content)
        manifest["files"]["database.sqlite3"] = {"size": database.stat().st_size, "sha256": hash_file(database)}
        archive.write(database, "database.sqlite3")
        archive.writestr("manifest.json", encode(manifest))
    if destination.stat().st_size > MAX_ARCHIVE: raise BackupError("压缩后的备份超过 64 MiB 上限")
    with destination.open("r+b") as file: os.fsync(file.fileno())
    return manifest


def readonly_database(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    db.execute("PRAGMA trusted_schema=OFF")
    deadline = time.monotonic() + 30
    db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
    return db


def copy_database(source, destination):
    with closing(readonly_database(source)) as original, closing(sqlite3.connect(destination)) as target:
        page_size = original.execute("PRAGMA page_size").fetchone()[0]
        size = original.execute("PRAGMA page_count").fetchone()[0] * page_size
        if size > MAX_DATABASE:
            raise BackupError("数据库超过 128 MiB 备份上限")
        deadline = time.monotonic() + 60
        def progress(status, remaining, total):
            if time.monotonic() > deadline or total * page_size > MAX_DATABASE:
                raise BackupError("数据库快照超时或超过大小限制")
        original.backup(target, pages=128, progress=progress, sleep=0.01)


def schema(db):
    return [(kind, name, table, " ".join(sql.split()) if sql else None)
            for kind, name, table, sql in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name")]


def operations_revision(db):
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
    settings = [list(row) for row in db.execute("SELECT * FROM operations_settings ORDER BY key")] if "operations_settings" in tables else []
    tasks = [list(row) for row in db.execute("SELECT id,definition,revision FROM scheduled_tasks ORDER BY id")] if "scheduled_tasks" in tables else []
    extra = {table:[list(row) for row in db.execute('SELECT * FROM '+table+' ORDER BY 1')]
             for table in ('runtime_settings','admin_users','plugin_versions') if table in tables}
    return hashlib.sha256(encode([settings, tasks, extra])).hexdigest()


_trusted_schema = None
def trusted_schema():
    global _trusted_schema
    if _trusted_schema is None:
        with tempfile.TemporaryDirectory(prefix="starbridge-schema-") as directory:
            store = Store(":memory:")
            Catalog(store)
            registration = Registration(directory, store)
            Authentication(directory, None, registration)
            _trusted_schema = schema(store.db)
            store.close()
    return _trusted_schema


def check_database(path):
    db = readonly_database(path)
    try:
        actual, expected = schema(db), trusted_schema()
        optional = {"operations_settings", "scheduled_tasks", "schedule_runs", "whitelist_applications",
                    "admin_users", "admin_sessions", "runtime_settings", "health_alerts", "server_samples",
                    "server_daily_players", "server_activity", "plugin_versions", "tickets", "ticket_messages", "sanctions", "sanction_targets"}
        present = {entry[1] for entry in actual}
        compatible = [entry for entry in expected if entry[2] not in optional or entry[2] in present]
        if actual != compatible:
            raise BackupError("数据库结构与当前星桥版本不兼容，或包含未知表、视图、触发器")
        if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise BackupError("数据库完整性检查失败")
        if "scheduled_tasks" in present:
            if db.execute("SELECT count(*) FROM scheduled_tasks").fetchone()[0] > 100:
                raise BackupError("定时任务超过 100 项")
            for row in db.execute("SELECT definition FROM scheduled_tasks"):
                task_definition(json.loads(row[0]))
        if "operations_settings" in present:
            for key, value, revision in db.execute("SELECT * FROM operations_settings"):
                if key not in ("whitelist", "tickets", "sanctions", "updates") or type(revision) is not int or revision < 0:
                    raise BackupError("自动化设置格式错误")
                setting = json.loads(value)
                if key == 'whitelist': whitelist_settings(setting)
                elif key == 'tickets':
                    if not isinstance(setting, dict) or setting.keys() != {'enabled', 'max_open'} or type(setting['enabled']) is not bool or type(setting['max_open']) is not int or not 1 <= setting['max_open'] <= 20:
                        raise BackupError('工单设置格式错误')
                elif key == 'sanctions':
                    if not isinstance(setting, dict) or setting.keys() != {'enabled'} or type(setting['enabled']) is not bool:
                        raise BackupError('跨服处罚设置格式错误')
                else:
                    from .github_updates import update_settings
                    update_settings(setting)
        if "runtime_settings" in present:
            from .runtime_features import validate_setting
            for key,value,revision in db.execute('SELECT * FROM runtime_settings'):
                if type(revision) is not int or revision<0:raise BackupError('运行设置版本错误')
                validate_setting(key,json.loads(value))
        if "admin_users" in present:
            from .admin_accounts import permissions
            if db.execute('SELECT count(*) FROM admin_users').fetchone()[0]>30:raise BackupError('管理员超过 30 位')
            for row in db.execute('SELECT username,permissions,enabled,revision FROM admin_users'):
                if not re.fullmatch(r'[A-Za-z0-9_\-]{3,32}',row[0]) or row[2] not in (0,1) or type(row[3]) is not int or row[3]<1:raise BackupError('管理员设置格式错误')
                permissions(json.loads(row[1]))
        if "plugin_versions" in present:
            if db.execute('SELECT count(*) FROM plugin_versions').fetchone()[0]>150:raise BackupError('插件历史数量超过上限')
            for pid,definition,settings in db.execute('SELECT plugin,definition,settings FROM plugin_versions'):
                value=validate_plugin(json.loads(definition))
                if value['id']!=pid:raise BackupError('插件历史 ID 错误')
                saved=json.loads(settings);permission_value(saved.get('permissions',{}))
        return {"players": db.execute("SELECT count(*) FROM player_profiles WHERE deleted=0").fetchone()[0],
                "accounts": db.execute("SELECT count(*) FROM registration_accounts").fetchone()[0],
                "bindings": db.execute("SELECT count(*) FROM bindings").fetchone()[0]}
    finally:
        db.close()


def check_settings(folder):
    cfg = validate(tomllib.loads((folder / "config.toml").read_text(encoding="utf-8")))
    website = safe_path(folder, "data/website-settings.json")
    if website.exists():
        validate_website(read_json(website))
    registration = safe_path(folder, "data/registration-settings.json")
    if registration.exists():
        values = validate_registration(read_json(registration))
        if values["api_token"] and values["api_token"] in [cfg["app"]["admin_token"], cfg["onebot"]["token"], *[s["token"] for s in cfg["servers"]]]:
            raise BackupError("网站 API 密钥与管理或桥接密钥冲突")
    authentication = safe_path(folder, "data/authentication-settings.json")
    if authentication.exists():
        validate_auth(read_json(authentication))
    definitions = dict(BUILTIN_PLUGINS)
    for path in sorted((folder / "plugins").glob("*.json")):
        definition = validate_plugin(read_json(path))
        if definition["id"] != path.stem:
            raise BackupError("插件 ID 与文件名称不一致")
        definitions[path.stem] = definition
    state_path = safe_path(folder, "data/plugin-state.json")
    if state_path.exists():
        values = read_json(state_path)
        if not isinstance(values, dict):
            raise BackupError("插件状态应为对象")
        for pid, entry in values.items():
            if (not IDENTIFIER.fullmatch(pid) or not isinstance(entry, dict) or entry.keys() - {"enabled", "settings", "permissions"}
                    or type(entry.get("enabled", False)) is not bool or not isinstance(entry.get("settings", {}), dict)):
                raise BackupError("插件状态格式错误")
            permission_value(entry.get("permissions", {}))
            if pid in definitions:
                specs, saved = definitions[pid]["settings"], entry.get("settings", {})
                if saved.keys() - specs.keys():
                    raise BackupError("插件设置包含未知字段")
                for key, spec in specs.items():
                    setting_value(spec, saved.get(key, spec["default"]))
    return cfg, len(definitions) - len(BUILTIN_PLUGINS)


def unpack_archive(archive, folder):
    """Never extractall: every filename, length, checksum and data format is bounded."""
    try:
        if archive.stat().st_size > MAX_ARCHIVE:
            raise BackupError("备份文件超过 64 MiB 上限", 413)
        with zipfile.ZipFile(archive) as source:
            entries = source.infolist()
            names = [entry.filename for entry in entries]
            if (not 3 <= len(entries) <= 37 or len(names) != len(set(names)) or "manifest.json" not in names):
                raise BackupError("备份清单缺失、重复或文件数量超限")
            if sum(entry.file_size for entry in entries) > MAX_TOTAL:
                raise BackupError("备份解压后超过大小上限", 413)
            for entry in entries:
                maximum = 64 * 1024 if entry.filename == "manifest.json" else file_limit(entry.filename)
                if (entry.file_size > maximum or entry.flag_bits & 1 or entry.is_dir()
                        or stat.S_ISLNK(entry.external_attr >> 16)
                        or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                    raise BackupError("备份包含超大文件、链接、目录或不支持的压缩格式")
            manifest = json.loads(source.read("manifest.json"), parse_constant=invalid_constant)
            if (not isinstance(manifest, dict) or manifest.get("format") != "starbridge-backup"
                    or type(manifest.get("version")) is not int or manifest["version"] != 1
                    or manifest.get("reason") not in ("manual", "before_restore", "scheduled")
                    or not isinstance(manifest.get("created_at"), str) or len(manifest["created_at"]) > 40
                    or not isinstance(manifest.get("app_version"), str) or len(manifest["app_version"]) > 40
                    or not isinstance(manifest.get("files"), dict)):
                raise BackupError("这不是支持的星桥备份格式")
            datetime.fromisoformat(manifest["created_at"])
            if set(manifest["files"]) != set(names) - {"manifest.json"} or not REQUIRED <= manifest["files"].keys():
                raise BackupError("清单与实际文件不一致或缺少配置、数据库")
            if sum(name.startswith("plugins/") for name in names) > MAX_PLUGINS:
                raise BackupError("备份插件数量超限")
            for name, expected in manifest["files"].items():
                content = source.read(name)
                if (not isinstance(expected, dict) or type(expected.get("size")) is not int
                        or expected["size"] != len(content) or expected.get("sha256") != hashlib.sha256(content).hexdigest()):
                    raise BackupError("备份校验失败：文件内容或长度不符")
                path = safe_path(folder, name); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(content)
        cfg, plugins = check_settings(folder)
        counts = check_database(folder / "database.sqlite3")
        return manifest, {**counts, "servers": len(cfg["servers"]), "plugins": plugins}
    except (zipfile.BadZipFile, zlib.error, EOFError, sqlite3.Error, UnicodeError, KeyError, TypeError, RuntimeError, OverflowError) as exc:
        raise BackupError("备份文件损坏或格式不受支持") from exc


class Backups:
    def __init__(self, state):
        self.state, self.busy, self.tasks = state, False, set()
        self.config = state["config_file"]
        self.base = self.config.path.parent if self.config else None
        self.root = safe_path(self.base, "data/backups") if self.base else None

    def require(self):
        if self.root is None:
            raise BackupError("此实例没有持久化配置，不支持备份", 503)
        self.root.mkdir(parents=True, exist_ok=True)
        safe_path(self.base, "data/backups")

    def capture_files(self):
        self.require()
        def bounded_read(path, name):
            if path.stat().st_size > file_limit(name): raise BackupError("配置或插件文件超过备份大小上限")
            return path.read_bytes()
        files = {"config.toml": bounded_read(self.config.path, "config.toml")}
        for name in FILES.keys() - REQUIRED:
            path = safe_path(self.base, name)
            if path.exists(): files[name] = bounded_read(path, name)
        paths = sorted(safe_path(self.base, "plugins").glob("*.json"))
        if len(paths) > MAX_PLUGINS:
            raise BackupError("插件数量超过备份上限")
        for path in paths:
            name = "plugins/" + path.name
            safe_path(self.base, name); files[name] = bounded_read(path, name)
        if any(len(content) > file_limit(name) for name, content in files.items()):
            raise BackupError("配置或插件文件超过备份大小上限")
        return files

    def fingerprint(self):
        return hashlib.sha256(encode({name: hashlib.sha256(content).hexdigest() for name, content in self.capture_files().items()})).hexdigest()

    async def work(self, function, *args):
        task = asyncio.create_task(asyncio.to_thread(function, *args)); self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        try: return await asyncio.shield(task)
        except asyncio.CancelledError:
            # A disconnected browser cannot free the operation slot while the disk worker runs.
            await task; raise

    async def close(self):
        if self.tasks: await asyncio.gather(*list(self.tasks), return_exceptions=True)

    def path(self, backup_id):
        self.require()
        if not isinstance(backup_id, str) or not ID.fullmatch(backup_id): raise BackupError("备份编号格式错误")
        path = safe_path(self.root, backup_id + ".zip")
        if not path.is_file(): raise BackupError("备份不存在", 404)
        return path

    def listing(self):
        self.require(); items = []
        for path in sorted(self.root.glob("*.zip"), reverse=True)[:100]:
            if not ID.fullmatch(path.stem): continue
            safe_path(self.root, path.name)
            try:
                with zipfile.ZipFile(path) as archive:
                    info = archive.getinfo("manifest.json")
                    if info.file_size > 64 * 1024: continue
                    manifest = json.loads(archive.read(info))
                items.append({"id": path.stem, "created_at": manifest["created_at"], "reason": manifest["reason"],
                              "size": path.stat().st_size, "app_version": manifest["app_version"]})
            except (OSError, ValueError, KeyError, TypeError, RuntimeError, zipfile.BadZipFile, zlib.error, EOFError):
                items.append({"id": path.stem, "created_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                              "reason": "damaged", "size": path.stat().st_size, "app_version": "未知"})
        result_path = safe_path(self.base, "data/last-restore.json")
        result = read_json(result_path) if result_path.exists() else None
        return {"backups": items, "busy": self.busy, "can_restore": self.state["restart_event"] is not None,
                "last_restore": result, "max_upload_bytes": MAX_ARCHIVE, "total_bytes": sum(item["size"] for item in items)}

    def cleanup_candidates(self, policy, now=None):
        now = time.time() if now is None else now
        entries = sorted(self.listing()["backups"], key=lambda item: item["created_at"], reverse=True)
        candidates = []
        for index, entry in enumerate(entries):
            if entry["reason"] in ("before_restore", "before_update", "before_rollback", "damaged") or (policy["protect_manual"] and entry["reason"] == "manual"):
                continue
            age = now - datetime.fromisoformat(entry["created_at"]).timestamp()
            if index >= policy["keep_count"] or age > policy["keep_days"] * 86400:
                candidates.append(entry)
        return candidates

    def apply_cleanup(self, policy):
        candidates = self.cleanup_candidates(policy)
        for entry in candidates:
            # Only our validated direct ZIP paths are eligible; never delete staging or safety backups.
            self.path(entry["id"]).unlink()
        return {"removed": len(candidates), "bytes_freed": sum(entry["size"] for entry in candidates)}

    async def cleanup_policy(self, manual=False):
        if self.busy: raise BackupError("备份或恢复操作正在处理中", 409)
        policy = self.state["runtime"].config("backup_policy")["settings"]
        if not manual and not policy["enabled"]: return {"removed":0,"bytes_freed":0}
        self.require(); self.busy = True
        try:
            result = await self.work(self.apply_cleanup, policy)
            if result["removed"]: self.state["store"].audit("backup", f"按保留规则清理 {result['removed']} 份备份")
            return result
        finally: self.busy = False

    def write_snapshot(self, files, reason):
        backup_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:12]
        target = safe_path(self.root, backup_id + ".zip")
        if len(list(self.root.glob("*.zip"))) >= 100:
            raise BackupError("最多保留 100 份备份，请删除不需要的旧备份", 409)
        with tempfile.TemporaryDirectory(prefix=".snapshot-", dir=self.root) as directory:
            folder = Path(directory); database = folder / "database.sqlite3"
            copy_database(self.state["config"]["app"]["database"], database)
            archive_path = folder / "snapshot.zip"
            manifest = write_archive(files, database, archive_path, reason)
            os.replace(archive_path, target)
        return {"id": backup_id, "created_at": manifest["created_at"], "reason": reason,
                "size": target.stat().st_size, "app_version": __version__}

    async def create(self, reason="manual"):
        if self.busy: raise BackupError("备份或恢复操作正在处理中", 409)
        runtime = self.state.get("runtime")
        if runtime and runtime.config("backup_policy")["settings"]["enabled"]:
            await self.cleanup_policy()
        self.busy = True
        try:
            return await self.snapshot(reason)
        finally: self.busy = False

    async def snapshot(self, reason):
        files = self.capture_files(); self.state["store"].db.commit()
        result = await self.work(self.write_snapshot, files, reason)
        self.state["store"].audit("backup", "已创建" + ("恢复前安全备份 " if reason == "before_restore" else "备份 ") + result["id"])
        return result

    async def preview(self, content):
        if self.busy: raise BackupError("备份或恢复操作正在处理中", 409)
        self.busy = True; folder = None
        try:
            self.require(); root = safe_path(self.root, "staging"); root.mkdir(exist_ok=True)
            for old in root.iterdir():
                if JOB_ID.fullmatch(old.name) and old.is_dir() and time.time() - old.stat().st_mtime > 600:
                    remove_stage(root, old)
            if len(list(root.iterdir())) >= 10: raise BackupError("待预览备份数量已达上限，请稍后重试", 429)
            folder = safe_path(root, uuid.uuid4().hex); folder.mkdir()
            archive = folder / "upload.zip"; total = 0
            with archive.open("wb") as output:
                async for chunk in content.iter_chunked(64 * 1024):
                    total += len(chunk)
                    if total > MAX_ARCHIVE: raise BackupError("备份文件超过 64 MiB 上限", 413)
                    output.write(chunk)
            manifest, counts = await self.work(unpack_archive, archive, folder / "incoming")
            cfg, _ = self.config.read()
            self.check_local(cfg)
            incoming, _ = check_settings(folder / "incoming")
            incoming["app"] = deepcopy(cfg["app"]); validate(incoming)
            (folder / "incoming/config.toml").write_text(serialize(incoming), encoding="utf-8")
            check_settings(folder / "incoming")
            values = {"preview_id": folder.name, "expires": time.time() + 300, "fingerprint": self.fingerprint(),
                      "operations_revision": operations_revision(self.state["store"].db),
                      "archive_sha256": await self.work(hash_file, archive),
                      "created_at": manifest["created_at"], "app_version": manifest["app_version"], "counts": counts}
            db = self.state["store"].db
            current_counts = {"players":db.execute('SELECT count(*) FROM player_profiles WHERE deleted=0').fetchone()[0],
                              "accounts":db.execute('SELECT count(*) FROM registration_accounts').fetchone()[0],
                              "bindings":db.execute('SELECT count(*) FROM bindings').fetchone()[0],
                              "servers":len(cfg['servers']), "plugins":len([p for p in self.state['plugins'].entries if p not in BUILTIN_PLUGINS])}
            values["differences"] = {key:{"current":current_counts[key],"incoming":counts[key],"delta":counts[key]-current_counts[key]} for key in current_counts}
            values["changed_sections"] = [key for key in ('onebot','servers','features','replies') if cfg.get(key)!=incoming.get(key)]
            atomic_json(folder / "preview.json", values)
            return {key: value for key, value in values.items() if key not in ("fingerprint", "archive_sha256", "operations_revision")}
        except BaseException:
            if folder and folder.exists(): remove_stage(folder.parent, folder)
            raise
        finally: self.busy = False

    def check_local(self, cfg):
        local = runtime_config(cfg, self.config.path)["app"]
        if any(local[key] != self.state["config"]["app"][key] for key in ("host", "port", "database")):
            raise BackupError("当前有尚未重启的连接或数据库设置，请先重启后恢复", 409)

    async def restore(self, preview_id):
        self.require()
        if self.state["restart_event"] is None: raise BackupError("此启动方式不支持恢复后的服务重启", 503)
        if self.busy: raise BackupError("备份或恢复操作正在处理中", 409)
        if not isinstance(preview_id, str) or not JOB_ID.fullmatch(preview_id): raise BackupError("预览编号格式错误")
        folder = safe_path(self.root, "staging/" + preview_id)
        if not (folder / "preview.json").is_file(): raise BackupError("预览已失效，请重新上传", 404)
        preview = read_json(folder / "preview.json")
        if preview["expires"] < time.time(): raise BackupError("预览已过期，请重新上传", 410)
        if preview["fingerprint"] != self.fingerprint(): raise BackupError("设置或插件已变化，请重新上传校验", 409)
        if preview.get("operations_revision") != operations_revision(self.state["store"].db):
            raise BackupError("定时任务或申请设置已变化，请重新上传校验", 409)
        cfg, _ = self.config.read(); self.check_local(cfg)
        self.busy = True
        try:
            if await self.work(hash_file, folder / "upload.zip") != preview["archive_sha256"]:
                raise BackupError("上传的备份已变化，请重新上传")
            self.state["maintenance"] = True
            safety = await self.snapshot("before_restore")
            if preview["fingerprint"] != self.fingerprint(): raise BackupError("设置已变化，请重新上传校验", 409)
            if preview["operations_revision"] != operations_revision(self.state["store"].db):
                raise BackupError("定时任务或申请设置已变化，请重新上传校验", 409)
            atomic_json(safe_path(self.base, "data/restore-job.json"), {"stage": preview_id, "phase": "pending",
                        "safety_backup": safety["id"], "fingerprint": preview["fingerprint"], "operations_revision":preview["operations_revision"]})
            asyncio.get_running_loop().call_later(0.5, self.state["restart_event"].set)
            return {"accepted": True, "safety_backup": safety["id"], "message": "正在恢复并重启，面板地址和管理令牌保持不变"}
        except BaseException:
            self.state["maintenance"] = False; raise
        finally: self.busy = False


def restore_paths(config_path):
    path = Path(config_path).resolve(); base = path.parent
    return path, base, safe_path(base, "data/restore-job.json")


def restore_file_set(base, config_path):
    result = {"config.toml": config_path}
    result.update({name: safe_path(base, name) for name in FILES.keys() - REQUIRED})
    result.update({"plugins/" + path.name: safe_path(base, "plugins/" + path.name)
                   for path in safe_path(base, "plugins").glob("*.json")})
    for name in result: file_limit(name)
    return result


def write_file(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".restore-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content); output.flush(); os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def replace_database(source, target):
    with closing(readonly_database(source)) as original, closing(sqlite3.connect(target, timeout=10)) as destination:
        original.backup(destination, pages=128)


def load_job(config_path):
    config_path, base, journal = restore_paths(config_path)
    if not journal.exists(): return None
    job = read_json(journal)
    if (not isinstance(job, dict) or not isinstance(job.get("stage"), str) or not JOB_ID.fullmatch(job["stage"])
            or job.get("phase") not in ("pending", "applying", "applied")
            or not isinstance(job.get("safety_backup"), str) or not ID.fullmatch(job["safety_backup"])):
        raise BackupError("恢复日志损坏，请保留 data/backups 并联系管理员处理")
    folder = safe_path(base, "data/backups/staging/" + job["stage"])
    return config_path, base, journal, folder, job


def rollback_restore(config_path, message="恢复失败，已恢复操作前的数据和设置"):
    loaded = load_job(config_path)
    if not loaded: return
    config_path, base, journal, folder, job = loaded
    if job["phase"] != "pending":
        rollback = folder / "rollback"
        cfg = validate(tomllib.loads((rollback / "config.toml").read_text(encoding="utf-8")))
        database = runtime_config(cfg, config_path)["app"]["database"]
        paths = restore_file_set(base, config_path)
        existing = job["original_files"]
        for name in existing: file_limit(name)
        paths.update({name: config_path if name == "config.toml" else safe_path(base, name) for name in existing})
        for name, path in paths.items():
            if name in existing: write_file(path, safe_path(rollback, name).read_bytes())
            elif path.exists(): path.unlink()
        replace_database(rollback / "database.sqlite3", database)
    atomic_json(safe_path(base, "data/last-restore.json"), {"status": "rolled_back", "message": message,
                "time": datetime.now(timezone.utc).isoformat(), "safety_backup": job["safety_backup"]})
    journal.unlink()


def apply_pending_restore(config_path):
    loaded = load_job(config_path)
    if not loaded: return False
    config_path, base, journal, folder, job = loaded
    if job["phase"] != "pending":
        rollback_restore(config_path, "上次恢复中断，已自动回滚到恢复前的数据与设置")
        return False
    try:
        current_paths = restore_file_set(base, config_path)
        files = {name: path.read_bytes() for name, path in current_paths.items() if path.exists()}
        fingerprint = hashlib.sha256(encode({name: hashlib.sha256(content).hexdigest() for name, content in files.items()})).hexdigest()
        if fingerprint != job["fingerprint"]: raise BackupError("恢复前设置发生变化，已取消恢复")
        preview = read_json(folder / "preview.json")
        if hash_file(folder / "upload.zip") != preview["archive_sha256"]:
            raise BackupError("上传的备份发生变化，已取消恢复")
        incoming = folder / "verified"
        manifest, _ = unpack_archive(folder / "upload.zip", incoming)
        current = validate(tomllib.loads(files["config.toml"].decode("utf-8")))
        cfg = validate(tomllib.loads((incoming / "config.toml").read_text(encoding="utf-8")))
        cfg["app"] = deepcopy(current["app"]); validate(cfg)
        (incoming / "config.toml").write_text(serialize(cfg), encoding="utf-8")
        check_settings(incoming)
        rollback = folder / "rollback"; rollback.mkdir(exist_ok=True)
        for name, content in files.items(): write_file(safe_path(rollback, name), content)
        database = runtime_config(current, config_path)["app"]["database"]
        if "operations_revision" in job:
            with closing(readonly_database(database)) as db:
                if operations_revision(db) != job["operations_revision"]:
                    raise BackupError("定时任务或申请设置在恢复前变化，已取消恢复")
        copy_database(database, rollback / "database.sqlite3")
        # Refresh the safety snapshot after all HTTP / QQ work has drained. It includes
        # commits made between the confirmation and the service shutting down.
        safety = safe_path(base, "data/backups/" + job["safety_backup"] + ".zip")
        safety_temporary = folder / "safety.zip"
        write_archive(files, rollback / "database.sqlite3", safety_temporary, "before_restore")
        os.replace(safety_temporary, safety)
        job.update(phase="applying", original_files=list(files))
        atomic_json(journal, job)
        with closing(sqlite3.connect(incoming / "database.sqlite3")) as db, db:
            for table in TRANSIENT: db.execute("DELETE FROM " + table)
            db.execute("UPDATE player_actions SET status='cancelled',detail='备份恢复，待执行操作已撤销' WHERE status='pending'")
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
            if "admin_sessions" in tables: db.execute('DELETE FROM admin_sessions')
            if "scheduled_tasks" in tables:
                for task_id, definition in db.execute("SELECT id,definition FROM scheduled_tasks").fetchall():
                    value = json.loads(definition); value["enabled"] = False
                    db.execute("UPDATE scheduled_tasks SET definition=?,status='paused',detail='备份恢复后已暂停，请确认设置后启用',revision=revision+1 WHERE id=?", (json.dumps(value),task_id))
            if "schedule_runs" in tables:
                db.execute("UPDATE schedule_runs SET status='interrupted',detail='备份恢复，未完成执行已撤销' WHERE status IN ('running','submitted')")
            if "whitelist_applications" in tables:
                db.execute("UPDATE whitelist_applications SET status='cancelled',review='备份恢复，下发已撤销；请核对游戏白名单后重试',revision=revision+1 WHERE status='submitted'")
        paths = {**current_paths, **{name: config_path if name == "config.toml" else safe_path(base, name)
                 for name in manifest["files"] if name != "database.sqlite3"}}
        for name, path in paths.items():
            if name in manifest["files"]: write_file(path, safe_path(incoming, name).read_bytes())
            elif path.exists(): path.unlink()
        replace_database(incoming / "database.sqlite3", database)
        job["phase"] = "applied"; atomic_json(journal, job)
        return True
    except (OSError, ValueError, sqlite3.Error):
        rollback_restore(config_path)
        return False


def finish_restore(config_path):
    loaded = load_job(config_path)
    if not loaded: return
    _, base, journal, folder, job = loaded
    if job["phase"] != "applied": raise BackupError("恢复尚未完成")
    atomic_json(safe_path(base, "data/last-restore.json"), {"status": "success", "message": "备份已恢复，旧验证码、登录会话与待执行命令已撤销",
                "time": datetime.now(timezone.utc).isoformat(), "safety_backup": job["safety_backup"]})
    journal.unlink()
    # The transaction is already committed. Temporary cleanup must not turn a
    # successful restore into a false rollback report.
    with suppress(OSError): remove_stage(folder.parent, folder)
