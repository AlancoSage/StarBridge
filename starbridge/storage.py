import json
from pathlib import Path
import secrets
import sqlite3
import time
import uuid


class Store:
    def __init__(self, path):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS bindings (
                server TEXT, qq TEXT, uuid TEXT, name TEXT, created REAL,
                PRIMARY KEY(server, qq), UNIQUE(server, uuid)
            );
            CREATE TABLE IF NOT EXISTS codes (
                code TEXT PRIMARY KEY, server TEXT, uuid TEXT, name TEXT, expires REAL,
                UNIQUE(server, uuid)
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, server TEXT, payload TEXT, created REAL,
                expires REAL, lease REAL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS seen (id TEXT PRIMARY KEY, expires REAL);
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT, time REAL, kind TEXT, detail TEXT
            );
            CREATE TABLE IF NOT EXISTS player_actions (
                id TEXT PRIMARY KEY, server TEXT, uuid TEXT, player TEXT, action TEXT,
                reason TEXT, status TEXT, detail TEXT, created REAL, expires REAL
            );
            CREATE TABLE IF NOT EXISTS operations_settings (
                key TEXT PRIMARY KEY, value TEXT NOT NULL, revision INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                id TEXT PRIMARY KEY, definition TEXT NOT NULL, revision INTEGER NOT NULL,
                next_run REAL NOT NULL, last_run REAL DEFAULT 0, status TEXT DEFAULT '', detail TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS schedule_runs (
                id TEXT PRIMARY KEY, task TEXT, name TEXT, started REAL, finished REAL,
                status TEXT, detail TEXT, job TEXT DEFAULT '', server TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS whitelist_applications (
                id TEXT PRIMARY KEY, server TEXT, player TEXT, qq TEXT, group_id TEXT,
                reason TEXT, status TEXT, created REAL, updated REAL, revision INTEGER,
                review TEXT DEFAULT '', job TEXT DEFAULT '', identity TEXT DEFAULT '', review_note TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS admin_users (
                id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
                permissions TEXT NOT NULL, enabled INTEGER NOT NULL, revision INTEGER NOT NULL, created REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS admin_owner (
                id TEXT PRIMARY KEY NOT NULL CHECK(id='owner'), username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL, revision INTEGER NOT NULL, created REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS admin_sessions (
                token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runtime_settings (
                key TEXT PRIMARY KEY, value TEXT NOT NULL, revision INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS health_alerts (
                id TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL,
                acknowledged INTEGER NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                notified INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS server_samples (
                server TEXT NOT NULL, bucket INTEGER NOT NULL, connected INTEGER NOT NULL,
                online_count INTEGER, max_players INTEGER, PRIMARY KEY(server,bucket)
            );
            CREATE TABLE IF NOT EXISTS server_daily_players (
                server TEXT NOT NULL, day TEXT NOT NULL, identity TEXT NOT NULL, PRIMARY KEY(server,day,identity)
            );
            CREATE TABLE IF NOT EXISTS server_activity (
                id TEXT PRIMARY KEY, server TEXT NOT NULL, player TEXT NOT NULL, kind TEXT NOT NULL, time REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS plugin_versions (
                id TEXT PRIMARY KEY, plugin TEXT NOT NULL, version TEXT NOT NULL, definition TEXT NOT NULL,
                settings TEXT NOT NULL, created REAL NOT NULL, note TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tickets (
                id TEXT PRIMARY KEY, account_id TEXT NOT NULL, player TEXT NOT NULL,
                title TEXT NOT NULL, kind TEXT NOT NULL, server TEXT NOT NULL,
                penalty_id TEXT NOT NULL, status TEXT NOT NULL, revision INTEGER NOT NULL,
                created REAL NOT NULL, updated REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ticket_messages (
                id TEXT PRIMARY KEY, ticket TEXT NOT NULL, author TEXT NOT NULL,
                role TEXT NOT NULL, body TEXT NOT NULL, internal INTEGER NOT NULL,
                created REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ticket_account ON tickets(account_id,updated);
            CREATE INDEX IF NOT EXISTS ticket_message_ticket ON ticket_messages(ticket,created);
            CREATE TABLE IF NOT EXISTS sanctions (
                id TEXT PRIMARY KEY, uuid TEXT NOT NULL, player TEXT NOT NULL,
                reason TEXT NOT NULL, action TEXT NOT NULL, servers TEXT NOT NULL,
                status TEXT NOT NULL, expires REAL NOT NULL, created REAL NOT NULL,
                updated REAL NOT NULL, revision INTEGER NOT NULL, author TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sanction_targets (
                sanction TEXT NOT NULL, server TEXT NOT NULL, phase TEXT NOT NULL,
                status TEXT NOT NULL, job TEXT NOT NULL, detail TEXT NOT NULL,
                attempts INTEGER NOT NULL, next_try REAL NOT NULL,
                PRIMARY KEY(sanction,server)
            );
        """)

    def close(self):
        self.db.close()

    def audit(self, kind, detail):
        with self.db:
            self.db.execute("INSERT INTO audit(time,kind,detail) VALUES(?,?,?)", (time.time(), kind, detail[:1000]))
            self.db.execute("DELETE FROM audit WHERE id < (SELECT COALESCE(MAX(id),0)-1000 FROM audit)")

    def logs(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 60")]

    def seen(self, key):
        now = time.time()
        with self.db:
            self.db.execute("DELETE FROM seen WHERE expires < ?", (now,))
            cursor = self.db.execute("INSERT OR IGNORE INTO seen VALUES(?,?)", (key, now + 3600))
            return cursor.rowcount == 0

    def issue_code(self, server, player_uuid, name):
        code = secrets.token_hex(4).upper()
        with self.db:
            self.db.execute("DELETE FROM codes WHERE expires < ? OR (server=? AND uuid=?)", (time.time(), server, player_uuid))
            self.db.execute("INSERT INTO codes VALUES(?,?,?,?,?)", (code, server, player_uuid, name, time.time() + 300))
        return code

    def bind(self, server, qq, code):
        # No await between validation and commit: one transaction consumes the code once.
        with self.db:
            row = self.db.execute("SELECT * FROM codes WHERE code=? AND server=? AND expires>?", (code.upper(), server, time.time())).fetchone()
            if row is None:
                raise ValueError("验证码无效或已过期，请在游戏中输入 /qbind 获取。")
            if self.db.execute("SELECT 1 FROM bindings WHERE server=? AND (qq=? OR uuid=?)", (server, qq, row["uuid"])).fetchone():
                raise ValueError("QQ 或游戏账号已有绑定，请先解绑。")
            self.db.execute("INSERT INTO bindings VALUES(?,?,?,?,?)", (server, qq, row["uuid"], row["name"], time.time()))
            self.db.execute("DELETE FROM codes WHERE code=?", (code.upper(),))
            return dict(row)

    def binding(self, server, qq):
        row = self.db.execute("SELECT * FROM bindings WHERE server=? AND qq=?", (server, qq)).fetchone()
        return dict(row) if row else None

    def unbind(self, server, qq):
        with self.db:
            return self.db.execute("DELETE FROM bindings WHERE server=? AND qq=?", (server, qq)).rowcount > 0

    def bindings(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM bindings ORDER BY created DESC")]

    def enqueue(self, server, payload):
        jid, now = uuid.uuid4().hex, time.time()
        with self.db:
            self.db.execute("DELETE FROM jobs WHERE expires < ?", (now,))
            if self.db.execute("SELECT count(*) FROM jobs WHERE server=?", (server,)).fetchone()[0] >= 200:
                raise ValueError("服务器待处理队列已满，请稍后重试。")
            self.db.execute("INSERT INTO jobs(id,server,payload,created,expires) VALUES(?,?,?,?,?)", (jid, server, json.dumps(payload, ensure_ascii=False), now, now + 60))
        return jid

    def player_action(self, jid):
        row = self.db.execute("SELECT * FROM player_actions WHERE id=?", (jid,)).fetchone()
        return dict(row) if row else None

    def create_player_action(self, jid, server, identity, player, action, reason):
        now = time.time()
        payload = {"kind": "player_action", "uuid": identity, "player": player, "action": action, "reason": reason}
        with self.db:
            self.db.execute("DELETE FROM jobs WHERE expires < ?", (now,))
            if self.db.execute("SELECT count(*) FROM jobs WHERE server=?", (server,)).fetchone()[0] >= 200:
                raise ValueError("服务器待处理队列已满，请稍后重试。")
            self.db.execute("INSERT INTO jobs(id,server,payload,created,expires) VALUES(?,?,?,?,?)",
                            (jid, server, json.dumps(payload, ensure_ascii=False), now, now + 60))
            self.db.execute("INSERT INTO player_actions VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (jid, server, identity, player, action, reason, "pending", "等待游戏插件执行", now, now + 60))
            self.db.execute("DELETE FROM player_actions WHERE id IN (SELECT id FROM player_actions WHERE status!='pending' ORDER BY created DESC LIMIT -1 OFFSET 500)")
        return self.player_action(jid)

    def complete_player_action(self, server, jid, ok, detail):
        with self.db:
            return self.db.execute("UPDATE player_actions SET status=?,detail=? WHERE server=? AND id=? AND status='pending'",
                                   ("success" if ok else "failed", detail[:1500], server, jid)).rowcount > 0

    def cancel_player_actions(self, server):
        with self.db:
            self.db.execute("UPDATE player_actions SET status='cancelled',detail='服务器连接或权限配置已修改，待执行操作已撤销' WHERE server=? AND status='pending'", (server,))

    def player_actions(self):
        with self.db:
            self.db.execute("UPDATE player_actions SET status='expired',detail='未在 60 秒内收到执行结果，请核对游戏端状态后再操作' WHERE status='pending' AND expires<?", (time.time(),))
        return [dict(r) for r in self.db.execute("SELECT * FROM player_actions ORDER BY created DESC LIMIT 30")]

    def poll(self, server):
        now = time.time()
        with self.db:
            self.db.execute("DELETE FROM jobs WHERE expires < ?", (now,))
            rows = self.db.execute("SELECT * FROM jobs WHERE server=? AND lease<? ORDER BY created LIMIT 30", (server, now)).fetchall()
            for r in rows:
                self.db.execute("UPDATE jobs SET lease=? WHERE id=?", (now + 15, r["id"]))
        return [{"id": r["id"], "expires": r["expires"], **json.loads(r["payload"])} for r in rows]

    def ack(self, server, ids):
        with self.db:
            self.db.executemany("DELETE FROM jobs WHERE server=? AND id=?", [(server, jid) for jid in ids])

    def job(self, server, jid):
        row = self.db.execute("SELECT payload FROM jobs WHERE server=? AND id=?", (server, jid)).fetchone()
        return json.loads(row[0]) if row else None
