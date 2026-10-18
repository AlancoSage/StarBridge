"""Private billing credentials and durable, single-use checkout confirmations.

Billing state uses its own SQLite database so the application's existing database
schema, MySQL adapter and portable backups retain their established contracts.
Back up the complete data directory: the database cannot decrypt bindings without
the accompanying billing.key file.
"""
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time

from cryptography.fernet import Fernet, InvalidToken


class BillingStoreError(ValueError):
    """Safe user-facing storage error; never includes credential values."""


class BillingStore:
    def __init__(self, store, base: Path):
        # Keep the application store argument for service construction symmetry;
        # billing never writes credentials into its shared database or audit log.
        self.base = Path(base) / "data"
        self.base.mkdir(parents=True, exist_ok=True)
        self.key_path = self.base / "billing.key"
        self.db = sqlite3.connect(self.base / "billing.sqlite3", timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS billing_bindings (
                qq TEXT NOT NULL, provider TEXT NOT NULL, account TEXT NOT NULL,
                credentials TEXT NOT NULL, generation TEXT NOT NULL,
                created REAL NOT NULL, PRIMARY KEY(qq,provider)
            );
            CREATE TABLE IF NOT EXISTS billing_orders (
                id TEXT PRIMARY KEY, qq TEXT NOT NULL, provider TEXT NOT NULL,
                account TEXT NOT NULL, generation TEXT NOT NULL,
                invoice_id TEXT NOT NULL, order_id TEXT NOT NULL,
                summary TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS billing_orders_owner
                ON billing_orders(qq,provider,generation,created);
            CREATE TABLE IF NOT EXISTS billing_checkouts (
                token TEXT PRIMARY KEY, qq TEXT NOT NULL, provider TEXT NOT NULL,
                account TEXT NOT NULL, generation TEXT NOT NULL,
                payload TEXT NOT NULL, summary TEXT NOT NULL, status TEXT NOT NULL,
                expires REAL NOT NULL, created REAL NOT NULL,
                local_order_id TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS billing_checkouts_owner
                ON billing_checkouts(qq,provider,generation);
        """)

    def close(self):
        self.db.close()

    @staticmethod
    def _identity(value):
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            raise BillingStoreError("财务账号标识无效")
        result = str(value)
        if not result or len(result) > 512 or any(ord(c) < 32 for c in result):
            raise BillingStoreError("财务账号标识无效")
        return result

    def _cipher(self):
        """Create a key only before the first binding; never replace a lost key."""
        try:
            if not self.key_path.exists():
                if self.db.execute("SELECT 1 FROM billing_bindings LIMIT 1").fetchone():
                    raise BillingStoreError("财务凭据密钥缺失，请恢复原 billing.key 文件后重试")
                key = Fernet.generate_key()
                try:
                    descriptor = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                except FileExistsError:
                    pass
                else:
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(key)
                        stream.flush()
                        os.fsync(stream.fileno())
            return Fernet(self.key_path.read_bytes())
        except BillingStoreError:
            raise
        except (OSError, ValueError, TypeError):
            raise BillingStoreError("财务凭据密钥无法读取，请检查原 billing.key 文件") from None

    def _encrypt(self, value):
        try:
            if not isinstance(value, dict):
                raise ValueError()
            data = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
            if len(data) > 128 * 1024:
                raise ValueError()
        except (TypeError, ValueError, OverflowError):
            raise BillingStoreError("财务请求数据格式无效") from None
        return self._cipher().encrypt(data).decode("ascii")

    def _decrypt(self, value):
        try:
            result = json.loads(self._cipher().decrypt(value.encode("ascii")))
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except BillingStoreError:
            raise
        except (InvalidToken, ValueError, TypeError, UnicodeError, AttributeError):
            raise BillingStoreError("财务凭据无法解密，请检查原 billing.key 文件或重新绑定账号") from None

    def bind(self, qq, provider, account, credentials):
        qq, provider, account = map(self._identity, (qq, provider, account))
        encrypted = self._encrypt(credentials)
        generation = secrets.token_hex(16)
        now = time.time()
        with self.db:
            self.db.execute("DELETE FROM billing_checkouts WHERE qq=? AND provider=?", (qq, provider))
            self.db.execute("INSERT INTO billing_bindings VALUES(?,?,?,?,?,?) "
                            "ON CONFLICT(qq,provider) DO UPDATE SET account=excluded.account,"
                            "credentials=excluded.credentials,generation=excluded.generation,created=excluded.created",
                            (qq, provider, account, encrypted, generation, now))
        return {"qq": qq, "provider": provider, "account": account,
                "credentials": dict(credentials), "generation": generation, "created": now}

    def get_binding(self, qq, provider):
        row = self.db.execute("SELECT * FROM billing_bindings WHERE qq=? AND provider=?",
                              (str(qq), str(provider))).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["credentials"] = self._decrypt(result["credentials"])
        return result

    def unbind(self, qq, provider):
        with self.db:
            self.db.execute("DELETE FROM billing_checkouts WHERE qq=? AND provider=?", (str(qq), str(provider)))
            return self.db.execute("DELETE FROM billing_bindings WHERE qq=? AND provider=?",
                                   (str(qq), str(provider))).rowcount == 1

    def create_order(self, qq, provider, account, generation, invoice_id, order_id="", summary="", status="unpaid"):
        """Retain a remote result even if its binding was revoked during the request."""
        qq, provider, account, generation, invoice_id = map(self._identity, (qq, provider, account, generation, invoice_id))
        local_id = secrets.token_hex(12)
        with self.db:
            self.db.execute("INSERT INTO billing_orders VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (local_id, qq, provider, account, generation, invoice_id,
                             str(order_id), str(summary), str(status), time.time()))
        return local_id

    def get_order(self, qq, provider, local_id):
        row = self.db.execute("SELECT o.* FROM billing_orders o JOIN billing_bindings b "
                              "ON b.qq=o.qq AND b.provider=o.provider AND b.account=o.account AND b.generation=o.generation "
                              "WHERE o.qq=? AND o.provider=? AND o.id=?",
                              (str(qq), str(provider), str(local_id))).fetchone()
        return dict(row) if row else None

    def list_orders(self, qq, provider, limit=20):
        limit = max(1, min(int(limit), 100))
        return [dict(row) for row in self.db.execute(
            "SELECT o.* FROM billing_orders o JOIN billing_bindings b "
            "ON b.qq=o.qq AND b.provider=o.provider AND b.account=o.account AND b.generation=o.generation "
            "WHERE o.qq=? AND o.provider=? ORDER BY o.created DESC,o.id DESC LIMIT ?",
            (str(qq), str(provider), limit))]

    def set_order_status(self, qq, provider, local_id, status):
        if self.get_order(qq, provider, local_id) is None:
            return False
        with self.db:
            return self.db.execute("UPDATE billing_orders SET status=? WHERE id=? AND qq=? AND provider=?",
                                   (str(status), str(local_id), str(qq), str(provider))).rowcount == 1

    def save_checkout(self, qq, provider, generation, payload, summary, ttl=300):
        qq, provider, generation = map(self._identity, (qq, provider, generation))
        if not isinstance(ttl, (int, float)) or not 0 < ttl <= 86400:
            raise BillingStoreError("下单确认有效期无效")
        encrypted = self._encrypt(payload)
        token, now = secrets.token_urlsafe(18), time.time()
        with self.db:
            binding = self.db.execute("SELECT account FROM billing_bindings WHERE qq=? AND provider=? AND generation=?",
                                      (qq, provider, generation)).fetchone()
            if binding is None:
                raise BillingStoreError("财务账号绑定已变化，请重新查询商品")
            self.db.execute("DELETE FROM billing_checkouts WHERE expires<? AND status='pending'", (now - 86400,))
            self.db.execute("INSERT INTO billing_checkouts VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (token, qq, provider, binding["account"], generation, encrypted,
                             str(summary), "pending", now + ttl, now, ""))
        return token

    def get_checkout(self, qq, provider, generation, token):
        row = self.db.execute("SELECT c.* FROM billing_checkouts c JOIN billing_bindings b "
                              "ON b.qq=c.qq AND b.provider=c.provider AND b.account=c.account AND b.generation=c.generation "
                              "WHERE c.qq=? AND c.provider=? AND c.generation=? AND c.token=?",
                              (str(qq), str(provider), str(generation), str(token))).fetchone()
        if row is None:
            return None
        result = dict(row)
        if result["status"] == "pending" and result["expires"] <= time.time():
            result["status"] = "expired"
        result["payload"] = self._decrypt(result["payload"])
        return result

    def claim_checkout(self, qq, provider, generation, token):
        """The conditional UPDATE is the durable, atomic submit-once boundary."""
        with self.db:
            changed = self.db.execute(
                "UPDATE billing_checkouts SET status='submitting' WHERE token=? AND qq=? AND provider=? "
                "AND generation=? AND status='pending' AND expires>? AND EXISTS "
                "(SELECT 1 FROM billing_bindings b WHERE b.qq=billing_checkouts.qq "
                "AND b.provider=billing_checkouts.provider AND b.account=billing_checkouts.account "
                "AND b.generation=billing_checkouts.generation)",
                (str(token), str(qq), str(provider), str(generation), time.time())).rowcount
            if changed != 1:
                return None
            row = self.db.execute("SELECT payload FROM billing_checkouts WHERE token=?", (str(token),)).fetchone()
            return self._decrypt(row["payload"])

    def finish_checkout(self, token, local_order_id):
        with self.db:
            return self.db.execute(
                "UPDATE billing_checkouts SET status='complete',local_order_id=? "
                "WHERE token=? AND status='submitting' AND EXISTS "
                "(SELECT 1 FROM billing_orders o WHERE o.id=? AND o.qq=billing_checkouts.qq "
                "AND o.provider=billing_checkouts.provider AND o.account=billing_checkouts.account "
                "AND o.generation=billing_checkouts.generation)",
                (str(local_order_id), str(token), str(local_order_id))).rowcount == 1
