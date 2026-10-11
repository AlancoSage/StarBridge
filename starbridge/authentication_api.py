from pathlib import Path

from aiohttp import web

from .registration import RegistrationError


def setup_routes(app, state_key, authorize, read_body, bridge):
    state = app[state_key]
    auth = state["authentication"]

    def response(data, status=200):
        return web.json_response(data, status=status, headers={"Cache-Control": "no-store"})

    async def game(request):
        _, server = bridge(request)
        try:
            return response(await auth.action(server, await read_body(request)))
        except RegistrationError as exc:
            return response({"error": str(exc), "code": exc.code}, exc.status)

    async def settings(request):
        authorize(request, state["config"]["app"]["admin_token"])
        try:
            if request.method == "GET":
                data = auth.config_response()
            else:
                payload = await read_body(request)
                data = await auth.save_settings(payload.get("settings"), payload.get("revision"))
            data["servers"] = [{"id": server["id"], "name": server["name"]} for server in state["bot"].servers.values()]
            return response(data)
        except RegistrationError as exc:
            return response({"error": str(exc), "code": exc.code}, exc.status)
        except OSError:
            return response({"error": "游戏登录设置写入失败，运行设置未更改"}, 500)

    async def clear_links(request):
        authorize(request, state["config"]["app"]["admin_token"])
        try:
            return response(auth.clear_links(request.match_info["account_id"]))
        except RegistrationError as exc:
            return response({"error": str(exc), "code": exc.code}, exc.status)

    async def password_info(request):
        return response({"available": auth.reset_available(), "min_length": 8, "max_length": 128})

    async def guide(request):
        authorize(request, state["config"]["app"]["admin_token"])
        platform = request.query.get("platform", "bukkit")
        if platform not in ("bukkit", "forge", "neoforge", "fabric"):
            raise web.HTTPBadRequest(text="不支持的游戏端类型")
        name = "fabric-game-ends.md" if platform == "fabric" else "mod-game-ends.md" if platform != "bukkit" else "game-login.md"
        return web.FileResponse(Path(__file__).resolve().parent.parent / "docs" / name,
            headers={"Cache-Control": "no-store", "Content-Disposition": f'attachment; filename="Myrinbot-{name}"'})

    async def password_request(request):
        if request.content_type != "application/json":
            raise RegistrationError("请求需要 application/json", 415, "content_type_invalid")
        data = await read_body(request)
        if data.keys() - {"player", "email"}:
            raise RegistrationError("只接受 player 和 email 字段")
        return response(await auth.request_password(data.get("player"), data.get("email"), request.remote or "unknown"), 202)

    async def password_verify(request):
        if request.content_type != "application/json":
            raise RegistrationError("请求需要 application/json", 415, "content_type_invalid")
        data = await read_body(request)
        if data.keys() - {"challenge_id", "code", "password"}:
            raise RegistrationError("只接受 challenge_id、code 和 password 字段")
        return response(await auth.verify_password(data.get("challenge_id"), data.get("code"), data.get("password"), request.remote or "unknown"))

    async def file(request):
        filename = {"/account-password": "account-password.html", "/account-password.js": "account-password.js",
                    "/authentication-panel.js": "authentication-panel.js"}[request.path]
        return web.FileResponse(Path(__file__).parent / filename, headers={"Cache-Control": "no-cache"})

    app.add_routes([
        web.post("/bridge/{sid}/auth", game),
        web.get("/api/authentication/settings", settings), web.put("/api/authentication/settings", settings),
        web.delete("/api/authentication/account-links/{account_id}", clear_links),
        web.get("/api/authentication/guide", guide),
        web.get("/api/v1/account/password/info", password_info),
        web.post("/api/v1/account/password/request", password_request),
        web.post("/api/v1/account/password/verify", password_verify),
        web.get("/account-password", file), web.get("/account-password.js", file), web.get("/authentication-panel.js", file),
    ])
