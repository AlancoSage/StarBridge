"""QQ Open Platform group/C2C transport, using documented REST and Gateway APIs."""
import asyncio
from collections import OrderedDict
from contextlib import suppress
from copy import deepcopy
import json
import re
import time
from urllib.parse import urlsplit, quote

from aiohttp import ClientSession, ClientTimeout, WSMsgType

from .qq_identity import OFFICIAL_DEFAULTS, official_id, official_parts


class QQOfficial:
    API_BASE = "https://api.bot.qq.com"
    INTENTS = 1 << 25
    REPLY_SECONDS = 240

    def __init__(self, cfg, store, events):
        self.cfg = {**deepcopy(OFFICIAL_DEFAULTS), **deepcopy(cfg)}
        self.store, self.events = store, events
        self.ws = None
        self.ready = False
        self.error = ""
        self.session = None
        self.task = None
        self.access_token = ""
        self.token_expires = 0
        self.token_lock = asyncio.Lock()
        self.send_lock = asyncio.Lock()
        self.session_id = ""
        self.sequence = None
        self.bot_id = ""
        self.contexts = OrderedDict()
        self.awaiting_ack = False
        self.generation = 0

    @property
    def connected(self):
        return self.ready and self.ws is not None and not self.ws.closed

    @property
    def self_id(self):
        return "official:" + self.cfg["app_id"] if self.cfg["enabled"] else ""

    async def start(self):
        if self.cfg["enabled"] and self.task is None:
            self.session = ClientSession(timeout=ClientTimeout(total=15), trust_env=False)
            self.task = asyncio.create_task(self.run())

    async def close(self):
        self.generation += 1
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None
        if self.ws is not None and not self.ws.closed:
            await self.ws.close()
        if self.session:
            await self.session.close()
            self.session = None
        self.ready = False
        self.access_token = ""
        self.error = ""
        self.token_expires = 0
        self.session_id = ""
        self.sequence = None
        self.contexts.clear()

    async def _json(self, method, path, payload=None, authenticated=True):
        if self.session is None or self.session.closed:
            raise ConnectionError("QQ 官机尚未启动")
        headers = {"Authorization": "QQBot " + await self.token()} if authenticated else {}
        async with self.session.request(method, self.API_BASE + path, json=payload, headers=headers, allow_redirects=False) as response:
            raw = await response.content.read(256 * 1024 + 1)
            if len(raw) > 256 * 1024:
                raise RuntimeError("QQ 官机接口返回数据过大")
            try:
                data = json.loads(raw) if raw else {}
            except (ValueError, UnicodeError):
                raise RuntimeError(f"QQ 官机接口返回无效数据（HTTP {response.status}）") from None
            if not isinstance(data, dict):
                raise RuntimeError("QQ 官机接口返回格式错误")
            code = data.get("err_code", data.get("code", 0))
            if not 200 <= response.status < 300 or code not in (0, "0", None):
                safe_code = str(code) if isinstance(code, (int, str)) and re.fullmatch(r"[0-9]{1,12}", str(code)) else "未知"
                # Never expose vendor response bodies or headers containing credentials.
                raise RuntimeError(f"QQ 官机接口请求失败（HTTP {response.status}，错误码 {safe_code}）")
            return data

    async def token(self):
        async with self.token_lock:
            if self.access_token and time.monotonic() < self.token_expires:
                return self.access_token
            generation = self.generation
            data = await self._json("POST", "/app/getAppAccessToken", {"appId": self.cfg["app_id"], "clientSecret": self.cfg["client_secret"]}, authenticated=False)
            token, expires = data.get("access_token"), data.get("expires_in")
            try:
                if isinstance(expires, bool):
                    raise ValueError()
                expires = int(expires)
            except (TypeError, ValueError, OverflowError):
                raise RuntimeError("QQ 官机访问凭证有效期错误") from None
            if not isinstance(token, str) or not re.fullmatch(r"[!-~]{1,4096}", token) or not 1 <= expires <= 86400:
                raise RuntimeError("QQ 官机访问凭证格式错误")
            if generation != self.generation:
                raise ConnectionError("QQ 官机配置已经变更")
            self.access_token = token
            self.token_expires = time.monotonic() + max(1, expires - min(60, expires / 2))
            return token

    @staticmethod
    def valid_gateway(url):
        try:
            parts = urlsplit(url)
            return (parts.scheme == "wss" and parts.hostname in ("api.bot.qq.com", "api.sgroup.qq.com")
                    and parts.port in (None, 443) and not parts.username and not parts.password and not parts.fragment)
        except (TypeError, ValueError):
            return False

    async def run(self):
        delay = 1
        while True:
            try:
                await self.connect()
                delay = 1
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.ready = False
                self.error = str(error) if isinstance(error, (RuntimeError, ConnectionError)) else "QQ 官机网络连接失败"
                self.store.audit("error", self.error)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

    async def connect(self):
        gateway = await self._json("GET", "/gateway")
        url = gateway.get("url")
        if not self.valid_gateway(url):
            raise RuntimeError("QQ 官机网关地址不在官方 HTTPS/WSS 范围内")
        heartbeat = None
        async with self.session.ws_connect(url, max_msg_size=256 * 1024, autoping=True) as ws:
            self.ws = ws
            try:
                first = await asyncio.wait_for(ws.receive(), 15)
                hello = json.loads(first.data) if first.type == WSMsgType.TEXT else {}
                body = hello.get("d") if isinstance(hello, dict) else None
                interval = body.get("heartbeat_interval") if isinstance(body, dict) else None
                if not isinstance(hello, dict) or hello.get("op") != 10 or type(interval) is not int or not 100 <= interval <= 300000:
                    raise RuntimeError("QQ 官机网关握手数据无效")
                token = "QQBot " + await self.token()
                if self.session_id:
                    await ws.send_json({"op": 6, "d": {"token": token, "session_id": self.session_id, "seq": self.sequence}})
                else:
                    await ws.send_json({"op": 2, "d": {"token": token, "intents": self.INTENTS, "shard": [0, 1]}})
                self.awaiting_ack = False
                heartbeat = asyncio.create_task(self.heartbeat(ws, interval / 1000))
                async for message in ws:
                    if message.type != WSMsgType.TEXT:
                        continue
                    try:
                        data = json.loads(message.data)
                    except (ValueError, UnicodeError):
                        continue
                    if not isinstance(data, dict):
                        continue
                    op = data.get("op")
                    if op == 11:
                        self.awaiting_ack = False
                    elif op == 1:
                        await ws.send_json({"op": 1, "d": self.sequence})
                    elif op in (7, 9):
                        if op == 9:
                            self.session_id = ""; self.sequence = None; self.token_expires = 0
                        break
                    elif op == 0:
                        kind, body = data.get("t"), data.get("d")
                        if kind == "READY" and isinstance(body, dict):
                            session_id = body.get("session_id")
                            if not isinstance(session_id, str) or not 1 <= len(session_id) <= 256:
                                raise RuntimeError("QQ 官机登录会话格式错误")
                            self.session_id = session_id
                            user = body.get("user")
                            self.bot_id = str(user.get("id", "")) if isinstance(user, dict) else ""
                            self.ready = True; self.error = ""
                            self.store.audit("onebot", f"QQ 官机 AppID {self.cfg['app_id']} 已连接")
                        elif kind == "RESUMED":
                            self.ready = True; self.error = ""
                        elif self.ready:
                            self.dispatch(kind, body)
                        if type(data.get("s")) is int and data["s"] >= 0:
                            self.sequence = data["s"]
            finally:
                self.ready = False
                if heartbeat:
                    heartbeat.cancel()
                    with suppress(asyncio.CancelledError):
                        await heartbeat
                self.ws = None

    async def heartbeat(self, ws, interval):
        while True:
            await asyncio.sleep(interval)
            if self.awaiting_ack:
                await ws.close(code=1000, message=b"Heartbeat timeout")
                return
            try:
                await self.token()
            except asyncio.CancelledError:
                raise
            except Exception:
                await ws.close(code=1000, message=b"Token refresh failed")
                return
            self.awaiting_ack = True
            await ws.send_json({"op": 1, "d": self.sequence})

    def dispatch(self, kind, data):
        if kind not in ("GROUP_AT_MESSAGE_CREATE", "C2C_MESSAGE_CREATE") or not isinstance(data, dict):
            return
        author, mid, content = data.get("author"), data.get("id"), data.get("content", "")
        if not isinstance(author, dict) or not isinstance(mid, str) or not 1 <= len(mid) <= 512 or not isinstance(content, str) or len(content) > 20000:
            return
        group_message = kind == "GROUP_AT_MESSAGE_CREATE"
        try:
            user = official_id("qug" if group_message else "qup", self.cfg["app_id"], author.get("member_openid" if group_message else "user_openid"))
            group = official_id("qg", self.cfg["app_id"], data.get("group_openid")) if group_message else ""
        except ValueError:
            return
        mention = re.match(r"^\s*<@!?([A-Za-z0-9_-]+)>\s*", content)
        if mention and mention[1] == self.bot_id:
            content = content[mention.end():]
        message = [{"type": "text", "data": {"text": content.strip()}}]
        if isinstance(data.get("attachments"), list) and data["attachments"]:
            message.append({"type": "image", "data": {}})
        target = group if group_message else user
        previous = self.contexts.get(target)
        if not previous or previous["id"] != mid:
            self.contexts[target] = {"id": mid, "expires": time.monotonic() + self.REPLY_SECONDS, "sequence": 0}
        self.contexts.move_to_end(target)
        while len(self.contexts) > 2048:
            self.contexts.popitem(last=False)
        event = {"post_type": "message", "message_type": "group" if group_message else "private", "self_id": self.self_id,
                 "user_id": user, "group_id": group, "message_id": mid, "message": message,
                 "sender": {"nickname": author.get("username", "官方用户")}, "provider": "official"}
        try:
            self.events.put_nowait(event)
        except asyncio.QueueFull:
            self.store.audit("error", "QQ 官机事件队列已满，丢弃新事件")

    async def send(self, target, text, kinds, endpoint):
        parts = official_parts(target, kinds)
        if not parts or parts[1] != self.cfg["app_id"]:
            raise ConnectionError("官机目标身份不属于当前应用或场景")
        if not self.connected:
            raise ConnectionError("QQ 官机尚未连接")
        if not isinstance(text, str):
            raise RuntimeError("QQ 官机消息必须是文字")
        generation = self.generation
        async with self.send_lock:
            if generation != self.generation or parts[1] != self.cfg["app_id"] or not self.connected:
                raise ConnectionError("QQ 官机配置或连接已经变更，消息未发送")
            context = self.contexts.get(target)
            payload = {"content": text[:3500], "msg_type": 0}
            if context and time.monotonic() < context["expires"]:
                context["sequence"] += 1
                payload.update(msg_id=context["id"], msg_seq=context["sequence"])
            elif not self.cfg["allow_active"]:
                raise RuntimeError("QQ 官机缺少有效回复消息，请先 @机器人；主动发送需单独启用并具备平台权限")
            return await self._json("POST", endpoint.format(openid=quote(parts[2], safe="")), payload)

    async def send_group(self, group, text):
        return await self.send(group, text, ("qg",), "/v2/groups/{openid}/messages")

    async def send_private(self, user, text):
        return await self.send(user, text, ("qup",), "/v2/users/{openid}/messages")
