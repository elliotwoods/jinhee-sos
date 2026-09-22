"""Browser fallback: serve console/web/ and the Api over loopback for the default browser.

Used when the native webview is unavailable (--browser, no WebView2 on Windows, or pywebview
failing to start). A per-launch token is required on every API call and the Origin must be our
own; that is a different rule from pairing_station/http_api.py, which rejects any browser Origin.
"""
import paths  # noqa: F401
import json
import mimetypes
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WEB = paths.CONSOLE / 'web'


class Bridge:
    def __init__(self, api, port=0):
        self.api = api
        self.token = secrets.token_urlsafe(24)
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, body, content_type='application/json'):
                data = body if isinstance(body, bytes) else json.dumps(body, default=repr).encode()
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_GET(self):
                path = self.path.split('?', 1)[0]
                if path == '/':
                    path = '/index.html'
                root = WEB.resolve()
                target = (root / path.lstrip('/')).resolve()
                if root not in target.parents or not target.is_file():
                    return self.reply(404, {'error': 'not found'})
                content_type = mimetypes.guess_type(str(target))[0] or 'application/octet-stream'
                if target.suffix in ('.mjs', '.js'):
                    content_type = 'text/javascript'
                self.reply(200, target.read_bytes(), content_type)

            def do_POST(self):
                origin = self.headers.get('Origin')
                own = f'http://127.0.0.1:{bridge.server.server_port}'
                if origin and origin != own:
                    return self.reply(403, {'ok': False, 'error': 'cross-origin request refused'})
                if not secrets.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + bridge.token):
                    return self.reply(403, {'ok': False, 'error': 'token required'})
                if not self.path.startswith('/api/'):
                    return self.reply(404, {'ok': False, 'error': 'unknown endpoint'})
                method = self.path[5:].split('?', 1)[0]
                if method.startswith('_') or not hasattr(bridge.api, method):
                    return self.reply(404, {'ok': False, 'error': f'unknown method {method}'})
                try:
                    size = int(self.headers.get('Content-Length', '0'))
                    body = json.loads(self.rfile.read(size) or b'{}') if size else {}
                    args = body.get('args', [])
                    if not isinstance(args, list):
                        raise ValueError('args must be a list')
                    result = getattr(bridge.api, method)(*args)
                except Exception as exc:
                    return self.reply(400, {'ok': False, 'error': str(exc)})
                self.reply(200, result)

        self.server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, name='http-bridge', daemon=True)

    @property
    def url(self):
        return f'http://127.0.0.1:{self.server.server_port}/?token={self.token}'

    def start(self, open_browser=True):
        self.thread.start()
        if open_browser:
            webbrowser.open(self.url)
        return self.url

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
