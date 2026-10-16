"""Validated, versioned configuration editing for the local management panel."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import tomllib
from .qq_identity import OFFICIAL_DEFAULTS, official_parts
from .reply_images import validate as validate_reply_images

FEATURES = ("qq_to_mc", "mc_to_qq", "join_quit", "unbind_on_leave", "set_group_card")


class ConfigConflict(ValueError):
    pass


def table(value, keys, label):
    if not isinstance(value, dict) or set(value) - set(keys):
        raise ValueError(f"{label} 格式错误或包含不支持的字段")


def string(value, label, maximum=256):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
        raise ValueError(f"{label} 必须为非空文本，最长 {maximum} 字符")
    return value


def ids(value, label, official=False):
    if (not isinstance(value, list) or len(value) > 1000
        or any(not isinstance(v, str) or not (re.fullmatch(r"[1-9][0-9]{0,18}", v) or (official and official_parts(v, ("qg",)))) for v in value)
        or len(set(value)) != len(value)):
        raise ValueError(f"{label} 必须是无重复的 QQ / 群号列表，官机群请填写接入信息中的 qg 身份")


def validate(value):
    cfg = deepcopy(value)
    table(cfg, ("app", "onebot", "qq_official", "reply_images", "features", "replies", "servers"), "配置")
    if "reply_images" in cfg:
        cfg["reply_images"] = validate_reply_images(cfg["reply_images"])
    try:
        app, ob = cfg["app"], cfg["onebot"]
        table(app, ("host", "port", "database", "admin_token"), "主程序设置")
        table(ob, ("token", "self_id", "admins"), "QQ 设置")
        if not re.fullmatch(r"[a-zA-Z0-9_.:\-]+", string(app["host"], "监听地址")):
            raise ValueError("监听地址应为 IP 或主机名，不包含协议、空格或路径")
        if type(app["port"]) is not int or not 1 <= app["port"] <= 65535:
            raise ValueError("端口必须是 1–65535 之间的整数")
        string(app["database"], "数据库路径", 1000)
        if app["database"] == ":memory:" or any(c in app["database"] for c in "\r\n"):
            raise ValueError("请输入有效的持久化数据库文件路径")
        tokens = [app["admin_token"], ob["token"]]
        if "qq_official" in cfg:
            official = cfg["qq_official"]
            table(official, OFFICIAL_DEFAULTS, "QQ 官机设置")
            official = cfg["qq_official"] = {**deepcopy(OFFICIAL_DEFAULTS), **official}
            if type(official["enabled"]) is not bool or type(official["allow_active"]) is not bool:
                raise ValueError("官机接入与主动消息开关必须是布尔值")
            app_id, secret = official["app_id"], official["client_secret"]
            if not isinstance(app_id, str) or (app_id and not re.fullmatch(r"[1-9][0-9]{0,19}", app_id)):
                raise ValueError("官机 AppID 必须为数字字符串")
            if not isinstance(secret, str) or (secret and not re.fullmatch(r"[!-~]{8,256}", secret)):
                raise ValueError("官机 AppSecret 必须为 8–256 位非空格 ASCII 字符")
            if official["enabled"] and (not app_id or not secret or secret.startswith("CHANGE-ME")):
                raise ValueError("启用 QQ 官机前请填写 AppID 和 AppSecret")
            admins = official["admins"]
            if (not isinstance(admins, list) or len(admins) > 1000 or any(not official_parts(v, ("qug", "qup")) or official_parts(v, ("qug", "qup"))[1] != app_id for v in admins)
                    or len(set(admins)) != len(admins)):
                raise ValueError("官机管理员必须为本 AppID 接入信息中的 qug / qup 身份，不能填写普通 QQ 号")
        ob.setdefault("admins", [])
        ob.setdefault("self_id", "")
        ids(ob["admins"], "管理员 QQ")
        if ob["self_id"] != "":
            ids([ob["self_id"]], "机器人 QQ")
        features = cfg.setdefault("features", {})
        table(features, FEATURES, "功能开关")
        for key in FEATURES:
            features.setdefault(key, key in FEATURES[:3])
            if type(features[key]) is not bool:
                raise ValueError(f"功能开关 {key} 必须为布尔值")
        replies = cfg.setdefault("replies", {})
        if not isinstance(replies, dict) or len(replies) > 200:
            raise ValueError("关键词回复必须是字典，最多 200 项")
        for key, reply in replies.items():
            string(key, "回复关键词", 80)
            string(reply, "回复内容", 3500)
        servers = cfg["servers"]
        if not isinstance(servers, list) or len(servers) > 100:
            raise ValueError("服务器列表格式错误或超过 100 台限制")
        groups, server_ids = set(), set()
        for server in servers:
            table(server, ("id", "name", "token", "groups", "commands"), "服务器设置")
            sid = server["id"]
            if not isinstance(sid, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", sid) or sid in server_ids:
                raise ValueError("服务器 id 必须唯一，且只能使用字母、数字、下划线、短横线")
            server_ids.add(sid)
            string(server["name"], "服务器名称", 80)
            tokens.append(server["token"])
            ids(server["groups"], f"{sid} 群号", official=True)
            if groups.intersection(server["groups"]):
                raise ValueError("每个群只能关联一台服务器，群号不能重复")
            groups.update(server["groups"])
            commands = server.setdefault("commands", {})
            if not isinstance(commands, dict) or len(commands) > 100:
                raise ValueError("预设命令最多 100 项")
            for name, command in commands.items():
                string(name, "命令名称", 80)
                string(command, "控制台命令", 500)
                if any(c in command for c in "\r\n") or name != name.strip():
                    raise ValueError("控制台命令必须是单行，命令名称两端不能有空格")
        if any(not isinstance(t, str) or not re.fullmatch(r"[!-~]{24,256}", t) or t.startswith("CHANGE-ME") for t in tokens):
            raise ValueError("所有令牌必须为 24–256 位非空格 ASCII 字符，请点击生成随机令牌")
        if len(set(tokens)) != len(tokens):
            raise ValueError("管理、OneBot 和各服务器必须使用不同令牌")
        if cfg.get("qq_official", {}).get("client_secret") in tokens:
            raise ValueError("官机 AppSecret 必须独立于管理、OneBot 和游戏令牌")
    except KeyError as exc:
        raise ValueError(f"缺少必填配置项：{exc.args[0]}") from None
    return cfg


def runtime_config(cfg, path):
    result = deepcopy(cfg)
    result["app"]["database"] = str((Path(path).resolve().parent / cfg["app"]["database"]).resolve())
    if cfg.get("qq_official", {}).get("enabled"):
        result["onebot"]["admins"] = list(cfg["qq_official"]["admins"])
    return result


def serialize(cfg):
    def literal(v):
        return str(v).lower() if isinstance(v, bool) else json.dumps(v, ensure_ascii=False)
    lines = ["# 由Myrinbot管理面板保存；修改前一版位于同目录 .bak 文件。"]
    if not cfg["servers"]:
        lines.append("servers = []")
    for section in ("app", "onebot", "qq_official", "reply_images", "features", "replies"):
        if section not in cfg:
            continue
        lines.extend(["", f"[{section}]"])
        lines.extend(f"{literal(k)} = {literal(v)}" for k, v in cfg[section].items())
    for server in cfg["servers"]:
        lines.extend(["", "[[servers]]"])
        lines.extend(f"{literal(k)} = {literal(server[k])}" for k in ("id", "name", "token", "groups"))
        lines.append("[servers.commands]")
        lines.extend(f"{literal(k)} = {literal(v)}" for k, v in server["commands"].items())
    return "\n".join(lines) + "\n"


class ConfigFile:
    def __init__(self, path):
        self.path = Path(path).resolve()

    def read(self):
        raw = self.path.read_bytes()
        return validate(tomllib.loads(raw.decode("utf-8"))), hashlib.sha256(raw).hexdigest()

    def save(self, cfg, revision):
        previous = self.path.read_bytes()
        if revision != hashlib.sha256(previous).hexdigest():
            raise ConfigConflict("配置已被其他页面或程序修改，请重新载入后再保存。")
        cfg = validate(cfg)
        data = serialize(cfg).encode("utf-8")
        validate(tomllib.loads(data.decode("utf-8")))
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix=".starbridge-", suffix=".tmp", delete=False) as f:
                temporary = f.name
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            self.path.with_suffix(self.path.suffix + ".bak").write_bytes(previous)
            os.replace(temporary, self.path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
        return cfg, hashlib.sha256(data).hexdigest()
