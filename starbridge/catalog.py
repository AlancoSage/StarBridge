"""Persistent player profiles, independent of transient game heartbeats."""
import ipaddress
import json
import math
import re
import sqlite3
import time
import uuid


def identity(value):
    return str(uuid.UUID(value))


def address(value):
    if not isinstance(value, str):
        raise ValueError("IP 地址格式错误")
    return str(ipaddress.ip_address(value.strip())) if value.strip() else ""


def profile_fields(data):
    name = data.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,16}", name):
        raise ValueError("玩家名需为 1–16 位字母、数字或下划线")
    return {"name": name, "uuid": identity(data.get("uuid")), "ip": address(data.get("ip", "")),
            **annotations(data)}


def annotations(data):
    result = {}
    for key, maximum in (("region", 120), ("notes", 1000)):
        value = data.get(key, "")
        if not isinstance(value, str) or len(value) > maximum:
            raise ValueError("归属地或备注超过长度限制")
        result[key] = value.strip()
    return result


class Catalog:
    def __init__(self, store):
        self.store, self.db = store, store.db
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS player_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT, uuid TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL, ip TEXT DEFAULT '', region TEXT DEFAULT '', notes TEXT DEFAULT '',
                source TEXT, created REAL, last_seen REAL DEFAULT 0, revision INTEGER DEFAULT 1,
                deleted INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS player_visits (
                profile INTEGER, server TEXT, server_name TEXT, first_seen REAL,
                last_seen REAL, ip TEXT DEFAULT '', snapshot TEXT DEFAULT '{}',
                PRIMARY KEY(profile,server)
            );
            CREATE INDEX IF NOT EXISTS player_profile_name ON player_profiles(name);
            CREATE INDEX IF NOT EXISTS player_visit_server ON player_visits(server,profile);
            CREATE INDEX IF NOT EXISTS binding_uuid ON bindings(uuid);
        """)
        self.sync_bindings()

    def sync_bindings(self):
        with self.db:
            for bound in self.store.bindings():
                try:
                    uid = identity(bound["uuid"])
                except (ValueError, TypeError, AttributeError):
                    continue
                self.db.execute("INSERT OR IGNORE INTO player_profiles(uuid,name,source,created) VALUES(?,?,?,?)",
                                (uid, bound["name"], "binding", bound["created"]))
                row = self.db.execute("SELECT id,deleted FROM player_profiles WHERE uuid=?", (uid,)).fetchone()
                if not row["deleted"]:
                    self.db.execute("INSERT OR IGNORE INTO player_visits(profile,server,server_name,first_seen,last_seen) VALUES(?,?,?,?,?)",
                                    (row["id"], bound["server"], bound["server"], bound["created"], 0))

    def observe(self, server, records, joined=()):
        now = time.time()
        with self.db:
            for event in joined:
                uid = event["uuid"]
                self.db.execute("UPDATE player_profiles SET deleted=0,revision=revision+1 WHERE uuid=? AND deleted=1", (uid,))
                self.db.execute("INSERT OR IGNORE INTO player_profiles(uuid,name,source,created,last_seen,ip) VALUES(?,?,?,?,?,?)",
                                (uid, event["player"], "game", now, now, event.get("ip", "")))
                row = self.db.execute("SELECT id FROM player_profiles WHERE uuid=?", (uid,)).fetchone()
                self.db.execute("INSERT OR IGNORE INTO player_visits(profile,server,server_name,first_seen,last_seen,ip) VALUES(?,?,?,?,?,?)",
                                (row["id"], server["id"], server["name"], now, now, event.get("ip", "")))
            for record in records:
                seen = now if record["online"] else record.get("last_played", 0) / 1000
                ip = record.get("ip", "")
                self.db.execute("INSERT OR IGNORE INTO player_profiles(uuid,name,source,created,last_seen,ip) VALUES(?,?,?,?,?,?)",
                                (record["uuid"], record["name"], "game", now, seen, ip))
                row = self.db.execute("SELECT * FROM player_profiles WHERE uuid=?", (record["uuid"],)).fetchone()
                if row["deleted"]:
                    continue
                ip = ip if seen >= row["last_seen"] else ""
                # A region annotation belongs to the address it describes.
                self.db.execute("UPDATE player_profiles SET name=?,last_seen=MAX(last_seen,?),revision=revision+CASE WHEN ?!='' AND ip!=? THEN 1 ELSE 0 END,region=CASE WHEN ?!='' AND ip!=? THEN '' ELSE region END,ip=CASE WHEN ?!='' THEN ? ELSE ip END,source='game' WHERE id=?",
                                (record["name"], seen, ip, ip, ip, ip, ip, ip, row["id"]))
                self.db.execute("INSERT INTO player_visits(profile,server,server_name,first_seen,last_seen,ip,snapshot) VALUES(?,?,?,?,?,?,?) ON CONFLICT(profile,server) DO UPDATE SET server_name=excluded.server_name,last_seen=MAX(last_seen,excluded.last_seen),ip=CASE WHEN excluded.ip!='' THEN excluded.ip ELSE ip END,snapshot=excluded.snapshot",
                                (row["id"], server["id"], server["name"], now, seen, record.get("ip", ""), json.dumps(record, ensure_ascii=False)))

    def rows(self, state, filters=None):
        self.sync_bindings()
        filters = filters or {}
        where, params = ["p.deleted=0"], []
        for key in ("name", "uuid", "ip", "region"):
            value = filters.get(key, "").strip()
            if value:
                value = "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                if key == "name":
                    where.append("(p.name LIKE ? ESCAPE '\\' OR EXISTS(SELECT 1 FROM bindings b WHERE b.uuid=p.uuid AND b.qq LIKE ? ESCAPE '\\'))")
                    params.extend((value, value))
                else:
                    where.append(f"p.{key} LIKE ? ESCAPE '\\'")
                    params.append(value)
        if filters.get("binding") in ("bound", "unbound"):
            where.append(("NOT " if filters["binding"] == "unbound" else "") + "EXISTS(SELECT 1 FROM bindings b WHERE b.uuid=p.uuid)")
        if filters.get("server"):
            where.append("EXISTS(SELECT 1 FROM player_visits v WHERE v.profile=p.id AND v.server=?)")
            params.append(filters["server"])
        profiles = [dict(row) for row in self.db.execute("SELECT p.* FROM player_profiles p WHERE " + " AND ".join(where) + " ORDER BY p.id DESC", params)]
        return self.hydrate(profiles, state)

    def hydrate(self, profiles, state):
        by_id = {p["id"]: p for p in profiles}
        by_uuid = {p["uuid"]: p for p in profiles}
        bot = state["bot"]
        current_records = {sid: {p["uuid"]: p for p in snap.get("player_records", [])} for sid, snap in bot.snapshots.items()}
        for p in profiles:
            p["servers"], p["bindings"] = [], []
        for row in self.db.execute("SELECT * FROM player_visits"):
            p = by_id.get(row["profile"])
            if p is None:
                continue
            sid = row["server"]
            configured = bot.servers.get(sid)
            snap = bot.snapshots.get(sid, {})
            connected = configured is not None and bot.online(sid)
            capable = "player_management" in snap.get("capabilities", [])
            current = current_records.get(sid, {}).get(p["uuid"])
            record = current or json.loads(row["snapshot"])
            mode = "unknown"
            if connected:
                if current is not None:
                    mode = "online" if current["online"] else "offline"
                elif capable and p["name"] not in snap.get("players", []):
                    mode = "offline"
                elif not capable and p["name"] in snap.get("players", []):
                    mode = "online"
            visit = {"server": sid, "server_name": configured["name"] if configured else row["server_name"],
                     "historical": configured is None, "status": mode, "manageable": connected and capable and current is not None,
                     "first_seen": row["first_seen"], "last_seen": row["last_seen"], "ip": row["ip"],
                     "uuid": p["uuid"], "name": record.get("name", p["name"]),
                     **{k: record[k] for k in ("op", "banned", "whitelisted", "world", "game_mode", "health", "ping", "last_played") if k in record}}
            p["servers"].append(visit)
        for row in self.db.execute("SELECT * FROM bindings"):
            p = by_uuid.get(row["uuid"])
            if p is not None:
                binding = dict(row)
                binding["server_name"] = bot.servers.get(row["server"], {}).get("name", row["server"])
                p["bindings"].append(binding)
        for p in profiles:
            modes = {s["status"] for s in p["servers"]}
            p["status"] = "online" if "online" in modes else "offline" if "offline" in modes else "unknown"
            p["bound"] = bool(p["bindings"])
        return profiles

    def get(self, pid, state):
        row = self.db.execute("SELECT * FROM player_profiles WHERE id=? AND deleted=0", (pid,)).fetchone()
        if row is None:
            raise LookupError("玩家档案不存在或已删除")
        return self.hydrate([dict(row)], state)[0]

    def create(self, fields):
        now = time.time()
        with self.db:
            old = self.db.execute("SELECT id,deleted FROM player_profiles WHERE uuid=?", (fields["uuid"],)).fetchone()
            if old and not old["deleted"]:
                raise ValueError("这个 UUID 已有玩家档案，请直接查看详情")
            if old:
                self.db.execute("UPDATE player_profiles SET name=?,ip=?,region=?,notes=?,deleted=0,source='manual',revision=revision+1 WHERE id=?",
                                (fields["name"], fields["ip"], fields["region"], fields["notes"], old["id"]))
                return old["id"]
            cursor = self.db.execute("INSERT INTO player_profiles(uuid,name,ip,region,notes,source,created) VALUES(?,?,?,?,?,'manual',?)",
                                     (fields["uuid"], fields["name"], fields["ip"], fields["region"], fields["notes"], now))
            return cursor.lastrowid

    def update(self, pid, fields, revision):
        with self.db:
            if self.db.execute("UPDATE player_profiles SET region=?,notes=?,revision=revision+1 WHERE id=? AND deleted=0 AND revision=?",
                               (fields["region"], fields["notes"], pid, revision)).rowcount != 1:
                raise ValueError("档案已被其他页面修改，请重新打开详情")

    def bind(self, pid, server, qq):
        row = self.db.execute("SELECT * FROM player_profiles WHERE id=? AND deleted=0", (pid,)).fetchone()
        if row is None:
            raise LookupError("玩家档案不存在")
        with self.db:
            try:
                self.db.execute("INSERT INTO bindings(server,qq,uuid,name,created) VALUES(?,?,?,?,?)", (server, qq, row["uuid"], row["name"], time.time()))
            except sqlite3.IntegrityError:
                raise ValueError("该服务器中 QQ 或玩家已有绑定，请先处理现有绑定") from None
            self.db.execute("DELETE FROM codes WHERE server=? AND uuid=?", (server, row["uuid"]))
            self.db.execute("INSERT OR IGNORE INTO player_visits(profile,server,server_name,first_seen,last_seen) VALUES(?,?,?,?,0)", (pid, server, server, time.time()))

    def bulk(self, ids, action, server=""):
        marks = ",".join("?" for _ in ids)
        with self.db:
            rows = list(self.db.execute(f"SELECT id,uuid FROM player_profiles WHERE deleted=0 AND id IN ({marks})", ids))
            if len(rows) != len(ids):
                raise ValueError("部分玩家已被删除，请刷新后重试")
            identities = [r["uuid"] for r in rows]
            changed = 0
            for uid in identities:
                sql = "DELETE FROM bindings WHERE uuid=?" + (" AND server=?" if server else "")
                changed += self.db.execute(sql, (uid, server) if server else (uid,)).rowcount
                self.db.execute("DELETE FROM codes WHERE uuid=?" + (" AND server=?" if server else ""), (uid, server) if server else (uid,))
                if action == "delete":
                    self.db.execute("DELETE FROM jobs WHERE json_extract(payload,'$.kind')='player_action' AND json_extract(payload,'$.uuid')=?", (uid,))
                    self.db.execute("UPDATE player_actions SET status='cancelled',detail='玩家档案已删除，待执行操作已撤销' WHERE uuid=? AND status='pending'", (uid,))
            if action == "delete":
                self.db.execute(f"UPDATE player_profiles SET deleted=1,revision=revision+1 WHERE id IN ({marks})", ids)
                self.db.execute(f"DELETE FROM player_visits WHERE profile IN ({marks})", ids)
        return {"profiles": len(rows), "bindings_removed": changed}

    def server_options(self, state):
        options = {sid: {"id": sid, "name": s["name"], "historical": False} for sid, s in state["bot"].servers.items()}
        for row in self.db.execute("SELECT server,MAX(server_name) AS name FROM player_visits GROUP BY server"):
            options.setdefault(row["server"], {"id": row["server"], "name": row["name"], "historical": True})
        return list(options.values())

    def list(self, state, filters, page, size):
        rows = self.rows(state, filters)
        status, scope = filters.get("status", ""), filters.get("server", "")
        if status:
            def matches(p):
                visits = [v for v in p["servers"] if not scope or v["server"] == scope]
                if status in ("banned", "whitelisted"):
                    return any(v.get(status) is True for v in visits)
                modes = {v["status"] for v in visits}
                mode = "online" if "online" in modes else "offline" if "offline" in modes else "unknown"
                return mode == status
            rows = [p for p in rows if matches(p)]
        total = len(rows)
        pages = max(1, math.ceil(total / size))
        page = min(page, pages)
        return {"items": rows[(page - 1) * size:page * size], "total": total, "page": page,
                "page_size": size, "pages": pages, "servers": self.server_options(state)}
