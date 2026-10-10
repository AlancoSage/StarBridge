import asyncio
from copy import deepcopy
from contextlib import suppress
from pathlib import Path
import re
import secrets
import time
from tempfile import TemporaryDirectory
import uuid

from aiohttp import web

from .bot import Bot, clean_text
from .onebot import OneBot
from .storage import Store
from .settings import ConfigConflict, ConfigFile, runtime_config
from .players import PLAYER_ACTIONS, management_state, player_records
from .catalog import Catalog, address, annotations, profile_fields
from .extensions import PluginConflict, PluginManager
from .registration import Registration
from .registration_api import setup_routes as registration_routes
from .authentication import Authentication
from .authentication_api import setup_routes as authentication_routes
from .backup_api import setup_routes as backup_routes
from .operations_api import setup_routes as operations_routes
from .website_api import setup_routes as website_routes
from .admin_accounts import setup_routes as admin_routes, ADMIN_IDENTITY
from .runtime_features import RuntimeFeatures
from .enhancement_api import setup_routes as enhancement_routes
from .community_api import setup_routes as community_routes
from .deployment_api import setup_routes as deployment_routes
from .update_api import setup_routes as update_routes


STATE = web.AppKey("state", dict)


def authorized(request, token):
    if request.get(ADMIN_IDENTITY) and not request[ADMIN_IDENTITY]["owner"] and token == request.app[STATE]["config"]["app"]["admin_token"]:
        return
    supplied = request.headers.get("Authorization", "").encode()
    if not secrets.compare_digest(supplied, ("Bearer " + token).encode()):
        raise web.HTTPUnauthorized(text="令牌错误")


async def body(request):
    try:
        data = await request.json()
    except (ValueError, UnicodeError):
        raise web.HTTPBadRequest(text="请求必须是 JSON")
    if not isinstance(data, dict):
        raise web.HTTPBadRequest(text="请求必须是 JSON 对象")
    return data


def bridge(request):
    state = request.app[STATE]
    server = state["bot"].servers.get(request.match_info["sid"])
    if server is None:
        raise web.HTTPNotFound()
    authorized(request, server["token"])
    return state, server


async def bind_code(request):
    state, server = bridge(request)
    data = await body(request)
    try:
        player_uuid = str(uuid.UUID(data["uuid"]))
        name = data["player"]
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,16}", name):
            raise ValueError()
    except (KeyError, ValueError, TypeError, AttributeError):
        raise web.HTTPBadRequest(text="需要合法的玩家 UUID 和 Java 版玩家名")
    if not state["bot"].allow(("issue", server["id"], player_uuid), count=3, period=60):
        raise web.HTTPTooManyRequests(text="请稍后再获取验证码")
    if not state["authentication"].allowed(server["id"], player_uuid, data.get("nonce"), name):
        raise web.HTTPForbidden(text="请先完成游戏登录，再获取 QQ 绑定码")
    code = state["store"].issue_code(server["id"], player_uuid, name)
    return web.json_response({"code": code, "expires_in": 300})


async def tick(request):
    state, server = bridge(request)
    data = await body(request)
    players = data.get("players", [])
    events = data.get("events", [])
    results = data.get("results", [])
    maximum = data.get("max_players", 0)
    try:
        auth_results = state["authentication"].heartbeat(server, data.get("auth_sessions", []))
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc)) from None
    if (not isinstance(players, list) or len(players) > 2000 or not all(isinstance(p, str) for p in players)
        or type(maximum) is not int or not 0 <= maximum <= 100000
        or not isinstance(events, list) or len(events) > 50
        or not isinstance(results, list) or len(results) > 50):
        raise web.HTTPBadRequest(text="桥接数据格式错误或超过大小限制")
    for event in events:
        if (not isinstance(event, dict) or event.get("kind") not in ("chat", "join", "quit")
            or not isinstance(event.get("id"), str) or not 1 <= len(event["id"]) <= 80
            or not isinstance(event.get("player"), str) or not isinstance(event.get("text", ""), str)):
            raise web.HTTPBadRequest(text="事件格式错误")
        if "uuid" in event:
            try:
                event["uuid"] = str(uuid.UUID(event["uuid"]))
                if not re.fullmatch(r"[A-Za-z0-9_]{1,16}", event["player"]):
                    raise ValueError()
                if "ip" in event:
                    event["ip"] = address(event["ip"])
            except (ValueError, TypeError, AttributeError):
                raise web.HTTPBadRequest(text="事件中的玩家身份或地址格式错误")
    for result in results:
        if (not isinstance(result, dict) or not isinstance(result.get("id"), str)
            or type(result.get("ok")) is not bool or not isinstance(result.get("detail", ""), str)):
            raise web.HTTPBadRequest(text="执行结果格式错误")
    try:
        records = player_records(data)
    except (ValueError, TypeError, AttributeError):
        raise web.HTTPBadRequest(text="玩家记录格式错误")
    capabilities = data.get("capabilities", [])
    if (not isinstance(capabilities, list) or len(capabilities) > 10
        or not all(isinstance(value, str) and len(value) <= 40 for value in capabilities)
        or type(data.get("players_truncated", False)) is not bool
        or ("whitelist_enabled" in data and type(data["whitelist_enabled"]) is not bool)):
        raise web.HTTPBadRequest(text="插件能力格式错误")
    queue = state["game_events"]
    if queue.qsize() + len(events) + len(results) > queue.maxsize:
        raise web.HTTPServiceUnavailable(text="事件队列繁忙，请稍后重试")
    sid = server["id"]
    state["bot"].snapshots[sid] = {
        "last_seen": time.time(), "players": [clean_text(p, 32) for p in players],
        "max_players": maximum, "version": clean_text(data.get("version", "未知"), 80),
        "player_records": records, "capabilities": capabilities,
        "players_truncated": data.get("players_truncated", False),
        "whitelist_enabled": data.get("whitelist_enabled"),
        "java_version": clean_text(data.get("java_version", "未上报"), 80),
        "server_software": clean_text(data.get("server_software", "未上报"), 80),
    }
    fresh_events = [event for event in events if not state["store"].seen(f"mc:{sid}:{event['id']}")]
    state["catalog"].observe(server, records, [event for event in fresh_events if event["kind"] == "join" and "uuid" in event])
    for event in fresh_events:
        state["runtime"].event(sid, event)
        queue.put_nowait((server, event))
    for result in results:
        job = state["store"].job(sid, result["id"])
        if job:
            if state["operations"].complete(sid, result["id"], job, result):
                if job.get("kind") == "whitelist_application":
                    row = state["operations"].application(job["application_id"])
                    queue.put_nowait((server, {"kind":"whitelist_result", "application":row}))
            elif job.get("kind") == "command":
                queue.put_nowait((server, {**result, "kind": "result", "group": job["reply_group"]}))
            elif job.get("kind") == "player_action":
                detail = clean_text(result.get("detail", ""), 1500)
                if state["store"].complete_player_action(sid, result["id"], result["ok"], detail):
                    label = "完成" if result["ok"] else "失败"
                    state["store"].audit("player", f"{sid} {job['player']} {job['action']} {label}：{detail}")
            state["store"].ack(sid, [result["id"]])
    state["sanctions"].observe(sid, records)
    return web.json_response({"jobs": state["store"].poll(sid),
                              "authentication": state["authentication"].policy(sid), "authentication_results": auth_results,
                              "allowed_commands": list(server.get("commands", {}).values())})


async def game_worker(state):
    while True:
        server, event = await state["game_events"].get()
        try:
            server = state["bot"].servers.get(server["id"])
            if server is None or (event["kind"] == "result" and event["group"] not in server["groups"]):
                continue
            if event["kind"] == "whitelist_result":
                await state["operations"].notify(event["application"])
            elif event["kind"] == "result":
                label = "已执行" if event["ok"] else "执行失败"
                detail = clean_text(event.get("detail", ""), 1500)
                state["store"].audit("command", f"{server['id']} {label}: {detail}")
                await state["onebot"].send_group(event["group"], f"[{server['name']}] {label}\n{detail}")
            else:
                await state["bot"].relay_game(server, event)
        except Exception as exc:
            state["store"].audit("error", f"游戏事件处理失败：{type(exc).__name__}: {exc}")
        finally:
            state["game_events"].task_done()


async def dashboard(request):
    return web.FileResponse(Path(__file__).parent / "panel.html", headers={"Cache-Control": "no-cache"})


async def dashboard_script(request):
    return web.FileResponse(Path(__file__).parent / "dashboard.js", headers={"Cache-Control": "no-cache"})


async def mod_bridge_script(request):
    return web.FileResponse(Path(__file__).parent / "mod-bridge-panel.js", headers={"Cache-Control": "no-cache"})


async def dashboard_style(request):
    return web.FileResponse(Path(__file__).parent / "panel.css", headers={"Cache-Control": "no-cache"})


async def extension_script(request):
    return web.FileResponse(Path(__file__).parent / "extension-panel.js", headers={"Cache-Control": "no-cache"})


def restart_fields(state, saved):
    resolved = runtime_config(saved, state["config_file"].path)
    return [key for key in ("host", "port", "database")
            if resolved["app"][key] != state["config"]["app"].get(key)]


def settings_response(state, cfg, revision):
    return {"config": cfg, "revision": revision, "restart_required": restart_fields(state, cfg),
            "can_restart": state["restart_event"] is not None,
            "restart_error": state.get("restart_error", "")}


async def admin_config(request):
    state = request.app[STATE]
    authorized(request, state["config"]["app"]["admin_token"])
    if state["config_file"] is None:
        raise web.HTTPServiceUnavailable(text="当前实例没有配置文件")
    try:
        cfg, revision = state["config_file"].read()
        return web.json_response(settings_response(state, cfg, revision), headers={"Cache-Control": "no-store"})
    except (ValueError, OSError) as exc:
        return web.json_response({"error": f"配置读取失败：{exc}"}, status=400)


async def save_config(request):
    state = request.app[STATE]
    authorized(request, state["config"]["app"]["admin_token"])
    payload = await body(request)
    return await commit_config(state, payload, lambda: authorized(request, state["config"]["app"]["admin_token"]))


async def commit_config(state, payload, recheck=lambda: None):
    async with state["settings_lock"]:
        recheck()
        if state["config_file"] is None:
            raise web.HTTPServiceUnavailable(text="当前实例没有配置文件")
        try:
            candidate = payload.get("config")
            stored, stored_revision = state["config_file"].read()
            if payload.get("revision") != stored_revision:
                raise ConfigConflict("配置已变化，请重新载入后再操作")
            if isinstance(candidate, dict) and candidate.get("replies", {}) != stored.get("replies", {}):
                raise ValueError("关键词回复已移至插件，请在「扩展 → 关键词回复 → 管理回复」中修改")
            api_token = state["registration"].settings["api_token"]
            if api_token and isinstance(candidate, dict):
                values = []
                for section, key in (("app", "admin_token"), ("onebot", "token")):
                    if isinstance(candidate.get(section), dict):
                        values.append(candidate[section].get(key))
                if isinstance(candidate.get("servers"), list):
                    values.extend(server.get("token") for server in candidate["servers"] if isinstance(server, dict))
                if api_token in values:
                    raise ValueError("管理、QQ 和游戏令牌必须独立于网站 API 密钥")
            cfg, revision = state["config_file"].save(payload.get("config"), payload.get("revision"))
        except ConfigConflict as exc:
            return web.json_response({"error": str(exc)}, status=409)
        except (ValueError, TypeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except OSError:
            return web.json_response({"error": "配置写入失败，请检查文件权限和磁盘空间；运行配置未更改。"}, status=500)
        current = state["config"]
        updated = runtime_config(cfg, state["config_file"].path)
        for key in ("host", "port", "database"):
            updated["app"][key] = current["app"][key]
        ob_changed = any(current["onebot"].get(k) != updated["onebot"].get(k) for k in ("token", "self_id"))
        servers = {s["id"]: s for s in updated["servers"]}
        # Revoke queued actions if their routing or authority changed.
        for sid, old in state["bot"].servers.items():
            new = servers.get(sid)
            if new is None or any(old.get(k) != new.get(k) for k in ("token", "groups", "commands")):
                state["store"].cancel_player_actions(sid)
                with state["store"].db:
                    state["store"].db.execute("DELETE FROM jobs WHERE server=?", (sid,))
                if new is None or old["token"] != new["token"]:
                    state["bot"].snapshots.pop(sid, None)
                    with state["store"].db:
                        state["store"].db.execute("DELETE FROM codes WHERE server=?", (sid,))
        if not updated["features"]["qq_to_mc"]:
            with state["store"].db:
                state["store"].db.execute("DELETE FROM jobs WHERE json_extract(payload,'$.kind')='broadcast'")
        state["config"] = updated
        state["bot"].cfg = updated
        state["bot"].servers = servers
        state["bot"].groups = {g: s for s in updated["servers"] for g in s["groups"]}
        state["onebot"].cfg = updated["onebot"]
        state["restart_error"] = ""
        if ob_changed and state["onebot"].connected:
            await state["onebot"].ws.close(code=1000, message=b"Configuration updated")
        state["store"].audit("settings", "管理员已通过面板保存配置")
        result = settings_response(state, cfg, revision)
        result["onebot_reconnect"] = ob_changed
        return web.json_response(result, headers={"Cache-Control": "no-store"})


async def restart_service(request):
    state = request.app[STATE]
    authorized(request, state["config"]["app"]["admin_token"])
    if state["restart_event"] is None:
        raise web.HTTPServiceUnavailable(text="此启动方式不支持面板重启")
    asyncio.get_running_loop().call_later(0.5, state["restart_event"].set)
    return web.json_response({"ok": True}, headers={"Cache-Control": "no-store"})


async def health(request):
    return web.json_response({"status": "ok", "service": "starbridge"})


async def player_action(request):
    state = request.app[STATE]
    authorized(request, state["config"]["app"]["admin_token"])
    data = await body(request)
    try:
        jid, identity = str(uuid.UUID(data["request_id"])), str(uuid.UUID(data["uuid"]))
        sid, name, action, reason = data["server"], data["player"], data["action"], data.get("reason", "")
        if (not isinstance(sid, str) or not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,16}", name)
            or not isinstance(action, str) or action not in PLAYER_ACTIONS
            or not isinstance(reason, str) or len(reason) > 120 or any(ord(c) < 32 or ord(c) == 127 for c in reason)):
            raise ValueError()
    except (KeyError, ValueError, TypeError, AttributeError):
        return web.json_response({"error": "玩家操作参数错误：需要合法 UUID、玩家名、操作类型和不超过 120 字的单行原因。"}, status=400)
    previous = state["store"].player_action(jid)
    if previous:
        if any(previous[k] != v for k, v in {"server": sid, "uuid": identity, "player": name, "action": action, "reason": reason}.items()):
            return web.json_response({"error": "请求编号已用于其他玩家操作。"}, status=409)
        return web.json_response(previous, headers={"Cache-Control": "no-store"})
    bot = state["bot"]
    if sid not in bot.servers:
        raise web.HTTPNotFound(text="服务器不存在")
    if not bot.online(sid):
        return web.json_response({"error": "游戏服务器未连接，无法提交玩家操作。"}, status=409)
    snap = bot.snapshots[sid]
    if "player_management" not in snap.get("capabilities", []):
        return web.json_response({"error": "请安装新版星桥插件以启用玩家管理。"}, status=409)
    target = next((p for p in snap.get("player_records", []) if p["uuid"] == identity and p["name"] == name), None)
    if target is None or (action == "kick" and not target["online"]):
        return web.json_response({"error": "玩家状态已变化，请刷新列表后重试。"}, status=409)
    try:
        result = state["store"].create_player_action(jid, sid, identity, name, action, reason)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=409)
    state["store"].audit("player", f"面板提交 {sid} {name} {action}，等待游戏插件确认")
    return web.json_response(result, status=202, headers={"Cache-Control": "no-store"})


async def plugin_download(request):
    authorized(request, request.app[STATE]["config"]["app"]["admin_token"])
    from . import __bridge_version__
    kind = request.query.get("platform", "bukkit")
    if kind not in ("bukkit", "forge", "neoforge", "fabric"):
        raise web.HTTPBadRequest(text="不支持的游戏端类型")
    if kind == "bukkit":
        if request.query.get("version"):
            raise web.HTTPBadRequest(text="Paper / Spigot / Folia 插件无需按游戏版本下载")
        filename = f"StarBridge-{__bridge_version__}.jar"
    else:
        from .game_bridges import bridge_filename
        try:
            filename = bridge_filename(kind, request.query.get("version", "1.21.1" if kind == "neoforge" else "1.20.1"))
        except ValueError as error:
            raise web.HTTPBadRequest(text=str(error))
    path = Path(__file__).resolve().parent.parent / "bridge" / "target" / filename
    if not path.is_file():
        raise web.HTTPNotFound(text="插件尚未构建")
    return web.FileResponse(path, headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})


async def game_bridge_catalog(request):
    authorized(request, request.app[STATE]["config"]["app"]["admin_token"])
    from .game_bridges import bridge_catalog
    rows = bridge_catalog()
    directory = Path(__file__).resolve().parent.parent / "bridge" / "target"
    for row in rows:
        row["available"] = (directory / row["filename"]).is_file()
    return web.json_response({"bridges": rows}, headers={"Cache-Control": "no-store"})


async def extension_api(request):
    state = request.app[STATE]
    authorized(request, state["config"]["app"]["admin_token"])
    manager = state["plugins"]
    if request.method == "GET":
        try:
            result = manager.versions(request.match_info["plugin_id"]) if request.match_info.get("action") == "versions" else manager.listing()
            return web.json_response(result, headers={"Cache-Control": "no-store"})
        except LookupError as exc: return web.json_response({"error":str(exc)},status=404)
    data = await body(request)
    try:
        action = request.match_info.get("action", "")
        plugin_id = request.match_info.get("plugin_id", "")
        if request.method == "PUT":
            result = await manager.update(plugin_id, data)
        elif request.method == "DELETE":
            result = await manager.remove(plugin_id, data.get("revision"))
        elif action == "install":
            result = await manager.install(data.get("plugin"), data.get("revision"))
        elif action == "scan":
            result = await manager.scan(data.get("revision"))
        elif action == "upgrade":
            result = await manager.upgrade(data.get("plugin"), data.get("revision"))
        elif action == "rollback":
            result = await manager.upgrade(plugin_id, data.get("revision"), data.get("version_id"))
        else:
            result = await manager.reload(plugin_id, data.get("revision"))
    except PluginConflict as exc:
        return web.json_response({"error": str(exc)}, status=409)
    except LookupError as exc:
        return web.json_response({"error": str(exc)}, status=404)
    except (ValueError, TypeError, OverflowError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except OSError:
        return web.json_response({"error": "插件文件写入失败，请检查目录权限和磁盘空间。"}, status=500)
    return web.json_response(result, headers={"Cache-Control": "no-store"})


async def extension_document(request):
    authorized(request, request.app[STATE]["config"]["app"]["admin_token"])
    base = Path(__file__).resolve().parent.parent
    example = request.match_info["document"] == "example"
    path = base / ("examples/community_helper.json" if example else "docs/plugin-development.md")
    filename = "community_helper.json" if example else "StarBridge-plugin-development.md"
    return web.FileResponse(path, headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})


async def profile_list(request):
    state = request.app[STATE]
    authorized(request, state["config"]["app"]["admin_token"])
    filters = {key: request.query.get(key, "") for key in ("name", "uuid", "ip", "region", "binding", "server", "status")}
    try:
        page, size = int(request.query.get("page", 1)), int(request.query.get("page_size", 25))
        if (page < 1 or size not in (10, 25, 50, 100) or any(len(v) > 120 for v in filters.values())
            or filters["binding"] not in ("", "bound", "unbound")
            or filters["status"] not in ("", "online", "offline", "unknown", "banned", "whitelisted")):
            raise ValueError()
    except (TypeError, ValueError):
        return web.json_response({"error": "分页或筛选参数错误"}, status=400)
    return web.json_response(state["catalog"].list(state, filters, page, size), headers={"Cache-Control": "no-store"})


async def profile_detail(request):
    state = request.app[STATE]
    authorized(request, state["config"]["app"]["admin_token"])
    try:
        result = state["catalog"].get(int(request.match_info["pid"]), state)
    except (LookupError, ValueError):
        raise web.HTTPNotFound(text="玩家档案不存在")
    return web.json_response(result, headers={"Cache-Control": "no-store"})


async def profile_create(request):
    state = request.app[STATE]
    authorized(request, state["config"]["app"]["admin_token"])
    data = await body(request)
    try:
        fields = profile_fields(data)
    except (ValueError, TypeError, AttributeError) as exc:
        return web.json_response({"error": str(exc) or "档案字段格式错误"}, status=400)
    try:
        pid = state["catalog"].create(fields)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=409)
    state["store"].audit("player", f"面板新增玩家档案 {pid} {fields['name']}")
    return web.json_response(state["catalog"].get(pid, state), status=201, headers={"Cache-Control": "no-store"})


async def profile_update(request):
    state = request.app[STATE]
    authorized(request, state["config"]["app"]["admin_token"])
    data = await body(request)
    try:
        pid = int(request.match_info["pid"])
        current = state["catalog"].get(pid, state)
        fields = annotations({**current, **data})
        revision = data.get("revision")
        if type(revision) is not int or revision < 1:
            raise ValueError("需要最新的档案版本")
        state["catalog"].update(pid, fields, revision)
    except LookupError:
        raise web.HTTPNotFound(text="玩家档案不存在")
    except (ValueError, TypeError) as exc:
        return web.json_response({"error": str(exc)}, status=409)
    state["store"].audit("player", f"面板更新玩家档案 {pid} 的归属地与备注")
    return web.json_response(state["catalog"].get(pid, state), headers={"Cache-Control": "no-store"})


async def profile_bind(request):
    state = request.app[STATE]
    authorized(request, state["config"]["app"]["admin_token"])
    data = await body(request)
    try:
        sid, qq = data.get("server"), data.get("qq")
        if not isinstance(sid, str) or sid not in state["bot"].servers or not isinstance(qq, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", qq):
            raise ValueError("请选择服务器并填写正确的 QQ 号")
        pid = int(request.match_info["pid"])
        state["catalog"].bind(pid, sid, qq)
    except LookupError:
        raise web.HTTPNotFound(text="玩家档案不存在")
    except (ValueError, TypeError) as exc:
        return web.json_response({"error": str(exc)}, status=409)
    state["store"].audit("binding", f"面板管理员将档案 {pid} 在 {sid} 关联到 QQ {qq}")
    return web.json_response(state["catalog"].get(pid, state), headers={"Cache-Control": "no-store"})


async def profile_bulk(request):
    state = request.app[STATE]
    authorized(request, state["config"]["app"]["admin_token"])
    data = await body(request)
    ids, action, sid = data.get("ids"), data.get("action"), data.get("server", "")
    if (not isinstance(ids, list) or not 1 <= len(ids) <= 100
        or any(type(value) is not int or value < 1 for value in ids) or len(set(ids)) != len(ids)
        or action not in ("delete", "unbind") or not isinstance(sid, str) or len(sid) > 40 or (action == "delete" and sid)):
        return web.json_response({"error": "需要有效的玩家编号和管理操作（每次最多 100 位）"}, status=400)
    try:
        result = state["catalog"].bulk(ids, action, sid)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=409)
    state["store"].audit("player", f"面板{'删除' if action == 'delete' else '解绑'}玩家档案 {','.join(map(str, ids))}；移除 {result['bindings_removed']} 项绑定")
    return web.json_response(result, headers={"Cache-Control": "no-store"})


async def admin_status(request):
    state = request.app[STATE]
    authorized(request, state["config"]["app"]["admin_token"])
    bot = state["bot"]
    data = {
        "onebot": state["onebot"].connected, "self_id": state["onebot"].self_id,
        "uptime": int(time.time() - bot.started),
        "servers": [{"id": s["id"], "name": s["name"], "groups": s["groups"],
                     "online": bot.online(s["id"]), **bot.snapshots.get(s["id"], {})} for s in bot.servers.values()],
        "bindings": state["store"].bindings(), "logs": state["store"].logs(),
        "restart_error": state.get("restart_error", ""),
        **management_state(state),
    }
    who = request.get(ADMIN_IDENTITY)
    if who and not who["owner"]:
        if "players.manage" not in who["permissions"]:
            data["bindings"] = []; data["player_actions"] = []; data["players"] = []
        data["logs"] = []
        for server in data["servers"]:
            server.pop("player_records", None)
    data["alerts_open"] = state["runtime"].monitoring()["open_count"]
    from .community_api import feature_settings
    data['community_features'] = {key: value['settings']['enabled'] for key, value in feature_settings(state).items()}
    return web.json_response(data, headers={"Cache-Control": "no-store"})


async def lifecycle(app):
    state = app[STATE]
    await state["plugins"].start()
    workers = [asyncio.create_task(state["bot"].worker()), asyncio.create_task(game_worker(state)), asyncio.create_task(state["operations"].worker()), asyncio.create_task(state["runtime"].worker())]
    yield
    if state["onebot"].connected:
        await state["onebot"].ws.close()
    for task in workers:
        task.cancel()
    for task in workers:
        with suppress(asyncio.CancelledError):
            await task
    await state["registration"].close()
    await state["backups"].close()
    await state["updates"].close()
    state["store"].close()
    if state.get("plugin_temp"):
        state["plugin_temp"].cleanup()


def create_app(cfg, config_path=None, restart_event=None):
    store = Store(cfg["app"]["database"])
    catalog = Catalog(store)
    onebot = OneBot(cfg["onebot"], store)
    bot = Bot(cfg, store, onebot)
    plugin_temp = TemporaryDirectory(prefix="starbridge-plugins-") if not config_path and cfg["app"]["database"] == ":memory:" else None
    base = (Path(config_path).resolve().parent if config_path else Path(plugin_temp.name) if plugin_temp
            else Path(cfg["app"]["database"]).resolve().parent)
    plugins = PluginManager(base, bot, store)
    bot.plugins = plugins
    registration = Registration(base, store)
    bot.registration = registration
    authentication = Authentication(base, bot, registration)
    bot.authentication = authentication
    app = web.Application(client_max_size=256 * 1024)
    app[STATE] = {"config": deepcopy(cfg), "store": store, "catalog": catalog, "onebot": onebot, "bot": bot, "plugins": plugins, "registration": registration, "authentication": authentication,
                  "game_events": asyncio.Queue(maxsize=256), "settings_lock": asyncio.Lock(),
                  "config_file": ConfigFile(config_path) if config_path else None, "restart_event": restart_event, "plugin_temp": plugin_temp}
    app.cleanup_ctx.append(lifecycle)
    registration_routes(app, STATE, authorized, body)
    authentication_routes(app, STATE, authorized, body, bridge)
    backup_routes(app, STATE, authorized, body)
    operations_routes(app, STATE, authorized, body)
    website_routes(app, STATE, authorized, body)
    app[STATE]["runtime"] = RuntimeFeatures(app[STATE])
    registration.mail_observer = app[STATE]["runtime"].mail_result
    admin_routes(app, STATE, body)
    enhancement_routes(app, STATE, body)
    community_routes(app, STATE, body)
    deployment_routes(app, STATE, body, commit_config, authorized)
    update_routes(app, STATE, body)
    app.add_routes([
        web.get("/", dashboard), web.get("/dashboard.js", dashboard_script), web.get("/panel.css", dashboard_style), web.get("/health", health),
        web.get("/extension-panel.js", extension_script),
        web.get("/api/config", admin_config), web.put("/api/config", save_config),
        web.post("/api/restart", restart_service),
        web.post("/api/player-actions", player_action), web.get("/api/plugin", plugin_download),
        web.get("/api/plugin/catalog", game_bridge_catalog),
        web.get("/mod-bridge-panel.js", mod_bridge_script),
        web.get("/api/extensions", extension_api),
        web.post("/api/extensions/{action:install|scan|upgrade}", extension_api),
        web.get("/api/extensions/{plugin_id:[a-z][a-z0-9_]{0,39}}/{action:versions}", extension_api),
        web.post("/api/extensions/{plugin_id:[a-z][a-z0-9_]{0,39}}/{action:rollback}", extension_api),
        web.put("/api/extensions/{plugin_id:[a-z][a-z0-9_]{0,39}}", extension_api),
        web.delete("/api/extensions/{plugin_id:[a-z][a-z0-9_]{0,39}}", extension_api),
        web.post("/api/extensions/{plugin_id:[a-z][a-z0-9_]{0,39}}/reload", extension_api),
        web.get("/api/extension-documents/{document:guide|example}", extension_document),
        web.get("/api/player-profiles", profile_list), web.post("/api/player-profiles", profile_create),
        web.post("/api/player-profiles/bulk", profile_bulk),
        web.get("/api/player-profiles/{pid:\\d+}", profile_detail), web.patch("/api/player-profiles/{pid:\\d+}", profile_update),
        web.post("/api/player-profiles/{pid:\\d+}/bind", profile_bind),
        web.get("/api/status", admin_status), web.get("/onebot/ws", onebot.handle),
        web.post("/bridge/{sid}/tick", tick), web.post("/bridge/{sid}/bind-code", bind_code),
    ])
    return app
