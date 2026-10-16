"""Keep the existing OneBot contract while selecting QQ's official transport."""
from copy import deepcopy
from aiohttp import web

from .onebot import OneBot
from .qq_official import QQOfficial
from .qq_identity import OFFICIAL_DEFAULTS, official_parts
from .reply_images import DEFAULTS as IMAGE_DEFAULTS, ReplyRenderer, command_key


class QQConnection:
    def __init__(self, cfg, store):
        self.legacy = OneBot(cfg["onebot"], store)
        self.events = self.legacy.events
        self.pending = self.legacy.pending
        self.official = QQOfficial(cfg.get("qq_official", {}), store, self.events)
        self.started = False
        self.store = store
        self.renderer = ReplyRenderer()
        self.image_config = {**deepcopy(IMAGE_DEFAULTS), **deepcopy(cfg.get('reply_images', {}))}
        self.generation = 0

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
        self.generation += 1
        await self.official.close()
        if self.legacy.connected:
            await self.legacy.ws.close()

    async def reconfigure(self, cfg, reconnect):
        if reconnect:
            self.generation += 1
            await self.official.close()
            if self.legacy.connected:
                await self.legacy.ws.close(code=1000, message=b"Configuration updated")
            while not self.events.empty():
                self.events.get_nowait(); self.events.task_done()
        self.legacy.cfg = cfg["onebot"]
        self.official.cfg = {**deepcopy(OFFICIAL_DEFAULTS), **deepcopy(cfg.get("qq_official", {}))}
        self.image_config = {**deepcopy(IMAGE_DEFAULTS), **deepcopy(cfg.get('reply_images', {}))}
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

    async def send_reply(self, group, text, command):
        key = command_key(command)
        settings = deepcopy(self.image_config)
        if not settings['enabled'] or key not in settings['commands']:
            return await self.send_group(group, text)
        generation = self.generation
        try:
            pages = await self.renderer.render(text, key)
        except Exception as error:
            # Log only the error type; reply bodies may contain private account data.
            self.store.audit('error', '图片回复渲染失败，回退文字：' + type(error).__name__)
            pages = None
        if generation != self.generation:
            raise ConnectionError('接入配置已经变更，旧图片回复未发送')
        if pages is None or self.image_config != settings:
            return await self.send_group(group, text)
        result = None
        for index, png in enumerate(pages):
            if generation != self.generation:
                raise ConnectionError('接入配置已经变更，旧图片回复未发送')
            if self.image_config != settings:
                if index:
                    raise ConnectionError('图片回复设置已变更，后续图片未发送')
                return await self.send_group(group, text)
            try:
                result = await self.current.send_group_image(group, png)
            except (RuntimeError, ValueError) as error:
                if generation != self.generation:
                    raise ConnectionError('接入配置已经变更，旧图片回复未发送') from None
                if index:
                    raise  # Some pages already arrived; do not replay the full reply.
                self.store.audit('error', '图片回复被拒绝，回退文字：' + type(error).__name__)
                return await self.send_group(group, text)
        return result
