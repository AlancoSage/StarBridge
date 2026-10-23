"""Trusted, bundled declarative plugins; no remote downloads or executable code."""
from copy import deepcopy
import hashlib
import re

from aiohttp import web

from .extensions import PluginConflict, encode, read_plugin, validate_plugin


CATEGORIES = (
    {"id": "community", "name": "社区管理"},
    {"id": "server", "name": "服务器工具"},
    {"id": "player", "name": "玩家服务"},
)


def text_setting(label, default, description=""):
    return {"type": "string", "label": label, "default": default,
            "description": description, "max_length": 2000}


def package(plugin_id, name, description, settings, rules, category, tags, capabilities, readme):
    return {
        "definition": {"api_version": 1, "id": plugin_id, "name": name, "version": "1.0.0",
                       "author": "VexBot", "description": description, "settings": settings,
                       "rules": rules, "changelog": "首次发布，支持在已安装插件中配置、授权和启用。"},
        "category": category, "tags": tags, "capabilities": capabilities, "readme": readme,
        # Future catalog upgrades retain exact prior definitions here. Unknown local
        # versions are never treated as an official update, even if numerically older.
        "previous_definitions": (),
    }


CATALOG = (
    package("community_rules", "群规公告", "通过群指令查看服主维护的社区规则，统一入群须知。",
            {"title": text_setting("公告标题", "社区规则"),
             "content": text_setting("群规内容", "请文明交流，不刷屏、不作弊；遇到问题请联系管理员。")},
            [{"event": "group_command", "command": "群规", "reply": "{settings.title}\n{settings.content}"}],
            "community", ["群规", "公告"], ["接收群指令", "向关联群发送消息"],
            "安装后在已安装插件中填写公告标题和群规内容，再启用插件。在关联群发送“群规”查看。"
            "仅回复文字，不修改群公告，也不自动禁言或踢人。"),
    package("server_address", "服务器地址卡", "向群成员提供可配置的 Java、基岩版连接地址与入服说明。",
            {"java_address": text_setting("Java 版地址", "请联系服主获取 Java 版地址"),
             "bedrock_address": text_setting("基岩版地址", "暂未开放基岩版入口"),
             "note": text_setting("入服说明", "请使用服主指定的游戏版本入服。")},
            [{"event": "group_command", "command": "服务器地址",
              "reply": "{server_name}\nJava：{settings.java_address}\n基岩：{settings.bedrock_address}\n{settings.note}"}],
            "server", ["连接地址", "入服"], ["接收群指令", "向关联群发送消息"],
            "在已安装插件中填写服务器入口和入服说明，然后启用。在关联群发送“服务器地址”。"
            "同一插件实例共用这些地址；多服入口可填写在说明中。这不会自动修改游戏服务器配置。"),
    package("online_digest", "在线快照摘要", "用简洁文字展示关联服务器最近一次上报的在线快照。",
            {"footer": text_setting("摘要附言", "桥接离线时，人数与名单可能是上次上报的快照。")},
            [{"event": "group_command", "command": "在线摘要",
              "reply": "{server_name} · 桥接{online}\n最近快照：{online_count} 人\n{players}\n{settings.footer}"}],
            "server", ["在线玩家", "快照"], ["接收群指令", "向关联群发送消息", "读取服务器在线状态"],
            "启用后在关联群发送“在线摘要”。需要游戏桥接上报状态，并在插件权限中允许读取服务器信息。"
            "桥接离线时显示最近快照，不代表实时在线人数；不会主动探测或连接游戏端口。"),
    package("binding_card", "个人绑定名片", "让成员查询自己在当前关联服务器上的游戏绑定名称。",
            {"note": text_setting("查询附言", "未绑定时，请在游戏中输入 /qbind 并按提示完成绑定。")},
            [{"event": "group_command", "command": "身份名片",
              "reply": "{server_name}\n你的游戏身份：{player}\n{settings.note}"}],
            "player", ["个人绑定", "账号"], ["接收群指令", "向关联群发送消息", "读取发起者的游戏绑定"],
            "启用后在关联群发送“身份名片”。需要在插件权限中允许读取绑定信息。"
            "只查询指令发起者在当前服务器的绑定，不显示其他成员、邮箱、IP 或密码，也不执行解绑。"),
    package("join_quit_notice", "入退服问候", "为玩家入服和退服配置问候前后缀，发送到关联群聊。",
            {"join_enabled": {"type": "boolean", "label": "发送入服问候", "default": True},
             "quit_enabled": {"type": "boolean", "label": "发送退服问候", "default": True},
             "join_prefix": text_setting("入服问候前缀", "欢迎"),
             "join_suffix": text_setting("入服问候附言", "祝你游戏愉快！"),
             "quit_prefix": text_setting("退服问候前缀", "再见"),
             "quit_suffix": text_setting("退服问候附言", "期待下次相遇。")},
            [{"event": "player_join", "reply": "{settings.join_prefix} {player} 来到 {server_name}。\n{settings.join_suffix}", "when": "join_enabled"},
             {"event": "player_quit", "reply": "{settings.quit_prefix} {player} 离开 {server_name}。\n{settings.quit_suffix}", "when": "quit_enabled"},
             {"event": "group_command", "command": "通知说明", "reply": "入退服问候由游戏桥接事件触发；服主可在已安装插件中调整文案与开关。"}],
            "community", ["玩家入服", "玩家退服", "问候"], ["接收游戏入退服事件", "向关联群发送消息", "接收群指令"],
            "安装后调整入服、退服问候的前后缀和开关，再启用；可发送“通知说明”查看用法。"
            "依赖游戏桥接事件。VexBot 自带入退服转发如果同时开启，会分别发送消息，可按需关闭原有转发。"
            "设置文本原样显示，玩家名和服务器名由规则安全填充；设置内的花括号不会二次展开。"),
    package("community_faq", "常见问题手册", "为新成员提供服主编写的常见问题和求助入口。",
            {"content": text_setting("常见问题", "如何入服：发送“服务器地址”或联系服主。\n如何绑定：在游戏中输入 /qbind 后按提示操作。"),
             "contact": text_setting("求助入口", "其他问题请在群内联系管理员。")},
            [{"event": "group_command", "command": "常见问题", "reply": "{settings.content}\n{settings.contact}"}],
            "player", ["新手指南", "帮助"], ["接收群指令", "向关联群发送消息"],
            "编辑常见问题及求助入口后启用。在关联群发送“常见问题”获取完整手册。"
            "不会收集建议、创建工单或自动提交反馈；请填写实际可用的求助渠道。"),
)


def digest(definition):
    """SHA-256 of the validated, canonical JSON package, independent of formatting."""
    return hashlib.sha256(encode(validate_plugin(deepcopy(definition)))).hexdigest()


def catalog():
    entries = []
    for source in CATALOG:
        item = deepcopy(source)
        item["definition"] = validate_plugin(item["definition"])
        item["sha256"] = digest(item["definition"])
        # Validate trusted history too; malformed history must not authorize updates.
        item["previous_definitions"] = tuple(validate_plugin(old) for old in item["previous_definitions"])
        entries.append(item)
    return entries


def release_version(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9][0-9]{0,8})\.(?:0|[1-9][0-9]{0,8})\.(?:0|[1-9][0-9]{0,8})", value):
        return None
    return tuple(map(int, value.split(".")))


def installed_state(manager, item):
    definition = item["definition"]
    plugin_id = definition["id"]
    entry = manager.entries.get(plugin_id)
    path = manager.root / (plugin_id + ".json")
    if entry is None and not path.exists() and not path.is_symlink():
        return "available", None
    if entry and entry["status"] == "error":
        return "error", entry["definition"].get("version")
    try:
        actual = read_plugin(path)
    except (OSError, ValueError, TypeError, OverflowError):
        return "error", entry["definition"].get("version") if entry else None
    version = actual["version"]
    # A local edit not yet reloaded must also be protected from market operations.
    if entry is None or encode(actual) != encode(entry["definition"]):
        return "custom", version
    actual_digest = digest(actual)
    if actual_digest == item["sha256"]:
        return "installed", version
    previous = release_version(version)
    latest = release_version(definition["version"])
    trusted_history = any(old["id"] == plugin_id and digest(old) == actual_digest for old in item["previous_definitions"])
    if trusted_history and previous is not None and latest is not None and latest > previous:
        return "update", version
    return "custom", version


def listing(manager, items=None):
    items = catalog() if items is None else items
    revision = hashlib.sha256(encode(items)).hexdigest()
    plugins = []
    for item in items:
        definition = item["definition"]
        status, version = installed_state(manager, item)
        plugins.append({
            **{key: definition.get(key, "") for key in ("id", "name", "version", "author", "description", "changelog")},
            **{key: item[key] for key in ("category", "tags", "capabilities", "readme", "sha256")},
            "commands": [rule["command"] for rule in definition["rules"] if rule["event"] == "group_command"],
            "settings_count": len(definition["settings"]), "installed_version": version,
            "status": status,
        })
    return {"revision": manager.revision, "catalog_revision": revision,
            "error": manager.state_error, "categories": deepcopy(CATEGORIES), "plugins": plugins}


def setup_routes(app, state_key, authorized, body):
    async def endpoint(request):
        state = request.app[state_key]
        headers = {"Cache-Control": "no-store"}
        try:
            authorized(request, state["config"]["app"]["admin_token"])
            manager = state["plugins"]
            if request.method == "GET":
                return web.json_response(listing(manager), headers=headers)
            data = await body(request)
            if (not isinstance(data, dict) or set(data) != {"revision", "catalog_revision", "sha256"}
                    or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in data.values())):
                raise ValueError("请提供最新的插件版本、市场目录版本和完整校验值；请求不能包含其他字段")
            # Check the loaded revision and on-disk definition while holding the same
            # manager lock used by install/upgrade. Releasing and directly awaiting the
            # manager method has no scheduling point while this lock is uncontended.
            async with manager.lock:
                manager.check_revision(data["revision"])
                items = catalog()
                current = listing(manager, items)
                item = next((row for row in items if row["definition"]["id"] == request.match_info["plugin_id"]), None)
                if item is None:
                    raise LookupError("市场中没有这个插件")
                if data["catalog_revision"] != current["catalog_revision"] or data["sha256"] != item["sha256"]:
                    raise PluginConflict("插件目录或校验值已变化，请重新载入后操作")
                status, _ = installed_state(manager, item)
                action = request.match_info["action"]
                expected = "available" if action == "install" else "update"
                if status != expected:
                    raise PluginConflict("插件状态已变化或包含本地修改，无法执行此操作；请重新载入并在已安装插件中检查")
                definition = deepcopy(item["definition"])
            if action == "install":
                await manager.install(definition, data["revision"])
            else:
                await manager.upgrade(definition, data["revision"])
            return web.json_response(listing(manager), headers=headers)
        except web.HTTPException as exc:
            return web.json_response({"error": exc.text}, status=exc.status, headers=headers)
        except PluginConflict as exc:
            return web.json_response({"error": str(exc)}, status=409, headers=headers)
        except LookupError as exc:
            return web.json_response({"error": str(exc)}, status=404, headers=headers)
        except (ValueError, TypeError, OverflowError) as exc:
            return web.json_response({"error": str(exc)}, status=400, headers=headers)
        except OSError:
            return web.json_response({"error": "插件文件写入失败，请检查目录权限和磁盘空间。"}, status=500, headers=headers)

    app.add_routes([
        web.get("/api/extension-market", endpoint),
        web.post("/api/extension-market/{plugin_id}/{action:install|upgrade}", endpoint),
    ])
