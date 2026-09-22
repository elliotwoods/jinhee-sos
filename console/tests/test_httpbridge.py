import json
import tempfile
import unittest
import urllib.request
from pathlib import Path

import support  # noqa: F401
import httpbridge


class DummyApi:
    def ping(self):
        return dict(ok=True)

    def call(self, name, args=None):
        return dict(ok=True, result=[name, args])

    def _secret(self):
        return 'no'


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.web = Path(tempfile.mkdtemp())
        (self.web / 'index.html').write_text('<!doctype html><title>t</title>', encoding='utf-8')
        (self.web / 'app.js').write_text('export const x = 1;', encoding='utf-8')
        self.original = httpbridge.WEB
        httpbridge.WEB = self.web
        self.bridge = httpbridge.Bridge(DummyApi())
        self.bridge.start(open_browser=False)
        self.base = f'http://127.0.0.1:{self.bridge.server.server_port}'

    def tearDown(self):
        self.bridge.stop()
        httpbridge.WEB = self.original

    def request(self, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data, headers or {}, method='POST' if data is not None else 'GET')
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.read(), response.headers.get('Content-Type')
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), exc.headers.get('Content-Type')

    def test_static_files(self):
        status, body, content_type = self.request('/')
        self.assertEqual((status, body), (200, b'<!doctype html><title>t</title>'))
        status, body, content_type = self.request('/app.js')
        self.assertEqual((status, content_type), (200, 'text/javascript'))
        self.assertEqual(self.request('/../hub.py')[0], 404)

    def test_token_and_origin(self):
        auth = {'Authorization': 'Bearer ' + self.bridge.token, 'Content-Type': 'application/json'}
        self.assertEqual(self.request('/api/call', {'args': ['x', {'a': 1}]})[0], 403)
        status, body, _ = self.request('/api/call', {'args': ['x', {'a': 1}]}, auth)
        self.assertEqual((status, json.loads(body)['result']), (200, ['x', {'a': 1}]))
        status, body, _ = self.request('/api/call', {'args': []}, dict(auth, Origin='http://evil.example'))
        self.assertEqual(status, 403)
        self.assertEqual(self.request('/api/_secret', {'args': []}, auth)[0], 404)
        self.assertEqual(self.request('/api/nope', {'args': []}, auth)[0], 404)


if __name__ == '__main__':
    unittest.main()
