"""Community settings and explicit public/private projections of player data."""
import asyncio
from copy import deepcopy
import hashlib
import json
import re
import secrets
import time
from urllib.parse import urlsplit
import uuid

from .extensions import atomic_json, invalid_constant
from .passwords import check_password
from .registration import RegistrationError

DEFAULTS = {"title": "VexBot社区", "subtitle": "在这里，开启下一段冒险。",
            "description": "和朋友一起创造、探索，让每一次相遇都留下故事。",
            "rules": "友善交流，尊重其他玩家，共同维护游戏环境。", "join_address": "",
            "group_url": "", "public_players": True, "public_servers": True, "login_enabled": True,
            "accent_color": "#54745d", "secondary_color": "#b78758", "theme_mode": "system", "grid_background": True,
            "website_url": "", "api_public_url": "", "connection_enabled": False, "website_mode": "none"}
TEXT_LIMITS = {"title": 60, "subtitle": 160, "description": 1000, "rules": 2000,
               "join_address": 160, "group_url": 500}


def validate_settings(value):
    if not isinstance(value, dict) or value.keys() - DEFAULTS.keys():
        raise RegistrationError("官网设置包含未知字段")
    result = {**DEFAULTS, **value}
    if "website_mode" not in value:
        result["website_mode"] = "custom" if result["connection_enabled"] else "none"
    if result["website_mode"] not in ("none", "provided", "custom"):
        raise RegistrationError("官网接入方式需为 none、provided 或 custom")
    for key, maximum in TEXT_LIMITS.items():
        text = result[key]
        if not isinstance(text, str) or len(text) > maximum or any(ord(c) < 32 and c not in "\n\t" for c in text):
            raise RegistrationError("官网文字格式或长度错误")
        result[key] = text.strip()
    if not result["title"]:
        raise RegistrationError("官网名称不能为空")
    for key in ("public_players", "public_servers", "login_enabled", "grid_background", "connection_enabled"):
        if type(result[key]) is not bool:
            raise RegistrationError("官网开关需为布尔值")
    result["connection_enabled"] = result["website_mode"] != "none"
    for key in ("accent_color", "secondary_color"):
        if not isinstance(result[key], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", result[key]):
            raise RegistrationError("主题颜色需为 #RRGGBB 格式")
        result[key] = result[key].lower()
    if result["theme_mode"] not in ("system", "light", "dark"):
        raise RegistrationError("官网外观模式需为 system、light 或 dark")
    result["website_url"] = website_url(result["website_url"])
    if result["api_public_url"]:
        result["api_public_url"] = api_base(result["api_public_url"])
    elif not isinstance(result["api_public_url"], str):
        raise RegistrationError("Bot API 地址需为字符串")
    if result["connection_enabled"] and not result["website_url"]:
        raise RegistrationError("启用网站接入前，请填写独立网站地址")
    if result["group_url"]:
        url = urlsplit(result["group_url"])
        if (url.scheme not in ("http", "https") or not url.hostname or url.username or url.password
                or any(c.isspace() for c in result["group_url"])):
            raise RegistrationError("入群链接需为 HTTP 或 HTTPS 地址")
        try:
            url.port
        except ValueError:
            raise RegistrationError("入群链接端口格式错误") from None
    return result


def website_url(value):
    if value == "":
        return value
    if not isinstance(value, str) or len(value) > 1000 or any(c.isspace() for c in value):
        raise RegistrationError("网站地址格式错误")
    try:
        url = urlsplit(value)
        origin = website_origin(value)
        if url.username or url.password or url.query or url.fragment:
            raise ValueError()
        return origin + (url.path or "/")
    except (ValueError, UnicodeError):
        raise RegistrationError("网站地址需为 HTTP(S) 链接，不包含账号、查询参数或片段") from None


def website_origin(value):
    url = urlsplit(value)
    if url.scheme not in ("http", "https") or not url.hostname:
        raise ValueError("网站来源格式错误")
    host = url.hostname.encode("idna").decode().lower()
    if ":" in host:
        import ipaddress
        host = "[" + str(ipaddress.IPv6Address(host)) + "]"
    port = url.port
    return url.scheme + "://" + host + (":" + str(port) if port is not None and port != (443 if url.scheme == "https" else 80) else "")


def api_base(value):
    if value == "/api/v1":
        return value
    if not isinstance(value, str) or len(value) > 500 or any(c.isspace() for c in value):
        raise RegistrationError("API 地址格式错误")
    value = value.rstrip("/")
    url = urlsplit(value)
    if (url.scheme not in ("http", "https") or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.path != "/api/v1"):
        raise RegistrationError("填写VexBot的公开 API 地址，例如 https://bridge.example.com/api/v1")
    try:
        url.port
    except ValueError:
        raise RegistrationError("API 端口格式错误") from None
    return value


class Website:
    def __init__(self, base, state):
        self.path = base / "data/website-settings.json"
        self.state = state
        self.settings = deepcopy(DEFAULTS)
        self.error = ""
        self.generation = 0
        self.lock = asyncio.Lock()
        try:
            if self.path.exists():
                if self.path.stat().st_size > 32768:
                    raise ValueError("文件过大")
                self.settings = validate_settings(json.loads(self.path.read_text(encoding="utf-8"), parse_constant=invalid_constant))
        except (OSError, ValueError, TypeError):
            self.error = "官网设置读取失败，请检查 data/website-settings.json，或在面板重新保存。"
            self.settings.update(public_players=False, public_servers=False, login_enabled=False)

    @property
    def revision(self):
        return hashlib.sha256(json.dumps([self.settings, self.error], sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def config_response(self):
        return {"settings": deepcopy(self.settings), "revision": self.revision, "error": self.error,
                "connection": {"origin": self.connected_origin, "enabled": self.settings["connection_enabled"],
                               "mode": self.settings["website_mode"]}}

    @property
    def connected_origin(self):
        return website_origin(self.settings["website_url"]) if self.settings["website_url"] else ""

    async def save(self, settings, revision):
        async with self.lock:
            if revision != self.revision:
                raise RegistrationError("官网设置已被修改，请重新载入后保存", 409, "revision_conflict")
            value = validate_settings(settings)
            atomic_json(self.path, value)
            self.settings, self.error = value, ""
            self.generation += 1
            self.state["store"].audit("website", "官网设置已更新")
            return self.config_response()

    @property
    def db(self):
        return self.state["store"].db

    def info(self):
        reg = self.state["registration"]
        public = {key:value for key,value in self.settings.items() if key not in ("website_url", "api_public_url", "connection_enabled", "website_mode")}
        return {**public, "registration_enabled": reg.settings["enabled"] and not reg.error,
                "password_reset_enabled": self.state["authentication"].reset_available(),
                "code_minutes": reg.settings["code_minutes"]}

    def servers(self):
        if not self.settings["public_servers"]:
            raise RegistrationError("服务器信息未公开", 403, "servers_private")
        bot = self.state["bot"]
        result = []
        for server in self.state["config"]["servers"]:
            fresh = bot.online(server["id"])
            snap = bot.snapshots.get(server["id"], {})
            result.append({"id": server["id"], "name": server["name"], "connected": fresh,
                           "online_count": len(snap.get("players", [])) if fresh else None,
                           "max_players": snap.get("max_players") if fresh else None})
        return {"servers": result}

    def status(self, profile_id, name, uid, server=None):
        bot = self.state["bot"]
        configured = {s["id"] for s in self.state["config"]["servers"]}
        states = []
        for visit in self.db.execute("SELECT server FROM player_visits WHERE profile=?", (profile_id,)):
            sid = visit["server"]
            if sid not in configured or server is not None and sid != server or not bot.online(sid):
                continue
            snap = bot.snapshots.get(sid, {})
            record = next((p for p in snap.get("player_records", []) if p["uuid"] == uid), None)
            if record:
                states.append("online" if record.get("online") else "offline")
            elif name in snap.get("players", []):
                states.append("online")
            elif "player_management" in snap.get("capabilities", []) and not snap.get("players_truncated", False):
                states.append("offline")
        return "online" if "online" in states else "offline" if "offline" in states else "unknown"

    def public_player(self, row):
        return {"name": row["name"], "uuid": row["uuid"], "status": self.status(row["id"], row["name"], row["uuid"])}

    def require_public(self):
        if not self.settings["public_players"]:
            raise RegistrationError("玩家档案未公开", 403, "players_private")

    def players(self, query="", page=1, page_size=24):
        self.require_public()
        if len(query) > 64 or not 1 <= page <= 10000 or not 1 <= page_size <= 50:
            raise RegistrationError("搜索或分页参数错误")
        query = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        params = (query, query)
        where = "deleted=0 AND (name LIKE ? ESCAPE '\\' OR uuid LIKE ? ESCAPE '\\')"
        total = self.db.execute("SELECT COUNT(*) FROM player_profiles WHERE " + where, params).fetchone()[0]
        rows = self.db.execute("SELECT id,name,uuid FROM player_profiles WHERE " + where + " ORDER BY id DESC LIMIT ? OFFSET ?",
                               (*params, page_size, (page - 1) * page_size)).fetchall()
        return {"players": [self.public_player(row) for row in rows], "page": page, "page_size": page_size, "total": total}

    def player(self, uid):
        self.require_public()
        try:
            uid = str(uuid.UUID(uid))
        except (ValueError, TypeError, AttributeError):
            raise RegistrationError("UUID 格式错误") from None
        row = self.db.execute("SELECT id,name,uuid FROM player_profiles WHERE uuid=? AND deleted=0", (uid,)).fetchone()
        if not row:
            raise RegistrationError("玩家档案不存在", 404, "player_missing")
        return {"player": self.public_player(row)}

    def profile(self, account):
        # Ownership comes from verified UUID links or the account's verified QQ,
        # never from a mutable name shared with a Minecraft profile.
        links = self.db.execute("SELECT server,uuid FROM account_game_links WHERE account_id=? UNION SELECT server,uuid FROM bindings WHERE qq=? LIMIT 101",
                                (account["id"], account["qq"] or "")).fetchall()
        servers = {s["id"]: s["name"] for s in self.state["config"]["servers"]}
        profiles = []
        for link in links[:100]:
            row = self.db.execute("SELECT id,name,uuid,created,last_seen FROM player_profiles WHERE uuid=? AND deleted=0", (link["uuid"],)).fetchone()
            if not row:
                continue
            visit = self.db.execute("SELECT first_seen,last_seen FROM player_visits WHERE profile=? AND server=?", (row["id"], link["server"])).fetchone()
            profiles.append({"name": row["name"], "uuid": row["uuid"], "server": link["server"],
                             "server_name": servers.get(link["server"], "历史服务器"),
                             "status": self.status(row["id"], row["name"], row["uuid"], link["server"]),
                             "first_seen": visit["first_seen"] if visit else row["created"],
                             "last_seen": visit["last_seen"] if visit else row["last_seen"]})
        return {"account": account, "game_profiles": profiles, "truncated": len(links) > 100}

    async def login(self, player, password, remote):
        if not self.settings["login_enabled"]:
            raise RegistrationError("官网登录暂未开放", 503, "login_disabled")
        if (not isinstance(player, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,16}", player)
                or not isinstance(password, str) or not 8 <= len(password) <= 128
                or any(ord(c) < 32 or ord(c) == 127 for c in password)):
            raise RegistrationError("玩家名或密码错误", 401, "credentials_invalid")
        reg = self.state["registration"]
        reg.limit("website-login-ip:" + remote, 30, 300)
        reg.limit("website-login-name:" + player.lower(), 8, 300)
        reg.limit("website-login-global", 120, 60)
        row = self.db.execute("SELECT a.id,p.password_hash FROM registration_accounts a LEFT JOIN account_passwords p ON p.account_id=a.id WHERE a.player_key=?", (player.lower(),)).fetchone()
        digest = row["password_hash"] if row and row["password_hash"] else "pbkdf2_sha256$600000$" + "0" * 32 + "$" + "0" * 64
        generation = (self.generation, reg.generation)
        valid = await reg.password_work.run(check_password, password, digest)
        latest = self.db.execute("SELECT password_hash FROM account_passwords WHERE account_id=?", (row["id"],)).fetchone() if row else None
        if generation != (self.generation, reg.generation) or not self.settings["login_enabled"]:
            raise RegistrationError("登录设置已改变，请重试", 409, "login_changed")
        if not valid or not latest or latest["password_hash"] != digest:
            raise RegistrationError("玩家名或密码错误", 401, "credentials_invalid")
        account = reg.account(row["id"])
        token = secrets.token_urlsafe(32)
        with self.db:
            self.db.execute("DELETE FROM registration_sessions WHERE expires<=?", (time.time(),))
            # At most ten active website sessions per account.
            self.db.execute("DELETE FROM registration_sessions WHERE token_hash IN (SELECT token_hash FROM registration_sessions WHERE account_id=? ORDER BY expires DESC LIMIT -1 OFFSET 9)", (row["id"],))
            self.db.execute("INSERT INTO registration_sessions(token_hash,account_id,expires) VALUES(?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), row["id"], time.time() + 3600))
        return {"account": account, "access_token": token, "token_type": "Bearer", "expires_in": 3600}

    def logout(self, token):
        self.state["registration"].account_for_token(token)
        with self.db:
            self.db.execute("DELETE FROM registration_sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
        return {"logged_out": True}
