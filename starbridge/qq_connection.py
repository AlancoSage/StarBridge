"""Keep the existing OneBot contract while selecting QQ's official transport."""
from copy import deepcopy
from aiohttp import web

from .onebot import OneBot
from .qq_official import QQOfficial
from .qq_identity import OFFICIAL_DEFAULTS, official_parts


class QQConnection:
    def __init__(self, cfg, store):
        self.legacy = OneBot(cfg["onebot"], store)
        self.events = self.legacy.events
        self.pending = self.legacy.pending
        self.official = QQOfficial(cfg.get("qq_official", {}), store, self.events)
        self.started = False

    @property
    def provider(self):
        return "official" if self.official.cfg["enabled"] else "onebot"

    @property
    def current(self):
        return self.official if self.provider == "official" else self.legacy

    @property
    def connected(self):
        return self.current.connected

    @property
    def self_id(self):
        return self.current.self_id

    @self_id.setter
    def self_id(self, value):
        if self.provider == "official":
            raise ValueError("官机身份由 AppID 决定")
        self.legacy.self_id = value

    @property
    def ws(self):
        return self.current.ws

    @ws.setter
    def ws(self, value):
        self.current.ws = value

    @property
    def cfg(self):
        return self.legacy.cfg

    @cfg.setter
    def cfg(self, value):
        self.legacy.cfg = value

    def valid_user(self, value):
        if self.provider == "onebot":
            return isinstance(value, str) and value.isdigit()
        parts = official_parts(value, ("qug", "qup"))
        return bool(parts and parts[1] == self.official.cfg["app_id"])

    async def handle(self, request):
        if self.provider == "official":
            raise web.HTTPConflict(text="当前使用 QQ 官方接入，请在面板切换到 OneBot 后再连接")
        return await self.legacy.handle(request)

    async def start(self):
        self.started = True
        await self.official.start()

    async def close(self):
        self.started = False
        await self.official.close()
        if self.legacy.connected:
            await self.legacy.ws.close()

    async def reconfigure(self, cfg, reconnect):
        if reconnect:
            await self.official.close()
            if self.legacy.connected:
                await self.legacy.ws.close(code=1000, message=b"Configuration updated")
            while not self.events.empty():
                self.events.get_nowait(); self.events.task_done()
        self.legacy.cfg = cfg["onebot"]
        self.official.cfg = {**deepcopy(OFFICIAL_DEFAULTS), **deepcopy(cfg.get("qq_official", {}))}
        if self.started:
            await self.official.start()

    async def call(self, action, params):
        if self.provider == "official":
            raise RuntimeError("QQ 官机不提供 OneBot 群管理接口")
        return await self.legacy.call(action, params)

    async def send_group(self, group, text):
        return await self.current.send_group(group, text)

    async def send_private(self, user, text):
        return await self.current.send_private(user, text)
