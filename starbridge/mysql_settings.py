"""Optional MySQL connection settings; credentials never form part of a DSN."""
from copy import deepcopy
from pathlib import Path
import re


MYSQL_DEFAULTS = {
    "enabled": False, "host": "127.0.0.1", "port": 3306,
    "database": "myrinbot", "user": "myrinbot", "password": "",
    "connect_timeout": 5, "read_timeout": 5, "write_timeout": 5,
    "tls": False, "ssl_ca": "",
}


def validate_mysql(value):
    if not isinstance(value, dict) or value.keys() - MYSQL_DEFAULTS.keys():
        raise ValueError("MySQL 设置格式错误或包含不支持的字段")
    cfg = {**deepcopy(MYSQL_DEFAULTS), **value}
    for key in ("enabled", "tls"):
        if type(cfg[key]) is not bool:
            raise ValueError("MySQL 启用与 TLS 开关必须为布尔值")
    if not isinstance(cfg["host"], str) or not re.fullmatch(r"[A-Za-z0-9_.:\-]{1,253}", cfg["host"]):
        raise ValueError("MySQL 主机应为 IP 或主机名，不包含协议、空格或路径")
    if type(cfg["port"]) is not int or not 1 <= cfg["port"] <= 65535:
        raise ValueError("MySQL 端口必须是 1–65535 之间的整数")
    if not isinstance(cfg["database"], str) or not re.fullmatch(r"[A-Za-z0-9_]{1,64}", cfg["database"]):
        raise ValueError("MySQL 数据库名只能使用 1–64 位字母、数字和下划线")
    if not isinstance(cfg["user"], str) or not cfg["user"].strip() or len(cfg["user"]) > 128 or any(ord(c) < 32 for c in cfg["user"]):
        raise ValueError("MySQL 用户名必须为 1–128 位文本，不能包含控制字符")
    if not isinstance(cfg["password"], str) or len(cfg["password"]) > 1024 or "\x00" in cfg["password"]:
        raise ValueError("MySQL 密码格式错误，最长 1024 字符")
    for key in ("connect_timeout", "read_timeout", "write_timeout"):
        if type(cfg[key]) is not int or not 1 <= cfg[key] <= 30:
            raise ValueError("MySQL 连接、读取和写入超时必须为 1–30 秒的整数")
    ca = cfg["ssl_ca"]
    if not isinstance(ca, str) or len(ca) > 1000 or any(c in ca for c in "\x00\r\n"):
        raise ValueError("MySQL CA 证书路径格式错误")
    if ca and not cfg["tls"]:
        raise ValueError("填写 MySQL CA 证书时需要启用 TLS")
    return cfg


def resolve_mysql(value, config_path):
    cfg = validate_mysql(value)
    if cfg["ssl_ca"]:
        cfg["ssl_ca"] = str((Path(config_path).resolve().parent / cfg["ssl_ca"]).resolve())
    return cfg
