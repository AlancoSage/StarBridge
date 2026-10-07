from aiohttp import web
from .deployment import Deployment
from .registration import RegistrationError


def setup_routes(app, state_key, read_body, commit, authorize):
    state = app[state_key]; service = state['deployment'] = Deployment(state)
    async def endpoint(request):
        try:
            path = request.path
            if path == '/api/diagnostics' and request.method == 'GET': result = service.diagnostics()
            elif path == '/api/diagnostics/probe':
                data = await read_body(request)
                if data.keys() != {'kind'}: raise RegistrationError('检测只接受 kind')
                result = await service.probe(data['kind'])
            elif path == '/api/deployment/templates': result = {'templates': [{'id': key, 'title': title} for key, title in [('single', '单服联动'), ('multi', '多服社区'), ('qq_login', '仅 QQ 确认登录'), ('chat_only', '聊天联动，不启用游戏认证')]]}
            elif path == '/api/deployment/export': return web.json_response(service.export(), headers={'Cache-Control': 'no-store', 'Content-Disposition': 'attachment; filename="StarBridge-config.json"'})
            elif path == '/api/deployment/preview': result = service.preview(await read_body(request))
            else:
                data = await read_body(request)
                if data.keys() != {'preview_id'} or not isinstance(data['preview_id'], str): raise RegistrationError('需要预览编号')
                return await service.apply(data['preview_id'], commit, lambda: authorize(request, state['config']['app']['admin_token']))
            return web.json_response(result, headers={'Cache-Control': 'no-store'})
        except RegistrationError as exc: return web.json_response({'error': str(exc)}, status=exc.status, headers={'Cache-Control': 'no-store'})
        except (ValueError, TypeError) as exc: return web.json_response({'error': str(exc)}, status=400)
    app.add_routes([web.get('/api/diagnostics', endpoint), web.post('/api/diagnostics/probe', endpoint),
                    web.get('/api/deployment/templates', endpoint), web.get('/api/deployment/export', endpoint),
                    web.post('/api/deployment/preview', endpoint), web.post('/api/deployment/apply', endpoint)])
