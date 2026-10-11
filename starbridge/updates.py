"""Owner-controlled package preparation. The stable supervisor performs offline switching."""
import ast
import asyncio
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time
from urllib.parse import urlsplit
import uuid
import venv
import zipfile

import aiohttp
from scripts import update_runtime as runtime
from . import __version__
from .registration import RegistrationError
from .github_updates import DEFAULT_SETTINGS, GitHubReleases, update_settings

MAX_PACKAGE = 64 * 1024 * 1024
PROBE = '''import asyncio,sys,tempfile
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from aiohttp import web,ClientSession
from starbridge.config import initialize,load
from starbridge.app import create_app
async def check():
    with tempfile.TemporaryDirectory(prefix="starbridge-update-check-") as tmp:
        path=Path(tmp)/"config.toml"; initialize(path); cfg=load(path)
        app=create_app(cfg,config_path=path); runner=web.AppRunner(app,access_log=None)
        try:
            await runner.setup(); site=web.TCPSite(runner,"127.0.0.1",0); await site.start()
            port=site._server.sockets[0].getsockname()[1]
            async with ClientSession() as client:
                async with client.get("http://127.0.0.1:"+str(port)+"/health") as response:
                    assert response.status==200
        finally: await runner.cleanup()
asyncio.run(check())
'''


def https_url(value):
    if not isinstance(value, str) or len(value) > 2000: raise RegistrationError('更新源地址错误')
    parts = urlsplit(value)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.fragment: raise RegistrationError('更新地址需为不含账号密码的 HTTPS 地址')
    return value


def extract_package(archive, destination):
    with zipfile.ZipFile(archive) as package:
        entries = package.infolist()
        if len(entries) > 1200 or sum(e.file_size for e in entries) > runtime.MAX_TOTAL: raise ValueError('更新包解压大小或文件数量超限')
        names = set(); folded = set()
        for entry in entries:
            if entry.is_dir(): continue
            if not entry.filename.startswith('StarBridge/'): raise ValueError('请上传完整的Myrinbot部署包')
            name = entry.filename[len('StarBridge/'):]
            target = runtime.safe(destination, name)
            if name.casefold() in folded or stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1 or entry.file_size > 32 * 1024 * 1024: raise ValueError('更新包包含重复、加密或不安全文件')
            names.add(name); folded.add(name.casefold())
            if name == 'update.json' and entry.file_size > 256 * 1024: raise ValueError('更新清单过大')
            if name != 'update.json' and name not in runtime.PROTECTED and not runtime.managed(name): raise ValueError('更新包含非部署文件：' + name)
            if name in runtime.PROTECTED: continue
            runtime.atomic(target, package.read(entry))
        manifest = runtime.manifest_check(runtime.read_json(destination / 'update.json'), destination)
        if names - manifest['files'].keys() - {'update.json'} - runtime.PROTECTED: raise ValueError('更新清单没有覆盖全部文件')
        for source in destination.rglob('*.py'): ast.parse(source.read_text(encoding='utf-8-sig'), filename=source.name)
        tree = ast.parse((destination / 'starbridge/__init__.py').read_text(encoding='utf-8-sig'))
        version = next((n.value.value for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '__version__' for t in n.targets) and isinstance(n.value, ast.Constant)), None)
        if version != manifest['version']: raise ValueError('包版本与代码版本不一致')
        return manifest


class Updates:
    def __init__(self, state, root=None):
        self.state = state; self.root = Path(root or Path(__file__).resolve().parent.parent).resolve()
        self.directory = runtime.safe(self.root, '.runtime/updates'); self.busy = False; self.task = None
        self.prepared = None; self.progress = {'status': 'idle', 'message': '连接 GitHub 检查正式版本，或上传部署包'}

    def config(self):
        row = self.state['store'].db.execute("SELECT value,revision FROM operations_settings WHERE key='updates'").fetchone()
        return {'settings': update_settings(json.loads(row['value']) if row else DEFAULT_SETTINGS), 'revision': row['revision'] if row else 0}

    def save(self, data):
        if self.busy or runtime.job_path(self.root).exists(): raise RegistrationError('正在准备或切换版本，请稍后修改更新源', 409)
        current = self.config(); settings = data.get('settings')
        if data.keys() - {'settings', 'revision', 'clear_github_token'} or not isinstance(settings, dict) or settings.keys() - DEFAULT_SETTINGS.keys() or type(data.get('clear_github_token', False)) is not bool: raise RegistrationError('更新设置格式错误')
        value = {**current['settings'], **settings}
        if 'source' not in settings and 'feed_url' in settings: value['source'] = 'https'
        if data.get('clear_github_token') or value['github_repository'] != current['settings']['github_repository']:
            value['github_token'] = settings.get('github_token', '') if not data.get('clear_github_token') else ''
        elif not settings.get('github_token'): value['github_token'] = current['settings']['github_token']
        settings = update_settings(value)
        if type(data['revision']) is not int or data['revision'] != current['revision']: raise RegistrationError('更新设置已变化，请刷新', 409)
        with self.state['store'].db:
            self.state['store'].db.execute("INSERT INTO operations_settings VALUES('updates',?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,revision=excluded.revision", (json.dumps(settings), current['revision'] + 1))
        return self.listing()

    def listing(self):
        history_path = runtime.safe(self.root, '.runtime/updates/history.json')
        history = runtime.read_json(history_path) if history_path.exists() else []
        config = self.config(); config['github_token_configured'] = bool(config['settings']['github_token']); config['settings']['github_token'] = ''
        return config | {'version': __version__, 'protocol': runtime.PROTOCOL, 'busy': self.busy, 'progress': self.progress,
                'can_apply': bool(self.state.get('restart_event')) and os.environ.get('STARBRIDGE_SUPERVISED') == '1',
                'prepared': {k: self.prepared[k] for k in ('id', 'version', 'sha256', 'size')} if self.prepared else None, 'history': list(reversed(history)), 'max_upload_bytes': MAX_PACKAGE}

    def require_idle(self):
        if self.busy or runtime.job_path(self.root).exists() or self.state.get('maintenance'): raise RegistrationError('已有升级、回退或恢复操作，请等待', 409)
        if not self.state['config_file']: raise RegistrationError('更新需要持久化部署', 503)
        self.directory.mkdir(parents=True, exist_ok=True)

    async def check_feed(self, tag=''):
        settings = self.config()['settings']
        if settings['source'] == 'github': return await GitHubReleases(settings).check(__version__, tag)
        if tag: raise RegistrationError('选择 GitHub 更新源后才能按版本下载')
        source = settings['feed_url']
        if not source: return {'available': False, 'message': '未配置更新源，可以上传部署包'}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15, connect=5)) as client:
            async with client.get(https_url(source), allow_redirects=False) as response:
                raw = await response.content.read(16385)
                if response.status != 200 or len(raw) > 16384: raise RegistrationError('更新清单不可访问或大小超限')
                try: value = json.loads(raw)
                except (ValueError, UnicodeError): raise RegistrationError('更新源没有返回 JSON') from None
        if not isinstance(value, dict) or value.keys() - {'version', 'url', 'sha256', 'notes', 'size'}: raise RegistrationError('更新源清单字段错误')
        https_url(value.get('url'))
        if not isinstance(value.get('version'), str) or not 1 <= len(value['version']) <= 40 or not isinstance(value.get('sha256'), str) or not re.fullmatch(r'[a-f0-9]{64}', value['sha256']): raise RegistrationError('更新源缺少版本或 SHA256')
        if 'size' in value and (type(value['size']) is not int or not 1 <= value['size'] <= MAX_PACKAGE): raise RegistrationError('更新源部署包大小错误')
        if 'notes' in value and (not isinstance(value['notes'], str) or len(value['notes']) > 3000): raise RegistrationError('更新说明过长')
        return value | {'available': value['version'] != __version__}

    async def releases(self):
        settings = self.config()['settings']
        if settings['source'] != 'github': return {'releases': [], 'source': settings['source']}
        return {'releases': await GitHubReleases(settings).releases(), 'source': 'github'}

    async def upload(self, stream):
        self.require_idle(); self.busy = True
        stage = runtime.folder(self.root, uuid.uuid4().hex)
        path = stage / 'upload.zip'; size = 0
        try:
            stage.mkdir(parents=True)
            await asyncio.to_thread(self.cleanup, [stage.name])
            with path.open('wb') as output:
                async for chunk in stream.iter_chunked(64 * 1024):
                    size += len(chunk)
                    if size > MAX_PACKAGE: raise RegistrationError('更新包最大 64 MiB', 413)
                    output.write(chunk)
            self.start_prepare(stage, size)
        except BaseException:
            self.busy = False; raise
        return self.listing()

    async def download(self, tag=''):
        self.require_idle(); self.busy = True
        stage = runtime.folder(self.root, uuid.uuid4().hex)
        try:
            stage.mkdir(parents=True)
            await asyncio.to_thread(self.cleanup, [stage.name])
            settings = self.config()['settings']
            info = await self.check_feed(tag); source = info.get('url')
            if not source and not info.get('asset_id'): raise RegistrationError('没有可下载的部署包，请检查更新源或上传部署包')
            size = 0
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120, connect=10, sock_read=15)) as client:
                request = GitHubReleases(settings).asset(client, info['asset_id']) if settings['source'] == 'github' else client.get(https_url(source), allow_redirects=False)
                async with request as response:
                    if response.status != 200: raise RegistrationError('部署包下载失败，请检查更新源与权限')
                    with (stage / 'upload.zip').open('wb') as output:
                        async for chunk in response.content.iter_chunked(64 * 1024):
                            size += len(chunk)
                            if size > MAX_PACKAGE: raise RegistrationError('更新包超过 64 MiB')
                            output.write(chunk)
            if 'size' in info and size != info['size']: raise RegistrationError('下载包大小与版本清单不一致，未准备升级')
            if await asyncio.to_thread(runtime.sha, stage / 'upload.zip') != info['sha256']: raise RegistrationError('下载包 SHA256 不符，未准备升级')
            self.start_prepare(stage, size)
        except BaseException:
            self.busy = False; raise
        return self.listing()

    def start_prepare(self, stage, size):
        self.prepared = None; self.progress = {'status': 'preparing', 'message': '校验文件并测试新版本启动，必要时建立独立运行环境'}
        async def prepare():
            try:
                manifest = await asyncio.to_thread(self.verify, stage)
                self.prepared = {'id': stage.name, 'version': manifest['version'], 'sha256': await asyncio.to_thread(runtime.sha, stage / 'upload.zip'), 'size': size}
                self.progress = {'status': 'ready', 'message': '包校验和隔离启动检查通过，可以升级'}
            except Exception as exc:
                self.progress = {'status': 'failed', 'message': '准备失败：' + (str(exc) if isinstance(exc, (ValueError, RegistrationError)) else type(exc).__name__)}
            finally: self.busy = False
        self.task = asyncio.create_task(prepare())

    def verify(self, stage):
        package = stage / 'package'; package.mkdir()
        manifest = extract_package(stage / 'upload.zip', package)
        runtime.atomic(package / 'scripts/update_runtime.py', (self.root / 'scripts/update_runtime.py').read_bytes())
        pins = []
        for line in (package / 'requirements.lock.txt').read_text().splitlines():
            if not line.strip() or line.startswith('#'): continue
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,79}==[0-9][A-Za-z0-9_.+-]{0,39}', line): raise ValueError('依赖需为明确的包名与固定版本')
            pins.append(line)
        missing = False
        for pin in pins:
            name, version = pin.split('==')
            try: missing |= importlib.metadata.version(name) != version
            except importlib.metadata.PackageNotFoundError: missing = True
        python = sys.executable
        if missing:
            venv.EnvBuilder(with_pip=True).create(stage / 'runtime')
            python = str(stage / 'runtime' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python'))
            environment = {k: v for k, v in os.environ.items() if not k.startswith('PIP_')}
            environment |= {'PIP_CONFIG_FILE': os.devnull, 'PIP_NO_INPUT': '1'}
            result = subprocess.run([python, '-m', 'pip', 'install', '--only-binary=:all:', '--index-url', 'https://pypi.org/simple', *pins], env=environment, capture_output=True, timeout=240)
            if result.returncode: raise ValueError('独立环境的依赖安装失败，请检查 PyPI 网络连接和 Python 版本')
        result = subprocess.run([python, '-c', PROBE, str(package)], cwd=package, capture_output=True, timeout=45)
        (stage / 'validation.log').write_bytes(result.stderr[-32000:])
        if result.returncode: raise ValueError('新版本未通过隔离启动检查，当前服务未修改')
        return manifest

    async def apply(self, data, rollback=False):
        self.require_idle()
        if os.environ.get('STARBRIDGE_SUPERVISED') != '1' or self.state['restart_event'] is None: raise RegistrationError('请用Myrinbot.bat（或旧入口）或 python -m starbridge run 启动，才能在线升级', 503)
        if data.keys() != {'id'} or not isinstance(data['id'], str): raise RegistrationError('请选择已准备的版本')
        if rollback:
            source = runtime.folder(self.root, data['id'])
            history = self.listing()['history']; item = next((i for i in history if i['id'] == data['id'] and i['status'] == 'success'), None)
            if not item or not (source / 'rollback/capture.json').is_file(): raise RegistrationError('回退副本不可用', 404)
            stage = runtime.folder(self.root, uuid.uuid4().hex); stage.mkdir()
            version = item['previous_version']
        else:
            if not self.prepared or self.prepared['id'] != data['id']: raise RegistrationError('更新预览已失效，请重新准备', 409)
            stage = runtime.folder(self.root, data['id']); version = self.prepared['version']
            if runtime.sha(stage / 'upload.zip') != self.prepared['sha256']: raise RegistrationError('包内容已变化，未升级', 409)
            runtime.manifest_check(runtime.read_json(stage / 'package/update.json'), stage / 'package')
        self.busy = True; self.state['maintenance'] = True
        try:
            safety = await self.state['backups'].create('before_rollback' if rollback else 'before_update')
            pointer = runtime.safe(self.root, '.runtime/updates/runtime.json')
            previous_runtime = runtime.read_json(pointer).get('stage', '') if pointer.exists() else ''
            job = {'id': stage.name, 'phase': 'pending', 'mode': 'rollback' if rollback else 'update', 'version': version,
                   'previous_version': __version__, 'previous_runtime': previous_runtime, 'created': time.time(), 'safety_backup': safety['id']}
            if rollback: job['source'] = source.name
            installed = runtime.safe(self.root, '.runtime/updates/installed.json')
            if installed.exists(): runtime.atomic(stage / 'previous-installed.json', installed.read_bytes())
            runtime.write_json(stage / 'job-metadata.json', job); runtime.write_json(runtime.job_path(self.root), job)
            self.state['store'].audit('update', ('准备回退至 ' if rollback else '准备升级至 ') + version)
            asyncio.get_running_loop().call_later(0.5, self.state['restart_event'].set)
            return {'ok': True, 'version': version, 'safety_backup': safety['id'], 'message': '服务将切换版本，请稍后重新连接面板'}
        except BaseException:
            self.state['maintenance'] = False; self.busy = False; raise

    def cleanup(self, keep=()):
        self.directory.mkdir(parents=True, exist_ok=True)
        history_path = self.directory / 'history.json'; history = runtime.read_json(history_path) if history_path.exists() else []
        history = history[-5:]
        protected = {h['id'] for h in history} | {h.get('previous_runtime', '') for h in history} | set(keep)
        pointer = self.directory / 'runtime.json'
        if pointer.exists(): protected.add(runtime.read_json(pointer).get('stage', ''))
        if self.prepared: protected.add(self.prepared['id'])
        removed = 0
        for entry in self.directory.iterdir():
            if re.fullmatch(r'[a-f0-9]{32}', entry.name) and entry.name not in protected:
                path = runtime.folder(self.root, entry.name)
                if path.is_dir(): shutil.rmtree(path); removed += 1
        if history_path.exists(): runtime.write_json(history_path, history)
        return {'removed': removed}

    async def close(self):
        if self.task: await asyncio.shield(self.task)
