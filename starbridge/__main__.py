import argparse
import asyncio
import logging
from pathlib import Path
import sqlite3

from .config import initialize, load


async def serve(path):
    import os
    from aiohttp import web
    from .app import STATE, create_app
    from .backups import apply_pending_restore, rollback_restore, finish_restore
    from scripts.update_runtime import job_path, safe, write_json
    restoring = await asyncio.to_thread(apply_pending_restore, path)
    cfg = load(path)
    fallback = None
    error = ""
    while True:
        restart = asyncio.Event()
        runner = None
        try:
            app = create_app(cfg, config_path=path, restart_event=restart)
            app[STATE]["maintenance"] = restoring
            app[STATE]["restart_error"] = error
            runner = web.AppRunner(app, access_log=None)
            await runner.setup()
            await web.TCPSite(runner, cfg["app"]["host"], cfg["app"]["port"]).start()
            if restoring:
                await asyncio.to_thread(finish_restore, path)
                restoring = False
                app[STATE]["maintenance"] = False
                app[STATE]["store"].audit("backup", "备份恢复完成，旧会话与待执行操作已撤销")
        except (OSError, ValueError, sqlite3.Error):
            if runner is not None:
                await runner.cleanup()
            if restoring:
                await asyncio.to_thread(rollback_restore, path, "恢复后的服务启动失败，已自动回滚到恢复前的数据与设置")
                restoring = False
                cfg, fallback = load(path), None
                error = "恢复后的服务启动失败，已回滚；可在备份页面查看结果。"
                continue
            if fallback is None:
                raise
            cfg, fallback = fallback, None
            error = "新配置启动失败，已恢复原连接地址和数据库。请检查端口占用、监听地址和数据库路径后重新保存。"
            logging.exception("新配置启动失败，恢复原运行设置")
            continue
        logging.info("管理面板已启动：http://%s:%s", cfg["app"]["host"], cfg["app"]["port"])
        if os.environ.get('STARBRIDGE_SUPERVISED') == '1':
            root = Path(__file__).resolve().parent.parent
            write_json(safe(root, '.runtime/updates/ready.json'), {'pid': os.getpid(), 'nonce': os.environ.get('STARBRIDGE_READY_NONCE', '')})
        try:
            await restart.wait()
            fallback = app[STATE]["config"]
        finally:
            await runner.cleanup()
        if os.environ.get('STARBRIDGE_SUPERVISED') == '1' and job_path(Path(__file__).resolve().parent.parent).exists():
            return 75
        try:
            restoring = await asyncio.to_thread(apply_pending_restore, path)
            cfg = load(path)
            error = ""
        except (OSError, ValueError):
            cfg, fallback = fallback, None
            error = "配置文件读取失败，已恢复原运行设置。"


def main():
    parser = argparse.ArgumentParser(description="Myrinbot · QQ / Minecraft 联动机器人")
    parser.add_argument("command", nargs="?", choices=["init", "run", "_serve"], default="run")
    parser.add_argument("--config", default="config.toml")
    args = parser.parse_args()
    path = Path(args.config)
    try:
        if args.command == "init":
            initialize(path)
            print(f"已生成配置：{path.resolve()}\n运行 python -m starbridge run，在面板内填写管理员 QQ 和群号。")
            return
        load(path)
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(1, f"配置错误：{exc}\n首次使用请运行 python -m starbridge init\n")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == 'run':
        from scripts.update_runtime import supervise
        print("Myrinbot已启动；设置可在管理面板调整。首次登录令牌在本地 config.toml 中。")
        raise SystemExit(supervise(path))
    try:
        raise SystemExit(asyncio.run(serve(path)) or 0)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
