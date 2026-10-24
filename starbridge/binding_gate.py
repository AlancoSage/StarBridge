"""Per-server QQ binding admission checks, independent from game authentication."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import unicodedata
import uuid

from .extensions import atomic_json, encode, invalid_constant
from .qq_identity import user_id
from .registration import RegistrationError


MAX_SETTINGS = 32 * 1024
DEFAULTS = {"enabled_servers": [],
            "message": "此服务器要求先绑定 QQ。请联系管理员核实身份并完成绑定后再连接。"}
UNAVAILABLE_MESSAGE = "绑定检查暂不可用，请稍后重新连接或联系管理员。"
UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def validate_settings(value):
    if not isinstance(value, dict) or value.keys() != DEFAULTS.keys():
        raise RegistrationError("强制绑定设置需包含完整的服务器列表与拒绝入服提示")
    result = deepcopy(value)
    ids = result["enabled_servers"]
    if (not isinstance(ids, list) or len(ids) > 100
            or any(not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", sid) for sid in ids)
            or len(set(ids)) != len(ids)):
        raise RegistrationError("强制绑定服务器列表格式错误")
    message = result["message"]
    if (not isinstance(message, str) or not message.strip() or len(message) > 300
            or any(unicodedata.category(char).startswith("C") for char in message)):
        raise RegistrationError("拒绝入服提示需为 1–300 个字符，不能包含控制字符")
    result["enabled_servers"] = sorted(ids)
    return result


def player_identity(data):
    if not isinstance(data, dict) or data.keys() - {"uuid", "player", "nonce"}:
        raise RegistrationError("绑定检查包含未知字段")
    identity, player = data.get("uuid"), data.get("player")
    if (not isinstance(identity, str) or not UUID.fullmatch(identity)
            or not isinstance(player, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,16}", player)):
        raise RegistrationError("需要合法的玩家 UUID 和 Java 版玩家名")
    if "nonce" in data and (not isinstance(data["nonce"], str) or not UUID.fullmatch(data["nonce"])):
        raise RegistrationError("连接 nonce 需为合法 UUID")
    return str(uuid.UUID(identity)), player


class BindingGate:
    def __init__(self, base, bot):
        self.path = Path(base) / "data" / "binding-gate-settings.json"
        self.bot, self.store = bot, bot.store
        self.settings, self.error = deepcopy(DEFAULTS), ""
        self.lock = asyncio.Lock()
        self._persisted = False
        self._revision = hashlib.sha256(encode(DEFAULTS)).hexdigest()
        self.reload()

    def reload(self):
        """Observe disk edits and corruption without ever silently disabling a live gate."""
        content = None
        try:
            if self.path.is_symlink():
                raise ValueError("设置不能使用符号链接")
            try:
                with self.path.open("rb") as source:
                    content = source.read(MAX_SETTINGS + 1)
            except FileNotFoundError:
                if self._persisted:
                    raise ValueError("已保存的设置文件缺失") from None
                self.settings, self.error = deepcopy(DEFAULTS), ""
                self._revision = hashlib.sha256(encode(DEFAULTS)).hexdigest()
                return
            self._persisted = True
            self._revision = hashlib.sha256(content).hexdigest()
            if len(content) > MAX_SETTINGS:
                raise ValueError("设置文件过大")
            self.settings = validate_settings(json.loads(content, parse_constant=invalid_constant))
            self.error = ""
        except (ValueError, TypeError, OSError):
            if content is None:
                self._revision = hashlib.sha256(b"binding-gate-settings-unavailable").hexdigest()
            self.error = "强制绑定设置读取失败，已拒绝游戏连接。请修复设置或由服主重新保存。"

    @property
    def revision(self):
        return self._revision

    def servers(self):
        result = []
        for sid in sorted(set(self.bot.servers) | set(self.settings["enabled_servers"])):
            server = self.bot.servers.get(sid)
            snapshot = self.bot.snapshots.get(sid, {})
            result.append({"id": sid, "name": server["name"] if server else sid,
                           "online": bool(server and self.bot.online(sid)),
                           "supported": bool(server and "binding_gate" in snapshot.get("capabilities", [])),
                           "missing": server is None})
        return result

    def config(self):
        self.reload()
        return {"settings": deepcopy(self.settings), "revision": self.revision,
                "error": self.error, "servers": self.servers()}

    def policy(self, sid):
        self.reload()
        return {"required": bool(self.error) or sid in self.settings["enabled_servers"],
                "available": not bool(self.error), "revision": self.revision,
                "message": UNAVAILABLE_MESSAGE if self.error else self.settings["message"]}

    async def save(self, settings, revision):
        async with self.lock:
            self.reload()
            if not isinstance(revision, str) or revision != self.revision:
                raise RegistrationError("强制绑定设置已变化，请重新载入", 409, "conflict")
            value = validate_settings(settings)
            newly_enabled = set(value["enabled_servers"]) - set(self.settings["enabled_servers"])
            for sid in newly_enabled:
                server = self.bot.servers.get(sid)
                if server is None:
                    raise RegistrationError("强制绑定服务器尚未配置")
                if not self.bot.online(sid):
                    raise RegistrationError("启用强制绑定前请先连接目标服务器")
                if "binding_gate" not in self.bot.snapshots.get(sid, {}).get("capabilities", []):
                    raise RegistrationError("目标服务器桥接插件尚不支持强制绑定，请先更新 Bukkit 插件")
            try:
                atomic_json(self.path, value, maximum=MAX_SETTINGS)
            except OSError:
                raise RegistrationError("强制绑定设置保存失败，请检查磁盘和访问权限", 503) from None
            self.settings, self.error, self._persisted = value, "", True
            self._revision = hashlib.sha256(encode(value)).hexdigest()
            self.store.audit("binding", "服主更新强制绑定设置")
            return self.config()

    def check(self, sid, data):
        identity, _player = player_identity(data)
        policy = self.policy(sid)
        if not policy["available"]:
            return {**policy, "allowed": False}
        if not policy["required"]:
            return {**policy, "allowed": True}
        try:
            # UUID, never a matching name, is the admission identity. Names may change.
            # Do not collapse official app-scoped OpenIDs into traditional QQ numbers.
            row = self.store.db.execute("SELECT qq FROM bindings WHERE server=? AND uuid=?", (sid, identity)).fetchone()
        except sqlite3.Error:
            return {**policy, "available": False, "allowed": False, "message": UNAVAILABLE_MESSAGE}
        return {**policy, "allowed": bool(row and user_id(row["qq"]))}
