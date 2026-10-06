import asyncio
import json
import secrets
import uuid

from aiohttp import WSMsgType, web


class OneBot:
    def __init__(self, cfg, store):
        self.cfg, self.store = cfg, store
        self.ws = None
        self.self_id = ""
        self.pending = {}
        self.events = asyncio.Queue(maxsize=256)

    @property
    def connected(self):
        return self.ws is not None and not self.ws.closed

    async def handle(self, request):
        expected = "Bearer " + self.cfg["token"]
        if not secrets.compare_digest(request.headers.get("Authorization", "").encode(), expected.encode()):
            raise web.HTTPUnauthorized(text="OneBot token 不正确")
        sid = request.headers.get("X-Self-ID", "")
        configured = self.cfg.get("self_id", "")
        if not sid.isdigit() or (configured and sid != configured):
            raise web.HTTPForbidden(text="X-Self-ID 缺失或与配置不符")
        if request.headers.get("X-Client-Role", "Universal").lower() != "universal":
            raise web.HTTPBadRequest(text="请选择 Universal / 通用反向 WebSocket")
        if self.connected:
            raise web.HTTPConflict(text="已有机器人连接，请先断开旧连接")
        ws = web.WebSocketResponse(heartbeat=30, max_msg_size=256 * 1024)
        # Reserve the connection before the handshake can yield to another request.
        self.ws, self.self_id = ws, sid
        try:
            await ws.prepare(request)
            self.store.audit("onebot", f"机器人 {sid} 已连接")
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                    if not isinstance(data, dict):
                        continue
                    if "post_type" in data:
                        if str(data.get("self_id", "")) != sid:
                            continue
                        if data["post_type"] != "meta_event":
                            try:
                                self.events.put_nowait(data)
                            except asyncio.QueueFull:
                                self.store.audit("error", "事件队列已满，丢弃新事件")
                    else:
                        echo = data.get("echo")
                        fut = self.pending.get(echo) if isinstance(echo, str) else None
                        if fut is not None and not fut.done():
                            fut.set_result(data)
                except (ValueError, TypeError):
                    self.store.audit("error", "忽略格式无效的 OneBot 数据")
        finally:
            if self.ws is ws:
                self.ws = None
                for fut in self.pending.values():
                    if not fut.done():
                        fut.set_exception(ConnectionError("OneBot 连接断开"))
                self.store.audit("onebot", "机器人连接断开")
        return ws

    async def call(self, action, params):
        if not self.connected:
            raise ConnectionError("OneBot 尚未连接")
        echo = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.pending[echo] = future
        try:
            await self.ws.send_json({"action": action, "params": params, "echo": echo})
            response = await asyncio.wait_for(future, timeout=10)
            if response.get("status") != "ok" or response.get("retcode") != 0:
                raise RuntimeError(f"OneBot {action} 失败，retcode={response.get('retcode')}")
            return response.get("data")
        finally:
            self.pending.pop(echo, None)

    async def send_group(self, group, text):
        return await self.call("send_group_msg", {
            "group_id": int(group),
            "message": [{"type": "text", "data": {"text": text[:3500]}}],
        })

    async def send_private(self, user, text):
        return await self.call("send_private_msg", {
            "user_id": int(user), "message": [{"type": "text", "data": {"text": text[:3500]}}],
        })
