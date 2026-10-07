"""Owner-only configuration previews and bounded connection diagnostics."""
import asyncio
from copy import deepcopy
import json
import platform
import secrets
import shutil
import smtplib
import ssl
import time
import tomllib
from urllib.parse import urlsplit

import aiohttp
from .authentication import validate_settings as validate_auth
from .extensions import atomic_json
from .registration import RegistrationError
from .settings import validate


class Deployment:
    def __init__(self, state):
        self.state = state; self.previews = {}; self.lock = asyncio.Lock(); self.probing = False

    def export(self):
        if not self.state['config_file']: raise RegistrationError('此实例没有配置文件', 503)
        cfg, _ = self.state['config_file'].read()
        cfg['app']['admin_token'] = '<保留本机令牌>'
        cfg['onebot']['token'] = '<保留本机令牌>'
        for server in cfg['servers']: server['token'] = '<自动生成或保留>'
        cfg['replies'] = {}
        return {'format': 'starbridge-config-v1', 'config': cfg, 'authentication': self.state['authentication'].config_response()['settings']}

    def preview(self, data):
        if data.keys() - {'content', 'template'} or bool(data.get('content')) == bool(data.get('template')): raise RegistrationError('请选择模板或上传配置内容')
        if not self.state['config_file']: raise RegistrationError('此实例没有配置文件', 503)
        current, revision = self.state['config_file'].read(); candidate = deepcopy(current); auth = None
        template = data.get('template')
        if template:
            if template not in ('single', 'multi', 'qq_login', 'chat_only'): raise RegistrationError('部署模板不存在')
            if not candidate['servers']:
                candidate['servers'] = [{'id': 'survival', 'name': '生存服', 'token': secrets.token_hex(32), 'groups': [], 'commands': {}}]
            if template == 'multi' and len(candidate['servers']) < 2:
                ids = {s['id'] for s in candidate['servers']}; sid = next('creative' + (str(i) if i else '') for i in range(101) if 'creative' + (str(i) if i else '') not in ids)
                candidate['servers'].append({'id': sid, 'name': '创造服', 'token': secrets.token_hex(32), 'groups': [], 'commands': {}})
            candidate['features'].update(qq_to_mc=True, mc_to_qq=True, join_quit=True)
            if template in ('qq_login', 'chat_only'):
                auth = deepcopy(self.state['authentication'].settings)
                auth.update(enabled_servers=[s['id'] for s in candidate['servers']] if template == 'qq_login' else [], password_login=template != 'qq_login', qq_login=True)
        else:
            content = data['content']
            if not isinstance(content, str) or len(content.encode()) > 200 * 1024: raise RegistrationError('配置文件最大 200 KiB')
            try:
                raw = json.loads(content) if content.lstrip().startswith('{') else tomllib.loads(content)
                if not isinstance(raw, dict): raise ValueError()
                if raw.get('format') == 'starbridge-config-v1':
                    if raw.keys() - {'format', 'config', 'authentication'}: raise ValueError()
                    candidate = deepcopy(raw['config']); auth = raw.get('authentication')
                else: candidate = deepcopy(raw)
            except (ValueError, KeyError, TypeError): raise RegistrationError('配置需为有效 TOML 或星桥导出的 JSON') from None
            if not isinstance(candidate, dict) or not isinstance(candidate.get('onebot'), dict) or not isinstance(candidate.get('servers'), list): raise RegistrationError('配置缺少 QQ 设置或服务器列表')
            old = {s['id']: s for s in current['servers']}
            candidate['app'] = deepcopy(current['app']); candidate['onebot']['token'] = current['onebot']['token']
            for server in candidate['servers']:
                if not isinstance(server, dict): raise RegistrationError('服务器格式错误')
                server['token'] = old.get(server.get('id'), {}).get('token') or secrets.token_hex(32)
            candidate['replies'] = deepcopy(current.get('replies', {}))
        candidate = validate(candidate)
        if auth is not None:
            auth = validate_auth(auth)
            if set(auth['enabled_servers']) - {s['id'] for s in candidate['servers']}: raise RegistrationError('登录模板包含未配置服务器')
        now = time.time(); self.previews = {k: v for k, v in self.previews.items() if v['expires'] > now}
        if len(self.previews) >= 10: raise RegistrationError('预览数量过多，请稍后重试', 429)
        pid = secrets.token_hex(16)
        preview = {'id': pid, 'config': candidate, 'authentication': auth, 'revision': revision, 'auth_revision': self.state['authentication'].revision, 'expires': now + 300}
        self.previews[pid] = preview
        old_ids = {s['id'] for s in current['servers']}; new_ids = {s['id'] for s in candidate['servers']}
        return {'preview_id': pid, 'expires_in': 300, 'servers': [{'id': s['id'], 'name': s['name'], 'groups': s['groups']} for s in candidate['servers']],
                'added': sorted(new_ids - old_ids), 'removed': sorted(old_ids - new_ids), 'features': candidate['features'], 'authentication': auth,
                'preserved': ['本机面板地址、端口、数据库和管理令牌', 'QQ 连接令牌与现有同 ID 游戏令牌', '关键词插件和业务数据']}

    async def apply(self, pid, commit, recheck):
        async with self.lock:
            row = self.previews.get(pid)
            if not row or row['expires'] <= time.time(): raise RegistrationError('预览已失效，请重新导入', 409)
            auth = self.state['authentication']
            async with auth.lock:
                recheck()
                if row['authentication'] is not None and row['auth_revision'] != auth.revision: raise RegistrationError('游戏登录设置已变化，请重新预览', 409)
                previous, _ = self.state['config_file'].read()
                result = await commit(self.state, {'config': row['config'], 'revision': row['revision']}, recheck)
                if result.status >= 400: return result
                if row['authentication'] is not None:
                    try: atomic_json(auth.path, row['authentication'])
                    except OSError:
                        _, latest_revision = self.state['config_file'].read()
                        await commit(self.state, {'config': previous, 'revision': latest_revision}, recheck)
                        raise RegistrationError('登录策略写入失败，已恢复原配置', 500) from None
                    auth.settings = row['authentication']; auth.sessions.clear()
                self.previews.pop(pid, None)
                self.state['store'].audit('deployment', '已应用部署模板或导入配置')
                return result

    def diagnostics(self):
        state = self.state; checks = []
        def add(key, title, status, detail, fix=''): checks.append({'id': key, 'title': title, 'status': status, 'detail': detail, 'fix': fix})
        add('python', 'Python 运行环境', 'ok', platform.python_version() + ' · ' + platform.system())
        connected = state['onebot'].connected
        add('onebot', 'QQ 机器人', 'ok' if connected else 'error', 'OneBot WebSocket 已连接' if connected else '尚未连接 OneBot', '在 QQ 实现端设置通用反向 WebSocket 地址及独立令牌。' if not connected else '')
        for sid, server in state['bot'].servers.items():
            snapshot = state['bot'].snapshots.get(sid, {}); online = state['bot'].online(sid)
            add('server:' + sid, server['name'], 'ok' if online else 'error',
                (snapshot.get('server_software', '未知核心') + ' · ' + snapshot.get('version', '未知版本') + ' · Java ' + snapshot.get('java_version', '未上报')) if online else '没有收到近期心跳',
                '' if online else '检查游戏插件的 Bot 地址、服务器 ID、令牌和网络可达性。')
            if online and 'managed_sanctions' not in snapshot.get('capabilities', []): add('plugin:' + sid, server['name'] + ' · 处罚能力', 'warning', '游戏插件需要更新', '下载当前面板提供的 JAR，保留配置并重启游戏服。')
        if not state['bot'].servers: add('servers', '游戏服务器', 'warning', '尚未添加服务器', '在服务器列表添加，或使用单服部署模板。')
        registration = state['registration']
        configured = all(registration.settings[k] for k in ('smtp_host', 'smtp_from', 'smtp_username', 'smtp_password'))
        add('smtp', '邮件服务', 'warning' if configured else 'skipped', '已配置，尚未进行连通与认证检查' if configured else '未配置 SMTP', '点“检测 SMTP”验证连接；检测不会发送邮件。' if configured else '需要邮件注册时，在注册账号页面填写 SMTP。')
        website = state['website']
        add('website', '官网 API', 'error' if website.error else 'warning' if website.settings['connection_enabled'] else 'skipped', website.error or ('已绑定，需检测公开 API' if website.settings['connection_enabled'] else '未接入官网'), '公开 API 检测只读取社区信息，不携带管理密钥。')
        path = state['config_file'].path.parent if state['config_file'] else state['registration'].path.parent
        free = shutil.disk_usage(path).free
        add('disk', '可用磁盘', 'ok' if free >= 256 * 1024 * 1024 else 'warning', f'{free // (1024 * 1024)} MiB 可用', '升级前需留出代码与数据备份的空间。')
        return {'checked_at': time.time(), 'checks': checks}

    async def probe(self, kind):
        if kind not in ('smtp', 'website'): raise RegistrationError('检测类型错误')
        if self.probing: raise RegistrationError('已有检测正在进行，请稍候', 409)
        self.probing = True
        try:
            if kind == 'smtp':
                settings = deepcopy(self.state['registration'].settings)
                if not settings['smtp_host'] or not settings['smtp_from']: raise RegistrationError('请先配置 SMTP')
                def check():
                    context = ssl.create_default_context()
                    factory = smtplib.SMTP_SSL if settings['smtp_security'] == 'ssl' else smtplib.SMTP
                    options = {'context': context} if factory is smtplib.SMTP_SSL else {}
                    with factory(settings['smtp_host'], settings['smtp_port'], timeout=5, **options) as smtp:
                        smtp.ehlo()
                        if settings['smtp_security'] == 'starttls': smtp.starttls(context=context); smtp.ehlo()
                        if settings['smtp_username']: smtp.login(settings['smtp_username'], settings['smtp_password'])
                    return {'status': 'ok', 'detail': 'TLS 连接与 SMTP 认证通过；未发送邮件'}
                # Keep the slot occupied until the bounded socket worker has really finished.
                task = asyncio.create_task(asyncio.to_thread(check))
                try: return await asyncio.shield(task)
                except asyncio.CancelledError: await task; raise
            source = self.state['website'].settings['api_public_url'].rstrip('/')
            parts = urlsplit(source)
            if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password: raise RegistrationError('请填写完整 Bot 公开 API 地址；相对地址可使用网站绑定页面的浏览器检测')
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12, connect=5)) as client:
                async with client.get(source + '/community/info', allow_redirects=False) as response:
                    raw = await response.content.read(16385)
                    if response.status != 200 or len(raw) > 16384: raise RegistrationError('公开 API 状态或响应大小不正确')
                    try: value = json.loads(raw)
                    except (ValueError, UnicodeError): raise RegistrationError('公开 API 没有返回 JSON') from None
                    if not isinstance(value, dict) or 'title' not in value: raise RegistrationError('此地址不是星桥社区 API')
                    return {'status': 'ok', 'detail': '公开社区 API 可访问，未携带任何密钥'}
        except (smtplib.SMTPException, OSError, aiohttp.ClientError, TimeoutError):
            return {'status': 'error', 'detail': '连接或认证失败，请检查主机、端口、TLS、网络与授权码'}
        finally: self.probing = False
