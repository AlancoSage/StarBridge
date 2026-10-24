"""Owner settings and token-scoped Minecraft binding admission endpoints."""
from pathlib import Path

from aiohttp import web

from .registration import RegistrationError


def setup_routes(app, state_key, read_body, bridge):
    state = app[state_key]
    service = state["binding_gate"]

    def response(data, status=200):
        return web.json_response(data, status=status, headers={"Cache-Control": "no-store"})

    async def settings(request):
        # Explicitly owner-only even if a future permission prefix includes this path.
        who = state["admin_accounts"].authorized_identity(request)
        if not who["owner"]:
            raise web.HTTPForbidden(text="只有服主可以修改强制绑定设置")
        try:
            if request.method == "GET":
                return response(service.config())
            data = await read_body(request)
            if data.keys() - {"settings", "revision"}:
                raise RegistrationError("强制绑定请求包含未知字段")
            return response(await service.save(data.get("settings"), data.get("revision")))
        except RegistrationError as error:
            return response({"error": str(error), "code": error.code}, error.status)

    async def check(request):
        _, server = bridge(request)
        try:
            return response(service.check(server["id"], await read_body(request)))
        except RegistrationError as error:
            return response({"error": str(error)}, error.status)

    async def script(request):
        return web.FileResponse(Path(__file__).with_name("binding-gate-panel.js"),
                                headers={"Cache-Control": "no-cache"})

    app.add_routes([
        web.get("/api/binding-gate/settings", settings), web.put("/api/binding-gate/settings", settings),
        web.post("/bridge/{sid}/binding-check", check),
        web.get("/binding-gate-panel.js", script),
    ])
