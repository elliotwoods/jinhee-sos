"""Loopback stand-in for the web inventory API (web/), mirroring its push semantics."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from urllib.parse import parse_qs, urlparse


class FakeWebInventory:
    def __init__(self):
        self.records = {}   # mac -> {'record', 'revision'}
        self.revision = 0
        self.password = 'test-password'
        self.offline = False
        self.before_push = None  # hook to simulate a concurrent writer
        self.lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def authorized(self):
                header = self.headers.get('Authorization', '')
                if header.removeprefix('Bearer ') != owner.password:
                    self.reply(401, {'error': 'Wrong inventory password'})
                    return False
                return True

            def do_GET(self):
                if owner.offline:
                    self.close_connection = True
                    return
                url = urlparse(self.path)
                if not self.authorized():
                    return
                assert parse_qs(url.query).get('dataset') == ['jinhee-sos']
                with owner.lock:
                    if url.path == '/api/inventory/head':
                        self.reply(200, {'revision': owner.revision, 'count': len(owner.records)})
                    elif url.path == '/api/inventory':
                        self.reply(200, {'revision': owner.revision, 'records': json.loads(json.dumps(owner.records))})
                    else:
                        self.reply(404, {'error': 'not found'})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
                path = urlparse(self.path).path
                if not self.authorized():
                    return
                if path == '/api/inventory/push':
                    if owner.before_push:
                        hook, owner.before_push = owner.before_push, None
                        hook()
                    with owner.lock:
                        stale = {mac: owner.records[mac] for mac, base in body['base_revisions'].items()
                                 if owner.records.get(mac, {'revision': 0})['revision'] != base}
                        if stale:
                            return self.reply(409, {'error': 'stale', 'records': stale})
                        owner.revision += 1
                        for mac, record in body['records'].items():
                            owner.records[mac] = {'record': record, 'revision': owner.revision}
                        return self.reply(200, {'revision': owner.revision})
                self.reply(404, {'error': 'not found'})

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def edit(self, mac, **changes):
        with self.lock:
            self.revision += 1
            record = dict(self.records[mac]['record'], **changes)
            self.records[mac] = {'record': record, 'revision': self.revision}

    def close(self):
        self.server.shutdown()
        self.server.server_close()
