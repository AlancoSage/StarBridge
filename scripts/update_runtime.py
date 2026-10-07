"""Stable, stdlib-only update supervisor. Web updates never replace this file."""
from contextlib import closing
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import tomllib
import uuid

PROTOCOL = 1
MAX_TOTAL = 128 * 1024 * 1024
PROTECTED = {'scripts/update_runtime.py'}


def safe(root, name):
    root = Path(root).resolve(); raw = PurePosixPath(name)
    if not isinstance(name, str) or not name or '\\' in name or ':' in name or raw.is_absolute() or any(p in ('', '.', '..') for p in name.split('/')):
        raise ValueError('不安全的更新路径')
    path = root.joinpath(*raw.parts)
    current = path
    while current != root:
        if current.is_symlink(): raise ValueError('更新不允许符号链接')
        current = current.parent
    if not path.resolve().is_relative_to(root): raise ValueError('更新路径超出安装目录')
    return path


def managed(name):
    if name in PROTECTED: return False
    path = PurePosixPath(name)
    if any(p.startswith('.') for p in path.parts): return False
    if name in ('README.md', 'config.example.toml', 'requirements.txt', 'requirements.lock.txt', '星桥.bat'): return True
    if len(path.parts) == 2 and path.parts[0] == 'starbridge': return path.suffix in ('.py', '.js', '.html', '.css')
    if path.parts[0] in ('docs', 'examples', 'scripts'): return path.suffix in {'.md', '.json', '.js', '.py'}
    if len(path.parts) == 3 and path.parts[:2] == ('bridge', 'target'): return path.name.startswith('StarBridge-') and path.suffix == '.jar'
    return name == 'dist/StarBridge-website.zip'


def atomic(path, content):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(prefix='.update-', dir=path.parent)
    try:
        with os.fdopen(handle, 'wb') as output:
            output.write(content); output.flush(); os.fsync(output.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def write_json(path, value): atomic(path, json.dumps(value, ensure_ascii=False, sort_keys=True).encode())
def read_json(path): return json.loads(Path(path).read_text(encoding='utf-8'))
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def folder(root, stage):
    if not isinstance(stage, str) or len(stage) != 32 or any(c not in '0123456789abcdef' for c in stage): raise ValueError('更新编号错误')
    return safe(root, '.runtime/updates/' + stage)  # Internal paths are checked separately from package paths.


def manifest_check(manifest, source):
    if not isinstance(manifest, dict) or manifest.get('format') != 'starbridge-update-v1' or manifest.get('protocol') != PROTOCOL:
        raise ValueError('更新包不支持当前升级协议')
    version = manifest.get('version'); files = manifest.get('files')
    if not isinstance(version, str) or not 1 <= len(version) <= 40 or not isinstance(files, dict) or not 4 <= len(files) <= 1000: raise ValueError('更新清单格式错误')
    required = {'starbridge/__init__.py', 'starbridge/__main__.py', 'starbridge/app.py', 'requirements.lock.txt'}
    if not required <= files.keys(): raise ValueError('更新包缺少核心文件')
    for name, digest in files.items():
        if not managed(name) or not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest): raise ValueError('更新清单包含不允许的路径或校验值')
        path = safe(source, name)
        if not path.is_file() or sha(path) != digest: raise ValueError('更新文件校验失败：' + name)
    return manifest


def managed_files(root):
    names = []
    for directory in ('starbridge', 'docs', 'examples', 'scripts', 'bridge/target', 'dist'):
        path = safe(root, directory)
        if not path.exists(): continue
        for entry in path.rglob('*'):
            if entry.is_file():
                name = entry.relative_to(root).as_posix()
                if managed(name): safe(root, name); names.append(name)
    for name in ('README.md', 'config.example.toml', 'requirements.txt', 'requirements.lock.txt', '星桥.bat'):
        if safe(root, name).is_file(): names.append(name)
    return sorted(set(names))


def state_files(config):
    config = Path(config).resolve(); base = config.parent
    names = ['data/registration-settings.json', 'data/authentication-settings.json', 'data/plugin-state.json', 'data/website-settings.json']
    names += [p.relative_to(base).as_posix() for p in safe(base, 'plugins').glob('*.json')]
    return {'config.toml': config, **{name: safe(base, name) for name in names}}


def database_path(config):
    value = tomllib.loads(Path(config).read_text(encoding='utf-8'))['app']['database']
    if value == ':memory:': raise ValueError('更新需要持久化数据库')
    path = Path(value)
    return path.resolve() if path.is_absolute() else (Path(config).resolve().parent / path).resolve()


def copy_database(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source)) as original, closing(sqlite3.connect(destination)) as target: original.backup(target)


def capture(root, config, destination):
    names = managed_files(root)
    for name in names: atomic(safe(destination / 'code', name), safe(root, name).read_bytes())
    settings = {name: path for name, path in state_files(config).items() if path.exists()}
    for name, path in settings.items(): atomic(safe(destination / 'state', name), path.read_bytes())
    copy_database(database_path(config), destination / 'state/database.sqlite3')
    write_json(destination / 'capture.json', {'files': names, 'state': list(settings)})


def restore_capture(root, config, source):
    info = read_json(source / 'capture.json'); original = info['files']
    if any(not managed(name) for name in original): raise ValueError('代码回退清单错误')
    for name in set(managed_files(root)) - set(original): safe(root, name).unlink()
    for name in original: atomic(safe(root, name), safe(source / 'code', name).read_bytes())
    current = state_files(config); existing = info['state']
    for name in existing:
        if name not in current and not (name.startswith('plugins/') and PurePosixPath(name).suffix == '.json'): raise ValueError('数据回退路径错误')
        current.setdefault(name, safe(Path(config).resolve().parent, name))
    for name, target in current.items():
        if name in existing: atomic(target, safe(source / 'state', name).read_bytes())
        elif target.exists(): target.unlink()
    copy_database(source / 'state/database.sqlite3', database_path(config))
    clear_caches(root)


def clear_caches(root):
    for p in safe(root, 'starbridge').rglob('*.pyc'):
        safe(root, p.relative_to(root).as_posix()).unlink()


def job_path(root): return safe(root, '.runtime/updates/job.json')


def apply_pending(root, config):
    journal = job_path(root)
    if not journal.exists(): return None
    job = read_json(journal); stage = folder(root, job['id'])
    if job.get('phase') in ('applying', 'applied'):
        rollback(root, config, '上次升级中断，已恢复升级前版本与数据'); return None
    if job.get('phase') != 'pending' or job.get('mode') not in ('update', 'rollback'): raise ValueError('升级日志格式错误')
    try:
        if job['mode'] == 'update':
            manifest = manifest_check(read_json(stage / 'package/update.json'), stage / 'package')
        else:
            source = folder(root, job['source']) / 'rollback'
            read_json(source / 'capture.json')
        capture(root, config, stage / 'rollback')
        job['phase'] = 'applying'; write_json(journal, job)
        if job['mode'] == 'update':
            for name in set(managed_files(root)) - manifest['files'].keys(): safe(root, name).unlink()
            for name in manifest['files']: atomic(safe(root, name), safe(stage / 'package', name).read_bytes())
            clear_caches(root)
        else: restore_capture(root, config, source)
        job['phase'] = 'applied'; write_json(journal, job)
        return job
    except Exception:
        rollback(root, config, '升级写入失败，已恢复升级前版本与数据'); return None


def rollback(root, config, message):
    journal = job_path(root); job = read_json(journal); stage = folder(root, job['id'])
    if job.get('phase') != 'pending': restore_capture(root, config, stage / 'rollback')
    pointer = safe(root, '.runtime/updates/runtime.json')
    write_json(pointer, {'stage': job.get('previous_runtime', '')})
    record(root, job, 'rolled_back', message); journal.unlink()


def record(root, job, status, message):
    path = safe(root, '.runtime/updates/history.json'); history = read_json(path) if path.exists() else []
    history.append({k: job.get(k) for k in ('id', 'mode', 'version', 'previous_version', 'created', 'safety_backup', 'previous_runtime') } | {'status': status, 'message': message, 'finished': time.time()})
    write_json(path, history[-20:])


def finish(root, job):
    stage = folder(root, job['id'])
    runtime = job['id'] if (stage / 'runtime').exists() else job.get('previous_runtime', '')
    if job['mode'] == 'rollback': runtime = read_json(folder(root, job['source']) / 'job-metadata.json').get('previous_runtime', '')
    write_json(safe(root, '.runtime/updates/runtime.json'), {'stage': runtime})
    if job['mode'] == 'update': write_json(safe(root, '.runtime/updates/installed.json'), read_json(stage / 'package/update.json'))
    else:
        previous = folder(root, job['source']) / 'previous-installed.json'
        installed = safe(root, '.runtime/updates/installed.json')
        if previous.exists(): atomic(installed, previous.read_bytes())
        elif installed.exists(): installed.unlink()
    record(root, job, 'success', '更新完成' if job['mode'] == 'update' else '代码与数据回退完成')
    job_path(root).unlink()


def windows_job(process):
    """Closing the supervisor also stops its server child on Windows."""
    if os.name != 'nt': return None
    from ctypes import wintypes as w
    class Basic(ctypes.Structure):
        _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong), ('flags', w.DWORD), ('min_working', ctypes.c_size_t), ('max_working', ctypes.c_size_t), ('active', w.DWORD), ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]
    class Counters(ctypes.Structure): _fields_ = [(name, ctypes.c_ulonglong) for name in ('read', 'write', 'other', 'read_bytes', 'write_bytes', 'other_bytes')]
    class Extended(ctypes.Structure): _fields_ = [('basic', Basic), ('io', Counters), ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]; kernel.CreateJobObjectW.restype = w.HANDLE
    kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel.CreateJobObjectW(None, None); info = Extended(); info.basic.flags = 0x2000
    if not handle or not kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)) or not kernel.AssignProcessToJobObject(handle, w.HANDLE(int(process._handle))):
        if handle: kernel.CloseHandle(handle)
        process.terminate(); process.wait(); raise OSError('无法建立 Windows 服务进程管理')
    return kernel, handle


def runtime_python(root, job=None):
    runtime = job['id'] if job and (folder(root, job['id']) / 'runtime').exists() else ''
    if job and job['mode'] == 'rollback': runtime = read_json(folder(root, job['source']) / 'job-metadata.json').get('previous_runtime', '')
    if not runtime and not (job and job['mode'] == 'rollback'):
        pointer = safe(root, '.runtime/updates/runtime.json')
        runtime = read_json(pointer).get('stage', '') if pointer.exists() else ''
    path = folder(root, runtime) / 'runtime' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python') if runtime else Path(sys.executable)
    if not path.is_file(): raise ValueError('升级运行环境不存在，请保留 .runtime/updates 目录')
    return str(path)


def supervisor_lock(root):
    path = safe(root, '.runtime/updates/supervisor.lock'); path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open('a+b')
    try:
        if path.stat().st_size == 0: handle.write(b'0'); handle.flush()
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except OSError:
        handle.close(); raise OSError('此安装目录已有 Bot 监督进程，请先正常停止旧实例') from None


def supervise(config, root=None):
    root = Path(root or Path(__file__).resolve().parent.parent).resolve(); config = Path(config).resolve()
    lock = supervisor_lock(root)
    ready = safe(root, '.runtime/updates/ready.json'); ready.parent.mkdir(parents=True, exist_ok=True)
    process = None
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    def stopping(signum, frame): raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, stopping)
    try:
        while True:
            job = apply_pending(root, config)
            if ready.exists(): ready.unlink()
            nonce = uuid.uuid4().hex
            env = os.environ | {'STARBRIDGE_SUPERVISED': '1', 'STARBRIDGE_READY_NONCE': nonce}
            try:
                process = subprocess.Popen([runtime_python(root, job), '-m', 'starbridge', '_serve', '--config', str(config)], cwd=root, env=env)
                handle = windows_job(process)
            except (OSError, ValueError):
                if not job: raise
                rollback(root, config, '新版本运行环境无法启动，已恢复升级前版本与数据'); continue
            started = time.monotonic(); running = False
            try:
                while process.poll() is None:
                    if not running and ready.exists():
                        try: marker = read_json(ready)
                        except (OSError, ValueError): marker = {}
                        # Windows venv redirectors can launch Python under a different PID.
                        # The fresh private nonce identifies this launch; the Job Object owns its tree.
                        if marker.get('nonce') == nonce and type(marker.get('pid')) is int and marker['pid'] > 0:
                            running = True
                            if job: finish(root, job); job = None
                    if not running and time.monotonic() - started > 90:
                        process.terminate(); break
                    time.sleep(0.1)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=15)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
                if handle: handle[0].CloseHandle(handle[1])
            if job:
                rollback(root, config, '更新后服务启动失败，已恢复升级前版本与数据'); continue
            if process.returncode == 75 and job_path(root).exists(): continue
            return process.returncode or 0
    except KeyboardInterrupt:
        if process and process.poll() is None:
            process.terminate()
            try: process.wait(timeout=15)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
        return 0
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm); lock.close()
