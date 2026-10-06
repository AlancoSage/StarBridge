"""Standard-library helpers for the Windows double-click installer."""
import argparse
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def dependencies_ready():
    for line in (ROOT / 'requirements.lock.txt').read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        name, expected = line.strip().split('==', 1)
        try:
            if version(name) != expected:
                return False
        except PackageNotFoundError:
            return False
    try:
        import aiohttp  # noqa: F401
    except ImportError:
        return False
    return True


def configuration():
    from starbridge.config import load
    return load(ROOT / 'config.toml')['app']


def panel_url(app):
    host = {'0.0.0.0': '127.0.0.1', '::': '::1'}.get(app['host'], app['host'])
    if ':' in host:
        host = f'[{host}]'
    return f'http://{host}:{app["port"]}/'


def check_port(app):
    addresses = socket.getaddrinfo(app['host'], app['port'], type=socket.SOCK_STREAM)
    sockets = []
    try:
        for family, kind, protocol, _, address in addresses:
            sock = socket.socket(family, kind, protocol)
            sockets.append(sock)
            if family == socket.AF_INET6:
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind(address)
    finally:
        for sock in sockets:
            sock.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('dependencies-ready', 'info', 'check-port'))
    args = parser.parse_args()
    try:
        if args.action == 'dependencies-ready':
            return 0 if dependencies_ready() else 1
        app = configuration()
        if args.action == 'info':
            print(json.dumps({'panel_url': panel_url(app)}, ensure_ascii=True))
        else:
            check_port(app)
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
