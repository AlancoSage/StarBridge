"""Bound-QQ recovery of native authentication passwords; credentials stay in RAM."""
import asyncio
from copy import deepcopy
import hashlib
import json
import re
import secrets
import time
import uuid

from .registration import RegistrationError


TARGETS = {("bukkit", "authme"), ("bukkit", "librelogin"),
           ("velocity", "limboauth"), ("velocity", "librelogin")}
DEFAULTS = {"servers": {}}
STATUSES = {
    "success": "密码已由原登录插件更新，请使用你刚才提交的新密码登录。",
    "not_found": "原登录插件中不存在这个账号，未修改密码。",
    "identity_mismatch": "原账号身份与已验证绑定不符，未修改密码，请联系服主。",
    "online": "请先完全退出游戏，再申请重置密码。",
    "unsupported": "当前登录插件或账号不支持安全重置，未修改密码。",
    "failed": "登录插件未能确认修改成功，请先核对游戏登录状态，再重新申请。",
    "expired": "请求已过期，未开始修改密码，请重新申请。",
    "uncertain": "原登录插件尚未确认，仍可能完成；系统不会重试。请保持该账号离线，联系服主重启游戏服后核对新密码，再申请找回。",
}


def validate_settings(value):
    if not isinstance(value, dict) or value.keys() != {"servers"}:
        raise RegistrationError("密码找回设置只接受服务器列表")
    servers = value["servers"]
    if not isinstance(servers, dict) or len(servers) > 100:
        raise RegistrationError("密码找回服务器列表格式错误")
    for sid, target in servers.items():
        if (not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", sid)
                or not isinstance(target, dict) or target.keys() != {"platform", "engine"}
                or not all(isinstance(v, str) for v in target.values())
                or (target["platform"], target["engine"]) not in TARGETS):
            raise RegistrationError("密码找回请选择 AuthMe、LibreLogin 或 LimboAuth 对应的服务端")
    return deepcopy(value)


def identity(value):
    try:
        if not isinstance(value, str):
            raise ValueError()
        return str(uuid.UUID(value))
    except (ValueError, AttributeError):
        raise RegistrationError("密码找回请求标识无效") from None


class NativePasswords:
    def __init__(self, bot):
        self.bot, self.store = bot, bot.store
        self.settings, self.error = deepcopy(DEFAULTS), ""
        self.epoch = secrets.token_hex(12)
        self.challenges, self.requests, self.code_proofs, self.peers = {}, {}, {}, {}
        self.notifications = asyncio.Queue(maxsize=256)
        self.store.db.executescript("""
            CREATE TABLE IF NOT EXISTS native_password_settings (
                id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS native_password_proofs (
                server TEXT NOT NULL, qq TEXT NOT NULL, uuid TEXT NOT NULL,
                name TEXT NOT NULL, binding_created REAL NOT NULL,
                platform TEXT NOT NULL, engine TEXT NOT NULL, account TEXT NOT NULL,
                PRIMARY KEY(server,qq)
            );
        """)
        if "account" not in {row[1] for row in self.store.db.execute("PRAGMA table_info(native_password_proofs)")}:
            with self.store.db:
                self.store.db.execute("ALTER TABLE native_password_proofs ADD COLUMN account TEXT NOT NULL DEFAULT ''")
                self.store.db.execute("DELETE FROM native_password_proofs")
        try:
            row = self.store.db.execute("SELECT value FROM native_password_settings WHERE id=1").fetchone()
            if row:
                self.settings = validate_settings(json.loads(row["value"]))
        except (ValueError, TypeError):
            self.error = "密码找回设置读取失败，已停止原生密码重置，请检查数据库设置。"

    @property
    def revision(self):
        return hashlib.sha256((json.dumps(self.settings, sort_keys=True) + self.epoch).encode()).hexdigest()

    def config(self):
        now = time.time()
        return {"settings": deepcopy(self.settings), "revision": self.revision, "error": self.error,
                "servers": [{"id": s["id"], "name": s["name"]} for s in self.bot.servers.values()],
                "connections": [{"server": sid, "platform": platform, "engine": peer["engine"]}
                                for (sid, platform, _), peer in self.peers.items() if peer["seen"] > now - 15]}

    def save(self, value, revision):
        if revision != self.revision:
            raise RegistrationError("密码找回设置已变化，请重新载入", 409, "conflict")
        value = validate_settings(value)
        if set(value["servers"]) - self.bot.servers.keys():
            raise RegistrationError("密码找回包含尚未配置的服务器")
        with self.store.db:
            self.store.db.execute("INSERT INTO native_password_settings VALUES(1,?) "
                                  "ON CONFLICT(id) DO UPDATE SET value=excluded.value",
                                  (json.dumps(value, sort_keys=True),))
        self.settings, self.error = value, ""
        self.epoch = secrets.token_hex(12)
        self.challenges.clear()
        self._prune()
        self.store.audit("authentication", "管理员更新原生密码找回设置；未开始的旧请求已撤销")
        return self.config()

    def _route(self, sid):
        server = self.bot.servers.get(sid)
        if not server:
            return None
        qq = self.bot.onebot
        return (getattr(qq, "provider", "onebot"), str(qq.self_id), getattr(qq, "generation", 0),
                hashlib.sha256(server["token"].encode()).digest(), tuple(server["groups"]))

    def record_code(self, sid, player_uuid, name, code, platform, engine, account=None):
        """Only a native-authenticated game endpoint can issue this proof."""
        self._prune()
        if (not isinstance(platform, str) or not isinstance(engine, str) or (platform, engine) not in TARGETS
                or not isinstance(account, str) or not re.fullmatch(r"[a-f0-9]{64}", account)):
            return
        proof = {"uuid": player_uuid, "name": name, "platform": platform, "engine": engine,
                 "account": account, "expires": time.time() + 300, "route": self._route(sid), "server": sid}
        if len(self.code_proofs) < 2000:
            self.code_proofs[code.upper()] = proof
        # A native login proves the game account, not ownership of an old QQ binding.
        # Recreated native accounts also revoke grants for their previous incarnation.
        with self.store.db:
            self.store.db.execute("DELETE FROM native_password_proofs WHERE server=? AND uuid=? AND account<>?",
                                  (sid, player_uuid, account))

    def renew(self, sid, qq, code):
        proof = self.code_proofs.get(code.upper())
        row = self.store.binding(sid, qq)
        issued = self.store.db.execute("SELECT * FROM codes WHERE code=? AND server=? AND expires>?",
                                       (code.upper(), sid, time.time())).fetchone()
        if (not proof or not row or not issued or proof["expires"] <= time.time()
                or proof["route"] != self._route(sid) or proof["server"] != sid
                or row["uuid"] != issued["uuid"] or row["uuid"] != proof["uuid"]
                or row["name"].lower() != issued["name"].lower()
                or row["name"].lower() != proof["name"].lower()):
            return None
        self.discard_code(sid, code)
        self._grant(row, proof)
        return row

    def verify_binding(self, qq, sid, code):
        """The game receipt must be confirmed privately by the intended QQ owner."""
        self._prune()
        if getattr(self.bot.onebot, "provider", "onebot") != "onebot" or not qq.isdigit():
            raise RegistrationError("原生密码找回的绑定验证仅支持 OneBot 私聊。")
        if not isinstance(sid, str) or sid not in self.bot.servers or not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9]{4,16}", code):
            raise RegistrationError("请完整发送游戏内的私聊验证指令：/验证绑定 服务器ID 验证码")
        self.bot.registration.limit("native-bind:" + qq, 5, 60)
        proof = self.code_proofs.get(code.upper())
        if not proof or proof["server"] != sid or proof["route"] != self._route(sid):
            raise RegistrationError("原生绑定验证码无效、已过期或已使用，请重新在游戏获取。")
        try:
            row = self.renew(sid, qq, code)
            if row is None:
                row = self.store.bind(sid, qq, code)
                self.bound(sid, qq, code)
        except ValueError:
            self.discard_code(sid, code)
            raise RegistrationError("游戏账号或 QQ 已有不同绑定，验证码已作废；请联系服主核对原绑定后重新验证。") from None
        self.store.audit("authentication", f"{sid}/{row['name']} 完成原生账号和本人 QQ 私聊绑定验证")
        return f"[✓] {row['name']}（{self.bot.servers[sid]['name']}）绑定已验证。已开放找回时，可私聊发送：/重置密码 {sid}"

    def discard_code(self, sid, code):
        proof = self.code_proofs.get(code.upper())
        if proof and proof["server"] == sid:
            self.code_proofs.pop(code.upper(), None)
            with self.store.db:
                self.store.db.execute("DELETE FROM codes WHERE code=? AND server=?", (code.upper(), sid))

    def discard_exposed(self, text):
        public = text.upper()
        for code, proof in list(self.code_proofs.items()):
            if code in public:
                self.discard_code(proof["server"], code)

    def bound(self, sid, qq, code):
        proof = self.code_proofs.pop(code.upper(), None)
        row = self.store.binding(sid, qq)
        if (proof and row and proof["server"] == sid and proof["expires"] > time.time()
                and proof["route"] == self._route(sid) and proof["uuid"] == row["uuid"]
                and proof["name"].lower() == row["name"].lower()):
            self._grant(row, proof)

    def _grant(self, row, proof):
        with self.store.db:
            self.store.db.execute("INSERT INTO native_password_proofs VALUES(?,?,?,?,?,?,?,?) "
                                  "ON CONFLICT(server,qq) DO UPDATE SET uuid=excluded.uuid,name=excluded.name,"
                                  "binding_created=excluded.binding_created,platform=excluded.platform,engine=excluded.engine,account=excluded.account",
                                  (row["server"], row["qq"], row["uuid"], row["name"], row["created"],
                                   proof["platform"], proof["engine"], proof["account"]))

    def _binding(self, sid, qq):
        target = self.settings["servers"].get(sid)
        row = self.store.binding(sid, qq)
        proof = self.store.db.execute("SELECT * FROM native_password_proofs WHERE server=? AND qq=?", (sid, qq)).fetchone()
        if (not row or not target or not proof or proof["uuid"] != row["uuid"]
                or proof["name"].lower() != row["name"].lower() or proof["binding_created"] != row["created"]
                or any(proof[key] != target[key] for key in ("platform", "engine"))
                or not re.fullmatch(r"[a-f0-9]{64}", proof["account"])):
            raise RegistrationError("没有可用于重置的本人绑定。请先完成原插件登录，在游戏输入 /qbind，再用自己的 QQ 发送绑定码验证；已有绑定不必解绑。")
        return {**row, "account": proof["account"]}

    def _peer(self, sid, target):
        now = time.time()
        peers = [(instance, peer) for (server, platform, instance), peer in self.peers.items()
                 if server == sid and platform == target["platform"] and peer["seen"] > now - 15]
        if len(peers) != 1 or peers[0][1]["engine"] != target["engine"]:
            raise RegistrationError("密码找回端未就绪或存在多个实例，请联系服主检查对应插件。")
        return peers[0][0]

    def _fence(self, sid, qq):
        if self.error or sid not in self.bot.servers or sid not in self.settings["servers"]:
            raise RegistrationError("该服务器尚未开放原生密码找回。")
        if getattr(self.bot.onebot, "provider", "onebot") != "onebot" or not qq.isdigit():
            raise RegistrationError("官机的群身份与私聊身份不同，暂不支持通过此方式重置；请使用原登录插件的找回入口。")
        row = self._binding(sid, qq)
        target = self.settings["servers"][sid]
        return (self.revision, self._route(sid), row["uuid"], row["name"], row["created"], row["account"], self._peer(sid, target))

    def _valid(self, request):
        try:
            return self._fence(request["server"], request["qq"]) == request["fence"]
        except RegistrationError:
            return False

    def _notify(self, request, message):
        # Messages never contain a password, challenge token or plugin exception.
        item = (request["server"], request["qq"], request["fence"][1],
                f"[VexBot · 密码找回]\n玩家：{request['player']}\n{message}")
        if not self.notifications.full():
            self.notifications.put_nowait(item)

    def _prune(self):
        now = time.time()
        self.peers = {key: value for key, value in self.peers.items() if value["seen"] > now - 30}
        self.code_proofs = {key: value for key, value in self.code_proofs.items() if value["expires"] > now}
        self.challenges = {key: value for key, value in self.challenges.items()
                           if value["expires"] > now and self._valid(value)}
        for jid, request in list(self.requests.items()):
            invalid = not self._valid(request)
            deadline = request["expires"] + (45 if request["state"] != "pending" else 0)
            if invalid or deadline <= now:
                request.pop("password", None)
                self.requests.pop(jid)
                if request["state"] == "pending":
                    message = "请求已撤销或过期，未提交密码修改。"
                else:
                    message = "未能确认本次修改结果，系统不会重复提交。请先核对新密码能否登录，再决定是否重新申请。"
                self._notify(request, message)

    def group_hint(self, sid):
        return f"请私聊机器人发送：/重置密码 {sid}\n新密码和确认指令只能发私聊，请勿发到群里。"

    def private_command(self, qq, command, argument):
        self._prune()
        if getattr(self.bot.onebot, "provider", "onebot") != "onebot":
            raise RegistrationError("官机暂不支持通过群绑定发起私聊密码找回，请使用原登录插件的找回入口。")
        if command == "/重置密码":
            sid = argument.strip()
            if not sid:
                servers = [s["id"] for s in self.bot.servers.values()
                           if s["id"] in self.settings["servers"] and self.store.binding(s["id"], qq)]
                return "请发送：/重置密码 服务器ID\n你的绑定服务器：" + ("、".join(servers) or "暂无已开放的绑定服务器")
            fence = self._fence(sid, qq)
            self.bot.registration.limit("native-reset-start:" + qq, 3, 60)
            if any(r["server"] == sid and r["qq"] == qq for r in self.requests.values()):
                raise RegistrationError("已有请求等待结果，请先核对本次结果。")
            if len(self.challenges) >= 500:
                raise RegistrationError("密码找回繁忙，请稍后重试。")
            self.challenges = {key: value for key, value in self.challenges.items()
                               if (value["server"], value["qq"]) != (sid, qq)}
            token = secrets.token_urlsafe(24)
            row = self._binding(sid, qq)
            self.challenges[hashlib.sha256(token.encode()).hexdigest()] = {
                "server": sid, "qq": qq, "player": row["name"], "fence": fence, "expires": time.time() + 120}
            return (f"将重置 {self.bot.servers[sid]['name']} 的 {row['name']} 原登录插件密码。请先退出游戏。\n"
                    f"120 秒内在本私聊发送：\n/确认重置 {token} 新密码\n密码需为 8–64 位可见 ASCII 字符，不含空格；不会修改网页密码或关闭二次验证。")
        token, separator, password = argument.partition(" ")
        if not separator or not re.fullmatch(r"[!-~]{8,64}", password):
            raise RegistrationError("请完整发送私聊确认指令，新密码需为 8–64 位可见 ASCII 字符，不含空格。")
        digest = hashlib.sha256(token.encode()).hexdigest()
        challenge = self.challenges.get(digest)
        if not challenge or challenge["qq"] != qq or not self._valid(challenge):
            raise RegistrationError("重置确认无效、已过期、已使用或不属于此 QQ。")
        self.bot.registration.limit("native-reset-confirm:" + challenge["server"] + ":" + qq, 1, 300)
        if len(self.requests) >= 200:
            raise RegistrationError("密码找回繁忙，请稍后重试。")
        self.challenges.pop(digest)
        jid = str(uuid.uuid4())
        target = self.settings["servers"][challenge["server"]]
        self.requests[jid] = {**challenge, **target, "id": jid, "uuid": challenge["fence"][2],
                              "password": password, "expires": time.time() + 30,
                              "instance": challenge["fence"][-1], "account": challenge["fence"][-2], "state": "pending"}
        self.store.audit("authentication", f"{challenge['server']}/{challenge['player']} 的已验证绑定 QQ 申请原生密码重置")
        return "已提交，等待原登录插件确认。系统只提交一次，请留意本私聊结果。"

    def tick(self, server, data):
        if not isinstance(data, dict) or data.keys() - {"instance", "platform", "engine", "results"}:
            raise RegistrationError("密码找回心跳格式错误")
        instance = identity(data.get("instance"))
        platform, engine = data.get("platform"), data.get("engine")
        if platform not in ("bukkit", "velocity") or not isinstance(engine, str) or (engine and (platform, engine) not in TARGETS):
            raise RegistrationError("密码找回插件类型无效")
        results = data.get("results", [])
        if (not isinstance(results, list) or len(results) > 50 or any(
                not isinstance(r, dict) or r.keys() != {"id", "status"}
                or not isinstance(r["id"], str) or not isinstance(r["status"], str) or r["status"] not in STATUSES for r in results)):
            raise RegistrationError("密码找回执行结果格式错误")
        sid = server["id"]
        self._prune()
        if (sid, platform, instance) not in self.peers and len(self.peers) >= 1000:
            raise RegistrationError("密码找回连接过多，请稍后重试", 503, "busy")
        self.peers[(sid, platform, instance)] = {"seen": time.time(), "engine": engine}
        self._prune()
        for result in results:
            request = self.requests.get(result["id"])
            if (not request or request["server"] != sid or request["platform"] != platform
                    or request["engine"] != engine or request["instance"] != instance
                    or (request["state"] != "claimed" and not (request["state"] == "sent" and result["status"] != "success"))):
                continue
            self.requests.pop(result["id"])
            self.store.audit("authentication", f"{sid}/{request['player']} 原生密码重置结果：{result['status']}")
            self._notify(request, STATUSES[result["status"]])
        target = self.settings["servers"].get(sid, {})
        enabled = not self.error and target.get("platform") == platform and target.get("engine") == engine and bool(engine)
        jobs = []
        if enabled:
            for request in self.requests.values():
                if len(jobs) >= 8:
                    break
                if (request["server"] == sid and request["instance"] == instance
                        and request["state"] == "pending" and self._valid(request)):
                    jobs.append({key: request[key] for key in ("id", "uuid", "player", "password", "expires", "engine", "instance", "account")})
                    request.pop("password")
                    request["state"] = "sent"
        return {"enabled": enabled, "engine": target.get("engine", ""), "instance": instance, "jobs": jobs}

    def claim(self, sid, data):
        if not isinstance(data, dict) or data.keys() != {"id", "instance", "platform", "engine"}:
            raise RegistrationError("密码找回认领格式错误")
        jid, instance = identity(data["id"]), identity(data["instance"])
        self._prune()
        request = self.requests.get(jid)
        allowed = bool(request and request["server"] == sid and request["instance"] == instance
                       and request["platform"] == data["platform"] and request["engine"] == data["engine"]
                       and request["state"] == "sent" and request["expires"] > time.time() and self._valid(request))
        if allowed:
            request["state"] = "claimed"
        return {"allowed": allowed}

    async def worker(self):
        while True:
            self._prune()
            try:
                sid, qq, route, message = await asyncio.wait_for(self.notifications.get(), timeout=1)
            except TimeoutError:
                continue
            try:
                if route == self._route(sid) and self.bot.onebot.connected:
                    await self.bot.onebot.send_private(qq, message)
            except (ConnectionError, RuntimeError, TimeoutError):
                self.store.audit("authentication", "原生密码重置结果私聊投递失败；操作未重试，请玩家核对登录状态")
            finally:
                self.notifications.task_done()
