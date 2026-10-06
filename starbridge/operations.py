"""Bounded scheduler and manually reviewed whitelist applications."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import re
import time
import uuid

from .bot import clean_text

CHINA = timezone(timedelta(hours=8))
PLAYER = re.compile(r"[A-Za-z0-9_]{1,16}")
QQ = re.compile(r"[1-9][0-9]{0,19}")
WHITELIST_DEFAULT = {"enabled": False, "require_registered": False, "require_bound": False,
                     "cooldown_minutes": 30, "max_pending": 100}
ACTIVE = ("pending", "approved", "submitted", "success")


class OperationError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def text(value, label, limit, required=False):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value) or (required and not value.strip()):
        raise OperationError(f"{label}需为不超过 {limit} 字的单行文字")
    return value.strip()


def whitelist_settings(value):
    if not isinstance(value, dict) or value.keys() != WHITELIST_DEFAULT.keys():
        raise OperationError("白名单设置字段不完整或包含未知字段")
    for key in ("enabled", "require_registered", "require_bound"):
        if type(value[key]) is not bool:
            raise OperationError("白名单开关必须是布尔值")
    for key, maximum in (("cooldown_minutes", 1440), ("max_pending", 500)):
        if type(value[key]) is not int or not 1 <= value[key] <= maximum:
            raise OperationError(f"{key}需为 1–{maximum} 的整数")
    return deepcopy(value)


def task_definition(value, bot=None):
    fields = {"name", "enabled", "schedule", "interval_minutes", "clock", "weekdays", "action", "server", "group", "message", "command"}
    if not isinstance(value, dict) or value.keys() != fields:
        raise OperationError("定时任务字段不完整或包含未知字段")
    out = deepcopy(value)
    out["name"] = text(value["name"], "任务名称", 60, True)
    if type(value["enabled"]) is not bool or value["schedule"] not in ("interval", "daily"):
        raise OperationError("请选择间隔执行或按星期定点执行")
    if type(value["interval_minutes"]) is not int or not 1 <= value["interval_minutes"] <= 43200:
        raise OperationError("执行间隔需为 1–43200 分钟")
    if not isinstance(value["clock"], str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value["clock"]):
        raise OperationError("执行时间需为 HH:MM")
    days = value["weekdays"]
    if not isinstance(days, list) or not 1 <= len(days) <= 7 or any(type(d) is not int or d not in range(1,8) for d in days) or len(set(days)) != len(days):
        raise OperationError("请至少选择一个星期，1 表示周一，7 表示周日")
    if value["action"] not in ("qq_message", "game_message", "command", "backup"):
        raise OperationError("不支持这个任务动作")
    for key in ("server", "group", "command"):
        out[key] = text(value[key], key, 80)
    if not isinstance(value["message"], str) or len(value["message"]) > 2000:
        raise OperationError("公告最多 2000 字")
    if value["action"] in ("qq_message", "game_message") and not value["message"].strip():
        raise OperationError("请填写公告内容")
    if value["action"] == "game_message" and len(value["message"]) > 600:
        raise OperationError("游戏公告最多 600 字")
    if bot is not None and value["action"] != "backup":
        server = bot.servers.get(out["server"])
        if server is None:
            raise OperationError("请先配置并选择服务器")
        if value["action"] == "qq_message" and out["group"] not in server["groups"]:
            raise OperationError("请选择该服务器关联的群聊")
        if value["action"] == "command" and out["command"] not in server.get("commands", {}):
            raise OperationError("只能选择面板中已有的预设命令")
    return out


def next_run(definition, now):
    if definition["schedule"] == "interval":
        return now + definition["interval_minutes"] * 60
    local = datetime.fromtimestamp(now, CHINA)
    hour, minute = map(int, definition["clock"].split(":"))
    for offset in range(8):
        candidate = (local + timedelta(days=offset)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate.isoweekday() in definition["weekdays"] and candidate.timestamp() > now:
            return candidate.timestamp()
    raise OperationError("无法计算下一次执行时间")


class Operations:
    def __init__(self, state):
        self.state = state
        self.store, self.bot = state["store"], state["bot"]
        self.db = self.store.db
        self.running = set()
        # An interrupted execution is uncertain; never automatically replay it.
        with self.db:
            self.db.execute("UPDATE schedule_runs SET status='interrupted',detail='服务重启，执行未确认；未自动重放',finished=? WHERE status='running'", (time.time(),))
            self.db.execute("UPDATE scheduled_tasks SET status='interrupted',detail='服务重启，执行未确认；未自动重放' WHERE status='running'")

    def config(self):
        row = self.db.execute("SELECT * FROM operations_settings WHERE key='whitelist'").fetchone()
        if not row:
            return {"settings": deepcopy(WHITELIST_DEFAULT), "revision": 0, "error": ""}
        try:
            return {"settings": whitelist_settings(json.loads(row["value"])), "revision": row["revision"], "error": ""}
        except (ValueError, TypeError):
            return {"settings": deepcopy(WHITELIST_DEFAULT), "revision": row["revision"], "error": "白名单设置损坏，申请已关闭；请重新保存设置"}

    def save_config(self, settings, revision):
        if type(revision) is not int or revision != self.config()["revision"]:
            raise OperationError("白名单设置已变化，请重新载入", 409)
        value = whitelist_settings(settings)
        with self.db:
            self.db.execute("INSERT INTO operations_settings VALUES('whitelist',?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,revision=excluded.revision",
                            (json.dumps(value), revision+1))
        self.store.audit("whitelist", "管理员保存白名单申请设置")
        return self.config()

    def task(self, task_id):
        row = self.db.execute("SELECT * FROM scheduled_tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise OperationError("任务不存在", 404)
        result = dict(row)
        try:
            result["definition"] = task_definition(json.loads(row["definition"]))
        except (ValueError, TypeError):
            result["definition"] = None
            result.update(status="invalid", detail="任务定义损坏，请删除后重新创建")
        return result

    def expire(self):
        now = time.time()
        with self.db:
            self.db.execute("UPDATE scheduled_tasks SET status='unconfirmed',detail='游戏端未确认；请核对状态，未自动重放' WHERE EXISTS(SELECT 1 FROM schedule_runs r WHERE r.task=scheduled_tasks.id AND r.started=scheduled_tasks.last_run AND r.status='submitted' AND r.started<?)", (now-75,))
            self.db.execute("UPDATE schedule_runs SET status='unconfirmed',detail='游戏端未确认；请核对状态，未自动重放',finished=? WHERE status='submitted' AND started<?", (now, now-75))
            self.db.execute("UPDATE whitelist_applications SET status='unconfirmed',review='游戏端未确认，请核对服务器白名单后重试',updated=?,revision=revision+1 WHERE status='submitted' AND updated<?", (now, now-75))

    def tasks(self):
        self.expire()
        return {"tasks": [self.task(r[0]) for r in self.db.execute("SELECT id FROM scheduled_tasks ORDER BY rowid DESC")],
                "runs": [dict(r) for r in self.db.execute("SELECT * FROM schedule_runs ORDER BY started DESC LIMIT 30")], "timezone": "Asia/Shanghai",
                "plugin": self.scheduler_plugin(), "plugin_revision": self.state['plugins'].revision,
                "servers": [{key: server[key] for key in ('id','name','groups','commands')} for server in self.bot.servers.values()]}

    def scheduler_plugin(self):
        return next((plugin for plugin in self.state['plugins'].listing()['plugins'] if plugin['id']=='scheduled_tasks'), None)

    def scheduler_enabled(self):
        entry = self.state['plugins'].entries.get('scheduled_tasks')
        return bool(entry and entry['enabled'] and entry['status']=='running' and not self.state['plugins'].state_error)

    def check_schedule_permissions(self, definition):
        policy = self.state['plugins'].entries['scheduled_tasks']['permissions']
        capability = {'qq_message':'send_group','game_message':'send_game','command':'execute_commands','backup':'create_backups'}[definition['action']]
        if not policy[capability]:
            raise OperationError('定时任务插件未获授权执行此动作', 403)
        if definition['action']!='backup' and policy['servers'] and definition['server'] not in policy['servers']:
            raise OperationError('目标服务器不在定时任务插件的授权范围内', 403)
        if definition['action']=='qq_message' and policy['groups'] and definition['group'] not in policy['groups']:
            raise OperationError('目标群不在定时任务插件的授权范围内', 403)

    def save_task(self, value, task_id=None, revision=None):
        definition = task_definition(value, self.bot)
        if definition["action"] == "backup" and self.state.get("config_file") is None:
            raise OperationError("此启动方式无法创建备份")
        if task_id:
            old = self.task(task_id)
            if type(revision) is not int or revision != old["revision"]:
                raise OperationError("任务已被其他页面修改，请重新载入", 409)
            if task_id in self.running:
                raise OperationError("任务正在执行，请稍后修改", 409)
        elif self.db.execute("SELECT count(*) FROM scheduled_tasks").fetchone()[0] >= 100:
            raise OperationError("最多保留 100 个定时任务")
        task_id = task_id or uuid.uuid4().hex
        with self.db:
            self.db.execute("INSERT INTO scheduled_tasks(id,definition,revision,next_run) VALUES(?,?,1,?) ON CONFLICT(id) DO UPDATE SET definition=excluded.definition,revision=scheduled_tasks.revision+1,next_run=excluded.next_run",
                            (task_id, json.dumps(definition, ensure_ascii=False), next_run(definition, time.time())))
        self.store.audit("schedule", f"管理员保存定时任务 {definition['name']}")
        return self.task(task_id)

    def delete_task(self, task_id, revision):
        row = self.task(task_id)
        if type(revision) is not int or revision != row["revision"] or task_id in self.running:
            raise OperationError("任务已变化或正在执行，请重新载入", 409)
        with self.db:
            self.db.execute("DELETE FROM scheduled_tasks WHERE id=?", (task_id,))
        self.store.audit("schedule", f"管理员删除定时任务 {task_id}")

    async def run_task(self, task_id, manual=False, revision=None):
        if not self.scheduler_enabled():
            if manual:
                raise OperationError('定时任务插件已停用，请先启用插件', 403)
            return None
        if self.state.get("maintenance"):
            raise OperationError("正在恢复备份，请稍后操作", 409)
        row = self.task(task_id)
        if manual and (type(revision) is not int or revision != row["revision"]):
            raise OperationError("任务已变化，请重新载入", 409)
        self.expire()
        if task_id in self.running or self.db.execute("SELECT 1 FROM schedule_runs WHERE task=? AND status IN ('running','submitted')", (task_id,)).fetchone():
            raise OperationError("任务正在执行", 409)
        if not row["definition"]:
            raise OperationError("任务定义损坏")
        definition, now = row["definition"], time.time()
        if not manual and (not definition["enabled"] or row["next_run"] > now):
            return None
        # Persist the new deadline before any side effect. A restart cannot replay it.
        with self.db:
            if not manual:
                self.db.execute("UPDATE scheduled_tasks SET next_run=? WHERE id=?", (next_run(definition, now), task_id))
            self.db.execute("UPDATE scheduled_tasks SET last_run=?,status='running',detail='正在执行' WHERE id=?", (now, task_id))
            run_id = uuid.uuid4().hex
            self.db.execute("INSERT INTO schedule_runs(id,task,name,started,finished,status,detail) VALUES(?,?,?,?,0,'running','正在执行')", (run_id, task_id, definition["name"], now))
            self.db.execute("DELETE FROM schedule_runs WHERE id IN (SELECT id FROM schedule_runs WHERE status!='running' AND status!='submitted' ORDER BY started DESC LIMIT -1 OFFSET 500)")
        self.running.add(task_id)
        try:
            definition = task_definition(definition, self.bot)
            self.check_schedule_permissions(definition)
            kind, sid = definition["action"], definition["server"]
            if kind == "backup":
                result = await self.state["backups"].create("scheduled" if not manual else "manual")
                detail, status = "备份已保存：" + result["id"], "success"
            elif kind == "qq_message":
                if not self.state["onebot"].connected:
                    raise OperationError("QQ 机器人离线，本次已跳过")
                await self.state["onebot"].send_group(definition["group"], definition["message"])
                detail, status = "群公告已发送", "success"
            else:
                if not self.bot.online(sid):
                    raise OperationError("游戏服务器离线，本次已跳过")
                payload = {"kind": "broadcast", "text": clean_text(definition["message"], 600)} if kind == "game_message" else {
                    "kind": "command", "command": self.bot.servers[sid]["commands"][definition["command"]], "reply_group": ""}
                payload["schedule_run"] = run_id
                job = self.store.enqueue(sid, payload)
                with self.db:
                    self.db.execute("UPDATE schedule_runs SET job=?,server=? WHERE id=?", (job, sid, run_id))
                detail, status = "已提交，等待游戏端确认", "submitted"
            self.finish_run(run_id, status, detail)
        except asyncio.CancelledError:
            self.finish_run(run_id, "interrupted", "服务停止，执行未确认；未自动重放")
            raise
        except Exception as exc:
            self.finish_run(run_id, "failed", clean_text(str(exc), 500) if isinstance(exc, (ValueError, RuntimeError, ConnectionError, TimeoutError)) else "执行失败，请检查磁盘或连接状态")
        finally:
            self.running.discard(task_id)
        return dict(self.db.execute("SELECT * FROM schedule_runs WHERE id=?", (run_id,)).fetchone())

    def finish_run(self, run_id, status, detail):
        row = self.db.execute("SELECT task FROM schedule_runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            return
        with self.db:
            self.db.execute("UPDATE schedule_runs SET status=?,detail=?,finished=? WHERE id=?", (status, detail, time.time(), run_id))
            self.db.execute("UPDATE scheduled_tasks SET status=?,detail=? WHERE id=? AND last_run=(SELECT started FROM schedule_runs WHERE id=?)", (status, detail, row[0],run_id))
        self.store.audit("schedule", f"任务 {row[0]} {status}：{detail}")

    async def worker(self):
        while True:
            try:
                await self.tick_due()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # A transient storage error must not silently stop the scheduler.
                if self.bot.allow(("schedule-error",), count=1, period=30):
                    self.store.audit("error", "定时任务检查失败：" + type(exc).__name__)
            await asyncio.sleep(2)

    async def tick_due(self, now=None):
        now = time.time() if now is None else now
        if not self.state.get("maintenance") and self.scheduler_enabled():
            for row in self.tasks()["tasks"]:
                definition = row["definition"]
                waiting = self.db.execute("SELECT 1 FROM schedule_runs WHERE task=? AND status IN ('running','submitted')", (row["id"],)).fetchone()
                if definition and definition["enabled"] and row["next_run"] <= now and row["id"] not in self.running and not waiting:
                    if row["next_run"] < now-60:
                        with self.db:
                            self.db.execute("UPDATE scheduled_tasks SET next_run=?,status='skipped',detail='服务停机期间错过的任务已跳过' WHERE id=?", (next_run(definition, now), row["id"]))
                    else:
                        await self.run_task(row["id"])

    def application(self, app_id):
        row = self.db.execute("SELECT * FROM whitelist_applications WHERE id=?", (app_id,)).fetchone()
        if not row:
            raise OperationError("申请不存在", 404)
        return dict(row)

    def applications(self, status="", page=1):
        self.expire()
        if status not in ("", "pending", "approved", "submitted", "success", "rejected", "failed", "unconfirmed", "cancelled") or type(page) is not int or page < 1:
            raise OperationError("申请筛选或页码错误")
        where, args = (" WHERE status=?", (status,)) if status else ("", ())
        total = self.db.execute("SELECT count(*) FROM whitelist_applications" + where, args).fetchone()[0]
        rows = self.db.execute("SELECT * FROM whitelist_applications" + where + " ORDER BY created DESC LIMIT 25 OFFSET ?", (*args, (page-1)*25))
        return {"applications": [dict(r) for r in rows], "total": total, "page": page, **self.config()}

    def apply(self, sid, player, qq, group="", reason="", admin=False):
        config = self.config()["settings"]
        if not admin and not config["enabled"]:
            raise OperationError("白名单申请尚未开放，请联系管理员", 503)
        if not isinstance(sid, str) or sid not in self.bot.servers or not isinstance(player, str) or not PLAYER.fullmatch(player):
            raise OperationError("请选择服务器并填写 1–16 位合法玩家名")
        if not isinstance(qq, str) or not QQ.fullmatch(qq) or (group and group not in self.bot.servers[sid]["groups"]):
            raise OperationError("QQ 号或关联群错误")
        reason = text(reason, "申请理由", 300)
        if not admin and config["require_registered"]:
            account = self.db.execute("SELECT 1 FROM registration_accounts WHERE player_key=? AND qq=?", (player.lower(), qq)).fetchone()
            if not account:
                raise OperationError("请先用本人 QQ 邮箱注册相同的玩家名", 403)
        if not admin and config["require_bound"]:
            bound = self.store.binding(sid, qq)
            if not bound or bound["name"].lower() != player.lower():
                raise OperationError("请先绑定这个服务器的同名游戏账号", 403)
        now = time.time()
        with self.db:
            old = self.db.execute("SELECT * FROM whitelist_applications WHERE server=? AND (lower(player)=? OR qq=?) AND status IN ('pending','approved','submitted') ORDER BY created DESC LIMIT 1", (sid, player.lower(), qq)).fetchone()
            if old:
                raise OperationError("这个玩家或 QQ 已有申请，请查询申请状态", 409)
            known = next((p for p in self.bot.snapshots.get(sid,{}).get("player_records",[]) if p["name"].lower()==player.lower()), None)
            if self.bot.online(sid) and known and known.get("whitelisted"):
                raise OperationError("这个玩家已经在服务器白名单中", 409)
            if not admin and self.db.execute("SELECT 1 FROM whitelist_applications WHERE qq=? AND created>?", (qq, now-config["cooldown_minutes"]*60)).fetchone():
                raise OperationError("申请过于频繁，请等待冷却时间", 429)
            if self.db.execute("SELECT count(*) FROM whitelist_applications WHERE status='pending'").fetchone()[0] >= config["max_pending"]:
                raise OperationError("待审核申请已满，请稍后再试", 409)
            app_id = uuid.uuid4().hex
            self.db.execute("INSERT INTO whitelist_applications(id,server,player,qq,group_id,reason,status,created,updated,revision) VALUES(?,?,?,?,?,?,'pending',?,?,1)", (app_id,sid,player,qq,group,reason,now,now))
            self.db.execute("DELETE FROM whitelist_applications WHERE id IN (SELECT id FROM whitelist_applications WHERE status NOT IN ('pending','approved','submitted') ORDER BY created DESC LIMIT -1 OFFSET 2000)")
        self.store.audit("whitelist", f"{qq} 申请 {sid}/{player} 白名单，等待人工审核")
        return self.application(app_id)

    def review(self, app_id, action, revision, note="", identity=""):
        self.expire()
        row = self.application(app_id)
        if type(revision) is not int or row["revision"] != revision:
            raise OperationError("申请状态已变化，请重新载入", 409)
        if action not in ("approve", "reject", "retry") or (action in ("approve","reject") and row["status"] != "pending") or (action == "retry" and row["status"] not in ("approved","failed","unconfirmed","cancelled")):
            raise OperationError("当前状态不支持这个审核操作", 409)
        note = text(note, "审核备注", 300)
        if not isinstance(identity, str):
            raise OperationError("UUID 需为文字，可留空")
        try:
            identity = str(uuid.UUID(identity)) if identity else row["identity"]
        except (ValueError, AttributeError):
            raise OperationError("玩家 UUID 格式错误") from None
        status = "rejected" if action == "reject" else "approved"
        with self.db:
            self.db.execute("UPDATE whitelist_applications SET status=?,review=?,review_note=?,identity=?,updated=?,revision=revision+1 WHERE id=?", (status,note,note,identity,time.time(),app_id))
        self.store.audit("whitelist", f"管理员{action}白名单申请 {row['server']}/{row['player']}")
        if status == "approved":
            self.dispatch_whitelist(app_id)
        return self.application(app_id)

    def dispatch_whitelist(self, app_id):
        row = self.application(app_id)
        sid = row["server"]
        if sid not in self.bot.servers or not self.bot.online(sid):
            detail = "审核通过；服务器未连接，连接后请点击重试下发"
        elif "whitelist_application" not in self.bot.snapshots[sid].get("capabilities", []):
            detail = "审核通过；请更新游戏插件到 0.5.0 后重试下发"
        else:
            try:
                job = self.store.enqueue(sid, {"kind":"whitelist_application", "player":row["player"], "uuid":row["identity"], "application_id":app_id})
            except ValueError as exc:
                detail = str(exc)
            else:
                with self.db:
                    self.db.execute("UPDATE whitelist_applications SET status='submitted',job=?,review='已提交，等待游戏端确认',updated=?,revision=revision+1 WHERE id=?", (job,time.time(),app_id))
                return
        with self.db:
            self.db.execute("UPDATE whitelist_applications SET review=? WHERE id=?", (detail, app_id))

    def complete(self, sid, job_id, payload, result):
        detail = clean_text(result.get("detail", ""), 500)
        if payload.get("schedule_run"):
            row = self.db.execute("SELECT id FROM schedule_runs WHERE id=? AND job=? AND server=? AND status='submitted'", (payload["schedule_run"],job_id,sid)).fetchone()
            if row:
                self.finish_run(row[0], "success" if result["ok"] else "failed", detail)
            return True
        if payload.get("kind") == "whitelist_application":
            app_id = payload.get("application_id")
            with self.db:
                changed = self.db.execute("UPDATE whitelist_applications SET status=?,review=?,updated=?,revision=revision+1 WHERE id=? AND server=? AND job=? AND status='submitted'", ("success" if result["ok"] else "failed", detail,time.time(),app_id,sid,job_id)).rowcount
            if changed:
                self.store.audit("whitelist", f"{sid}/{payload['player']} {'加入白名单成功' if result['ok'] else '执行失败'}：{detail}")
            return True
        return False

    async def notify(self, row):
        group, sid = row["group_id"], row["server"]
        if not group or sid not in self.bot.servers or group not in self.bot.servers[sid]["groups"]:
            return
        try:
            await self.state["onebot"].send_group(group, f"白名单申请 · {row['player']}（QQ {row['qq']}）\n{status_label(row['status'])}\n{row['review']}" + ("\n备注："+row["review_note"] if row["review_note"] and row["review_note"]!=row["review"] else ""))
        except (ConnectionError, RuntimeError, TimeoutError):
            self.store.audit("whitelist", "审核通知发送失败；申请结果可通过 /白名单状态 查询，消息未重放")

    async def group_command(self, command, arg, server, group, qq):
        try:
            if command == "/白名单":
                player, _, reason = arg.partition(" ")
                if not player:
                    return "用法：/白名单 <玩家名> [申请理由]\n查询：/白名单状态"
                row = self.apply(server["id"], player, qq, group, reason)
                return f"白名单申请已提交：{row['player']}\n等待管理员审核，使用 /白名单状态 查询。"
            row = self.db.execute("SELECT * FROM whitelist_applications WHERE server=? AND qq=? ORDER BY created DESC LIMIT 1", (server["id"],qq)).fetchone()
            self.expire()
            if not row:
                return "你还没有申请。使用 /白名单 <玩家名> [申请理由] 提交。"
            row = self.application(row["id"])
            return f"{row['player']} · {status_label(row['status'])}\n{row['review'] or '等待管理员审核'}"
        except OperationError as exc:
            return "[×] " + str(exc)


def status_label(status):
    return {"pending":"待审核","approved":"已批准，待下发","submitted":"等待游戏端确认","success":"已加入白名单","rejected":"已拒绝","failed":"游戏端执行失败","unconfirmed":"执行未确认","cancelled":"下发已撤销"}.get(status,status)
