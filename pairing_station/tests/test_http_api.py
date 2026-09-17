import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from http_api import AppAPI


class APITest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = SimpleNamespace(controller=SimpleNamespace(), db=None, root=None)
        self.api = AppAPI(self.app, self.tmp.name, port=0)

    def tearDown(self):
        self.api.close()
        self.tmp.cleanup()

    def request(self, path, body=None, token=True, origin=None):
        headers = {'Content-Type': 'application/json'}
        if token: headers['Authorization'] = 'Bearer ' + self.api.token
        if origin: headers['Origin'] = origin
        request = urllib.request.Request(self.api.url + path,
            data=json.dumps(body).encode() if body is not None else None, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=4) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.load(error)

    def execute(self, code):
        result = []
        worker = threading.Thread(target=lambda: result.append(self.request('/execute', {'code': code})))
        worker.start()
        deadline = time.monotonic() + 3
        while worker.is_alive() and time.monotonic() < deadline:
            self.api.drain()
            time.sleep(.005)
        worker.join(1)
        self.assertFalse(worker.is_alive())
        return result[0][1]

    def test_live_main_thread_namespace_and_error_isolation(self):
        result = self.execute('import threading\nanswer = 42\napp.marker = answer\nprint("hello")\nthreading.get_ident()')
        self.assertEqual(result['result'], threading.get_ident())
        self.assertEqual(result['stdout'], 'hello\n')
        self.assertEqual(self.app.marker, 42)
        self.assertEqual(self.execute('answer + 1')['result'], 43)
        self.assertEqual(self.execute('raise SystemExit("test")')['state'], 'error')
        self.assertEqual(self.execute('answer')['result'], 42)

    def test_auth_browser_rejection_and_validation(self):
        self.assertEqual(self.request('/status', token=False)[0], 403)
        self.assertEqual(self.request('/execute', {'code': '1'}, origin='https://example.com')[0], 403)
        self.assertEqual(self.request('/execute', {'code': 1})[0], 400)
        self.assertEqual(self.request('/missing')[0], 404)
        self.assertEqual(self.api.config.stat().st_mode & 0o777, 0o600)

    def test_timeout_keeps_one_job_and_shutdown_cancels_queued_work(self):
        status, job = self.request('/execute', {'code': 'app.marker = 1'})
        self.assertEqual(status, 202)
        self.assertEqual(job['state'], 'queued')
        self.api.drain()
        status, done = self.request('/jobs/' + job['id'])
        self.assertEqual(done['state'], 'done')
        self.assertEqual(self.app.marker, 1)
        _, job = self.request('/execute', {'code': 'app.marker = 2'})
        self.api.close()
        self.assertEqual(self.api.jobs[job['id']]['state'], 'cancelled')
        self.assertEqual(self.app.marker, 1)

if __name__ == '__main__': unittest.main()
