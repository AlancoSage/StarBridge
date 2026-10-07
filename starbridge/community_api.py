from pathlib import Path
from aiohttp import web
from .admin_accounts import ADMIN_IDENTITY
from .community_operations import Tickets, Sanctions
from .registration import RegistrationError


def setup_routes(app, state_key, read_body):
    state = app[state_key]
    tickets = state['tickets'] = Tickets(state)
    sanctions = state['sanctions'] = Sanctions(state)

    def user(request):
        header = request.headers.get('Authorization', '')
        account = state['registration'].account_for_token(header[7:] if header.startswith('Bearer ') else '')
        state['registration'].limit('tickets-read:' + account['id'], 100, 60)
        return account

    async def endpoint(request):
        try:
            path = request.path; tid = request.match_info.get('tid'); public = path.startswith('/api/v1/')
            if public:
                who = user(request)
                if request.method == 'GET': result = tickets.detail(tid, who['id']) if tid else tickets.listing(who['id'], page=request.query.get('page', 1))
                elif tid: result = tickets.reply(tid, await read_body(request), who['player'], who['id'])
                else: result = tickets.create(who, await read_body(request))
            elif path == '/api/tickets/settings':
                result = tickets.config() if request.method == 'GET' else tickets.save(await read_body(request))
            elif path.startswith('/api/tickets'):
                if request.method == 'GET': result = tickets.detail(tid) if tid else tickets.listing(status=request.query.get('status', ''), page=request.query.get('page', 1))
                else: result = tickets.reply(tid, await read_body(request), request[ADMIN_IDENTITY]['username'])
            elif request.method == 'GET': result = sanctions.listing(request.query.get('page', 1))
            elif path.endswith('/revoke'):
                data = await read_body(request)
                if data.keys() != {'revision'}: raise RegistrationError('撤销只接受 revision')
                result = sanctions.release(request.match_info['rid'], data['revision'])
            elif path.endswith('/retry'):
                data = await read_body(request); row = sanctions.detail(request.match_info['rid'])
                if data.keys() != {'revision'} or type(data['revision']) is not int or data['revision'] != row['revision']: raise RegistrationError('处罚已变化，请刷新', 409)
                with sanctions.db:
                    sanctions.db.execute("UPDATE sanction_targets SET attempts=0,next_try=0 WHERE sanction=? AND status IN ('failed','waiting')", (row['id'],))
                sanctions.reconcile(); result = sanctions.detail(row['id'])
            else: result = sanctions.create(await read_body(request), request[ADMIN_IDENTITY]['username'])
            return web.json_response(result, status=201 if request.method == 'POST' and not tid and path in ('/api/v1/me/tickets', '/api/sanctions') else 200, headers={'Cache-Control': 'no-store'})
        except RegistrationError as exc: return web.json_response({'error': str(exc)}, status=exc.status, headers={'Cache-Control': 'no-store'})

    async def script(request): return web.FileResponse(Path(__file__).parent / 'service-panel.js', headers={'Cache-Control': 'no-cache'})
    app.add_routes([
        web.get('/service-panel.js', script),
        web.get('/api/tickets', endpoint), web.get('/api/tickets/settings', endpoint), web.put('/api/tickets/settings', endpoint),
        web.get('/api/tickets/{tid:[a-f0-9]{32}}', endpoint), web.post('/api/tickets/{tid:[a-f0-9]{32}}/reply', endpoint),
        web.get('/api/v1/me/tickets', endpoint), web.post('/api/v1/me/tickets', endpoint),
        web.get('/api/v1/me/tickets/{tid:[a-f0-9]{32}}', endpoint), web.post('/api/v1/me/tickets/{tid:[a-f0-9]{32}}/reply', endpoint),
        web.get('/api/sanctions', endpoint), web.post('/api/sanctions', endpoint),
        web.post('/api/sanctions/{rid:[a-f0-9]{32}}/revoke', endpoint), web.post('/api/sanctions/{rid:[a-f0-9]{32}}/retry', endpoint),
    ])
