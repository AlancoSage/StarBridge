"""Panel accounts and server-enforced capability checks."""
import hashlib
import json
import re
import secrets
import time
import uuid
from aiohttp import web
from .passwords import hash_password, check_password
from .registration import RegistrationError

PERMISSIONS = {'status.read':'运行概览', 'players.manage':'玩家与绑定管理',
               'whitelist.review':'白名单审核', 'plugins.manage':'插件管理',
               'schedules.manage':'定时任务管理', 'monitoring.manage':'故障提醒设置',
               'stats.read':'查看服务器统计', 'stats.manage':'统计采集设置', 'backups.manage':'创建、清理备份',
               'diagnostics.run':'连接自检', 'tickets.manage':'工单与申诉', 'sanctions.manage':'跨服处罚'}
PRESETS = {'admin':list(PERMISSIONS), 'reviewer':['status.read','whitelist.review'],
           'observer':['status.read','stats.read']}
ADMIN_IDENTITY = getattr(web,'RequestKey',web.AppKey)('admin_identity',dict)


def permissions(value):
    if not isinstance(value,list) or any(not isinstance(v,str) or v not in PERMISSIONS for v in value) or len(value)!=len(set(value)):
        raise RegistrationError('管理员权限格式错误')
    if 'status.read' not in value:
        raise RegistrationError('管理员需要运行概览权限')
    return sorted(value)


class AdminAccounts:
    def __init__(self,state):
        self.state=state;self.db=state['store'].db

    def identity(self,token):
        root=self.state['config']['app']['admin_token']
        if secrets.compare_digest(token.encode(),root.encode()):
            return {'id':'owner','username':'服主','owner':True,'permissions':list(PERMISSIONS)}
        row=self.db.execute('SELECT u.* FROM admin_sessions s JOIN admin_users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>? AND u.enabled=1',
                            (hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
        return {'id':row['id'],'username':row['username'],'owner':False,'permissions':json.loads(row['permissions'])} if row else None

    def listing(self):
        users=[{k:row[k] for k in ('id','username','enabled','revision','created')}|{'permissions':json.loads(row['permissions'])}
               for row in self.db.execute('SELECT * FROM admin_users ORDER BY created')]
        return {'users':users,'permissions':PERMISSIONS,'presets':PRESETS}

    async def save(self,data,user_id=None):
        if data.keys()-{'username','password','permissions','enabled','revision'}:
            raise RegistrationError('管理员请求包含未知字段')
        old=self.db.execute('SELECT * FROM admin_users WHERE id=?',(user_id,)).fetchone() if user_id else None
        if user_id and not old:raise RegistrationError('管理员不存在',404)
        if old and data.get('revision')!=old['revision']:raise RegistrationError('管理员已被修改，请刷新',409)
        username=data.get('username',old['username'] if old else '')
        if not isinstance(username,str) or not re.fullmatch(r'[A-Za-z0-9_\-]{3,32}',username):raise RegistrationError('管理员名称需为 3–32 位字母、数字、下划线或短横线')
        scope=permissions(data.get('permissions',json.loads(old['permissions']) if old else PRESETS['observer']))
        enabled=data.get('enabled',bool(old['enabled']) if old else True)
        if type(enabled) is not bool:raise RegistrationError('启用状态需为布尔值')
        password=data.get('password','')
        if not isinstance(password,str) or (password and (not 10<=len(password)<=128 or any(ord(c)<32 for c in password))):raise RegistrationError('密码需为 10–128 位')
        if not old and not password:raise RegistrationError('新增管理员需要密码')
        if not old and self.db.execute('SELECT count(*) FROM admin_users').fetchone()[0]>=30:raise RegistrationError('最多创建 30 位管理员')
        # Hashing yields; recheck revision and limits afterwards.
        digest=await self.state['registration'].password_work.run(hash_password,password) if password else old['password_hash']
        latest=self.db.execute('SELECT * FROM admin_users WHERE id=?',(user_id,)).fetchone() if old else None
        if old and (not latest or latest['revision']!=old['revision']):raise RegistrationError('管理员已被修改，请刷新',409)
        if not old and self.db.execute('SELECT count(*) FROM admin_users').fetchone()[0]>=30:raise RegistrationError('最多创建 30 位管理员')
        collision=self.db.execute('SELECT id FROM admin_users WHERE lower(username)=lower(?)',(username,)).fetchone()
        if collision and (not old or collision['id']!=user_id):raise RegistrationError('管理员名称已存在',409)
        uid=user_id or uuid.uuid4().hex
        with self.db:
            self.db.execute('INSERT INTO admin_users VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET username=excluded.username,password_hash=excluded.password_hash,permissions=excluded.permissions,enabled=excluded.enabled,revision=excluded.revision',
                            (uid,username,digest,json.dumps(scope),int(enabled),old['revision']+1 if old else 1,old['created'] if old else time.time()))
            self.db.execute('DELETE FROM admin_sessions WHERE user_id=?',(uid,))
        self.state['store'].audit('admin',f'服主保存管理员 {username}；旧登录会话已撤销')
        return self.listing()

    async def login(self,data,remote):
        reg=self.state['registration']
        reg.limit('admin-login-ip:'+remote,20,300);reg.limit('admin-login-global',100,60)
        username,password=data.get('username'),data.get('password')
        if not isinstance(username,str) or len(username)>32 or not isinstance(password,str) or not 10<=len(password)<=128:raise RegistrationError('管理员名称或密码错误',401)
        reg.limit('admin-login-name:'+username.lower(),8,300)
        row=self.db.execute('SELECT * FROM admin_users WHERE lower(username)=lower(?)',(username,)).fetchone()
        digest=row['password_hash'] if row else 'pbkdf2_sha256$600000$'+'0'*32+'$'+'0'*64
        valid=await reg.password_work.run(check_password,password,digest)
        latest=self.db.execute('SELECT * FROM admin_users WHERE id=?',(row['id'],)).fetchone() if row else None
        if not valid or not latest or not latest['enabled'] or latest['revision']!=row['revision']:raise RegistrationError('管理员名称或密码错误',401)
        token=secrets.token_urlsafe(32)
        with self.db:
            self.db.execute('DELETE FROM admin_sessions WHERE expires<=?',(time.time(),))
            self.db.execute('DELETE FROM admin_sessions WHERE token_hash IN (SELECT token_hash FROM admin_sessions WHERE user_id=? ORDER BY expires DESC LIMIT -1 OFFSET 4)',(row['id'],))
            self.db.execute('INSERT INTO admin_sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),row['id'],time.time()+28800))
        self.state['store'].audit('admin',f'管理员 {username} 登录面板')
        return {'access_token':token,'expires_in':28800,'identity':self.identity(token)}


def required(request):
    path,method=request.path,request.method
    if path=='/api/statistics' and method!='GET':return 'stats.manage'
    if path in ('/api/session','/api/admin-auth/logout'):return 'status.read'
    if path=='/api/status':return 'status.read'
    if path=='/api/community-features' and method=='GET':return 'status.read'
    for prefix,scope in (('/api/diagnostics','diagnostics.run'),('/api/tickets','tickets.manage'),('/api/sanctions','sanctions.manage')):
        if path.startswith(prefix):return scope
    for prefix,scope in (('/api/player-','players.manage'),('/api/extensions','plugins.manage'),
                         ('/api/extension-documents','plugins.manage'),('/api/schedules','schedules.manage'),
                         ('/api/monitoring','monitoring.manage'),('/api/statistics','stats.read'),('/api/backup-policy','backups.manage')):
        if path.startswith(prefix):return scope
    if path.startswith('/api/whitelist') and not (path=='/api/whitelist/settings' and method=='PUT'):return 'whitelist.review'
    if path=='/api/operations/guide':return ('whitelist.review','schedules.manage')
    if path=='/api/backups':return 'backups.manage'
    if path.startswith('/api/backups/') and method=='DELETE':return 'backups.manage'
    return None # Secrets, root settings, backup downloads and restore require owner.


def setup_routes(app,state_key,read_body):
    state=app[state_key];service=state['admin_accounts']=AdminAccounts(state)
    @web.middleware
    async def access(request,handler):
        if not request.path.startswith('/api/') or request.path.startswith('/api/v1/') or request.path=='/api/admin-auth/login':return await handler(request)
        header=request.headers.get('Authorization','');token=header[7:] if header.startswith('Bearer ') else ''
        who=service.identity(token)
        if not who:return web.json_response({'error':'管理登录无效或已过期'},status=401,headers={'Cache-Control':'no-store'})
        scope=required(request)
        allowed = any(item in who['permissions'] for item in scope) if isinstance(scope, tuple) else scope in who['permissions']
        if not who['owner'] and not allowed:return web.json_response({'error':'没有此操作的管理权限'},status=403,headers={'Cache-Control':'no-store'})
        request[ADMIN_IDENTITY]=who
        response=await handler(request)
        if request.method not in ('GET','HEAD','OPTIONS') and response.status<400:
            state['store'].audit('admin',f"{who['username']} {request.method} {request.path}")
        return response
    app.middlewares.append(access)

    async def endpoint(request):
        try:
            if request.path=='/api/admin-auth/login':result=await service.login(await read_body(request),request.remote or 'unknown')
            elif request.path=='/api/admin-auth/logout':
                header=request.headers.get('Authorization','')
                with service.db:service.db.execute('DELETE FROM admin_sessions WHERE token_hash=?',(hashlib.sha256(header[7:].encode()).hexdigest(),))
                result={'ok':True}
            elif request.path=='/api/session':result=request[ADMIN_IDENTITY]
            elif request.method=='GET':result=service.listing()
            elif request.method=='DELETE':
                uid=request.match_info['uid'];data=await read_body(request)
                with service.db:
                    changed=service.db.execute('DELETE FROM admin_users WHERE id=? AND revision=?',(uid,data.get('revision'))).rowcount
                    if not changed:raise RegistrationError('管理员状态已变化，请刷新',409)
                    service.db.execute('DELETE FROM admin_sessions WHERE user_id=?',(uid,))
                result=service.listing()
            else:result=await service.save(await read_body(request),request.match_info.get('uid'))
            return web.json_response(result,headers={'Cache-Control':'no-store'})
        except RegistrationError as exc:return web.json_response({'error':str(exc)},status=exc.status)
    app.add_routes([web.get('/api/session',endpoint),web.post('/api/admin-auth/login',endpoint),web.post('/api/admin-auth/logout',endpoint),
                    web.get('/api/admin-users',endpoint),web.post('/api/admin-users',endpoint),
                    web.put('/api/admin-users/{uid:[a-f0-9]{32}}',endpoint),web.delete('/api/admin-users/{uid:[a-f0-9]{32}}',endpoint)])
