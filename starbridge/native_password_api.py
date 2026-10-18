from pathlib import Path

from aiohttp import web

from .registration import RegistrationError
from . import __velocity_version__
from .branding import ARTIFACT_PREFIX, artifact_path


def setup_routes(app, state_key, authorize, read_body, bridge):
    state = app[state_key]
    recovery = state["native_passwords"]

    def response(data, status=200):
        return web.json_response(data, status=status, headers={"Cache-Control": "no-store"})

    async def settings(request):
        authorize(request, state["config"]["app"]["admin_token"])
        try:
            if request.method == "GET":
                return response(recovery.config())
            data = await read_body(request)
            return response(recovery.save(data.get("settings"), data.get("revision")))
        except RegistrationError as error:
            return response({"error": str(error), "code": error.code}, error.status)

    async def tick(request):
        _, server = bridge(request)
        try:
            return response(recovery.tick(server, await read_body(request)))
        except RegistrationError as error:
            return response({"error": str(error)}, error.status)

    async def claim(request):
        _, server = bridge(request)
        try:
            return response(recovery.claim(server["id"], await read_body(request)))
        except RegistrationError as error:
            return response({"error": str(error)}, error.status)

    async def download(request):
        authorize(request, state["config"]["app"]["admin_token"])
        root = Path(__file__).resolve().parent.parent
        if request.path.endswith("/guide"):
            path = root / "docs/native-password-reset.md"
            filename = f"{ARTIFACT_PREFIX}-native-password-reset.md"
        else:
            filename = f"{ARTIFACT_PREFIX}-Velocity-{__velocity_version__}.jar"
            path = artifact_path(root / "bridge/target", filename)
        if not path.is_file():
            raise web.HTTPNotFound(text="请先构建或安装相应的发布附件")
        return web.FileResponse(path, headers={"Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="{filename}"'})

    async def script(request):
        return web.FileResponse(Path(__file__).with_name("native-password-panel.js"), headers={"Cache-Control": "no-cache"})

    app.add_routes([
        web.get("/api/native-passwords/settings", settings), web.put("/api/native-passwords/settings", settings),
        web.get("/api/native-passwords/guide", download), web.get("/api/native-passwords/velocity", download),
        web.post("/bridge/{sid}/password-reset/tick", tick), web.post("/bridge/{sid}/password-reset/claim", claim),
        web.get("/native-password-panel.js", script),
    ])
