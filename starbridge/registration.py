"""Email verified community accounts shared by QQ and website clients."""
import asyncio
from copy import deepcopy
from email.message import EmailMessage
import hashlib
import json
from pathlib import Path
import re
import secrets
import smtplib
import sqlite3
import ssl
import time
from urllib.parse import urlsplit
import uuid

from .extensions import atomic_json


DEFAULTS = {"enabled": False, "site_name": "VexBot社区", "website_url": "", "api_token": "",
            "smtp_host": "", "smtp_port": 465, "smtp_security": "ssl", "smtp_username": "",
            "smtp_password": "", "smtp_from": "", "code_minutes": 5, "resend_seconds": 60,
            "hourly_limit": 60, "allowed_origins": []}
EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?\.[A-Za-z]{2,63}")
PLAYER = re.compile(r"[A-Za-z0-9_]{3,16}")


class RegistrationError(ValueError):
    def __init__(self, message, status=400, code="invalid_request"):
        super().__init__(message)
        self.status, self.code = status, code


def mail_address(value):
    if not isinstance(value, str) or not EMAIL.fullmatch(value) or len(value) > 254:
        raise RegistrationError("请填写合法的邮箱地址")
    return value.lower()


def validate_settings(value):
    if not isinstance(value, dict) or value.keys() - DEFAULTS.keys():
        raise RegistrationError("注册设置包含未知字段")
    result = {**deepcopy(DEFAULTS), **value}
    if type(result["enabled"]) is not bool:
        raise RegistrationError("注册开关必须为布尔值")
    for key, maximum in (("site_name", 80), ("website_url", 1000), ("api_token", 256), ("smtp_host", 253),
                         ("smtp_username", 254), ("smtp_password", 256), ("smtp_from", 254)):
        if not isinstance(result[key], str) or len(result[key]) > maximum or any(ord(c) < 32 for c in result[key]):
            raise RegistrationError(f"设置 {key} 格式错误")
    if not result["site_name"].strip():
        raise RegistrationError("社区名称不能为空")
    if result["smtp_host"] and not re.fullmatch(r"[A-Za-z0-9_.:\-]+", result["smtp_host"]):
        raise RegistrationError("SMTP 主机应为域名或 IP，不包含协议、路径和空格")
    if result["smtp_from"]:
        result["smtp_from"] = mail_address(result["smtp_from"])
    if result["smtp_security"] not in ("ssl", "starttls"):
        raise RegistrationError("SMTP 加密方式需为 SSL 或 STARTTLS")
    for key, lower, upper in (("smtp_port", 1, 65535), ("code_minutes", 1, 15), ("resend_seconds", 30, 600), ("hourly_limit", 1, 1000)):
        if type(result[key]) is not int or not lower <= result[key] <= upper:
            raise RegistrationError(f"设置 {key} 需为 {lower}–{upper} 的整数")
    if result["api_token"] and not re.fullmatch(r"[!-~]{32,256}", result["api_token"]):
        raise RegistrationError("网站 API 密钥需为 32–256 位非空格 ASCII 字符")
    if result["website_url"]:
        url = urlsplit(result["website_url"])
        if (url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment):
            raise RegistrationError("注册网页地址需要 HTTP / HTTPS 链接，不包含账号、查询参数或片段")
    origins = result["allowed_origins"]
    if not isinstance(origins, list) or len(origins) > 20:
        raise RegistrationError("网站来源最多 20 个")
    normalized = []
    for origin in origins:
        if not isinstance(origin, str) or len(origin) > 500:
            raise RegistrationError("网站来源格式错误")
        url = urlsplit(origin)
        try:
            url.port
        except ValueError:
            raise RegistrationError("网站来源端口错误") from None
        if (url.scheme not in ("http", "https") or not url.hostname or url.username or url.password
            or url.path not in ("", "/") or url.query or url.fragment):
            raise RegistrationError("网站来源只填写协议、域名及端口，不包含路径或通配符")
        normalized.append(origin.rstrip("/"))
    if len(set(normalized)) != len(normalized):
        raise RegistrationError("网站来源不能重复")
    result["allowed_origins"] = normalized
    if result["enabled"] and (not result["smtp_host"] or not result["smtp_from"]):
        raise RegistrationError("启用注册前请填写 SMTP 主机和发件邮箱")
    if result["smtp_password"] and not result["smtp_username"]:
        raise RegistrationError("填写 SMTP 授权码时也需要登录账号")
    return result


def code_hash(challenge_id, code):
    return hashlib.sha256((challenge_id + ":" + code).encode()).hexdigest()


def send_verification(settings, email, player, code, challenge_id, channel):
    message = EmailMessage()
    message["From"], message["To"] = settings["smtp_from"], email
    purpose = "设置游戏登录密码" if channel == "password" else "注册账号"
    message["Subject"] = settings["site_name"] + (" · 登录密码设置验证码" if channel == "password" else " · 注册验证码")
    instruction = f"请在申请的 QQ 群发送 /注册 {code}。" if channel == "group" else "请在申请的网页输入验证码。\n申请编号：" + challenge_id
    if channel == "web" and settings["website_url"]:
        instruction += "\n注册网页：" + settings["website_url"]
    message.set_content(f"你正在为 {settings['site_name']} 的 {player} {purpose}。\n\n验证码：{code}\n有效期：{settings['code_minutes']} 分钟，仅能使用一次。\n\n{instruction}\n如果不是你本人申请，请忽略这封邮件。")
    context = ssl.create_default_context()
    if settings["smtp_security"] == "ssl":
        smtp = smtplib.SMTP_SSL(settings["smtp_host"], settings["smtp_port"], timeout=10, context=context)
    else:
        smtp = smtplib.SMTP(settings["smtp_host"], settings["smtp_port"], timeout=10)
    with smtp:
        if settings["smtp_security"] == "starttls":
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
        if settings["smtp_username"]:
            smtp.login(settings["smtp_username"], settings["smtp_password"])
        refused = smtp.send_message(message)
        if refused:
            raise smtplib.SMTPException("收件人被拒绝")


class Registration:
    def __init__(self, base, store):
        self.path = Path(base) / "data" / "registration-settings.json"
        self.store, self.settings, self.error = store, deepcopy(DEFAULTS), ""
        self.lock, self.mail_slots = asyncio.Lock(), asyncio.Semaphore(2)
        self.mail_tasks = set()
        self.generation = 0
        try:
            if self.path.exists():
                if self.path.stat().st_size > 32 * 1024:
                    raise ValueError("文件过大")
                self.settings = validate_settings(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            self.error = "注册设置读取失败，注册已关闭。请检查 data/registration-settings.json 后重启。"
        self.store.db.executescript("""
            CREATE TABLE IF NOT EXISTS registration_accounts (
                id TEXT PRIMARY KEY, player TEXT NOT NULL, player_key TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE, qq TEXT UNIQUE, created REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS registration_challenges (
                id TEXT PRIMARY KEY, player TEXT NOT NULL, player_key TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE, qq TEXT, channel TEXT NOT NULL, scope TEXT NOT NULL,
                code_hash TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL,
                settings_revision TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS registration_limits (key TEXT NOT NULL, time REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS registration_limits_key_time ON registration_limits(key,time);
            CREATE TABLE IF NOT EXISTS registration_sessions (
                token_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL, expires REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS account_passwords (
                account_id TEXT PRIMARY KEY, password_hash TEXT NOT NULL, changed REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS account_game_links (
                account_id TEXT NOT NULL, server TEXT NOT NULL, uuid TEXT NOT NULL,
                PRIMARY KEY(account_id,server), UNIQUE(server,uuid)
            );
        """)
        # Deferred import keeps the public registration error shared without an import cycle.
        from .passwords import PasswordWork
        self.password_work = PasswordWork()

    @property
    def revision(self):
        return hashlib.sha256(json.dumps(self.settings, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def config_response(self):
        return {"settings": deepcopy(self.settings), "revision": self.revision, "error": self.error}

    async def save_settings(self, settings, revision, forbidden_tokens=()):
        async with self.lock:
            if self.error:
                raise RegistrationError(self.error, 503, "settings_unavailable")
            if revision != self.revision:
                raise RegistrationError("注册设置已被其他页面修改，请重新载入", 409, "conflict")
            value = validate_settings(settings)
            if value["api_token"] and value["api_token"] in forbidden_tokens:
                raise RegistrationError("网站 API 密钥必须独立于管理、QQ 和游戏连接令牌")
            atomic_json(self.path, value)
            self.settings = value
            self.generation += 1
            # Configuration changes invalidate previously issued codes.
            with self.store.db:
                self.store.db.execute("DELETE FROM registration_challenges")
            self.store.audit("registration", "管理员保存注册与邮件设置；旧验证码已失效")
            return self.config_response()

    def require_enabled(self):
        if self.error or not self.settings["enabled"]:
            raise RegistrationError("账号注册尚未开放，请联系管理员", 503, "registration_disabled")

    def limit(self, key, count, period):
        with self.store.db:
            self._limit(key, count, period)

    def _limit(self, key, count, period):
        now = time.time()
        key = hashlib.sha256(key.encode()).hexdigest()
        self.store.db.execute("DELETE FROM registration_limits WHERE time<?", (now - 86400,))
        total = self.store.db.execute("SELECT count(*) FROM registration_limits WHERE key=? AND time>?", (key, now - period)).fetchone()[0]
        if total >= count:
            raise RegistrationError("操作过于频繁，请稍后再试", 429, "rate_limited")
        self.store.db.execute("INSERT INTO registration_limits VALUES(?,?)", (key, now))

    async def request_code(self, player, email, channel="web", scope="", remote="", replace_id=""):
        self.require_enabled()
        if not isinstance(player, str) or not PLAYER.fullmatch(player):
            raise RegistrationError("玩家名需为 3–16 位字母、数字或下划线")
        email = mail_address(email)
        qq = email[:-7] if email.endswith("@qq.com") and re.fullmatch(r"[1-9][0-9]{4,18}", email[:-7]) else None
        now, challenge_id, code = time.time(), secrets.token_urlsafe(24), f"{secrets.randbelow(1000000):06d}"
        async with self.lock:
            self.require_enabled()
            settings, generation = deepcopy(self.settings), self.generation
            self.limit("request-client:" + channel + ":" + (remote or scope), 5, 600)
            self.limit("request-email:" + email, 1, settings["resend_seconds"])
            with self.store.db:
                self.store.db.execute("DELETE FROM registration_challenges WHERE expires<?", (now,))
                if self.store.db.execute("SELECT 1 FROM registration_accounts WHERE player_key=? OR email=? OR (qq IS NOT NULL AND qq=?)", (player.lower(), email, qq)).fetchone():
                    raise RegistrationError("玩家名或邮箱已有注册账号", 409, "account_exists")
                existing = self.store.db.execute("SELECT * FROM registration_challenges WHERE player_key=? OR email=?", (player.lower(), email)).fetchone()
                if existing:
                    # A QQ sender may reapply after cooldown; a web request cannot steal a pending challenge.
                    if ((channel == "group" and existing["channel"] == channel and existing["scope"] == scope and existing["email"] == email)
                        or (channel == "web" and existing["channel"] == "web" and existing["id"] == replace_id and existing["status"] == "ready")):
                        self.store.db.execute("DELETE FROM registration_challenges WHERE id=?", (existing["id"],))
                    else:
                        raise RegistrationError("这个玩家名或邮箱已有待验证申请，请完成验证或等待过期", 409, "application_pending")
                self._limit("request-global", settings["hourly_limit"], 3600)
                self.store.db.execute("INSERT INTO registration_challenges(id,player,player_key,email,qq,channel,scope,code_hash,status,created,expires,settings_revision) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                                      (challenge_id, player, player.lower(), email, qq, channel, scope, code_hash(challenge_id, code), "sending", now, now + settings["code_minutes"] * 60, self.revision))
        try:
            await self.deliver(settings, generation, email, player, code, challenge_id, channel)
        except RegistrationError:
            with self.store.db:
                self.store.db.execute("DELETE FROM registration_challenges WHERE id=?", (challenge_id,))
            raise
        except (OSError, smtplib.SMTPException, ValueError, TimeoutError):
            with self.store.db:
                self.store.db.execute("DELETE FROM registration_challenges WHERE id=?", (challenge_id,))
            self.store.audit("error", "注册邮件发送失败，请检查 SMTP 配置；未创建账号")
            raise RegistrationError("验证码邮件发送失败，请联系管理员检查 SMTP 设置", 502, "mail_failed") from None
        except asyncio.CancelledError:
            with self.store.db:
                self.store.db.execute("DELETE FROM registration_challenges WHERE id=?", (challenge_id,))
            raise
        async with self.lock:
            if generation != self.generation or not self.settings["enabled"]:
                raise RegistrationError("注册设置已变化，请重新申请验证码", 409, "settings_changed")
            if now + settings["code_minutes"] * 60 <= time.time():
                raise RegistrationError("邮件发送耗时过长，验证码已过期，请重新申请", 409, "code_expired")
            with self.store.db:
                cursor = self.store.db.execute("UPDATE registration_challenges SET status='ready' WHERE id=?", (challenge_id,))
            if cursor.rowcount != 1:
                raise RegistrationError("申请已失效，请重新申请", 409, "application_missing")
        self.store.audit("registration", f"注册验证码已发送：{player}（{channel}）")
        return {"challenge_id": challenge_id, "player": player, "email": email, "expires_in": int(now + settings["code_minutes"] * 60 - time.time()), "message": "验证码已发送，请检查邮箱"}

    async def close(self):
        if self.mail_tasks:
            await asyncio.gather(*list(self.mail_tasks), return_exceptions=True)
        await self.password_work.close()

    async def deliver(self, settings, generation, email, player, code, challenge_id, channel):
        await asyncio.wait_for(self.mail_slots.acquire(), timeout=5)
        if generation != self.generation:
            self.mail_slots.release()
            raise RegistrationError("邮件设置已变化，请重新申请验证码", 409, "settings_changed")
        task = asyncio.create_task(asyncio.to_thread(send_verification, settings, email, player, code, challenge_id, channel))
        self.mail_tasks.add(task)
        def release(result):
            self.mail_tasks.discard(result)
            self.mail_slots.release()
            if not result.cancelled():
                error = result.exception()
                if getattr(self, "mail_observer", None):
                    self.mail_observer(error is None)
        task.add_done_callback(release)
        # A cancelled request cannot release the slot while SMTP is still running.
        await asyncio.wait_for(asyncio.shield(task), timeout=30)

    async def verify_with_password(self, challenge_id, code, password=None):
        digest = ""
        if password is not None:
            from .passwords import hash_password, validate_password
            validate_password(password)
            # Reject invalid/used codes before spending password hashing work.
            self.verification(challenge_id, code)
            digest = await self.password_work.run(hash_password, password)
        return self.verify(challenge_id, code, password_hash=digest)

    async def resend(self, challenge_id, remote):
        if not isinstance(challenge_id, str) or not 20 <= len(challenge_id) <= 80:
            raise RegistrationError("申请编号格式错误")
        row = self.store.db.execute("SELECT * FROM registration_challenges WHERE id=? AND channel='web'", (challenge_id,)).fetchone()
        if not row or row["status"] != "ready":
            raise RegistrationError("申请不存在或已经使用，请重新申请", 404, "application_missing")
        return await self.request_code(row["player"], row["email"], remote=remote, replace_id=challenge_id)

    def verification(self, challenge_id, code, channel="web", scope=""):
        self.require_enabled()
        if not isinstance(challenge_id, str) or not 20 <= len(challenge_id) <= 80 or not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
            raise RegistrationError("请输入申请编号和 6 位数字验证码")
        row = self.store.db.execute("SELECT * FROM registration_challenges WHERE id=?", (challenge_id,)).fetchone()
        if not row or row["channel"] != channel or (channel == "group" and row["scope"] != scope):
            raise RegistrationError("申请不存在或不属于当前用户，请重新申请", 404, "application_missing")
        if row["expires"] <= time.time() or row["settings_revision"] != self.revision:
            raise RegistrationError("验证码已过期，请重新申请", 410, "code_expired")
        if row["status"] != "ready":
            raise RegistrationError("验证码尚未就绪或已经使用", 409, "code_used")
        if row["attempts"] >= 5:
            raise RegistrationError("验证码错误次数过多，请等待过期后重新申请", 429, "code_locked")
        if not secrets.compare_digest(row["code_hash"], code_hash(challenge_id, code)):
            with self.store.db:
                self.store.db.execute("UPDATE registration_challenges SET attempts=attempts+1 WHERE id=?", (challenge_id,))
            raise RegistrationError("验证码不正确", 400, "code_invalid")
        return row

    def verify(self, challenge_id, code, channel="web", scope="", password_hash=""):
        row = self.verification(challenge_id, code, channel, scope)
        account_id, access_token = str(uuid.uuid4()), secrets.token_urlsafe(32)
        try:
            with self.store.db:
                self.store.db.execute("INSERT INTO registration_accounts VALUES(?,?,?,?,?,?)", (account_id, row["player"], row["player_key"], row["email"], row["qq"], time.time()))
                if password_hash:
                    self.store.db.execute("INSERT INTO account_passwords VALUES(?,?,?)", (account_id, password_hash, time.time()))
                self.store.db.execute("UPDATE registration_challenges SET status='used' WHERE id=?", (challenge_id,))
                self.store.db.execute("DELETE FROM registration_sessions WHERE expires<?", (time.time(),))
                self.store.db.execute("INSERT INTO registration_sessions VALUES(?,?,?)", (hashlib.sha256(access_token.encode()).hexdigest(), account_id, time.time() + 3600))
        except sqlite3.IntegrityError:
            raise RegistrationError("玩家名或邮箱已有注册账号", 409, "account_exists") from None
        self.store.audit("registration", f"账号注册完成：{row['player']}（{channel}）")
        return {"account": self.account(account_id), "access_token": access_token, "token_type": "Bearer", "expires_in": 3600}

    def account(self, account_id):
        row = self.store.db.execute("SELECT id,player,email,qq,created FROM registration_accounts WHERE id=?", (account_id,)).fetchone()
        if not row:
            raise RegistrationError("账号不存在", 404, "account_missing")
        return {**dict(row), "has_password": bool(self.store.db.execute("SELECT 1 FROM account_passwords WHERE account_id=?", (account_id,)).fetchone())}

    def account_for_token(self, token):
        if not isinstance(token, str) or not 30 <= len(token) <= 100:
            raise RegistrationError("用户访问令牌无效或已过期", 401, "token_invalid")
        row = self.store.db.execute("SELECT account_id FROM registration_sessions WHERE token_hash=? AND expires>?", (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        if not row:
            raise RegistrationError("用户访问令牌无效或已过期", 401, "token_invalid")
        return self.account(row["account_id"])

    def list_accounts(self, query="", page=1):
        pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where = "WHERE player LIKE ? ESCAPE '\\' OR email LIKE ? ESCAPE '\\' OR qq LIKE ? ESCAPE '\\'"
        total = self.store.db.execute("SELECT count(*) FROM registration_accounts " + where, (pattern,) * 3).fetchone()[0]
        rows = self.store.db.execute("SELECT id,player,email,qq,created FROM registration_accounts " + where + " ORDER BY created DESC LIMIT 25 OFFSET ?", (*((pattern,) * 3), (page - 1) * 25)).fetchall()
        accounts = []
        for row in rows:
            account = self.account(row["id"])
            account["game_links"] = [dict(link) for link in self.store.db.execute("SELECT server,uuid FROM account_game_links WHERE account_id=?", (row["id"],))]
            accounts.append(account)
        return {"accounts": accounts, "total": total, "page": page, "page_size": 25}

    async def group_command(self, command, arg, server, group, user):
        if command == "/申请":
            parts = arg.split()
            if len(parts) != 2:
                return "[×] 格式错误\n正确格式：/申请 <玩家名> <QQ号>\n示例：/申请 Steve 123456789"
            player, qq = parts
            if qq != user or not re.fullmatch(r"[1-9][0-9]{4,18}", qq):
                return "[×] 只能使用你本人发送消息的 QQ 号申请。"
            try:
                result = await self.request_code(player, qq + "@qq.com", "group", f"{server['id']}:{group}:{user}")
                return f"[✓] 验证码已发送\n邮箱：{result['email']}\n有效期：{self.settings['code_minutes']} 分钟\n请检查邮箱，并发送：/注册 <6位验证码>"
            except RegistrationError as exc:
                return "[×] " + str(exc)
        if command == "/注册":
            scope = f"{server['id']}:{group}:{user}"
            row = self.store.db.execute("SELECT id FROM registration_challenges WHERE channel='group' AND scope=? ORDER BY created DESC LIMIT 1", (scope,)).fetchone()
            if not row:
                return "[×] 还没有注册申请，请先发送：/申请 <玩家名> <你的QQ号>"
            try:
                result = self.verify(row["id"], arg, "group", scope)
                account = result["account"]
                return f"[✓] 注册成功\n玩家名：{account['player']}\n邮箱：{account['email']}\n游戏密码可在网页「设置登录密码」通过邮箱验证后设置。也可使用已绑定 QQ 确认游戏登录。\n欢迎加入 {self.settings['site_name']}！"
            except RegistrationError as exc:
                return "[×] " + str(exc)
        return None
