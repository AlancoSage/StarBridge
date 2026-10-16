"""Declarative JSON plugins; plugin files never execute code."""
import asyncio
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
import uuid

from .bot import clean_text
from .qq_identity import user_id, group_id


PLUGIN_API = 1
MAX_PLUGINS = 30
MAX_FILE = 64 * 1024
MAX_STATE = 4 * 1024 * 1024
KEYWORDS_ID = "keyword_replies"
KEYWORDS_PLUGIN = {
    "id": KEYWORDS_ID, "name": "关键词回复", "version": "1.0.0", "author": "Myrinbot",
    "description": "为关联群聊配置关键词与文字回复，精确匹配整条消息。内置命令优先。",
    "settings": {"replies": {"type": "reply_map", "label": "关键词回复", "default": {}}},
    "rules": [{"event": "keyword_reply"}],
}
SCHEDULES_ID = "scheduled_tasks"
SCHEDULES_PLUGIN = {
    "id": SCHEDULES_ID, "name": "定时任务", "version": "1.0.0", "author": "Myrinbot",
    "description": "按北京时间安排群公告、游戏公告、预设命令与备份，保留任务和执行记录。停用插件后暂停所有任务。",
    "settings": {}, "rules": [],
}
BUILTIN_PLUGINS = {KEYWORDS_ID: KEYWORDS_PLUGIN, SCHEDULES_ID: SCHEDULES_PLUGIN}
IDENTIFIER = re.compile(r"[a-z][a-z0-9_]{0,39}")
BUILTINS = {"帮助", "help", "/help", "状态", "在线", "绑定", "我的绑定", "解绑", "执行", "/申请", "/注册", "/确认登录", "/拒绝登录", "/白名单", "/白名单状态"}
PERMISSION_DEFAULT = {"send_group": True, "group_commands": True, "game_events": True,
                      "send_game": True, "execute_commands": True, "create_backups": True,
                      "read_bindings": True, "read_server": True, "servers": [], "groups": [],
                      "user_mode": "all", "allow_users": [], "deny_users": []}
VARIABLE = re.compile(r"\{([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)?)\}")
VARIABLES = {"server_name", "server_id", "group_id", "user_id", "arg", "player", "players", "online_count", "online"}


def invalid_constant(value):
    raise ValueError("JSON 不支持 NaN 或 Infinity")


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True).encode("utf-8")


def permission_value(value):
    if not isinstance(value, dict) or value.keys() - PERMISSION_DEFAULT.keys():
        raise ValueError("插件权限包含未知字段")
    output = {**deepcopy(PERMISSION_DEFAULT), **deepcopy(value)}
    for key in ("send_group", "group_commands", "game_events", "read_bindings", "read_server", "send_game", "execute_commands", "create_backups"):
        if type(output[key]) is not bool:
            raise ValueError("插件权限开关必须是布尔值")
    if output["user_mode"] not in ("all", "bound", "admins"):
        raise ValueError("使用者需选择所有成员、已绑定成员或机器人管理员")
    for key in ("servers", "groups", "allow_users", "deny_users"):
        values = output[key]
        valid = (lambda item: isinstance(item, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,40}", item))) if key == "servers" else group_id if key == "groups" else user_id
        if not isinstance(values, list) or len(values) > 100 or any(not valid(item) for item in values) or len(set(values)) != len(values):
            raise ValueError("权限范围最多 100 项且不能重复；身份需为 QQ / 群号或官机接入身份")
    return output


def atomic_json(path, value, maximum=128 * 1024):
    content = encode(value)
    if len(content) > maximum:
        raise ValueError("设置文件超过允许的大小")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".starbridge-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def setting_value(spec, value):
    kind = spec["type"]
    if kind == "reply_map":
        if not isinstance(value, dict) or len(value) > 200:
            raise ValueError("关键词回复最多 200 项")
        from .settings import string
        for key, reply in value.items():
            string(key, "回复关键词", 80)
            string(reply, "回复内容", 3500)
        return deepcopy(value)
    if kind == "boolean":
        valid = type(value) is bool
    elif kind in ("integer", "number"):
        valid = (type(value) is int if kind == "integer" else type(value) in (int, float))
        valid = valid and -1e9 <= value <= 1e9 and math.isfinite(value) and spec.get("min", -1e9) <= value <= spec.get("max", 1e9)
    elif kind == "select":
        valid = isinstance(value, str) and value in spec["options"]
    else:
        valid = isinstance(value, str) and len(value) <= spec.get("max_length", 2000)
    if not valid:
        raise ValueError(f"设置「{spec['label']}」的值不合法")
    return value


def validate_plugin(data):
    if not isinstance(data, dict) or not isinstance(data.get("id"), str) or not IDENTIFIER.fullmatch(data["id"]):
        raise ValueError("插件 ID 需为小写字母开头的字母、数字或下划线，最多 40 字")
    if type(data.get("api_version")) is not int or data["api_version"] != PLUGIN_API:
        raise ValueError("插件需要 api_version = 1")
    if data["id"] in BUILTIN_PLUGINS:
        raise ValueError("这是内置插件 ID，请在面板内管理对应插件")
    allowed = {"id", "api_version", "name", "version", "description", "author", "settings", "rules", "changelog"}
    if data.keys() - allowed:
        raise ValueError("插件包含不支持的字段；仅支持 JSON 规则，不支持执行代码")
    if not isinstance(data.get("changelog", ""), str) or len(data.get("changelog", "")) > 2000:
        raise ValueError("更新说明最多 2000 字")
    for key, limit in (("name", 80), ("version", 40), ("description", 500), ("author", 80)):
        value = data.get(key, "")
        if not isinstance(value, str) or len(value) > limit or (key in ("name", "version") and not value.strip()):
            raise ValueError(f"插件 {key} 字段格式错误")
    schema = data.get("settings", {})
    if not isinstance(schema, dict) or len(schema) > 20:
        raise ValueError("settings 最多包含 20 个设置项")
    for key, spec in schema.items():
        if (not IDENTIFIER.fullmatch(key) or not isinstance(spec, dict)
            or spec.get("type") not in ("string", "integer", "number", "boolean", "select")
            or not isinstance(spec.get("label"), str) or not 1 <= len(spec["label"]) <= 80
            or not isinstance(spec.get("description", ""), str) or len(spec.get("description", "")) > 500):
            raise ValueError("插件设置声明格式错误")
        if spec.keys() - {"type", "label", "description", "default", "min", "max", "max_length", "options"}:
            raise ValueError("设置声明包含不支持的字段")
        if spec["type"] == "select":
            options = spec.get("options")
            if (not isinstance(options, list) or not 1 <= len(options) <= 30
                or not all(isinstance(v, str) and 1 <= len(v) <= 100 for v in options) or len(set(options)) != len(options)):
                raise ValueError("选择项需要 1–30 个不同的字符串")
        if spec["type"] in ("integer", "number"):
            for bound in ("min", "max"):
                value = spec.get(bound, -1e9 if bound == "min" else 1e9)
                if type(value) not in (int, float) or abs(value) > 1e9 or not math.isfinite(value):
                    raise ValueError("数值设置边界格式错误")
            if spec.get("min", -1e9) > spec.get("max", 1e9):
                raise ValueError("数值设置最小值不能大于最大值")
        if type(spec.get("max_length", 2000)) is not int or not 1 <= spec.get("max_length", 2000) <= 2000:
            raise ValueError("文字设置长度需为 1–2000")
        if "default" not in spec:
            raise ValueError("每个设置项必须声明 default")
        setting_value(spec, spec["default"])
    rules = data.get("rules")
    if not isinstance(rules, list) or not 1 <= len(rules) <= 20:
        raise ValueError("插件需要 1–20 条规则")
    commands = set()
    for rule in rules:
        if (not isinstance(rule, dict) or rule.get("event") not in ("group_command", "player_join", "player_quit")
            or rule.keys() - {"event", "command", "match", "reply", "admin_only", "bound_only", "cooldown", "when"}
            or not isinstance(rule.get("reply"), str) or not 1 <= len(rule["reply"]) <= 2000):
            raise ValueError("规则需要有效的 event 和 1–2000 字的 reply")
        if rule["event"] == "group_command":
            command = rule.get("command")
            if (not isinstance(command, str) or not 1 <= len(command) <= 40 or any(c.isspace() for c in command)
                or command in BUILTINS or command in commands or rule.get("match", "exact") not in ("exact", "prefix")):
                raise ValueError("群命令需为 1–40 字且无空白，不能重复或覆盖内置命令")
            commands.add(command)
        elif "command" in rule or "match" in rule or rule.get("admin_only") or rule.get("bound_only"):
            raise ValueError("游戏事件不支持群命令或 QQ 身份限制")
        for key in ("admin_only", "bound_only"):
            if type(rule.get(key, False)) is not bool:
                raise ValueError("规则权限开关必须是布尔值")
        if type(rule.get("cooldown", 3)) is not int or not 1 <= rule.get("cooldown", 3) <= 3600:
            raise ValueError("规则冷却需为 1–3600 秒")
        when = rule.get("when")
        if when is not None and (not isinstance(when, str) or when not in schema or schema[when]["type"] != "boolean"):
            raise ValueError("when 必须引用一个布尔设置项")
        for variable in VARIABLE.findall(rule["reply"]):
            if variable not in VARIABLES and not (variable.startswith("settings.") and variable[9:] in schema):
                raise ValueError(f"模板变量 {{{variable}}} 不存在")
    return {**data, "settings": schema}


def read_plugin(path):
    if path.stat().st_size > MAX_FILE or path.is_symlink():
        raise ValueError("插件 JSON 不能超过 64 KiB 或使用链接")
    return validate_plugin(json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=invalid_constant))


class PluginConflict(ValueError):
    pass


class PluginManager:
    def __init__(self, base, bot, store):
        self.root = Path(base).resolve() / "plugins"
        self.state_path = Path(base).resolve() / "data" / "plugin-state.json"
        self.bot, self.store = bot, store
        self.lock = asyncio.Lock()
        self.entries, self.saved, self.cooldowns = {}, {}, {}
        self.state_error = ""
        try:
            if self.state_path.exists():
                if self.state_path.stat().st_size > MAX_STATE:
                    raise ValueError("状态文件过大")
                value = json.loads(self.state_path.read_text(encoding="utf-8"), parse_constant=invalid_constant)
                if not isinstance(value, dict):
                    raise ValueError("状态必须是对象")
                self.saved = value
        except (OSError, ValueError):
            self.state_error = "插件状态读取失败，插件未启用。请检查 data/plugin-state.json 后重启。"

    @property
    def revision(self):
        # Definition changes also invalidate a stale panel's settings.
        return hashlib.sha256(encode([self.saved, {k: e["definition"] for k, e in self.entries.items()}])).hexdigest()

    def check_revision(self, revision):
        if self.state_error:
            raise ValueError(self.state_error)
        if revision != self.revision:
            raise PluginConflict("插件设置已变化，请重新载入后再操作")

    def values(self, definition, values):
        schema = definition["settings"]
        if not isinstance(values, dict) or values.keys() - schema.keys():
            raise ValueError("插件设置包含未知字段")
        return {key: setting_value(spec, values.get(key, spec["default"])) for key, spec in schema.items()}

    def listing(self):
        return {"revision": self.revision, "error": self.state_error, "plugins": [
            {**{key: e["definition"].get(key, "") for key in ("id", "name", "version", "description", "author", "changelog")},
             "schema": e["definition"].get("settings", {}), "settings": e["settings"],
             "builtin": e["definition"]["id"] in BUILTIN_PLUGINS,
             "permissions": e["permissions"],
             "enabled": e["enabled"], "status": e["status"], "error": e["error"],
             "rules": [{key: rule[key] for key in ("event", "command", "match", "admin_only", "bound_only") if key in rule}
                       for rule in e["definition"].get("rules", [])]}
            for e in self.entries.values()]}

    def builtin_entry(self, definition):
        plugin_id = definition['id']
        entry = {"path": None, "definition": deepcopy(definition), "settings": {key: deepcopy(spec['default']) for key, spec in definition['settings'].items()},
                 "enabled": False, "status": "disabled", "error": "", "permissions": deepcopy(PERMISSION_DEFAULT)}
        try:
            saved = self.saved.get(plugin_id, {})
            if not isinstance(saved, dict) or type(saved.get("enabled", False)) is not bool:
                raise ValueError("已保存的插件状态无效")
            entry["settings"] = self.values(definition, saved.get("settings", {}))
            entry["permissions"] = permission_value(saved.get("permissions", {}))
            entry["enabled"] = saved.get("enabled", False) and not self.state_error
            entry["status"] = "running" if entry["enabled"] else "disabled"
        except (ValueError, TypeError) as exc:
            entry.update(status="error", error=f"内置插件设置无效：{str(exc)[:200]}")
        return entry

    def keywords_entry(self):
        return self.builtin_entry(KEYWORDS_PLUGIN)

    def discover_all(self):
        # Keep migrated keywords ahead of imported plugins, as before migration.
        return {**{key: self.builtin_entry(definition) for key, definition in BUILTIN_PLUGINS.items()},
                **{p.stem: self.discover(p) for p in self.paths()}}

    def discover(self, path):
        entry = {"path": path, "definition": {"id": path.stem, "name": path.stem},
                 "settings": {}, "enabled": False, "status": "disabled", "error": "", "permissions": deepcopy(PERMISSION_DEFAULT)}
        try:
            definition = read_plugin(path)
            if definition["id"] != path.stem:
                raise ValueError("文件名必须是插件 ID.json")
            entry["definition"] = definition
            saved = self.saved.get(path.stem, {})
            if not isinstance(saved, dict) or type(saved.get("enabled", False)) is not bool:
                raise ValueError("已保存的插件状态无效")
            entry["settings"] = self.values(definition, saved.get("settings", {}))
            entry["permissions"] = permission_value(saved.get("permissions", {}))
            entry["enabled"] = saved.get("enabled", False) and not self.state_error
            entry["status"] = "running" if entry["enabled"] else "disabled"
        except (OSError, ValueError, TypeError, OverflowError) as exc:
            entry.update(status="error", error=f"声明或设置无效：{str(exc)[:200]}")
        return entry

    async def start(self):
        async with self.lock:
            if self.root.resolve() != self.root:
                self.state_error = "插件目录不能使用链接，请使用配置目录下的 plugins 文件夹。"
                return
            self.root.mkdir(parents=True, exist_ok=True)
            if not self.state_error and KEYWORDS_ID not in self.saved:
                # A durable marker prevents a restart from restoring deleted replies or re-enabling the plugin.
                replies = self.values(KEYWORDS_PLUGIN, {"replies": self.bot.cfg.get("replies", {})})
                updated = {**self.saved, KEYWORDS_ID: {"enabled": bool(replies["replies"]), "settings": replies}}
                try:
                    atomic_json(self.state_path, updated, MAX_STATE)
                    self.saved = updated
                    self.store.audit("extension", f"关键词回复已迁移到内置插件，共 {len(replies['replies'])} 项")
                except (OSError, ValueError):
                    self.state_error = "关键词迁移写入失败，原配置已保留。请检查 data 目录权限、磁盘空间和插件状态文件大小后重启。"
            if not self.state_error and SCHEDULES_ID not in self.saved:
                # Only the first migration inherits enabled legacy tasks. The marker persists later stops.
                enabled = False
                for row in self.store.db.execute('SELECT definition FROM scheduled_tasks'):
                    try:
                        enabled = enabled or json.loads(row[0]).get('enabled') is True
                    except (ValueError, TypeError, AttributeError):
                        continue
                updated = {**self.saved, SCHEDULES_ID: {"enabled": enabled, "settings": {}}}
                try:
                    atomic_json(self.state_path, updated, MAX_STATE)
                    self.saved = updated
                    self.store.audit('extension', '定时任务已迁移到内置插件，原任务与执行记录已保留')
                except (OSError, ValueError):
                    self.state_error = '定时任务插件迁移写入失败，任务已暂停。请检查插件状态文件后重启。'
            self.entries = self.discover_all()

    def paths(self):
        return [p for p in sorted(self.root.glob("*.json")) if IDENTIFIER.fullmatch(p.stem) and p.stem not in BUILTIN_PLUGINS][:MAX_PLUGINS]

    async def scan(self, revision):
        async with self.lock:
            self.check_revision(revision)
            self.entries = self.discover_all()
            self.store.audit("extension", "管理员重新扫描插件目录")
            return self.listing()

    async def update(self, plugin_id, data):
        async with self.lock:
            self.check_revision(data.get("revision"))
            entry = self.entries.get(plugin_id)
            if entry is None:
                raise LookupError("插件不存在")
            if entry["status"] == "error":
                raise ValueError("请修复插件声明并重新加载")
            values = self.values(entry["definition"], data.get("settings", entry["settings"]))
            enabled = data.get("enabled", entry["enabled"])
            if type(enabled) is not bool:
                raise ValueError("enabled 必须是布尔值")
            permissions = permission_value(data.get("permissions", entry["permissions"]))
            updated = {**self.saved, plugin_id: {"enabled": enabled, "settings": values, "permissions": permissions}}
            with self.store.db:
                if plugin_id == SCHEDULES_ID and enabled and not entry['enabled']:
                    from .operations import next_run, task_definition
                    now = time.time()
                    for row in self.store.db.execute('SELECT id,definition FROM scheduled_tasks WHERE next_run<=?', (now,)).fetchall():
                        try:
                            definition = task_definition(json.loads(row['definition']))
                        except (ValueError, TypeError):
                            continue
                        if definition['enabled']:
                            self.store.db.execute("UPDATE scheduled_tasks SET next_run=?,status='skipped',detail='插件暂停期间错过的任务已跳过' WHERE id=?", (next_run(definition, now), row['id']))
                atomic_json(self.state_path, updated, MAX_STATE)
            self.saved = updated
            entry.update(settings=values, permissions=permissions, enabled=enabled, status="running" if enabled else "disabled")
            self.store.audit("extension", f"管理员更新插件 {plugin_id}，{'启用' if enabled else '停用'}")
            return self.listing()

    async def reload(self, plugin_id, revision):
        async with self.lock:
            self.check_revision(revision)
            entry = self.entries.get(plugin_id)
            if entry is None:
                raise LookupError("插件不存在")
            self.entries[plugin_id] = self.builtin_entry(BUILTIN_PLUGINS[plugin_id]) if plugin_id in BUILTIN_PLUGINS else self.discover(entry["path"])
            self.store.audit("extension", f"管理员重新加载插件 {plugin_id}")
            return self.listing()

    async def install(self, data, revision):
        async with self.lock:
            self.check_revision(revision)
            if sum(key not in BUILTIN_PLUGINS for key in self.entries) >= MAX_PLUGINS:
                raise ValueError("最多安装 30 个插件")
            if len(encode(data)) > MAX_FILE:
                raise ValueError("插件 JSON 不能超过 64 KiB")
            definition = validate_plugin(data)
            plugin_id = definition["id"]
            target = self.root / (plugin_id + ".json")
            if target.exists() or target.is_symlink():
                raise ValueError("同 ID 插件已存在，请停用并移除旧版本后导入")
            # New packages and reinstalls are always disabled.
            updated = {**self.saved, plugin_id: {"enabled": False, "settings": {}}}
            atomic_json(self.state_path, updated, MAX_STATE)
            self.saved = updated
            atomic_json(target, definition)
            self.entries[plugin_id] = self.discover(target)
            self.entries = {**{k: self.entries[k] for k in BUILTIN_PLUGINS}, **dict(sorted((k, e) for k, e in self.entries.items() if k not in BUILTIN_PLUGINS))}
            self.store.audit("extension", f"管理员导入插件 {plugin_id}，尚未启用")
            return self.listing()

    async def remove(self, plugin_id, revision):
        async with self.lock:
            self.check_revision(revision)
            entry = self.entries.get(plugin_id)
            if entry is None:
                raise LookupError("插件不存在")
            if plugin_id in BUILTIN_PLUGINS:
                raise ValueError("内置插件可停用，无需移除")
            if entry["enabled"]:
                raise ValueError("请先停用插件再移除")
            archive = self.state_path.parent / "plugin-archive"
            archive.mkdir(parents=True, exist_ok=True)
            entry["path"].rename(archive / (plugin_id + "-" + uuid.uuid4().hex + ".json"))
            self.entries.pop(plugin_id)
            self.store.audit("extension", f"管理员移除插件 {plugin_id}，原文件已归档")
            return self.listing()

    def versions(self, plugin_id):
        if plugin_id not in self.entries or plugin_id in BUILTIN_PLUGINS: raise LookupError("外部插件不存在")
        rows = self.store.db.execute('SELECT id,version,created,note FROM plugin_versions WHERE plugin=? ORDER BY created DESC LIMIT 5', (plugin_id,))
        return {"revision":self.revision, "versions":[dict(row) for row in rows]}

    async def upgrade(self, data, revision, version_id=None):
        async with self.lock:
            self.check_revision(revision)
            if version_id:
                plugin_id = data
                row = self.store.db.execute('SELECT * FROM plugin_versions WHERE plugin=? AND id=?',(plugin_id,version_id)).fetchone()
                if not row: raise LookupError("历史版本不存在")
                definition = validate_plugin(json.loads(row['definition']))
                restore_settings = json.loads(row['settings'])
            else:
                if len(encode(data)) > MAX_FILE: raise ValueError("插件 JSON 不能超过 64 KiB")
                definition = validate_plugin(data); plugin_id = definition['id']; restore_settings = None
            entry = self.entries.get(plugin_id)
            if not entry or plugin_id in BUILTIN_PLUGINS: raise LookupError("请先安装这个外部插件")
            if definition['version'] == entry['definition'].get('version'): raise ValueError("版本号相同，无需更新或回退")
            old_definition = read_plugin(entry['path'])
            old_saved = deepcopy(self.saved)
            old_values = deepcopy(self.saved.get(plugin_id, {"enabled":False,"settings":entry['settings'],"permissions":entry['permissions']}))
            source = restore_settings or old_values
            values = {}
            for key, spec in definition['settings'].items():
                try: values[key] = setting_value(spec,source.get('settings',{}).get(key,spec['default']))
                except ValueError: values[key] = spec['default']
            policy = permission_value(source.get('permissions',entry['permissions']))
            updated = {**self.saved,plugin_id:{"enabled":False,"settings":values,"permissions":policy}}
            try:
                atomic_json(entry['path'],definition)
                atomic_json(self.state_path,updated,MAX_STATE)
            except (OSError,ValueError):
                atomic_json(entry['path'],old_definition)
                atomic_json(self.state_path,old_saved,MAX_STATE)
                raise
            try:
                with self.store.db:
                    self.store.db.execute('INSERT INTO plugin_versions VALUES(?,?,?,?,?,?,?)',
                        (uuid.uuid4().hex,plugin_id,old_definition['version'],json.dumps(old_definition,ensure_ascii=False),json.dumps(old_values,ensure_ascii=False),time.time(),definition.get('changelog','') if not version_id else '回退前保存的版本'))
                    self.store.db.execute('DELETE FROM plugin_versions WHERE plugin=? AND id IN (SELECT id FROM plugin_versions WHERE plugin=? ORDER BY created DESC LIMIT -1 OFFSET 5)',(plugin_id,plugin_id))
                    self.store.db.execute('DELETE FROM plugin_versions WHERE id IN (SELECT id FROM plugin_versions ORDER BY created DESC LIMIT -1 OFFSET 150)')
            except Exception:
                atomic_json(entry['path'],old_definition);atomic_json(self.state_path,old_saved,MAX_STATE);raise
            self.saved = updated; self.entries[plugin_id] = self.discover(entry['path'])
            self.store.audit('extension', f"管理员{'回退' if version_id else '更新'}插件 {plugin_id} 到 {definition['version']}，保持停用")
            return self.listing()

    def template(self, entry, rule, server, **extra):
        snap = self.bot.snapshots.get(server["id"], {})
        values = {"server_name": server["name"], "server_id": server["id"], "online_count": len(snap.get("players", [])),
                  "players": "、".join(snap.get("players", [])) or "暂无玩家", "online": "在线" if self.bot.online(server["id"]) else "离线",
                  "group_id": "", "user_id": "", "arg": "", "player": "", **extra}
        values.update({"settings." + key: value for key, value in entry["settings"].items()})
        if not entry["permissions"]["read_server"]:
            values.update(online_count="未授权", players="未授权", online="未授权")
        return VARIABLE.sub(lambda match: str(values[match[1]]), rule["reply"])[:3500]

    def permitted(self, entry, server, group, user=None, event="group_commands"):
        policy = entry["permissions"]
        if not policy["send_group"] or not policy[event]:
            return False
        if policy["servers"] and server["id"] not in policy["servers"]:
            return False
        if policy["groups"] and group not in policy["groups"]:
            return False
        if user is not None:
            if user in policy["deny_users"] or (policy["allow_users"] and user not in policy["allow_users"]):
                return False
            if policy["user_mode"] == "admins" and user not in self.bot.cfg["onebot"].get("admins", []):
                return False
            if policy["user_mode"] == "bound" and not self.store.binding(server["id"], user):
                return False
        return True

    def ready(self, entry, rule, index, scope):
        when = rule.get("when")
        if when is not None and not entry["settings"][when]:
            return False
        now = time.monotonic()
        if len(self.cooldowns) >= 10000:
            self.cooldowns = {key: deadline for key, deadline in self.cooldowns.items() if deadline > now}
            if len(self.cooldowns) >= 10000:
                return False
        key = (entry["definition"]["id"], index, scope)
        if self.cooldowns.get(key, 0) > now:
            return False
        self.cooldowns[key] = now + rule.get("cooldown", 3)
        return True

    async def group_message(self, server, group, user, text):
        async with self.lock:
            keywords = self.entries.get(KEYWORDS_ID)
            if keywords and keywords["status"] == "running" and text in keywords["settings"]["replies"]:
                if not self.permitted(keywords, server, group, user):
                    return True
                if self.bot.allow(("plugin", KEYWORDS_ID), count=12, period=10):
                    # Literal text: braces and CQ syntax are never interpreted.
                    await self.bot.reply(group, keywords["settings"]["replies"][text], text)
                    self.store.audit("extension", f"插件 {KEYWORDS_ID} 响应关键词 {text}")
                return True
            for entry in self.entries.values():
                if entry["status"] != "running":
                    continue
                for index, rule in enumerate(entry["definition"]["rules"]):
                    if rule["event"] != "group_command":
                        continue
                    command = rule["command"]
                    prefix = rule.get("match", "exact") == "prefix"
                    if text != command and not (prefix and text.startswith(command + " ")):
                        continue
                    if not self.permitted(entry, server, group, user):
                        return True
                    if rule.get("when") is not None and not entry["settings"][rule["when"]]:
                        continue
                    if not self.ready(entry, rule, index, (group, user)):
                        return True
                    if not self.bot.allow(("plugin", entry["definition"]["id"]), count=12, period=10):
                        return True
                    if rule.get("admin_only") and user not in self.bot.cfg["onebot"].get("admins", []):
                        reply = "此插件命令仅限机器人管理员使用。"
                    elif rule.get("bound_only") and not self.store.binding(server["id"], user):
                        reply = "请先绑定游戏账号后再使用此命令。"
                    else:
                        row = self.store.binding(server["id"], user) if entry["permissions"]["read_bindings"] else None
                        reply = self.template(entry, rule, server, group_id=group, user_id=user,
                                              arg=text[len(command):].strip(), player=row["name"] if row else "未绑定")
                    # Text segments are escaped by OneBot.send_group; no CQ code execution.
                    await self.bot.reply(group, reply, command)
                    self.store.audit("extension", f"插件 {entry['definition']['id']} 响应命令 {command}")
                    return True
            return False

    async def game_event(self, server, event):
        trigger = {"join": "player_join", "quit": "player_quit"}.get(event["kind"])
        if not trigger:
            return
        async with self.lock:
            for entry in self.entries.values():
                if entry["status"] != "running":
                    continue
                for index, rule in enumerate(entry["definition"]["rules"]):
                    if rule["event"] != trigger or not self.ready(entry, rule, index, (server["id"], event.get("uuid") or event["player"])):
                        continue
                    for group in server["groups"]:
                        if not self.permitted(entry, server, group, event="game_events"):
                            continue
                        if not self.bot.allow(("plugin", entry["definition"]["id"]), count=12, period=10):
                            break
                        try:
                            reply = self.template(entry, rule, server, group_id=group, player=clean_text(event["player"], 32))
                            await self.bot.onebot.send_group(group, reply)
                        except (ConnectionError, RuntimeError, TimeoutError):
                            self.store.audit("error", f"插件 {entry['definition']['id']} 游戏通知发送失败，不重放")
