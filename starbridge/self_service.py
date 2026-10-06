"""User-scoped website actions; ownership never comes from submitted QQ or player names."""
import re
import sqlite3
import time
from aiohttp import web
from .registration import RegistrationError
from .operations import OperationError


def setup_routes(app,state_key,read_body):
    state=app[state_key];store=state['store'];db=store.db;reg=state['registration']
    def account(request):
        header=request.headers.get('Authorization','')
        user=reg.account_for_token(header[7:] if header.startswith('Bearer ') else '')
        reg.limit('self-service:'+user['id'],60,60)
        return user

    def summary(user):
        state['operations'].expire()
        servers=[{'id':s['id'],'name':s['name']} for s in state['bot'].servers.values()]
        bindings=[{key:row[key] for key in ('server','uuid','name','created')} for row in db.execute('SELECT * FROM bindings WHERE qq=? ORDER BY created DESC',(user['qq'] or '',))]
        applications=[]
        for row in db.execute('SELECT * FROM whitelist_applications WHERE qq=? ORDER BY created DESC LIMIT 50',(user['qq'] or '',)):
            # Review notes and execution output are management data, not a public profile.
            applications.append({key:row[key] for key in ('id','server','player','reason','status','created','updated')})
        links=db.execute('SELECT server,uuid FROM account_game_links WHERE account_id=? UNION SELECT server,uuid FROM bindings WHERE qq=?',(user['id'],user['qq'] or '')).fetchall()
        penalties=[]
        for link in links[:100]:
            penalties.extend({key:row[key] for key in ('server','player','action','reason','status','created')}
                for row in db.execute("SELECT * FROM player_actions WHERE server=? AND uuid=? AND action IN ('kick','ban','unban') AND status='success' ORDER BY created DESC LIMIT 30",(link['server'],link['uuid'])))
        penalties.sort(key=lambda row:row['created'],reverse=True)
        return {'servers':servers,'bindings':bindings,'applications':applications,'penalties':penalties[:50],
                'whitelist_enabled':state['operations'].config()['settings']['enabled']}

    async def endpoint(request):
        try:
            user=account(request)
            if request.method=='GET':return web.json_response(summary(user),headers={'Cache-Control':'no-store'})
            data=await read_body(request);action=request.match_info['action']
            allowed={'bind':{'server','code'},'unbind':{'server'},'whitelist':{'server','reason'}}[action]
            if data.keys()-allowed:raise RegistrationError('自助请求包含未知字段')
            sid=data.get('server')
            if not isinstance(sid,str) or sid not in state['bot'].servers:raise RegistrationError('服务器不存在',404)
            qq=user['qq']
            if not qq or not re.fullmatch(r'[1-9][0-9]{0,19}',qq):raise RegistrationError('此账号未关联已验证 QQ',403)
            reg.limit('self-service-mutation:'+user['id'],10,300)
            if action=='whitelist':
                state['operations'].apply(sid,user['player'],qq,reason=data.get('reason',''))
            elif action=='bind':
                code=data.get('code')
                if not isinstance(code,str) or not re.fullmatch(r'[0-9A-Fa-f]{8}',code):raise RegistrationError('请输入游戏内 /qbind 获取的 8 位验证码')
                row=db.execute('SELECT * FROM codes WHERE code=? AND server=? AND expires>?',(code.upper(),sid,time.time())).fetchone()
                if not row:raise RegistrationError('绑定码无效或已过期',409)
                other=db.execute('SELECT account_id FROM account_game_links WHERE server=? AND uuid=?',(sid,row['uuid'])).fetchone()
                existing=db.execute('SELECT uuid FROM account_game_links WHERE account_id=? AND server=?',(user['id'],sid)).fetchone()
                if (other and other['account_id']!=user['id']) or (existing and existing['uuid']!=row['uuid']):raise RegistrationError('游戏身份已有账号关联，请联系管理员核实',409)
                # Store.bind consumes the code and checks uniqueness in one transaction.
                store.bind(sid,qq,code)
            else:
                bound=store.binding(sid,qq)
                if not bound:raise RegistrationError('你在此服务器没有绑定',404)
                with db:
                    db.execute('DELETE FROM bindings WHERE server=? AND qq=?',(sid,qq))
                    db.execute('DELETE FROM account_game_links WHERE account_id=? AND server=? AND uuid=?',(user['id'],sid,bound['uuid']))
                auth=state['authentication']
                auth.sessions={key:value for key,value in auth.sessions.items() if key!=(sid,bound['uuid'])}
            store.audit('self_service',f"{user['player']} 自助 {action} {sid}")
            return web.json_response(summary(user),status=201 if action=='whitelist' else 200,headers={'Cache-Control':'no-store'})
        except (RegistrationError,OperationError) as exc:return web.json_response({'error':str(exc)},status=exc.status,headers={'Cache-Control':'no-store'})
        except (ValueError,sqlite3.IntegrityError) as exc:return web.json_response({'error':str(exc)},status=409,headers={'Cache-Control':'no-store'})
    app.add_routes([web.get('/api/v1/me/services',endpoint),web.post('/api/v1/me/{action:bind|unbind|whitelist}',endpoint)])
