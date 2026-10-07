from aiohttp import web, ClientError
from .updates import Updates
from .registration import RegistrationError
from .backups import BackupError


def setup_routes(app, state_key, read_body):
    state = app[state_key]; updates = state['updates'] = Updates(state)
    async def endpoint(request):
        try:
            path = request.path
            if request.method == 'GET': result = updates.listing()
            elif request.method == 'PUT': result = updates.save(await read_body(request))
            elif path.endswith('/check'): result = await updates.check_feed()
            elif path.endswith('/upload'):
                if request.content_type != 'application/zip': raise RegistrationError('请上传 ZIP 部署包', 415)
                result = await updates.upload(request.content)
            elif path.endswith('/download'): result = await updates.download()
            elif path.endswith('/cleanup'):
                updates.require_idle(); updates.busy = True
                try: result = await asyncio.to_thread(updates.cleanup)
                finally: updates.busy = False
            else: result = await updates.apply(await read_body(request), rollback=path.endswith('/rollback'))
            return web.json_response(result, status=202 if path.endswith(('/upload', '/download', '/apply', '/rollback')) else 200, headers={'Cache-Control': 'no-store'})
        except (RegistrationError, BackupError) as exc: return web.json_response({'error': str(exc)}, status=exc.status, headers={'Cache-Control': 'no-store'})
        except (ValueError, OSError, TimeoutError, ClientError): return web.json_response({'error': '更新操作失败，请检查部署包、网络与磁盘空间'}, status=400)
    import asyncio
    app.add_routes([web.get('/api/updates', endpoint), web.put('/api/updates', endpoint),
                    *[web.post('/api/updates/' + action, endpoint) for action in ('check', 'upload', 'download', 'apply', 'rollback', 'cleanup')]])
