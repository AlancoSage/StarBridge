"""Community APIs and configuration for separately deployed websites."""
from pathlib import Path
import secrets

from aiohttp import web

from .registration import RegistrationError
from .website import Website, api_base

ROOT = Path(__file__).resolve().parent.parent


def setup_routes(app, state_key, authorize, read_body):
    state = app[state_key]
    base = state["registration"].path.parent.parent
    service = state["website"] = Website(base, state)
    reg = state["registration"]

    def response(data, status=200):
        return web.json_response(data, status=status, headers={"Cache-Control": "no-store"})

    def user_token(request):
        header = request.headers.get("Authorization", "")
        return header[7:] if header.startswith("Bearer ") else ""

    def limit(request):
        reg.limit("community-read:" + (request.remote or "unknown"), 300, 60)

    async def public(request):
        limit(request)
        action = request.match_info["action"]
        if "uuid" in request.match_info:
            return response(service.player(request.match_info["uuid"]))
        if action == "info":
            return response(service.info())
        if action == "servers":
            return response(service.servers())
        if action == "players":
            if request.query.keys() - {"q", "page", "page_size"}:
                raise RegistrationError("查询只接受 q、page、page_size")
            try:
                data = service.players(request.query.get("q", ""), int(request.query.get("page", 1)), int(request.query.get("page_size", 24)))
            except (ValueError, TypeError) as exc:
                if isinstance(exc, RegistrationError):
                    raise
                raise RegistrationError("分页参数格式错误") from None
            return response(data)
        return response(service.player(request.match_info["uuid"]))

    async def own_profile(request):
        limit(request)
        return response(service.profile(reg.account_for_token(user_token(request))))

    async def integration_profile(request):
        expected = reg.settings["api_token"]
        if not expected or not secrets.compare_digest(user_token(request).encode(), expected.encode()):
            raise RegistrationError("网站 API 密钥无效", 401, "api_token_invalid")
        reg.limit("integration-profile:" + (request.remote or "unknown"), 100, 600)
        return response(service.profile(reg.account(request.match_info["account_id"])))

    async def login(request):
        if request.content_type != "application/json":
            raise RegistrationError("请求需要 application/json", 415, "content_type_invalid")
        data = await read_body(request)
        if data.keys() - {"player", "password"}:
            raise RegistrationError("登录只接受 player 和 password")
        return response(await service.login(data.get("player"), data.get("password"), request.remote or "unknown"))

    async def logout(request):
        return response(service.logout(user_token(request)))

    async def redirect(request):
        if service.settings["connection_enabled"] and service.settings["website_url"] and not service.error:
            raise web.HTTPFound(service.settings["website_url"])
        raise web.HTTPNotFound(text="官网已成为独立项目，请在 Bot 面板「网站绑定」中填写网站地址并启用接入。")

    async def panel_script(request):
        return web.FileResponse(Path(__file__).parent / "website-panel.js", headers={"Cache-Control": "no-cache"})

    async def admin(request):
        authorize(request, state["config"]["app"]["admin_token"])
        action = request.match_info["action"]
        try:
            if action == "settings":
                if request.method == "GET":
                    return response(service.config_response())
                data = await read_body(request)
                if data.keys() - {"settings", "revision"}:
                    raise RegistrationError("设置请求包含未知字段")
                async with state["settings_lock"]:
                    return response(await service.save(data.get("settings"), data.get("revision")))
            if action == "package":
                raise RegistrationError("官网已拆分为独立项目，请下载独立项目及接入配置", 410, "website_separated")
            if action == "config":
                data = await read_body(request)
                if data.keys() - {"api_base"}:
                    raise RegistrationError("接入配置只接受 api_base")
                address = data.get("api_base", service.settings["api_public_url"])
                return web.json_response({"apiBase":api_base(address)}, headers={"Cache-Control":"no-store", "Content-Disposition":'attachment; filename="config.json"'})
            if action == "project":
                from .branding import artifact_path
                file = artifact_path(ROOT / "dist", "Myrinbot-website.zip")
                if not file.is_file():
                    raise RegistrationError("尚未生成官网独立项目包，请使用独立项目的 build.py 打包", 404, "project_missing")
                if file.stat().st_size > 4 * 1024 * 1024:
                    raise RegistrationError("官网项目包超过 4 MiB 上限", 413)
                return web.FileResponse(file, headers={"Cache-Control":"no-store", "Content-Disposition":'attachment; filename="Myrinbot-website.zip"'})
            return web.FileResponse(ROOT / "docs/website-deployment.md", headers={"Cache-Control": "no-store",
                "Content-Disposition": 'attachment; filename="website-deployment.md"'})
        except RegistrationError as exc:
            return response({"error": str(exc), "code": exc.code}, exc.status)
        except (ValueError, TypeError):
            return response({"error": "请求参数格式错误"}, 400)
        except OSError:
            return response({"error": "官网文件读取或保存失败，请检查文件权限"}, 500)

    app.add_routes([
        web.get("/community", redirect), web.get("/community/", redirect),
        web.get("/website-panel.js", panel_script),
        web.get("/api/v1/community/{action:info}", public),
        web.get("/api/v1/{action:servers|players}", public),
        web.get("/api/v1/{action:players}/{uuid}", public),
        web.get("/api/v1/me/profile", own_profile),
        web.get("/api/v1/accounts/{account_id}/profile", integration_profile),
        web.post("/api/v1/account/login", login), web.post("/api/v1/account/logout", logout),
        web.get("/api/website/{action:settings|guide|project}", admin), web.put("/api/website/{action:settings}", admin),
        web.post("/api/website/{action:config|package}", admin),
    ])
