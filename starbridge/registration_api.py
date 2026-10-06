from pathlib import Path
import secrets

from aiohttp import web

from .registration import RegistrationError


def setup_routes(app, state_key, authorize, read_body):
    state = app[state_key]
    service = state["registration"]

    def response(value, status=200):
        return web.json_response(value, status=status, headers={"Cache-Control": "no-store"})

    @web.middleware
    async def registration_cors(request, handler):
        if not request.path.startswith("/api/v1/"):
            return await handler(request)
        origin = request.headers.get("Origin")
        allowed = origin is None or origin == f"{request.scheme}://{request.host}" or origin in service.settings["allowed_origins"]
        website = state.get("website")
        if origin and website and website.connected_origin and origin == website.connected_origin:
            allowed = website.settings["connection_enabled"] and not website.error
        if not allowed:
            return response({"error": "这个网站来源未获准接入", "code": "origin_forbidden"}, 403)
        if request.method == "OPTIONS":
            result = web.Response(status=204)
        else:
            try:
                result = await handler(request)
            except RegistrationError as exc:
                result = response({"error": str(exc), "code": exc.code}, exc.status)
            except web.HTTPException as exc:
                result = response({"error": exc.text, "code": "request_error"}, exc.status)
        if origin:
            result.headers["Access-Control-Allow-Origin"] = origin
            result.headers["Vary"] = "Origin"
            result.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            result.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        result.headers["Cache-Control"] = "no-store"
        return result

    app.middlewares.append(registration_cors)

    async def public_page(request):
        filename = "register.html" if request.path == "/register" else "register.js"
        return web.FileResponse(Path(__file__).parent / filename, headers={"Cache-Control": "no-cache"})

    async def info(request):
        return response({"enabled": service.settings["enabled"] and not service.error,
                         "site_name": service.settings["site_name"], "code_minutes": service.settings["code_minutes"],
                         "website_url": service.settings["website_url"]})

    async def public_body(request):
        if request.content_type != "application/json":
            raise RegistrationError("请求需要 application/json", 415, "content_type_invalid")
        return await read_body(request)

    async def request_code(request):
        data = await public_body(request)
        if data.keys() - {"player", "email"}:
            raise RegistrationError("申请只接受 player 和 email 字段")
        result = await service.request_code(data.get("player"), data.get("email"), remote=request.remote or "unknown")
        return response(result, 202)

    async def verify_code(request):
        data = await public_body(request)
        if data.keys() - {"challenge_id", "code", "password"}:
            raise RegistrationError("验证只接受 challenge_id、code 和 password 字段")
        service.limit("verify-client:" + (request.remote or "unknown"), 30, 600)
        return response(await service.verify_with_password(data.get("challenge_id"), data.get("code"), data.get("password")), 201)

    async def resend_code(request):
        data = await public_body(request)
        if data.keys() - {"challenge_id"}:
            raise RegistrationError("重新发送只接受 challenge_id 字段")
        return response(await service.resend(data.get("challenge_id"), request.remote or "unknown"), 202)

    async def own_account(request):
        service.limit("account-client:" + (request.remote or "unknown"), 100, 600)
        header = request.headers.get("Authorization", "")
        return response({"account": service.account_for_token(header[7:] if header.startswith("Bearer ") else "")})

    async def integration_account(request):
        token = service.settings["api_token"]
        supplied = request.headers.get("Authorization", "").encode()
        if not token or not secrets.compare_digest(supplied, ("Bearer " + token).encode()):
            raise RegistrationError("网站 API 密钥无效", 401, "api_token_invalid")
        service.limit("integration-client:" + (request.remote or "unknown"), 100, 600)
        return response({"account": service.account(request.match_info["account_id"])})

    async def admin(request):
        authorize(request, state["config"]["app"]["admin_token"])
        action = request.match_info["action"]
        try:
            if action == "settings" and request.method == "GET":
                return response(service.config_response())
            if action == "settings":
                data = await read_body(request)
                cfg = state["config"]
                forbidden = [cfg["app"]["admin_token"], cfg["onebot"]["token"], *[s["token"] for s in cfg["servers"]]]
                result = await service.save_settings(data.get("settings"), data.get("revision"), forbidden)
                return response(result)
            if action == "accounts":
                query = request.query.get("q", "")
                page = int(request.query.get("page", 1))
                if len(query) > 120 or not 1 <= page <= 10000:
                    raise RegistrationError("搜索或分页参数错误")
                return response(service.list_accounts(query, page))
            filename = "account-api.md" if action == "guide" else "website-registration.js"
            base = Path(__file__).resolve().parent.parent
            file = base / ("docs" if action == "guide" else "examples") / filename
            return web.FileResponse(file, headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})
        except RegistrationError as exc:
            return response({"error": str(exc), "code": exc.code}, exc.status)
        except (ValueError, TypeError):
            return response({"error": "请求参数格式错误"}, 400)
        except OSError:
            return response({"error": "注册设置写入失败，运行设置未更改"}, 500)

    async def panel_script(request):
        return web.FileResponse(Path(__file__).parent / "registration-panel.js", headers={"Cache-Control": "no-cache"})

    app.add_routes([
        web.get("/register", public_page), web.get("/register.js", public_page), web.get("/registration-panel.js", panel_script),
        web.get("/api/v1/registration/info", info), web.post("/api/v1/registration/request", request_code),
        web.post("/api/v1/registration/verify", verify_code), web.get("/api/v1/account", own_account),
        web.post("/api/v1/registration/resend", resend_code),
        web.get("/api/v1/accounts/{account_id}", integration_account),
        web.options("/api/v1/{tail:.*}", info),
        web.get("/api/registration/{action:settings|accounts|guide|example}", admin),
        web.put("/api/registration/{action:settings}", admin),
    ])
