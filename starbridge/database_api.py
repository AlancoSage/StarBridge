"""Owner-only, non-persistent database connection checks."""
import asyncio
import importlib.util
import os
from pathlib import Path
import sqlite3

from aiohttp import web
from .database import MySQLConnection
from .mysql_settings import MYSQL_DEFAULTS, resolve_mysql


def setup_routes(app, state_key, authorize, read_body):
    state = app[state_key]
    probing = False

    async def status(request):
        authorize(request, state['config']['app']['admin_token'])
        return web.json_response({
            'backend': 'mysql' if state['config'].get('mysql', {}).get('enabled') else 'sqlite',
            'driver_available': importlib.util.find_spec('pymysql') is not None,
            'full_restart_required': (os.environ.get('STARBRIDGE_SUPERVISED') == '1'
                                      and os.environ.get('MYRINBOT_MYSQL_SUPERVISOR') != '1'),
        }, headers={'Cache-Control': 'no-store'})

    async def test(request):
        nonlocal probing
        authorize(request, state['config']['app']['admin_token'])
        data = await read_body(request)
        if data.keys() != {'mysql'}:
            raise web.HTTPBadRequest(text='连接检测只接受 MySQL 设置')
        try:
            config_path = state['config_file'].path if state['config_file'] else Path.cwd() / 'config.toml'
            cfg = resolve_mysql(data['mysql'], config_path)
            # A connection check is bounded independently of saved timeouts.
            for key in ('connect_timeout', 'read_timeout', 'write_timeout'):
                cfg[key] = min(cfg[key], MYSQL_DEFAULTS[key])
        except ValueError as exc:
            return web.json_response({'error': str(exc)}, status=400, headers={'Cache-Control': 'no-store'})
        if probing:
            raise web.HTTPConflict(text='正在检测数据库连接，请稍候')
        probing = True

        def check():
            connection = None
            try:
                connection = MySQLConnection(cfg)
                connection.execute('SELECT 1').fetchone()
                return {'status': 'ok', 'detail': 'MySQL 连接与读取通过；数据库需为 MySQL 8.0.17+，启动时将检查建表与写入权限。'}
            except (sqlite3.Error, OSError, ValueError):
                return {'status': 'error', 'detail': 'MySQL 连接失败，请检查驱动、主机、端口、数据库、账号权限和 TLS 证书。'}
            finally:
                if connection is not None:
                    connection.close()

        task = asyncio.create_task(asyncio.to_thread(check))
        try:
            try:
                result = await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise
            return web.json_response(result, headers={'Cache-Control': 'no-store'})
        finally:
            probing = False

    app.add_routes([web.get('/api/database/status', status), web.post('/api/database/test', test)])
