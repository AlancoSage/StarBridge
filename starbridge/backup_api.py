from pathlib import Path
import sqlite3
from aiohttp import web
from .backups import Backups, BackupError


def setup_routes(app, state_key, authorize, read_body):
    state = app[state_key]
    manager = Backups(state); state["backups"] = manager

    @web.middleware
    async def maintenance(request, handler):
        if state.get("maintenance") and (request.method not in ("GET", "HEAD") or request.path == "/onebot/ws"):
            return web.json_response({"error": "正在恢复备份或切换版本，请等待服务重新连接"}, status=503, headers={"Cache-Control": "no-store"})
        return await handler(request)
    app.middlewares.insert(0, maintenance)

    async def endpoint(request):
        authorize(request, state["config"]["app"]["admin_token"])
        try:
            if request.path == "/api/backups" and request.method == "GET":
                result = await manager.work(manager.listing)
            elif request.path == "/api/backups" and request.method == "POST":
                result = await manager.create()
            elif request.path == "/api/backups/preview":
                if request.content_type != "application/zip": raise BackupError("请上传 ZIP 备份，Content-Type 需为 application/zip", 415)
                result = await manager.preview(request.content)
            elif request.path == "/api/backups/restore":
                data = await read_body(request)
                if data.keys() != {"preview_id"}: raise BackupError("只接受 preview_id 字段")
                result = await manager.restore(data["preview_id"])
            elif request.method == "GET":
                return web.FileResponse(manager.path(request.match_info["backup_id"]), headers={"Cache-Control": "no-store",
                    "Content-Disposition": 'attachment; filename="VexBot-' + request.match_info["backup_id"] + '.zip"'})
            else:
                if manager.busy: raise BackupError("备份或恢复操作正在处理中", 409)
                manager.path(request.match_info["backup_id"]).unlink()
                state["store"].audit("backup", "管理员删除备份 " + request.match_info["backup_id"])
                result = {"ok": True}
            return web.json_response(result, headers={"Cache-Control": "no-store"})
        except BackupError as exc:
            return web.json_response({"error": str(exc)}, status=exc.status, headers={"Cache-Control": "no-store"})
        except (OSError, ValueError, sqlite3.Error):
            return web.json_response({"error": "备份操作失败，请检查文件格式、磁盘空间和目录权限"}, status=400, headers={"Cache-Control": "no-store"})

    async def script(request):
        return web.FileResponse(Path(__file__).parent / "backup-panel.js", headers={"Cache-Control": "no-cache"})
    app.add_routes([web.get("/backup-panel.js", script), web.get("/api/backups", endpoint), web.post("/api/backups", endpoint),
                    web.post("/api/backups/preview", endpoint), web.post("/api/backups/restore", endpoint),
                    web.get("/api/backups/{backup_id}", endpoint), web.delete("/api/backups/{backup_id}", endpoint)])
