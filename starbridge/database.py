"""The application's SQLite API, backed by SQLite or a real MySQL connection.

The MySQL dialect deliberately supports the SQL used by this project, rather
than accepting arbitrary SQLite SQL. Parameters always remain driver-bound.
"""
from collections.abc import Mapping
from contextlib import closing
from decimal import Decimal
from pathlib import Path
import re
import sqlite3
import time
import uuid


_TOKEN = re.compile(r"\s+|--[^\n]*(?:\n|$)|/\*.*?\*/|'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`|[A-Za-z_][A-Za-z_0-9]*|[0-9]+(?:\.[0-9]+)?|!=|<>|<=|>=|\|\||.", re.S)
_WORD = re.compile(r"[A-Za-z_][A-Za-z_0-9]*\Z")
_INDEXED = {"player_profiles": {"name"}, "player_visits": {"server", "profile"},
            "bindings": {"uuid"}, "registration_limits": {"key", "time"},
            "tickets": {"account_id", "updated"}, "ticket_messages": {"ticket", "created"}}
_WIDTHS = {"server": 40, "uuid": 128, "token_hash": 64, "username": 32,
           "email": 254, "qq": 512, "key": 384, "identity": 512,
           "day": 32, "account_id": 128, "name": 512, "player_key": 16,
           "ticket": 128, "sanction": 128}
_ERRORS = {"IntegrityError": sqlite3.IntegrityError, "DataError": sqlite3.DataError,
           "ProgrammingError": sqlite3.ProgrammingError, "InterfaceError": sqlite3.InterfaceError,
           "OperationalError": sqlite3.OperationalError, "InternalError": sqlite3.InternalError,
           "NotSupportedError": sqlite3.NotSupportedError}


def _tokens(sql):
    return [value for value in _TOKEN.findall(sql) if not value.isspace()
            and not value.startswith(("--", "/*"))]


def _upper(token):
    return token.upper() if _WORD.fullmatch(token) else token


def _identifier(token):
    return token.strip('`"')


def _quote(name):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name):
        raise sqlite3.ProgrammingError("数据库标识符无效")
    return "`" + name + "`"


def _close(tokens, start):
    depth = 0
    for index in range(start, len(tokens)):
        depth += tokens[index] == "("
        depth -= tokens[index] == ")"
        if depth == 0:
            return index
    raise sqlite3.ProgrammingError("数据库语句括号不完整")


def _split(tokens, separator=","):
    result, start, depth = [], 0, 0
    for index, token in enumerate(tokens):
        if token == separator and depth == 0:
            result.append(tokens[start:index]); start = index + 1
        depth += token == "("
        depth -= token == ")"
    result.append(tokens[start:])
    return result


def _render(tokens):
    # PyMySQL interpolates its own escaped parameters with %, so literal SQL
    # percent characters must be doubled, including inside quoted literals.
    return " ".join("%s" if item == "?" else item.replace("%", "%%") for item in tokens)


def _functions(tokens):
    result, index = [], 0
    while index < len(tokens):
        token = tokens[index]
        if index + 1 < len(tokens) and tokens[index + 1] == "(" and _WORD.fullmatch(token):
            end = _close(tokens, index + 1)
            inner = _functions(tokens[index + 2:end])
            name = token.upper()
            if name in ("MAX", "MIN") and len(_split(inner)) > 1:
                token = "GREATEST" if name == "MAX" else "LEAST"
            if name == "JSON_EXTRACT":
                call = ["JSON_EXTRACT", "(", *inner, ")"]
                # SQLite returns SQL NULL for a JSON null, MySQL returns JSON
                # 'null'. Preserve the distinction from the string "null".
                result.extend(["CASE", "WHEN", "JSON_TYPE", "(", *call, ")", "COLLATE", "utf8mb4_0900_bin", "=", "'NULL'",
                               "THEN", "NULL", "ELSE", "JSON_UNQUOTE", "(", *call, ")", "COLLATE", "utf8mb4_0900_bin", "END"])
            else:
                result.extend([token, "(", *inner, ")"])
            index = end + 1
        else:
            result.append(token); index += 1
    return result


def _dialect(tokens):
    tokens = _functions(tokens)
    result, index = [], 0
    while index < len(tokens):
        token, upper = tokens[index], _upper(tokens[index])
        if upper == "LIMIT" and tokens[index + 1:index + 3] == ["-", "1"]:
            result.extend(["LIMIT", "18446744073709551615"]); index += 3; continue
        if token == "/" and result and _identifier(result[-1]).lower() == "bucket":
            token = "DIV"
        if upper in ("KEY", "GROUPS", "RANK", "SYSTEM", "ROWS") and not (upper == "KEY" and result and _upper(result[-1]) == "PRIMARY"):
            token = _quote(token)
        if upper == "LIKE":
            result.extend(["COLLATE", "utf8mb4_0900_as_ci"])
        if upper == "FROM" and index + 2 < len(tokens) and tokens[index + 1] == "(" and _upper(tokens[index + 2]) == "SELECT":
            end = _close(tokens, index + 1)
            result.extend([token, "(", *_dialect(tokens[index + 2:end]), ")"])
            if end + 1 == len(tokens) or _upper(tokens[end + 1]) in ("WHERE", "GROUP", "ORDER", "LIMIT", "HAVING", "UNION", ")", ";"):
                result.extend(["AS", "_sb_derived"])
            index = end + 1; continue
        result.append(token); index += 1
    if len(result) > 2 and [_upper(t) for t in result[:2]] == ["DELETE", "FROM"]:
        target, index, rewritten = _identifier(result[2]), 0, []
        while index < len(result):
            if result[index:index + 2] and result[index] == "(" and index + 1 < len(result) and _upper(result[index + 1]) == "SELECT":
                end = _close(result, index)
                inner = result[index + 1:end]
                if any(_upper(inner[j]) == "FROM" and _identifier(inner[j + 1]) == target for j in range(len(inner) - 1)):
                    rewritten.extend(["(", "SELECT", "*", "FROM", "(", *inner, ")", "AS", "_sb_delete", ")"])
                    index = end + 1; continue
            rewritten.append(result[index]); index += 1
        result = rewritten
    return result


def _create_table(tokens):
    start = tokens.index("("); end = _close(tokens, start)
    table = _identifier(tokens[start - 1])
    definitions = _split(tokens[start + 1:end])
    indexed = set(_INDEXED.get(table, ()))
    for definition in definitions:
        upper = [_upper(token) for token in definition]
        if upper[0] in ("PRIMARY", "UNIQUE"):
            indexed.update(_identifier(token) for token in definition if _WORD.fullmatch(token) and _upper(token) not in ("PRIMARY", "KEY", "UNIQUE"))
        elif "PRIMARY" in upper or "UNIQUE" in upper:
            indexed.add(_identifier(definition[0]))
    rewritten = []
    for definition in definitions:
        if len(definition) > 1 and _upper(definition[1]) == "TEXT":
            column = _identifier(definition[0])
            if column in indexed:
                width = _WIDTHS.get(column, 768)
                definition[1:2] = [f"VARCHAR({width})"]
            else:
                definition[1] = "LONGTEXT"
                upper = [_upper(value) for value in definition]
                if "DEFAULT" in upper:
                    at = upper.index("DEFAULT") + 1
                    if definition[at] != "(":
                        definition[at:at + 1] = ["(", definition[at], ")"]
        definition = ["AUTO_INCREMENT" if _upper(value) == "AUTOINCREMENT" else
                      "BIGINT" if _upper(value) == "INTEGER" else
                      "DOUBLE" if _upper(value) == "REAL" else value for value in definition]
        rewritten.extend(([","] if rewritten else []) + definition)
    return _dialect(tokens[:start + 1] + rewritten + tokens[end:]) + ["ENGINE=InnoDB", "DEFAULT", "CHARSET=utf8mb4", "COLLATE=utf8mb4_0900_bin"]


def _check_signature(tokens):
    result = []
    for index, token in enumerate(tokens):
        if token in ("(", ")"):
            continue
        if token.lower().startswith("_utf8") and index + 1 < len(tokens) and tokens[index + 1].startswith("'"):
            continue
        result.append(_upper(_identifier(token)) if not token.startswith("'") else token)
    return tuple(result)


def _table_definition(sql):
    tokens = _create_table(_tokens(sql))
    start = tokens.index("(")
    parts = _split(tokens[start + 1:_close(tokens, start)])
    primary, uniques, checks, definitions = (), set(), [], {}
    for part in parts:
        upper = [_upper(value) for value in part]
        if upper[0] in ("PRIMARY", "UNIQUE"):
            at = part.index("(")
            names = tuple(_identifier(value[0]) for value in _split(part[at + 1:_close(part, at)]))
            if upper[0] == "PRIMARY":
                primary = names
            else:
                uniques.add(names)
        else:
            name = _identifier(part[0])
            if "PRIMARY" in upper:
                primary = (name,)
            if "UNIQUE" in upper:
                uniques.add((name,))
            varchar = re.fullmatch(r"VARCHAR\((\d+)\)", part[1], re.I)
            kind = "varchar" if varchar else part[1].lower()
            maximum = int(varchar[1]) if varchar else 4294967295 if kind == "longtext" else None
            nullable = not any(upper[i:i + 2] == ["NOT", "NULL"] for i in range(len(upper) - 1))
            definitions[name] = (kind, maximum, nullable, "AUTO_INCREMENT" in upper)
        for at, value in enumerate(upper):
            if value == "CHECK":
                checks.append(_check_signature(part[at + 2:_close(part, at + 1)]))
    for name in primary:
        kind, maximum, nullable, auto = definitions[name]
        definitions[name] = (kind, maximum, False, auto)
    return definitions, primary, uniques, checks


def _default_matches(actual, expected):
    if expected is None:
        return actual is None
    if actual is None:
        return False
    if isinstance(expected, (int, float)):
        try:
            return Decimal(str(actual)) == Decimal(str(expected))
        except Exception:
            return False
    if actual == expected:
        return True
    # MySQL reports LONGTEXT defaults as charset-introduced expressions.
    # Decode only a single constant literal, never evaluate metadata SQL.
    expression = _check_signature(_tokens(re.sub(r"\\+(?=')", "", str(actual))))
    return (len(expression) == 1 and expression[0].startswith("'") and expression[0].endswith("'")
            and expression[0][1:-1].replace("''", "'") == expected)


class Row:
    """sqlite3.Row-compatible integer/name access and mapping conversion."""
    def __init__(self, names, values):
        self._names = tuple(names)
        self._values = tuple(float(value) if isinstance(value, Decimal) else value for value in values)

    def keys(self):
        return list(self._names)

    def __getitem__(self, key):
        if isinstance(key, str):
            for index, name in enumerate(self._names):
                if name.lower() == key.lower():
                    return self._values[index]
            raise IndexError("No item with that key")
        return self._values[key]

    def __len__(self):
        return len(self._values)

    def __iter__(self):
        return iter(self._values)


class Cursor:
    def __init__(self, rows=(), names=(), rowcount=-1, lastrowid=None):
        self._rows = iter(Row(names, values) for values in rows)
        self.rowcount, self.lastrowid = rowcount, lastrowid
        self.description = tuple((name, None, None, None, None, None, None) for name in names) if names else None

    def fetchone(self):
        return next(self._rows, None)

    def fetchall(self):
        return list(self._rows)

    def fetchmany(self, size=1):
        result = []
        for _ in range(size):
            row = self.fetchone()
            if row is None:
                break
            result.append(row)
        return result

    def __iter__(self):
        return self._rows

    def close(self):
        self._rows = iter(())


class MySQLConnection:
    dialect = "mysql"

    def __init__(self, settings):
        self.settings = dict(settings)
        self._raw = None
        self._active = False
        self._depth = 0
        self._failed = False
        self._closed = False
        self._columns = {}
        self.row_factory = Row
        try:
            import pymysql
        except ImportError:
            raise sqlite3.OperationalError("MySQL 驱动未安装，请安装 PyMySQL[rsa]") from None
        self._driver = pymysql
        self._open()

    @property
    def in_transaction(self):
        return self._active

    def _open(self):
        cfg = self.settings
        options = {key: cfg[key] for key in ("host", "port", "database", "user", "password", "connect_timeout", "read_timeout", "write_timeout") if key in cfg}
        options.update(charset="utf8mb4", collation="utf8mb4_0900_bin", autocommit=True,
                       client_flag=self._driver.constants.CLIENT.FOUND_ROWS,
                       sql_mode="STRICT_ALL_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION,NO_BACKSLASH_ESCAPES,IGNORE_SPACE")
        if cfg.get("tls"):
            options.update(ssl_ca=cfg.get("ssl_ca") or None, ssl_verify_cert=True, ssl_verify_identity=True)
        else:
            options["ssl_disabled"] = True
        raw = None
        try:
            raw = self._driver.connect(**options)
            with raw.cursor() as cursor:
                cursor.execute("SELECT VERSION()")
                version = str(cursor.fetchone()[0])
            numbers = re.match(r"(\d+)\.(\d+)\.(\d+)", version)
            if "mariadb" in version.lower() or not numbers or tuple(map(int, numbers.groups())) < (8, 0, 17):
                raw.close()
                raise sqlite3.NotSupportedError("需要 MySQL 8.0.17 或更新版本")
            self._raw = raw
            self._failed = False
            self._require_metadata_access()
            # Reject a mistaken existing database before application startup
            # can create project tables in it. The one historical column
            # migration remains the responsibility of NativePasswords.
            self._validate_schema(allow_legacy=True)
        except self._driver.Error as exc:
            if raw is not None and raw.open:
                raw.close()
            self._raise(exc)
        except BaseException:
            if raw is not None and raw.open:
                raw.close()
            raise

    def _require_metadata_access(self):
        # MySQL hides triggers from INFORMATION_SCHEMA without TRIGGER
        # privilege. An empty result is meaningful only after checking that
        # the current account has an explicit global/schema grant. Role-only
        # grants are intentionally refused rather than guessed at.
        current = self._run(_tokens("SELECT CURRENT_USER()")).fetchone()[0]
        user, host = current.rsplit("@", 1)
        grantee = "'" + user.replace("'", "''") + "'@'" + host.replace("'", "''") + "'"
        global_grant = self._run(_tokens("SELECT 1 FROM INFORMATION_SCHEMA.USER_PRIVILEGES WHERE GRANTEE=? AND PRIVILEGE_TYPE='TRIGGER' LIMIT 1"), (grantee,)).fetchone()
        schema_grant = self._run(_tokens("SELECT 1 FROM INFORMATION_SCHEMA.SCHEMA_PRIVILEGES WHERE GRANTEE=? AND TABLE_SCHEMA=DATABASE() AND PRIVILEGE_TYPE='TRIGGER' LIMIT 1"), (grantee,)).fetchone()
        if not global_grant and not schema_grant:
            raise ValueError("MySQL 用户需要直接授予本数据库的 TRIGGER 权限，以检查并拒绝未知触发器；不支持仅由角色授予此权限")

    def _raise(self, exc):
        self._last_error_code = exc.args[0] if exc.args else None
        cls = _ERRORS.get(type(exc).__name__, sqlite3.DatabaseError)
        message = "MySQL 数据约束冲突" if cls is sqlite3.IntegrityError else "MySQL 数据操作失败，请检查数据库连接、权限和数据格式"
        raise cls(message) from None

    def _ready(self):
        if self._closed:
            raise sqlite3.ProgrammingError("数据库连接已关闭")
        if self._failed:
            if self._active:
                raise sqlite3.OperationalError("MySQL 事务连接中断，操作未自动重试")
            self._open()

    def _run(self, tokens, params=()):
        self._ready()
        try:
            with self._raw.cursor() as cursor:
                cursor.execute(_render(tokens), tuple(params))
                names = [column[0] for column in cursor.description] if cursor.description else []
                rows = cursor.fetchall() if names else ()
                return Cursor(rows, names, cursor.rowcount, cursor.lastrowid)
        except self._driver.Error as exc:
            if isinstance(exc, (self._driver.OperationalError, self._driver.InterfaceError)) and (not exc.args or exc.args[0] in (0, 2002, 2003, 2006, 2013, 2014, 2045, 2055)):
                self._failed = True
                try:
                    self._raw.close()
                except Exception:
                    pass
            self._raise(exc)

    def _begin(self):
        self._ready()
        if not self._active:
            self._run(["START", "TRANSACTION"])
            self._active = True

    def __enter__(self):
        self._ready()
        self._depth += 1
        return self

    def __exit__(self, kind, value, traceback):
        self._depth -= 1
        if kind is None:
            self.commit()
        else:
            self.rollback()
        return False

    def commit(self):
        if self._active:
            try:
                self._run(["COMMIT"])
            finally:
                self._active = False

    def rollback(self):
        if self._active:
            try:
                if not self._failed:
                    self._run(["ROLLBACK"])
            finally:
                self._active = False

    def close(self):
        if self._closed:
            return
        if self._raw is not None and self._raw.open:
            self._raw.close()
        self._closed = True
        self._active = False

    def _table_columns(self, table):
        if table not in self._columns:
            rows = self._run(_tokens("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=? ORDER BY ORDINAL_POSITION"), (table,))
            self._columns[table] = [row[0] for row in rows]
        return self._columns[table]

    def _insert(self, tokens, params):
        upper = [_upper(value) for value in tokens]
        ignore = upper[1:3] == ["OR", "IGNORE"]
        if ignore:
            tokens = tokens[:1] + tokens[3:]
            upper = [_upper(value) for value in tokens]
        conflict = next((i for i in range(len(tokens) - 1) if upper[i:i + 2] == ["ON", "CONFLICT"]), None)
        if conflict is None and not ignore:
            return self._run(_dialect(tokens), params)
        insert = tokens[:conflict] if conflict is not None else tokens
        # Ignore only duplicate-key errors; MySQL INSERT IGNORE also turns
        # truncation and invalid values into warnings, which is unsafe here.
        try:
            return self._run(_dialect(insert), params)
        except sqlite3.IntegrityError:
            if ignore:
                # A duplicate is the only IntegrityError SQLite ignores for
                # project inputs. NOT NULL/CHECK/FK errors must still fail.
                # Identify it without retaining or printing SQL/parameters.
                if getattr(self, "_last_error_code", None) != 1062:
                    raise
                return Cursor(rowcount=0)
            if getattr(self, "_last_error_code", None) != 1062:
                raise
            table = _identifier(insert[2])
            values_at = next(i for i, value in enumerate(insert) if _upper(value) == "VALUES")
            columns = [_identifier(part[0]) for part in _split(insert[4:values_at - 1])] if insert[3] == "(" else self._table_columns(table)
            values = _split(insert[values_at + 2:_close(insert, values_at + 1)])
            if len(columns) != len(values):
                raise sqlite3.ProgrammingError("MySQL 插入列不匹配") from None
            mapping, offset = {}, 0
            for column, expression in zip(columns, values):
                count = expression.count("?")
                mapping[column] = (expression, tuple(params[offset:offset + count])); offset += count
            target_end = _close(tokens, conflict + 2)
            targets = [_identifier(part[0]) for part in _split(tokens[conflict + 3:target_end])]
            where, where_params = [], []
            for target in targets:
                if target not in mapping:
                    raise sqlite3.ProgrammingError("MySQL 冲突目标无插入值") from None
                expression, arguments = mapping[target]
                where.extend((["AND"] if where else []) + [_quote(target), "=", *expression])
                where_params.extend(arguments)
            existing = self._run(["SELECT", "1", "FROM", _quote(table), "WHERE", *where, "FOR", "UPDATE"], where_params).fetchone()
            if not existing:
                raise sqlite3.IntegrityError("MySQL 数据约束冲突") from None
            tail = tokens[target_end + 1:]
            if [_upper(value) for value in tail[:2]] == ["DO", "NOTHING"]:
                return Cursor(rowcount=0)
            if [_upper(value) for value in tail[:3]] != ["DO", "UPDATE", "SET"]:
                raise sqlite3.NotSupportedError("MySQL 冲突更新语句不支持") from None
            rewritten, arguments, index = [], [], 3
            while index < len(tail):
                if index + 2 < len(tail) and _upper(tail[index]) == "EXCLUDED" and tail[index + 1] == ".":
                    expression, bound = mapping[_identifier(tail[index + 2])]
                    rewritten.extend(expression); arguments.extend(bound); index += 3
                else:
                    rewritten.append(tail[index]); index += 1
            return self._run(_dialect(["UPDATE", _quote(table), "SET", *rewritten, "WHERE", *where]), (*arguments, *where_params))

    def execute(self, sql, parameters=()):
        if isinstance(parameters, Mapping):
            raise sqlite3.NotSupportedError("MySQL 使用位置参数")
        tokens = _tokens(sql)
        if tokens and tokens[-1] == ";":
            tokens.pop()
        if not tokens:
            return Cursor()
        upper = [_upper(value) for value in tokens]
        command = upper[0]
        if ";" in tokens:
            raise sqlite3.ProgrammingError("一次只能执行一条数据库语句")
        if command == "PRAGMA":
            if len(tokens) > 2 and upper[1] == "TABLE_INFO":
                table = _identifier(tokens[3])
                rows = self._run(_tokens("SELECT ORDINAL_POSITION-1,COLUMN_NAME,DATA_TYPE,IS_NULLABLE,COLUMN_DEFAULT,COLUMN_KEY FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=? ORDER BY ORDINAL_POSITION"), (table,))
                return Cursor([(row[0], row[1], row[2], int(row[3] == "NO"), row[4], int(row[5] == "PRI")) for row in rows], ("cid", "name", "type", "notnull", "dflt_value", "pk"))
            if len(tokens) > 1 and upper[1] in ("JOURNAL_MODE", "TRUSTED_SCHEMA"):
                return Cursor()
            raise sqlite3.NotSupportedError("MySQL 不支持此 SQLite PRAGMA")
        if command == "BEGIN":
            self._begin(); return Cursor()
        if command in ("COMMIT", "END"):
            self.commit(); return Cursor()
        if command == "ROLLBACK":
            self.rollback(); return Cursor()
        ddl = command in ("CREATE", "ALTER", "DROP")
        if ddl and self._active:
            raise sqlite3.ProgrammingError("MySQL 结构变更不能在数据事务中执行")
        if not ddl and (self._depth or command in ("INSERT", "UPDATE", "DELETE", "REPLACE")):
            self._begin()
        if command == "CREATE" and "TABLE" in upper[:3]:
            result = self._run(_create_table(tokens), parameters)
            self._columns.clear()
            return result
        if command == "CREATE" and upper[1:5] == ["INDEX", "IF", "NOT", "EXISTS"]:
            name, table = _identifier(tokens[5]), _identifier(tokens[7])
            existing = self._run(_tokens("SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=? AND INDEX_NAME=? LIMIT 1"), (table, name)).fetchone()
            return Cursor() if existing else self._run(_dialect(tokens[:2] + tokens[5:]), parameters)
        if command == "ALTER":
            # The one legacy native_password_proofs migration adds unindexed
            # account text with a default; retain a large, lossless value.
            tokens = ["LONGTEXT" if _upper(value) == "TEXT" else value for value in tokens]
            if "DEFAULT" in upper:
                at = upper.index("DEFAULT") + 1
                tokens[at:at + 1] = ["(", tokens[at], ")"]
            self._columns.clear()
        if command == "INSERT":
            return self._insert(tokens, tuple(parameters))
        if command == "REPLACE":
            return self._run(_dialect(tokens), parameters)
        return self._run(_dialect(tokens), parameters)

    def executemany(self, sql, parameters):
        count, lastrowid = 0, None
        for values in parameters:
            result = self.execute(sql, values)
            count += max(result.rowcount, 0); lastrowid = result.lastrowid
        return Cursor(rowcount=count, lastrowid=lastrowid)

    def executescript(self, script):
        # sqlite3.executescript commits any pending transaction first.
        self.commit()
        tokens = _tokens(script)
        for statement in _split(tokens, ";"):
            if statement:
                self.execute(" ".join(statement))
        return Cursor()

    def tables(self):
        rows = self._run(_tokens("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE'"))
        return {row[0] for row in rows}

    @staticmethod
    def _canonical():
        # Keeping the portable backup schema byte-for-byte equal to SQLite's
        # trusted schema lets existing archives and validators keep working.
        from .backups import trusted_schema
        return trusted_schema()

    def _validate_schema(self, initialize=False, allow_legacy=False):
        entries = self._canonical()
        expected = {entry[1]: entry for entry in entries if entry[0] == "table" and not entry[1].startswith("sqlite_")}
        present = self.tables()
        if present - expected.keys():
            raise ValueError("MySQL 数据库包含非本项目表，请使用独立的空数据库")
        # Views/triggers can redirect writes or make snapshots incomplete.
        objects = self._run(_tokens("SELECT 1 FROM INFORMATION_SCHEMA.VIEWS WHERE TABLE_SCHEMA=DATABASE() LIMIT 1")).fetchone()
        triggers = self._run(_tokens("SELECT 1 FROM INFORMATION_SCHEMA.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE() LIMIT 1")).fetchone()
        foreign_keys = self._run(_tokens("SELECT 1 FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA=DATABASE() AND CONSTRAINT_TYPE='FOREIGN KEY' LIMIT 1")).fetchone()
        if objects or triggers or foreign_keys:
            raise ValueError("MySQL 数据库包含不支持的视图、触发器或外键")
        if initialize and not present:
            for entry in expected.values():
                self.execute(entry[3])
            for kind, name, table, sql in entries:
                if kind == "index" and sql:
                    self.execute(sql)
            present = self.tables()
        with closing(sqlite3.connect(":memory:")) as canonical:
            for entry in expected.values():
                canonical.execute(entry[3])
            infos = {table: list(canonical.execute("PRAGMA table_info(" + _quote(table) + ")")) for table in expected}
            columns = {table: [row[1] for row in info] for table, info in infos.items()}
            defaults = {table: {row[1]: canonical.execute("SELECT " + row[4]).fetchone()[0] if row[4] is not None else None
                                for row in info} for table, info in infos.items()}
        if present:
            table_info = {row[0]: (row[1], row[2]) for row in self._run(_tokens("SELECT TABLE_NAME,ENGINE,TABLE_COLLATION FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE'"))}
            actual_columns, actual_indexes, actual_checks = {}, {}, {}
            for row in self._run(_tokens("SELECT TABLE_NAME,COLUMN_NAME,DATA_TYPE,CHARACTER_MAXIMUM_LENGTH,IS_NULLABLE,EXTRA,COLLATION_NAME,COLUMN_DEFAULT,GENERATION_EXPRESSION,COLUMN_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME,ORDINAL_POSITION")):
                actual_columns.setdefault(row[0], []).append(tuple(row)[1:])
            for row in self._run(_tokens("SELECT TABLE_NAME,INDEX_NAME,NON_UNIQUE,COLUMN_NAME,SUB_PART FROM INFORMATION_SCHEMA.STATISTICS WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME,INDEX_NAME,SEQ_IN_INDEX")):
                key = (row[1], bool(row[2]))
                actual_indexes.setdefault(row[0], {}).setdefault(key, []).append((row[3], row[4]))
            for row in self._run(_tokens("SELECT t.TABLE_NAME,c.CHECK_CLAUSE,t.ENFORCED FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS t JOIN INFORMATION_SCHEMA.CHECK_CONSTRAINTS c ON t.CONSTRAINT_SCHEMA=c.CONSTRAINT_SCHEMA AND t.CONSTRAINT_NAME=c.CONSTRAINT_NAME WHERE t.TABLE_SCHEMA=DATABASE() AND t.CONSTRAINT_TYPE='CHECK'")):
                if row[2] != "YES":
                    raise ValueError("MySQL 检查约束未启用")
                # INFORMATION_SCHEMA quotes CHECK string literals with
                # backslashes even under NO_BACKSLASH_ESCAPES. Decode that
                # metadata representation; never rewrite application values.
                clause = re.sub(r"\\+(?=')", "", row[1])
                actual_checks.setdefault(row[0], []).append(_check_signature(_tokens(clause)))
            for table in present:
                if table_info[table] != ("InnoDB", "utf8mb4_0900_bin"):
                    raise ValueError("MySQL 数据表需要 InnoDB 和 utf8mb4_0900_bin")
                definitions, primary, uniques, checks = _table_definition(expected[table][3])
                actual = actual_columns.get(table, [])
                # A previous supported release did not have this column;
                # no other missing/extra column is accepted.
                legacy = allow_legacy and table == "native_password_proofs" and [row[0] for row in actual] == columns[table][:-1]
                expected_names = columns[table][:-1] if legacy else columns[table]
                if [row[0] for row in actual] != expected_names:
                    raise ValueError("MySQL 数据库字段与当前版本不兼容")
                for name, data_type, maximum, nullable, extra, collation, default, generation, column_type in actual:
                    expected_type, expected_maximum, expected_nullable, auto = definitions[name]
                    if (data_type, maximum, nullable == "YES", "auto_increment" in extra.lower()) != (expected_type, expected_maximum, expected_nullable, auto):
                        raise ValueError("MySQL 字段类型或约束与当前版本不兼容")
                    if collation is not None and collation != "utf8mb4_0900_bin":
                        raise ValueError("MySQL 字段排序规则与当前版本不兼容")
                    if generation or "unsigned" in column_type.lower() or not _default_matches(default, defaults[table][name]):
                        raise ValueError("MySQL 字段生成规则或默认值与当前版本不兼容")
                indexes = actual_indexes.get(table, {})
                if any(part is not None for values in indexes.values() for name, part in values):
                    raise ValueError("MySQL 索引不能使用字段前缀")
                actual_primary = tuple(name for name, part in indexes.get(("PRIMARY", False), []))
                actual_unique = {tuple(name for name, part in values) for (name, non_unique), values in indexes.items() if not non_unique and name != "PRIMARY"}
                if actual_primary != primary or actual_unique != uniques:
                    raise ValueError("MySQL 唯一索引与当前版本不兼容")
                expected_secondary = {}
                for kind, index_name, index_table, sql in entries:
                    if kind == "index" and sql and index_table == table:
                        parts = _tokens(sql)
                        at = parts.index("(")
                        expected_secondary[index_name] = tuple(_identifier(value[0]) for value in _split(parts[at + 1:_close(parts, at)]))
                actual_secondary = {name: tuple(column for column, part in values) for (name, non_unique), values in indexes.items() if non_unique}
                secondary_ok = (all(expected_secondary.get(name) == values for name, values in actual_secondary.items())
                                if allow_legacy else actual_secondary == expected_secondary)
                if not secondary_ok or sorted(actual_checks.get(table, [])) != sorted(checks):
                    raise ValueError("MySQL 索引或检查约束与当前版本不兼容")
                self._columns[table] = list(expected_names)
        return expected, present, columns

    def has_data(self):
        _, present, _ = self._validate_schema()
        return any(self._run(["SELECT", "1", "FROM", _quote(table), "LIMIT", "1"]).fetchone() is not None for table in sorted(present))

    def export_sqlite(self, destination, max_bytes=128 * 1024 * 1024):
        """Write a bounded, consistent, portable SQLite snapshot.

        A separate connection makes this safe for the backup worker thread;
        the application's live transaction is never committed or reused.
        """
        from .backups import OPTIONAL_TABLES
        destination = Path(destination)
        if destination.exists():
            raise ValueError("数据库快照目标已存在")
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = MySQLConnection(self.settings)
        target = None
        try:
            expected, present, columns = source._validate_schema()
            if expected.keys() - present - OPTIONAL_TABLES:
                raise ValueError("MySQL 数据库缺少必要表")
            target = sqlite3.connect(destination)
            for entry in expected.values():
                target.execute(entry[3])
            for kind, name, table, sql in source._canonical():
                if kind == "index" and sql:
                    target.execute(sql)
            source._run(_tokens("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
            source._run(_tokens("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY"))
            source._active = True
            deadline, used = time.monotonic() + 60, 0
            for table in sorted(present):
                names = columns[table]
                insert = "INSERT INTO " + _quote(table) + "(" + ",".join(_quote(name) for name in names) + ") VALUES(" + ",".join("?" for _ in names) + ")"
                try:
                    with source._raw.cursor(source._driver.cursors.SSCursor) as cursor:
                        cursor.execute("SELECT " + ",".join(_quote(name) for name in names) + " FROM " + _quote(table))
                        for row in cursor:
                            used += sum(len(value.encode("utf-8")) if isinstance(value, str) else len(value) if isinstance(value, bytes) else 8 for value in row)
                            if used > max_bytes or time.monotonic() > deadline:
                                raise ValueError("数据库快照超时或超过大小限制")
                            target.execute(insert, row)
                except source._driver.Error as exc:
                    source._raise(exc)
            # Keep AUTOINCREMENT monotonic even when the most recent rows
            # have been pruned from a table before this backup.
            sequences = source._run(_tokens("SELECT TABLE_NAME,AUTO_INCREMENT FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA=DATABASE() AND AUTO_INCREMENT IS NOT NULL"))
            for table, next_id in sequences:
                if table in present and next_id:
                    target.execute("DELETE FROM sqlite_sequence WHERE name=?", (table,))
                    target.execute("INSERT INTO sqlite_sequence VALUES(?,?)", (table, max(int(next_id) - 1, 0)))
            target.commit()
            if destination.stat().st_size > max_bytes:
                raise ValueError("数据库快照超过大小限制")
        except BaseException:
            if target is not None:
                target.close(); target = None
            destination.unlink(missing_ok=True)
            raise
        finally:
            if target is not None:
                target.close()
            source.close()

    def restore_sqlite(self, source, max_bytes=128 * 1024 * 1024):
        """Offline restore: validate first, then replace all rows atomically."""
        from .backups import OPTIONAL_TABLES, check_database, readonly_database
        source = Path(source)
        if source.stat().st_size > max_bytes:
            raise ValueError("数据库超过恢复大小限制")
        check_database(source)
        target = MySQLConnection(self.settings)
        original = None
        try:
            expected, present, columns = target._validate_schema(initialize=True)
            # A partially initialized database is not an empty target and is
            # refused before deleting rows; DDL cannot be transactionally
            # rolled back in MySQL.
            if present != expected.keys():
                raise ValueError("MySQL 数据库结构不完整，请先启动当前版本完成建表")
            original = readonly_database(source)
            incoming = {row[0] for row in original.execute("SELECT name FROM sqlite_schema WHERE type='table'") if not row[0].startswith("sqlite_")}
            if incoming - expected.keys() or expected.keys() - incoming - OPTIONAL_TABLES:
                raise ValueError("备份数据表与当前版本不兼容")
            deadline = time.monotonic() + 120
            with target:
                for table in sorted(present):
                    target.execute("DELETE FROM " + _quote(table))
                for table in sorted(incoming):
                    names = columns[table]
                    insert = "INSERT INTO " + _quote(table) + "(" + ",".join(_quote(name) for name in names) + ") VALUES(" + ",".join("?" for _ in names) + ")"
                    for row in original.execute("SELECT " + ",".join(_quote(name) for name in names) + " FROM " + _quote(table)):
                        if time.monotonic() > deadline:
                            raise ValueError("数据库恢复超过时间限制")
                        target.execute(insert, row)
                # MySQL ALTER TABLE ... AUTO_INCREMENT implicitly commits.
                # A temporary explicit-ID row advances the counter without
                # breaking the restore transaction; it is removed before
                # commit. This also preserves IDs deleted before the backup.
                for table, sequence in original.execute("SELECT name,seq FROM sqlite_sequence"):
                    if table not in ("audit", "player_profiles") or type(sequence) is not int or not 0 <= sequence <= 2 ** 63 - 1:
                        raise ValueError("备份自增序列格式错误")
                    maximum = target.execute("SELECT COALESCE(MAX(id),0) FROM " + _quote(table)).fetchone()[0]
                    if sequence <= maximum:
                        continue
                    if table == "audit":
                        target.execute("INSERT INTO audit(id,time,kind,detail) VALUES(?,0,'migration','')", (sequence,))
                    else:
                        target.execute("INSERT INTO player_profiles(id,uuid,name) VALUES(?,?,?)", (sequence, str(uuid.uuid4()), "RestoreSequence"))
                    target.execute("DELETE FROM " + _quote(table) + " WHERE id=?", (sequence,))
        finally:
            if original is not None:
                original.close()
            target.close()


def connect(path, mysql=None):
    if mysql and mysql.get("enabled"):
        return MySQLConnection(mysql)
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection
