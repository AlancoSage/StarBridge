"""Panel accounts and server-enforced capability checks."""
import hashlib
import json
import re
import secrets
import sqlite3
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
SESSION_SECONDS = 28800


def credentials(data):
    username,password=data.get('username'),data.get('password')
    if not isinstance(username,str) or not re.fullmatch(r'[A-Za-z0-9_\-]{3,32}',username):
        raise RegistrationError('管理员名称需为 3–32 位字母、数字、下划线或短横线')
    if not isinstance(password,str) or not 10<=len(password)<=128 or any(ord(c)<32 or ord(c)==127 for c in password):
        raise RegistrationError('密码需为 10–128 位，不能包含控制字符')
    return username,password


def permissions(value):
    if not isinstance(value,list) or any(not isinstance(v,str) or v not in PERMISSIONS for v in value) or len(value)!=len(set(value)):
        raise RegistrationError('管理员权限格式错误')
    if 'status.read' not in value:
        raise RegistrationError('管理员需要运行概览权限')
    return sorted(value)


class AdminAccounts:
    def __init__(self,state):
        self.state=state;self.db=state['store'].db

    def owner(self):
        return self.db.execute("SELECT * FROM admin_owner WHERE id='owner'").fetchone()

    def setup_required(self):
        return self.owner() is None

    def bootstrap_authorized(self,request):
        supplied=request.headers.get('Authorization','').encode()
        expected=('Bearer '+self.state['config']['app']['admin_token']).encode()
        if not secrets.compare_digest(supplied,expected):
            raise RegistrationError('需要当前管理令牌授权创建服主账号',401)

    async def setup_owner(self,data,recheck):
        recheck()
        if not self.setup_required():raise RegistrationError('服主账号已创建，请直接登录',409)
        if data.keys()-{'username','password'}:raise RegistrationError('服主账号请求包含未知字段')
        username,password=credentials(data)
        digest=await self.state['registration'].password_work.run(hash_password,password)
        recheck()
        try:
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                if not self.setup_required():raise RegistrationError('服主账号已创建，请直接登录',409)
                if self.db.execute('SELECT id FROM admin_users WHERE lower(username)=lower(?)',(username,)).fetchone():
                    raise RegistrationError('管理员名称已存在',409)
                self.db.execute('INSERT INTO admin_owner VALUES(?,?,?,?,?)',('owner',username,digest,1,time.time()))
        except sqlite3.IntegrityError:
            raise RegistrationError('服主账号已创建，请刷新后登录',409) from None
        self.state['store'].audit('admin',f'服主账号 {username} 已创建')
        return self.session('owner',username)

    def identity(self,token):
        root=self.state['config']['app']['admin_token']
        if secrets.compare_digest(token.encode(),root.encode()):
            return {'id':'owner','username':'服主','owner':True,'permissions':list(PERMISSIONS)}
        session=self.db.execute('SELECT user_id FROM admin_sessions WHERE token_hash=? AND expires>?',
                                (hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
        if not session:return None
        if session['user_id']=='owner':
            row=self.owner()
            return {'id':'owner','username':row['username'],'owner':True,'permissions':list(PERMISSIONS)} if row else None
        row=self.db.execute('SELECT * FROM admin_users WHERE id=? AND enabled=1',(session['user_id'],)).fetchone()
        return {'id':row['id'],'username':row['username'],'owner':False,'permissions':json.loads(row['permissions'])} if row else None

    def authorized_identity(self,request):
        header=request.headers.get('Authorization','');token=header[7:] if header.startswith('Bearer ') else ''
        who=self.identity(token)
        if not who:raise web.HTTPUnauthorized(text='管理登录无效或已过期')
        scope=required(request)
        allowed=any(item in who['permissions'] for item in scope) if isinstance(scope,tuple) else scope in who['permissions']
        if not who['owner'] and not allowed:raise web.HTTPForbidden(text='没有此操作的管理权限')
        request[ADMIN_IDENTITY]=who
        return who

    def session(self,user_id,username):
        token=secrets.token_urlsafe(32);now=time.time()
        with self.db:
            self.db.execute('DELETE FROM admin_sessions WHERE expires<=?',(now,))
            self.db.execute('DELETE FROM admin_sessions WHERE token_hash IN (SELECT token_hash FROM admin_sessions WHERE user_id=? ORDER BY expires DESC LIMIT -1 OFFSET 4)',(user_id,))
            self.db.execute('INSERT INTO admin_sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),user_id,now+SESSION_SECONDS))
        self.state['store'].audit('admin',f'管理员 {username} 登录面板')
        return {'access_token':token,'expires_in':SESSION_SECONDS,'identity':self.identity(token)}

    def listing(self):
        users=[{k:row[k] for k in ('id','username','enabled','revision','created')}|{'permissions':json.loads(row['permissions'])}
               for row in self.db.execute('SELECT * FROM admin_users ORDER BY created')]
        return {'users':users,'permissions':PERMISSIONS,'presets':PRESETS}

    async def save(self,data,user_id=None,recheck=lambda:None):
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
        if not isinstance(password,str) or (password and (not 10<=len(password)<=128 or any(ord(c)<32 or ord(c)==127 for c in password))):raise RegistrationError('密码需为 10–128 位')
        if not old and not password:raise RegistrationError('新增管理员需要密码')
        if not old and self.db.execute('SELECT count(*) FROM admin_users').fetchone()[0]>=30:raise RegistrationError('最多创建 30 位管理员')
        # Hashing yields; recheck revision and limits afterwards.
        digest=await self.state['registration'].password_work.run(hash_password,password) if password else old['password_hash']
        uid=user_id or uuid.uuid4().hex
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            recheck()
            latest=self.db.execute('SELECT * FROM admin_users WHERE id=?',(user_id,)).fetchone() if old else None
            if old and (not latest or latest['revision']!=old['revision']):raise RegistrationError('管理员已被修改，请刷新',409)
            if not old and self.db.execute('SELECT count(*) FROM admin_users').fetchone()[0]>=30:raise RegistrationError('最多创建 30 位管理员')
            collision=self.db.execute('SELECT id FROM admin_users WHERE lower(username)=lower(?)',(username,)).fetchone()
            if collision and (not old or collision['id']!=user_id):raise RegistrationError('管理员名称已存在',409)
            if self.db.execute('SELECT id FROM admin_owner WHERE lower(username)=lower(?)',(username,)).fetchone():
                raise RegistrationError('管理员名称已存在',409)
            self.db.execute('INSERT INTO admin_users VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET username=excluded.username,password_hash=excluded.password_hash,permissions=excluded.permissions,enabled=excluded.enabled,revision=excluded.revision',
                            (uid,username,digest,json.dumps(scope),int(enabled),old['revision']+1 if old else 1,old['created'] if old else time.time()))
            self.db.execute('DELETE FROM admin_sessions WHERE user_id=?',(uid,))
        self.state['store'].audit('admin',f'服主保存管理员 {username}；旧登录会话已撤销')
        return self.listing()

    async def login(self,data,remote):
        reg=self.state['registration']
        reg.limit('admin-login-ip:'+remote,20,300);reg.limit('admin-login-global',100,60)
        username,password=data.get('username'),data.get('password')
        if not isinstance(username,str) or len(username)>32 or not isinstance(password,str) or not 10<=len(password)<=128 or any(ord(c)<32 or ord(c)==127 for c in password):raise RegistrationError('管理员名称或密码错误',401)
        reg.limit('admin-login-name:'+username.lower(),8,300)
        row=self.db.execute('SELECT * FROM admin_owner WHERE lower(username)=lower(?)',(username,)).fetchone()
        owner=row is not None
        if not owner:row=self.db.execute('SELECT * FROM admin_users WHERE lower(username)=lower(?)',(username,)).fetchone()
        digest=row['password_hash'] if row else 'pbkdf2_sha256$600000$'+'0'*32+'$'+'0'*64
        valid=await reg.password_work.run(check_password,password,digest)
        table='admin_owner' if owner else 'admin_users'
        latest=self.db.execute('SELECT * FROM '+table+' WHERE id=?',(row['id'],)).fetchone() if row else None
        if not valid or not latest or (not owner and (not latest['enabled'] or row['id']=='owner')) or latest['revision']!=row['revision'] or latest['password_hash']!=digest:raise RegistrationError('管理员名称或密码错误',401)
        return self.session(row['id'],latest['username'])


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
        if not request.path.startswith('/api/') or request.path.startswith('/api/v1/') or request.path in ('/api/admin-auth/login','/api/admin-auth/setup'):return await handler(request)
        try:who=service.authorized_identity(request)
        except (web.HTTPUnauthorized,web.HTTPForbidden) as exc:
            return web.json_response({'error':exc.text},status=exc.status,headers={'Cache-Control':'no-store'})
        response=await handler(request)
        if request.method not in ('GET','HEAD','OPTIONS') and response.status<400:
            state['store'].audit('admin',f"{who['username']} {request.method} {request.path}")
        return response
    app.middlewares.append(access)

    async def endpoint(request):
        try:
            if request.path=='/api/admin-auth/setup':
                if request.method in ('GET','HEAD'):result={'required':service.setup_required()}
                else:
                    service.bootstrap_authorized(request)
                    result=await service.setup_owner(await read_body(request),lambda:service.bootstrap_authorized(request))
            elif request.path=='/api/admin-auth/login':result=await service.login(await read_body(request),request.remote or 'unknown')
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
            else:result=await service.save(await read_body(request),request.match_info.get('uid'),lambda:service.authorized_identity(request))
            return web.json_response(result,headers={'Cache-Control':'no-store'})
        except RegistrationError as exc:return web.json_response({'error':str(exc)},status=exc.status,headers={'Cache-Control':'no-store'})
    app.add_routes([web.get('/api/admin-auth/setup',endpoint),web.post('/api/admin-auth/setup',endpoint),
                    web.get('/api/session',endpoint),web.post('/api/admin-auth/login',endpoint),web.post('/api/admin-auth/logout',endpoint),
                    web.get('/api/admin-users',endpoint),web.post('/api/admin-users',endpoint),
                    web.put('/api/admin-users/{uid:[a-f0-9]{32}}',endpoint),web.delete('/api/admin-users/{uid:[a-f0-9]{32}}',endpoint)])
