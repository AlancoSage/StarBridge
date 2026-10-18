from pathlib import Path
import sqlite3
from aiohttp import web
from .operations import OperationError, Operations
from .extensions import PluginConflict, SCHEDULES_ID


def setup_routes(app, state_key, authorize, read_body):
    state = app[state_key]
    manager = Operations(state)
    state["operations"] = manager
    state["bot"].operations = manager

    async def endpoint(request):
        authorize(request, state["config"]["app"]["admin_token"])
        try:
            path, method = request.path, request.method
            if path == "/api/schedules/plugin":
                data = await read_body(request)
                if data.keys()-{'revision','enabled'} or type(data.get('enabled')) is not bool:
                    raise OperationError('插件开关只接受 enabled 和 revision')
                await state['plugins'].update(SCHEDULES_ID, data)
                result = manager.tasks()
            elif path == "/api/schedules" and method == "GET":
                result = manager.tasks()
            elif path == "/api/schedules":
                result = manager.save_task((await read_body(request)).get("definition"))
            elif path.startswith("/api/schedules/"):
                data = await read_body(request)
                task_id = request.match_info["task_id"]
                if path.endswith("/run"):
                    result = await manager.run_task(task_id, manual=True, revision=data.get("revision"))
                elif method == "PUT":
                    result = manager.save_task(data.get("definition"), task_id, data.get("revision"))
                else:
                    manager.delete_task(task_id, data.get("revision")); result = {"ok":True}
            elif path == "/api/whitelist/settings" and method == "GET":
                result = manager.config()
            elif path == "/api/whitelist/settings":
                data = await read_body(request)
                result = manager.save_config(data.get("settings"), data.get("revision"))
            elif path == "/api/whitelist" and method == "GET":
                try: page = int(request.query.get("page",1))
                except ValueError: raise OperationError("页码错误") from None
                result = manager.applications(request.query.get("status", ""), page)
            elif path == "/api/whitelist":
                data = await read_body(request)
                result = manager.apply(data.get("server"), data.get("player"), data.get("qq"), reason=data.get("reason",""), admin=True)
            else:
                data = await read_body(request)
                result = manager.review(request.match_info["application_id"], data.get("action"), data.get("revision"), data.get("note",""), data.get("uuid",""))
                await manager.notify(result)
            return web.json_response(result, headers={"Cache-Control":"no-store"})
        except OperationError as exc:
            return web.json_response({"error":str(exc)}, status=exc.status, headers={"Cache-Control":"no-store"})
        except PluginConflict as exc:
            return web.json_response({'error':str(exc)},status=409,headers={'Cache-Control':'no-store'})
        except (ValueError, LookupError) as exc:
            return web.json_response({'error':str(exc)},status=400,headers={'Cache-Control':'no-store'})
        except (OSError, sqlite3.Error):
            return web.json_response({"error":"操作失败，请检查数据库、磁盘空间与目录权限"}, status=500)

    async def script(request):
        return web.FileResponse(Path(__file__).parent / "operations-panel.js", headers={"Cache-Control":"no-cache"})
    async def guide(request):
        authorize(request, state["config"]["app"]["admin_token"])
        return web.FileResponse(Path(__file__).parent.parent / "docs/automation-and-whitelist.md", headers={"Cache-Control":"no-store", "Content-Disposition":'attachment; filename="VexBot-automation-and-whitelist.md"'})
    app.add_routes([web.get("/operations-panel.js", script), web.get("/api/schedules", endpoint), web.post("/api/schedules", endpoint),
                    web.put('/api/schedules/plugin', endpoint),
                    web.get("/api/operations/guide",guide),
                    web.put("/api/schedules/{task_id:[a-f0-9]{32}}",endpoint), web.delete("/api/schedules/{task_id:[a-f0-9]{32}}",endpoint),
                    web.post("/api/schedules/{task_id:[a-f0-9]{32}}/run", endpoint),
                    web.get("/api/whitelist/settings",endpoint), web.put("/api/whitelist/settings",endpoint),
                    web.get("/api/whitelist",endpoint), web.post("/api/whitelist",endpoint),
                    web.post("/api/whitelist/{application_id:[a-f0-9]{32}}/review",endpoint)])
