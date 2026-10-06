import asyncio
from collections import defaultdict, deque
import re
import time


HELP = """星桥 · Minecraft 群助手
帮助 — 查看命令
状态 / 在线 — 查看服务器状态与玩家
绑定 验证码 — 先在游戏中输入 /qbind
我的绑定 — 查看游戏账号
解绑 — 解除自己的绑定
执行 命令名 — 管理员执行预设命令
普通群消息会同步到游戏。"""


def plain_message(message):
    if isinstance(message, str):
        # Remove CQ segments before decoding so escaped user text stays literal.
        text = re.sub(r"\[CQ:[^\]]*\]", "", message)
        for old, new in (("&#91;", "["), ("&#93;", "]"), ("&#44;", ","), ("&amp;", "&")):
            text = text.replace(old, new)
        return text.strip()
    if isinstance(message, list):
        parts = []
        for segment in message:
            if not isinstance(segment, dict):
                continue
            data = segment.get("data")
            if segment.get("type") == "text" and isinstance(data, dict) and isinstance(data.get("text"), str):
                parts.append(data["text"])
            elif segment.get("type") == "image":
                parts.append("[图片]")
        return "".join(parts).strip()
    return ""


def clean_text(value, limit=500):
    text = re.sub(r"§.", "", str(value))
    return "".join(c for c in text if c.isprintable())[:limit]


class Bot:
    def __init__(self, cfg, store, onebot):
        self.cfg, self.store, self.onebot = cfg, store, onebot
        self.servers = {s["id"]: s for s in cfg["servers"]}
        self.groups = {g: s for s in cfg["servers"] for g in s["groups"]}
        self.snapshots = {}
        self.limits = defaultdict(deque)
        self.started = time.time()
        self.plugins = None
        self.authentication = None
        self.registration = None
        self.operations = None

    def allow(self, key, count=12, period=10):
        now = time.monotonic()
        if len(self.limits) > 10000:
            self.limits = defaultdict(deque, {k: v for k, v in self.limits.items() if v and now - v[-1] < 60})
        entries = self.limits[key]
        while entries and now - entries[0] >= period:
            entries.popleft()
        if len(entries) >= count:
            return False
        entries.append(now)
        return True

    def online(self, sid):
        return time.time() - self.snapshots.get(sid, {}).get("last_seen", 0) < 15

    def status_text(self, server, players=False):
        sid = server["id"]
        if not self.online(sid):
            return f"{server['name']}：桥接离线，请检查 Minecraft 插件与令牌。"
        snap = self.snapshots[sid]
        text = f"{server['name']} · 在线\n玩家：{len(snap['players'])}/{snap['max_players']}\n版本：{snap['version']}"
        if players:
            text += "\n在线玩家：" + ("、".join(snap["players"]) or "暂无玩家")
        return text

    async def worker(self):
        while True:
            event = await self.onebot.events.get()
            try:
                if self.onebot.connected and str(event.get("self_id")) == self.onebot.self_id:
                    await self.handle_event(event)
            except Exception as exc:
                self.store.audit("error", f"处理群事件失败：{type(exc).__name__}: {exc}")
            finally:
                self.onebot.events.task_done()

    async def handle_event(self, event):
        group, qq = str(event.get("group_id", "")), str(event.get("user_id", ""))
        if (event.get("post_type") == "message" and event.get("message_type") == "private"
                and not event.get("anonymous") and qq.isdigit() and qq != str(event.get("self_id")) and self.authentication):
            mid = event.get("message_id")
            if not isinstance(mid, (int, str)) or isinstance(mid, bool):
                return
            if self.store.seen(f"qq-private:{event.get('self_id')}:{qq}:{mid}") or not self.allow(("qq-private", qq), count=5, period=10):
                return
            text = plain_message(event.get("message", ""))[:200]
            command, _, token = text.partition(" ")
            if command in ("/确认登录", "/拒绝登录"):
                try:
                    reply = self.authentication.confirm(qq, token.strip(), command == "/确认登录")
                except ValueError as exc:
                    reply = "[×] " + str(exc)
                await self.onebot.send_private(qq, reply)
            return
        server = self.groups.get(group)
        if not server or not qq.isdigit() or qq == str(event.get("self_id")):
            return
        sid = server["id"]
        if event.get("post_type") == "notice":
            if event.get("notice_type") == "group_decrease" and self.cfg["features"].get("unbind_on_leave"):
                if self.store.unbind(sid, qq):
                    self.store.audit("binding", f"{qq} 退群，已解除 {sid} 绑定")
            return
        if event.get("post_type") != "message" or event.get("message_type") != "group" or event.get("anonymous"):
            return
        mid = event.get("message_id")
        if not isinstance(mid, (str, int)) or isinstance(mid, bool):
            return
        if self.store.seen(f"qq:{event.get('self_id')}:{group}:{mid}"):
            return
        if not self.allow((group, qq)):
            return
        text = plain_message(event.get("message", ""))[:2000]
        if not text:
            return
        command, _, arg = text.partition(" ")
        arg = arg.strip()
        reply = None
        if command in ("帮助", "help", "/help"):
            reply = HELP
            if self.registration and self.registration.settings["enabled"]:
                reply += "\n/申请 玩家名 QQ号 — 邮箱验证注册\n/注册 验证码 — 完成社区账号注册"
            if self.operations and self.operations.config()["settings"]["enabled"]:
                reply += "\n/白名单 玩家名 [理由] — 申请入服\n/白名单状态 — 查询申请进度"
        elif command in ("/白名单", "/白名单状态") and self.operations:
            reply = await self.operations.group_command(command, arg, server, group, qq)
        elif command in ("/申请", "/注册") and self.registration:
            reply = await self.registration.group_command(command, arg, server, group, qq)
        elif command in ("/确认登录", "/拒绝登录"):
            reply = "请私聊机器人使用登录确认指令，不要将确认消息发送到群里。"
        elif command in ("状态", "在线"):
            reply = self.status_text(server, command == "在线")
        elif command == "绑定":
            if not self.allow(("bind", group, qq), count=5, period=60):
                reply = "验证码尝试过多，请一分钟后重试。"
            else:
                try:
                    row = self.store.bind(sid, qq, arg)
                    reply = f"绑定成功：{row['name']}（{server['name']}）"
                    self.store.audit("binding", f"{qq} 绑定 {sid}/{row['name']}")
                    if self.cfg["features"].get("set_group_card"):
                        try:
                            await self.onebot.call("set_group_card", {"group_id": int(group), "user_id": int(qq), "card": row["name"]})
                        except (RuntimeError, ConnectionError, TimeoutError):
                            reply += "\n群名片更新失败，请确认机器人有管理员权限。"
                except ValueError as exc:
                    reply = str(exc)
        elif command == "我的绑定":
            row = self.store.binding(sid, qq)
            reply = f"你的绑定：{row['name']}（{server['name']}）" if row else "尚未绑定，请在游戏中输入 /qbind。"
        elif command == "解绑":
            removed = self.store.unbind(sid, qq)
            reply = "已解除绑定。" if removed else "你还没有绑定账号。"
            if removed:
                self.store.audit("binding", f"{qq} 解除 {sid} 绑定")
        elif command == "执行":
            if qq not in self.cfg["onebot"].get("admins", []):
                reply = "权限不足：只有配置中的机器人管理员能执行服务器命令。"
            elif arg not in server.get("commands", {}):
                reply = "可用命令：" + "、".join(server.get("commands", {}))
            elif not self.online(sid):
                reply = "桥接离线，命令未提交。"
            else:
                try:
                    self.store.enqueue(sid, {"kind": "command", "command": server["commands"][arg], "reply_group": group})
                    self.store.audit("command", f"{qq} 请求 {sid} 预设命令 {arg}")
                    reply = f"已提交「{arg}」，等待服务器执行。"
                except ValueError as exc:
                    reply = str(exc)
        elif self.plugins and await self.plugins.group_message(server, group, qq, text):
            pass
        elif self.cfg["features"].get("qq_to_mc") and self.online(sid):
            sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
            name = clean_text(sender.get("card") or sender.get("nickname") or qq, 32)
            row = self.store.binding(sid, qq)
            if row:
                name = row["name"]
            try:
                self.store.enqueue(sid, {"kind": "broadcast", "text": f"[QQ] {name}: {clean_text(text)}"})
                self.store.audit("relay", f"QQ → {sid}：{name}")
            except ValueError as exc:
                self.store.audit("error", str(exc))
        if reply is not None:
            await self.onebot.send_group(group, reply)

    async def relay_game(self, server, data):
        if self.plugins:
            try:
                await self.plugins.game_event(server, data)
            except Exception as exc:
                self.store.audit("error", f"插件事件处理失败：{type(exc).__name__}")
        kind = data["kind"]
        name = clean_text(data.get("player", ""), 32)
        if kind == "chat" and self.cfg["features"].get("mc_to_qq"):
            text = f"[{server['name']}] {name}: {clean_text(data.get('text', ''))}"
        elif kind in ("join", "quit") and self.cfg["features"].get("join_quit"):
            text = f"[{server['name']}] {name} {'加入了游戏' if kind == 'join' else '离开了游戏'}"
        else:
            return
        for group in server["groups"]:
            try:
                await self.onebot.send_group(group, text)
            except (ConnectionError, RuntimeError, TimeoutError) as exc:
                self.store.audit("error", f"游戏消息发送失败（不重放）：{exc}")
        self.store.audit("relay", f"{server['id']} → QQ：{kind}/{name}")
