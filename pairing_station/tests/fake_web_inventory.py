"""Loopback stand-in for the web inventory API (web/), mirroring its push semantics."""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from urllib.parse import parse_qs, urlparse
import zlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import web_client  # noqa: E402

# Tests must never read or overwrite this computer's stored web password (pairing_station/data/web_password).
web_client.PASSWORD_FILE = Path(tempfile.mkdtemp(prefix='nct-test-password-')) / 'web_password'


class FakeWebInventory:
    def __init__(self):
        self.records = {}   # mac -> {'record', 'revision'}
        self.revision = 0
        self.password = 'test-password'
        self.sightings = {}  # computer -> last report
        self.offline = False
        self.before_push = None  # hook to simulate a concurrent writer
        self.zonedb = dict(version=0, hash='', count=0, crc=0, records_b64='', published_at=None, published_by='',
                           inventory_revision=0)
        self.zonedb_missing = False  # simulate a server deployed before /api/zonedb existed
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
                if url.path == '/api/zonedb/head' and not owner.zonedb_missing:  # public: no records
                    with owner.lock:
                        return self.reply(200, {k: owner.zonedb[k] for k in ('version', 'hash', 'count', 'published_at')})
                if not self.authorized():
                    return
                assert parse_qs(url.query).get('dataset') == ['jinhee-sos']
                with owner.lock:
                    if url.path == '/api/inventory/head':
                        self.reply(200, {'revision': owner.revision, 'count': len(owner.records)})
                    elif url.path == '/api/inventory':
                        self.reply(200, {'revision': owner.revision, 'records': json.loads(json.dumps(owner.records))})
                    elif url.path == '/api/zonedb' and not owner.zonedb_missing:
                        self.reply(200, dict(owner.zonedb))
                    else:
                        self.reply(404, {'error': 'not found'})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
                path = urlparse(self.path).path
                if not self.authorized():
                    return
                if path == '/api/sightings':
                    owner.sightings[self.headers.get('X-Inventory-Client', '').split(' · ')[0]] = body
                    return self.reply(200, {'cubes': len(body.get('cubes', {}))})
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
                if path == '/api/zonedb/publish' and not owner.zonedb_missing:
                    body_bytes = base64.b64decode(body['records_b64'])
                    if not body_bytes or len(body_bytes) % 18:
                        return self.reply(400, {'error': 'Invalid zone database'})
                    digest = hashlib.sha256(body_bytes).hexdigest()
                    with owner.lock:
                        doc = owner.zonedb
                        if doc['hash'] == digest and doc['version'] >= body['min_version']:
                            return self.reply(200, dict(doc, changed=False))
                        owner.zonedb = dict(version=max(doc['version'], body['min_version']) + 1, hash=digest,
                                            count=len(body_bytes) // 18, crc=zlib.crc32(body_bytes) & 0xFFFFFFFF,
                                            records_b64=body['records_b64'], published_at='2026-09-21T00:00:00Z',
                                            published_by=body['client'], inventory_revision=body['inventory_revision'])
                        return self.reply(200, dict(owner.zonedb, changed=True))
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
