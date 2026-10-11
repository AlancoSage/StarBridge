"""Myrinbot standalone website server. Python standard library only."""
import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit, unquote

ROOT = Path(__file__).resolve().parent
ASSETS = {'index.html', 'site.js', 'site.css', 'config.json', 'mark.png', 'mark.svg', 'sdk/starbridge.js'}


def api_base(value):
    if value == '/api/v1':
        return value
    if not isinstance(value, str) or len(value) > 500 or any(c.isspace() for c in value):
        raise ValueError('API address must be /api/v1 or an HTTP(S) URL ending in /api/v1')
    value = value.rstrip('/')
    url = urlsplit(value)
    if (url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.path != '/api/v1'):
        raise ValueError('API address must be /api/v1 or an HTTP(S) URL ending in /api/v1')
    url.port
    return value


def handler(address):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT), **kwargs)

        def end_headers(self):
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self' http: https:; img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
            super().end_headers()

        def send_head(self):
            name = unquote(urlsplit(self.path).path).lstrip('/') or 'index.html'
            if name not in ASSETS:
                self.send_error(404)
                return None
            if name == 'config.json':
                import io
                data = json.dumps({'apiBase': address}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                return io.BytesIO(data)
            return super().send_head()
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8089)
    parser.add_argument('--api-base', help='Overrides config.json in memory; does not change the file')
    args = parser.parse_args()
    try:
        address = api_base(args.api_base if args.api_base is not None else json.loads((ROOT/'config.json').read_text(encoding='utf-8'))['apiBase'])
    except (ValueError, KeyError, OSError, TypeError) as exc:
        parser.error(str(exc))
    with ThreadingHTTPServer((args.host, args.port), handler(address)) as server:
        print(f'Myrinbot website: http://{args.host}:{server.server_port}/ | Bot API: {address}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
