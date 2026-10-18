"""Minecraft connection authentication: website password or bound QQ approval."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import secrets
import time
import uuid

from .extensions import atomic_json
from .passwords import check_password, hash_password, validate_password
from .registration import RegistrationError, code_hash, mail_address
from .catalog import address


DEFAULTS = {"enabled_servers": [], "login_engine": "auto", "password_login": True, "qq_login": True,
            "login_seconds": 120, "qq_seconds": 90, "max_attempts": 5, "qq_cooldown": 30}


def validate_settings(value):
    if not isinstance(value, dict) or value.keys() - DEFAULTS.keys():
        raise RegistrationError("游戏登录设置包含未知字段")
    result = {**deepcopy(DEFAULTS), **value}
    if result["login_engine"] not in ("auto", "builtin", "authme", "nlogin", "loginsecurity", "librelogin"):
        raise RegistrationError("登录引擎请选择自动、VexBot内置、AuthMe、nLogin、LoginSecurity 或 LibreLogin 兼容")
    ids = result["enabled_servers"]
    if (not isinstance(ids, list) or len(ids) > 100
            or any(not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", sid) for sid in ids)
            or len(set(ids)) != len(ids)):
        raise RegistrationError("登录服务器列表格式错误")
    for key in ("password_login", "qq_login"):
        if type(result[key]) is not bool:
            raise RegistrationError("登录方式必须为布尔值")
    if ids and not (result["password_login"] or result["qq_login"]):
        raise RegistrationError("启用登录时请选择一种登录方式")
    for key, low, high in (("login_seconds", 30, 600), ("qq_seconds", 30, 300),
                           ("max_attempts", 1, 10), ("qq_cooldown", 15, 300)):
        if type(result[key]) is not int or not low <= result[key] <= high:
            raise RegistrationError(f"{key} 需为 {low}–{high} 的整数")
    return result


class Authentication:
    def __init__(self, base, bot, registration):
        self.path = Path(base) / "data" / "authentication-settings.json"
        self.bot, self.registration, self.store = bot, registration, registration.store
        self.settings, self.error = deepcopy(DEFAULTS), ""
        self.sessions, self.lock = {}, asyncio.Lock()
        try:
            if self.path.exists():
                if self.path.stat().st_size > 32 * 1024:
                    raise ValueError("设置文件过大")
                self.settings = validate_settings(json.loads(self.path.read_text(encoding="utf-8")))
        except (ValueError, TypeError, OSError):
            # Unreadable authentication settings must never silently turn login off.
            self.error = "游戏登录设置读取失败，已拒绝游戏登录。请检查 data/authentication-settings.json 后重启。"
        self.store.db.executescript("""
            CREATE TABLE IF NOT EXISTS password_challenges (
                id TEXT PRIMARY KEY, account_id TEXT NOT NULL, code_hash TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL,
                expires REAL NOT NULL, settings_revision TEXT NOT NULL
            );
        """)

    @property
    def revision(self):
        return hashlib.sha256(json.dumps(self.settings, sort_keys=True).encode()).hexdigest()

    def config_response(self):
        return {"settings": deepcopy(self.settings), "revision": self.revision, "error": self.error}

    def policy(self, sid):
        return {"required": bool(self.error) or sid in self.settings["enabled_servers"],
                "available": not bool(self.error), "revision": self.revision,
                **{key: self.settings[key] for key in ("login_engine", "password_login", "qq_login", "login_seconds", "qq_seconds")}}

    async def save_settings(self, settings, revision):
        async with self.lock:
            if self.error:
                raise RegistrationError(self.error, 503, "settings_unavailable")
            if revision != self.revision:
                raise RegistrationError("游戏登录设置已变化，请重新载入", 409, "conflict")
            value = validate_settings(settings)
            if set(value["enabled_servers"]) - self.bot.servers.keys():
                raise RegistrationError("登录服务器列表包含尚未配置的服务器")
            atomic_json(self.path, value)
            self.settings = value
            self.sessions.clear()
            self.store.audit("authentication", "管理员更新游戏登录设置；旧游戏登录会话已失效")
            return self.config_response()

    @staticmethod
    def identity(data):
        try:
            identity = str(uuid.UUID(data["uuid"]))
            nonce = str(uuid.UUID(data["nonce"]))
            player = data["player"]
            if not isinstance(player, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,16}", player):
                raise ValueError()
            return identity, nonce, player
        except (ValueError, TypeError, AttributeError, KeyError):
            raise RegistrationError("需要玩家 UUID、连接 nonce 和合法玩家名") from None

    def current(self, server, data):
        identity, nonce, player = self.identity(data)
        session = self.sessions.get((server["id"], identity))
        if not session or session["nonce"] != nonce or session["player"] != player:
            raise RegistrationError("游戏连接已变化，请重新进入服务器", 409, "connection_changed")
        if session["status"] == "pending" and session["expires"] <= time.time():
            session.update(status="denied", message="登录超时，请重新进入服务器")
        return session

    def response(self, session):
        return {"uuid": session["uuid"], "nonce": session["nonce"], "status": session["status"],
                "revision": self.revision,
                "message": session["message"], "expires_in": max(0, int(session["expires"] - time.time()))}

    def account_for_player(self, player):
        return self.store.db.execute("SELECT * FROM registration_accounts WHERE player_key=?", (player.lower(),)).fetchone()

    def binding(self, sid, session):
        row = self.store.db.execute("SELECT * FROM bindings WHERE server=? AND uuid=?", (sid, session["uuid"])).fetchone()
        if row and row["name"].lower() == session["player"].lower():
            return row
        return None

    def link(self, server, session, method):
        account = self.account_for_player(session["player"])
        if account:
            link = self.store.db.execute("SELECT uuid FROM account_game_links WHERE account_id=? AND server=?", (account["id"], server["id"])).fetchone()
            owner = self.store.db.execute("SELECT account_id FROM account_game_links WHERE server=? AND uuid=?", (server["id"], session["uuid"])).fetchone()
            if (link and link["uuid"] != session["uuid"]) or (owner and owner["account_id"] != account["id"]):
                raise RegistrationError("游戏 UUID 与已验证账号不符，请联系管理员重置游戏身份", 409, "identity_mismatch")
            binding = self.binding(server["id"], session)
            if not link and binding and account["qq"] != binding["qq"]:
                if method == "qq":
                    # A later website name claim cannot take over or block an existing bound player.
                    return
                raise RegistrationError("此游戏身份已有不同 QQ 的绑定，请用绑定 QQ 登录并联系管理员核对注册账号", 409, "identity_mismatch")
            with self.store.db:
                self.store.db.execute("INSERT OR IGNORE INTO account_game_links VALUES(?,?,?)", (account["id"], server["id"], session["uuid"]))

    def authenticated(self, server, session, method):
        self.link(server, session, method)
        session.update(status="authenticated", message="登录成功，欢迎回来！", challenge=None)
        self.store.audit("authentication", f"{server['id']}/{session['player']} 通过{'密码' if method == 'password' else 'QQ 确认'}登录")

    def allowed(self, sid, identity, nonce=None, player=None):
        if self.error:
            return False
        if not self.policy(sid)["required"]:
            return True
        session = self.sessions.get((sid, identity))
        return bool(session and session["status"] == "authenticated" and session["nonce"] == nonce
                    and session["player"] == player and session["last_seen"] > time.time() - 15)

    async def action(self, server, data):
        if self.error:
            raise RegistrationError(self.error, 503, "authentication_unavailable")
        sid, action = server["id"], data.get("action")
        identity, nonce, player = self.identity(data)
        if action not in ("join", "password", "qq", "leave"):
            raise RegistrationError("游戏登录操作无效")
        if not self.policy(sid)["required"]:
            return {"uuid": identity, "nonce": nonce, "revision": self.revision, "status": "disabled", "message": "服务器未启用游戏登录"}
        if action == "join":
            now = time.time()
            try:
                ip = address(data.get("ip", ""))
            except ValueError:
                raise RegistrationError("游戏连接 IP 格式错误") from None
            self.sessions = {key: value for key, value in self.sessions.items() if value["last_seen"] > now - 300}
            previous = self.sessions.get((sid, identity))
            if previous and previous["nonce"] == nonce:
                return self.response(self.current(server, data))
            if len(self.sessions) >= 2000:
                raise RegistrationError("认证会话已满，请稍后重试", 503, "authentication_busy")
            session = {"uuid": identity, "nonce": nonce, "player": player, "ip": ip,
                       "started": now, "expires": now + self.settings["login_seconds"], "last_seen": now,
                       "status": "pending", "attempts": 0, "challenge": None,
                       "message": "请使用 /login <密码> 或 /qqlogin 登录"}
            self.sessions[(sid, identity)] = session
            return self.response(session)
        session = self.current(server, data)
        if action == "leave":
            self.sessions.pop((sid, identity), None)
            return {"status": "closed"}
        if session["status"] != "pending":
            return self.response(session)
        if action == "password":
            if not self.settings["password_login"]:
                raise RegistrationError("服务器未开放密码登录", 403, "method_disabled")
            password = validate_password(data.get("password"))
            self.registration.limit(f"game-password:{sid}:{player.lower()}", self.settings["max_attempts"], 300)
            self.registration.limit(f"game-password-ip:{sid}:{session['ip']}", 30, 300)
            session["attempts"] += 1
            account = self.account_for_player(player)
            row = self.store.db.execute("SELECT password_hash FROM account_passwords WHERE account_id=?", (account["id"] if account else "",)).fetchone()
            digest = row["password_hash"] if row else ""
            revision = self.revision
            valid = await self.registration.password_work.run(check_password, password, digest)
            if self.current(server, data) is not session or revision != self.revision:
                raise RegistrationError("登录状态已变化，请重试", 409, "connection_changed")
            latest = self.store.db.execute("SELECT password_hash FROM account_passwords WHERE account_id=?", (account["id"] if account else "",)).fetchone()
            if not latest or latest["password_hash"] != digest:
                valid = False
            if session["status"] != "pending":
                return self.response(session)
            if valid and session["status"] == "pending":
                self.authenticated(server, session, "password")
            elif not valid:
                session["message"] = "玩家名或密码不正确；旧账号可在网页设置密码，也可使用 QQ 登录"
                if session["attempts"] >= self.settings["max_attempts"]:
                    session.update(status="denied", message="密码尝试次数过多，请稍后重新进入服务器")
            return self.response(session)
        return await self.request_qq(server, session)

    async def request_qq(self, server, session):
        if not self.settings["qq_login"]:
            raise RegistrationError("服务器未开放 QQ 登录", 403, "method_disabled")
        binding = self.binding(server["id"], session)
        if not binding:
            raise RegistrationError("没有与此游戏身份匹配的 QQ 绑定，请使用密码登录或联系管理员", 403, "binding_missing")
        if not self.bot.onebot.connected:
            raise RegistrationError("QQ 机器人未连接，请使用密码登录或稍后重试", 503, "qq_unavailable")
        self.registration.limit(f"game-qq:{server['id']}:{binding['qq']}", 1, self.settings["qq_cooldown"])
        token = secrets.token_urlsafe(18)
        challenge = {"hash": hashlib.sha256(token.encode()).hexdigest(), "qq": binding["qq"], "ready": False,
                     "expires": min(session["expires"], time.time() + self.settings["qq_seconds"])}
        session["challenge"] = challenge
        message = (f"[VexBot · 游戏登录确认]\n服务器：{server['name']}\n玩家：{session['player']}\n连接 IP：{session['ip'] or '未提供'}"
                   f"\n有效期：{max(1, int(challenge['expires'] - time.time()))} 秒"
                   f"\n如果是你本人登录，请回复：\n/确认登录 {token}\n不是本人请回复：\n/拒绝登录 {token}\n请勿转发确认消息。")
        try:
            await self.bot.onebot.send_private(binding["qq"], message)
        except (ConnectionError, RuntimeError, TimeoutError):
            if session["challenge"] is challenge:
                session["challenge"] = None
            raise RegistrationError("QQ 私聊发送失败，请添加机器人为好友或使用密码登录", 502, "qq_delivery_failed") from None
        if self.sessions.get((server["id"], session["uuid"])) is not session or session["status"] != "pending":
            raise RegistrationError("游戏连接已失效，确认消息不可使用", 409, "connection_changed")
        challenge["ready"] = True
        session["message"] = "已向绑定 QQ 私聊发送登录确认，请在 QQ 中确认；不要把消息发到群里"
        return self.response(session)

    def confirm(self, user, token, approve):
        if not isinstance(token, str) or not 20 <= len(token) <= 80:
            raise RegistrationError("请完整复制私聊中的确认或拒绝指令")
        digest, now = hashlib.sha256(token.encode()).hexdigest(), time.time()
        for (sid, _), session in self.sessions.items():
            challenge = session["challenge"]
            if (not challenge or not challenge["ready"] or challenge["qq"] != user
                    or not secrets.compare_digest(challenge["hash"], digest)):
                continue
            if self.error or not self.policy(sid)["required"] or not self.settings["qq_login"]:
                break
            if session["status"] != "pending" or now >= min(session["expires"], challenge["expires"]):
                break
            server = self.bot.servers.get(sid)
            binding = self.binding(sid, session)
            if not server or not binding or binding["qq"] != user:
                break
            if approve:
                self.authenticated(server, session, "qq")
                return f"[✓] 已确认 {session['player']} 在 {server['name']} 的本次游戏登录。"
            session.update(status="denied", message="绑定 QQ 已拒绝本次登录", challenge=None)
            self.store.audit("authentication", f"{sid}/{session['player']} 的游戏登录被绑定 QQ 拒绝")
            return "[✓] 已拒绝本次游戏登录。"
        raise RegistrationError("确认消息无效、已过期、已使用，或不属于此 QQ", 400, "confirmation_invalid")

    def heartbeat(self, server, entries):
        if not isinstance(entries, list) or len(entries) > 500:
            raise RegistrationError("登录会话列表格式错误")
        result = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise RegistrationError("登录会话格式错误")
            identity, nonce, player = self.identity(entry)
            session = self.sessions.get((server["id"], identity))
            if session and session["nonce"] == nonce and session["player"] == player:
                session["last_seen"] = time.time()
                session = self.current(server, entry)
                result.append(self.response(session))
            else:
                result.append({"uuid": identity, "nonce": nonce, "status": "missing", "message": "请重新验证游戏连接"})
        return result

    def clear_links(self, account_id):
        account = self.registration.account(account_id)
        with self.store.db:
            count = self.store.db.execute("DELETE FROM account_game_links WHERE account_id=?", (account_id,)).rowcount
        self.sessions = {key: value for key, value in self.sessions.items() if value["player"].lower() != account["player"].lower()}
        self.store.audit("authentication", f"管理员重置 {account['player']} 的游戏身份关联，共 {count} 项")
        return {"removed": count}

    def reset_available(self):
        settings = self.registration.settings
        return not self.registration.error and bool(settings["smtp_host"] and settings["smtp_from"])

    async def request_password(self, player, email, remote):
        if not self.reset_available():
            raise RegistrationError("密码设置邮件尚未配置，请联系管理员", 503, "mail_unavailable")
        if not isinstance(player, str) or not re.fullmatch(r"[A-Za-z0-9_]{3,16}", player):
            raise RegistrationError("玩家名格式错误")
        email = mail_address(email)
        reg = self.registration
        reg.limit("password-request-client:" + remote, 5, 600)
        reg.limit("password-request-email:" + email, 1, reg.settings["resend_seconds"])
        reg.limit("request-global", reg.settings["hourly_limit"], 3600)
        challenge_id, code, now = secrets.token_urlsafe(24), f"{secrets.randbelow(1000000):06d}", time.time()
        settings, generation = deepcopy(reg.settings), reg.generation
        account = self.account_for_player(player)
        result = {"challenge_id": challenge_id, "expires_in": settings["code_minutes"] * 60,
                  "message": "如果玩家名与注册邮箱匹配，密码设置验证码将发送到该邮箱"}
        if not account or account["email"] != email:
            return result
        with self.store.db:
            self.store.db.execute("DELETE FROM password_challenges WHERE account_id=? OR expires<?", (account["id"], now))
            self.store.db.execute("INSERT INTO password_challenges VALUES(?,?,?,?,?,?,?)",
                                  (challenge_id, account["id"], code_hash(challenge_id, code), 0, "sending", now + result["expires_in"], reg.revision))
        try:
            await reg.deliver(settings, generation, email, player, code, challenge_id, "password")
            if generation != reg.generation:
                raise RegistrationError("邮件设置已变化，请重新申请", 409, "settings_changed")
            with self.store.db:
                self.store.db.execute("UPDATE password_challenges SET status='ready' WHERE id=?", (challenge_id,))
        except BaseException as exc:
            with self.store.db:
                self.store.db.execute("DELETE FROM password_challenges WHERE id=?", (challenge_id,))
            if isinstance(exc, (asyncio.CancelledError, RegistrationError)):
                raise
            raise RegistrationError("密码设置邮件发送失败，请稍后重试", 502, "mail_failed") from None
        return result

    async def verify_password(self, challenge_id, code, password, remote):
        validate_password(password)
        reg = self.registration
        reg.limit("password-verify-client:" + remote, 20, 600)
        if not isinstance(challenge_id, str) or not 20 <= len(challenge_id) <= 80 or not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
            raise RegistrationError("请填写申请编号和 6 位邮箱验证码")
        row = self.store.db.execute("SELECT * FROM password_challenges WHERE id=?", (challenge_id,)).fetchone()
        if (not row or row["status"] != "ready" or row["expires"] <= time.time() or row["settings_revision"] != reg.revision):
            raise RegistrationError("密码设置验证码无效、已过期或已使用", 400, "code_invalid")
        if row["attempts"] >= 5:
            raise RegistrationError("验证码尝试次数过多", 429, "code_locked")
        if not secrets.compare_digest(row["code_hash"], code_hash(challenge_id, code)):
            with self.store.db:
                self.store.db.execute("UPDATE password_challenges SET attempts=attempts+1 WHERE id=?", (challenge_id,))
            raise RegistrationError("验证码不正确", 400, "code_invalid")
        digest = await reg.password_work.run(hash_password, password)
        latest = self.store.db.execute("SELECT * FROM password_challenges WHERE id=?", (challenge_id,)).fetchone()
        if (not latest or latest["status"] != "ready" or latest["expires"] <= time.time()
                or latest["settings_revision"] != reg.revision or latest["attempts"] >= 5):
            raise RegistrationError("密码设置申请已失效，请重新申请", 409, "code_used")
        with self.store.db:
            self.store.db.execute("INSERT INTO account_passwords VALUES(?,?,?) ON CONFLICT(account_id) DO UPDATE SET password_hash=excluded.password_hash,changed=excluded.changed",
                                  (row["account_id"], digest, time.time()))
            self.store.db.execute("UPDATE password_challenges SET status='used' WHERE id=?", (challenge_id,))
            self.store.db.execute("DELETE FROM registration_sessions WHERE account_id=?", (row["account_id"],))
        account = reg.account(row["account_id"])
        self.sessions = {key: value for key, value in self.sessions.items() if value["player"].lower() != account["player"].lower()}
        self.store.audit("authentication", f"{account['player']} 通过邮箱验证更新游戏登录密码；旧会话已失效")
        return {"message": "游戏登录密码已保存，请使用新密码登录；旧游戏会话已失效"}
