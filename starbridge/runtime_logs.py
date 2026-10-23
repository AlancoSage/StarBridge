"""Bounded, owner-only runtime console; no file tailing or log-level changes."""
from collections import deque
import json
import logging
import math
import re
import secrets
import threading
import time
from urllib.parse import quote, quote_plus

from aiohttp import web


CAPACITY = 1000
MAX_MESSAGE = 8192
LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
REDACTED = "[已隐藏]"
_PRIVATE_KEY = re.compile(r"password|passwd|passphrase|token|secret|api[_-]?key|authorization|credential|验证码|密码|令牌|密钥|授权码", re.I)
_KEY_VALUE = re.compile(
    r'''(?<![\w.-])(?P<prefix>["']?(?P<name>[\w.-]{0,40}(?:''' + _PRIVATE_KEY.pattern + r''')[\w.-]{0,40})["']?\s*[:=：]\s*)'''
    r'''(?P<value>\[已隐藏\]|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[\[{][^\r\n]*|[^\s,;}&\]]+)''', re.I)
_AUTHORIZATION = re.compile(r'''(\bauthorization["']?\s*[:=]\s*["']?)[^\r\n,}"']+''', re.I)
_BEARER = re.compile(r"\b(?:Bearer|Basic|QQBot)\s+[A-Za-z0-9_.~+/=\-]+", re.I)
_URL_CREDENTIALS = re.compile(r"(?<![A-Za-z0-9+.-])([A-Za-z][A-Za-z0-9+.-]{0,31}://)[^/\s?#]+@")
_SECRET_COMMAND = re.compile(
    r"(?P<command>/(?:确认重置|确认登录|拒绝登录|注册|绑定|设置密码|修改密码|财务绑定|财务确认|login|register|changepassword))(?=\s)\s+[^\r\n]+", re.I)
_CQ = re.compile(r"\[CQ:[^\]\r\n]*(?:\]|$)", re.I)
_ANSI = re.compile(r"\x1b(?:\][^\x07\x1b]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~]|[@-_])")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_NUMBER = re.compile(r"(?:0|[1-9][0-9]{0,15})\Z")


def _secret_values(state):
    """Read only explicit in-memory config/credential containers, never a DB/file."""
    values = set()

    def collect(value, private=False, depth=0):
        if depth > 12:
            return
        if isinstance(value, str):
            if private and value:
                values.add(value)
        elif isinstance(value, dict):
            for key, child in list(value.items()):
                collect(child, private or bool(_PRIVATE_KEY.search(str(key))), depth + 1)
        elif isinstance(value, (list, tuple)):
            for child in list(value):
                collect(child, private, depth + 1)

    collect(state.get("config", {}))
    for key in ("registration", "authentication", "native_passwords", "billing"):
        service = state.get(key)
        collect(getattr(service, "settings", {}))
    native = state.get("native_passwords")
    collect(getattr(native, "requests", {}))
    # Native binding proofs use the secret code as their dictionary key.
    values.update(str(value) for value in list(getattr(native, "code_proofs", {})) if value)
    qq = state.get("onebot")
    collect(getattr(getattr(qq, "legacy", None), "cfg", {}))
    official = getattr(qq, "official", None)
    collect(getattr(official, "cfg", {}))
    for key in ("access_token", "session_id"):
        value = getattr(official, key, "")
        if isinstance(value, str) and value:
            values.add(value)
    # Settings introduced after a message was captured are also applied when
    # serializing the ring, so new credentials cannot expose older matching text.
    encoded = set(values)
    for value in values:
        encoded.update((quote(value, safe=""), quote_plus(value, safe=""),
                        json.dumps(value, ensure_ascii=True)[1:-1],
                        json.dumps(value, ensure_ascii=False)[1:-1]))
    return sorted(encoded, key=len, reverse=True)


def _redact(value, private_values):
    text = str(value)
    # Remove terminal escape/control sequences; HTML is retained as inert text
    # and rendered with textContent by the console, never interpreted as markup.
    text = _CONTROL.sub("", _ANSI.sub("", text)).replace("\r\n", "\n").replace("\r", "\n")
    if private_values:
        known = re.compile("|".join(re.escape(value) for value in private_values))
        text = REDACTED.join(known.sub(REDACTED, part) for part in text.split(REDACTED))
    text = _AUTHORIZATION.sub(lambda match: match[1] + REDACTED, text)
    text = _BEARER.sub(REDACTED, text)
    text = _URL_CREDENTIALS.sub(lambda match: match[1] + REDACTED + "@", text)
    text = _KEY_VALUE.sub(lambda match: match["prefix"] + REDACTED
                          if _PRIVATE_KEY.search(match["name"]) else match[0], text)
    text = _SECRET_COMMAND.sub(lambda match: match["command"] + " " + REDACTED, text)
    return _CQ.sub("[CQ 消息已省略]", text)


def _bounded(value, maximum):
    return value if len(value) <= maximum else value[:maximum - 7] + "…[已截断]"


class _RuntimeHandler(logging.Handler):
    def __init__(self, hub):
        super().__init__(logging.NOTSET)
        self.hub = hub
        self.local = threading.local()
        self.formatter = logging.Formatter("%(message)s")

    def emit(self, record):
        if (record.name != "root" and record.name != "starbridge" and not record.name.startswith("starbridge.")):
            return
        if getattr(self.local, "busy", False):
            return
        self.local.busy = True
        try:
            # Formatter includes a traceback as part of the same multiline row.
            # Never call handleError: it can dump the original unsanitized record.
            self.hub.record(record.levelno, record.name, self.formatter.format(record), record.created)
        except Exception:
            pass
        finally:
            self.local.busy = False


class RuntimeLogs:
    def __init__(self, state):
        self.state = state
        self.instance_id = secrets.token_hex(16)
        self.entries = deque(maxlen=CAPACITY)
        self.cursor = 0
        self.lock = threading.RLock()
        self.handler = None
        self._observer = self.record_audit
        self._started = False
        self._seeded = False

    def start(self):
        if self._started:
            return
        self._started = True
        store = self.state["store"]
        if not self._seeded:
            rows = list(store.db.execute("SELECT time,kind,detail FROM audit ORDER BY id DESC LIMIT 200"))
            for row in reversed(rows):
                self.record_audit(row["kind"], row["detail"], row["time"])
            self._seeded = True
        store.audit_observer = self._observer
        self.handler = _RuntimeHandler(self)
        logging.getLogger().addHandler(self.handler)

    def close(self):
        if self.handler is not None:
            logging.getLogger().removeHandler(self.handler)
            self.handler.close()
            self.handler = None
        store = self.state["store"]
        if store.audit_observer is self._observer:
            store.audit_observer = None
        self._started = False

    def record(self, level, source, message, created=None):
        private_values = _secret_values(self.state)
        safe_message = _bounded(_redact(message, private_values), MAX_MESSAGE)
        safe_source = _bounded(_redact(source, private_values), 120)
        level_name = ("CRITICAL" if level >= logging.CRITICAL else "ERROR" if level >= logging.ERROR
                      else "WARNING" if level >= logging.WARNING else "INFO" if level >= logging.INFO else "DEBUG")
        created = time.time() if created is None else float(created)
        if not math.isfinite(created):
            created = time.time()
        with self.lock:
            self.cursor += 1
            self.entries.append({"id": self.cursor, "time": created, "level": level_name,
                                 "source": safe_source, "message": safe_message})

    def record_audit(self, kind, detail, created=None):
        kind = str(kind)
        level = (logging.ERROR if kind.lower() in ("error", "failure", "critical")
                 else logging.WARNING if kind.lower() in ("alert", "warning", "warn") else logging.INFO)
        self.record(level, "audit." + kind, detail, created)

    def snapshot(self, after=None, instance=None, limit=500):
        private_values = _secret_values(self.state)
        with self.lock:
            rows = list(self.entries)
            latest = self.cursor
        oldest = rows[0]["id"] if rows else 0
        reset = instance is not None and instance != self.instance_id
        if after is not None and after > latest:
            reset = True
        truncated = bool(after is not None and not reset and rows and after < oldest - 1)
        if after is None or reset:
            # Initial loads and process restarts show the latest tail. A caller
            # clearing its own view can also take this boundary without replay.
            selected = rows[-limit:]
            cursor = latest
        else:
            selected = [row for row in rows if row["id"] > after][:limit]
            # Advance only to the last delivered row, so pagination is lossless.
            cursor = selected[-1]["id"] if selected else min(after, latest)
        result = {"instance_id": self.instance_id, "cursor": cursor, "oldest_cursor": oldest,
                  "entries": [{**row, "source": _bounded(_redact(row["source"], private_values), 120),
                                "message": _bounded(_redact(row["message"], private_values), MAX_MESSAGE)} for row in selected],
                  "capacity": CAPACITY, "truncated": truncated, "reset": reset,
                  "levels": list(LEVELS),
                  "capture_level": logging.getLevelName(logging.getLogger().getEffectiveLevel())}
        return result


def setup_routes(app, state_key, authorized, body):
    state = app[state_key]
    hub = state["runtime_logs"] = RuntimeLogs(state)

    async def lifecycle(application):
        try:
            hub.start()
            yield
        finally:
            hub.close()

    # Start before the workers and detach after their shutdown messages. No
    # process-wide logging threshold is changed, and nothing reads a log file.
    app.cleanup_ctx.insert(0, lifecycle)

    async def endpoint(request):
        headers = {"Cache-Control": "no-store"}
        try:
            authorized(request, state["config"]["app"]["admin_token"])
            if set(request.query) - {"after", "instance", "limit"} or any(len(request.query.getall(key)) != 1 for key in request.query):
                raise web.HTTPBadRequest(text="日志查询参数无效")
            after, limit = request.query.get("after"), request.query.get("limit", "500")
            instance = request.query.get("instance")
            if ((after is not None and not _NUMBER.fullmatch(after)) or not _NUMBER.fullmatch(limit) or not 1 <= int(limit) <= 500
                    or (instance is not None and not re.fullmatch(r"[0-9a-f]{32}", instance))):
                raise web.HTTPBadRequest(text="日志游标或查询数量无效")
            return web.json_response(hub.snapshot(int(after) if after is not None else None, instance, int(limit)), headers=headers)
        except web.HTTPException as exc:
            return web.json_response({"error": exc.text}, status=exc.status, headers=headers)

    app.add_routes([web.get("/api/logs", endpoint)])
