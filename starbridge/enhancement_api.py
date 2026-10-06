"""Management endpoints for low-frequency operational features."""
from pathlib import Path
from aiohttp import web
from .registration import RegistrationError
from .backups import BackupError
from .self_service import setup_routes as self_service_routes


def setup_routes(app,state_key,read_body):
    state=app[state_key];runtime=state['runtime']
    self_service_routes(app,state_key,read_body)
    async def endpoint(request):
        try:
            path=request.path
            if path=='/api/monitoring' and request.method=='GET':result=runtime.monitoring()
            elif path.endswith('/ack'):result=runtime.acknowledge(request.match_info['alert_id'])
            elif path=='/api/statistics' and request.method=='GET':
                try:days=int(request.query.get('days','1'))
                except ValueError:raise RegistrationError('统计天数格式错误') from None
                result=runtime.statistics(request.query.get('server',''),days)
            elif path=='/api/backup-policy/cleanup':result=await state['backups'].cleanup_policy(manual=True)
            else:
                key={'/api/monitoring':'monitoring','/api/statistics':'statistics','/api/backup-policy':'backup_policy'}[path]
                if request.method=='GET':result=runtime.config(key)
                else:
                    data=await read_body(request)
                    if data.keys()-{'settings','revision'}:raise RegistrationError('设置包含未知字段')
                    result=runtime.save(key,data.get('settings'),data.get('revision'))
            return web.json_response(result,headers={'Cache-Control':'no-store'})
        except (RegistrationError,BackupError) as exc:return web.json_response({'error':str(exc)},status=exc.status,headers={'Cache-Control':'no-store'})
    async def script(request):return web.FileResponse(Path(__file__).parent/'enhancement-panel.js',headers={'Cache-Control':'no-cache'})
    app.add_routes([web.get('/enhancement-panel.js',script),web.get('/api/monitoring',endpoint),web.put('/api/monitoring',endpoint),
                    web.post('/api/monitoring/{alert_id:[a-f0-9]{32}}/ack',endpoint),
                    web.get('/api/statistics',endpoint),web.put('/api/statistics',endpoint),
                    web.get('/api/backup-policy',endpoint),web.put('/api/backup-policy',endpoint),web.post('/api/backup-policy/cleanup',endpoint)])
