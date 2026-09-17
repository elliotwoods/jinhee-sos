"""Loopback HTTP control; Python runs on the app's Tk/SQLite owner thread."""
import ast
import contextlib
import io
import json
import queue
import secrets
import threading
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class AppAPI:
    def __init__(self, app, directory, port=8765):
        self.app = app
        self.namespace = dict(app=app, controller=app.controller, db=app.db, root=app.root, zones=getattr(app, 'zones', None))
        self.owner = threading.get_ident()
        self.pending = queue.Queue(maxsize=32)
        self.jobs = {}
        self.lock = threading.Lock()
        self.closed = False
        self.token = secrets.token_urlsafe(32)
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, body):
                data = json.dumps(body, default=repr, allow_nan=False).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def authorized(self):
                # No browser cross-origin access, even with a valid token.
                if self.headers.get('Origin') or not secrets.compare_digest(
                        self.headers.get('Authorization', ''), 'Bearer ' + api.token):
                    self.reply(403, {'error': 'Authorization required; use the local curl config.'})
                    return False
                return True

            def do_GET(self):
                if not self.authorized(): return
                if self.path.startswith('/jobs/'):
                    with api.lock:
                        job = api.jobs.get(self.path.removeprefix('/jobs/'))
                        result = dict(job) if job else None
                    self.reply(200 if result else 404, result or {'error': 'Unknown job'})
                elif self.path == '/status':
                    self.submit('status', None)
                else:
                    self.reply(404, {'error': 'Unknown endpoint'})

            def do_POST(self):
                if not self.authorized(): return
                if self.path != '/execute':
                    self.reply(404, {'error': 'Unknown endpoint'})
                    return
                try:
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size <= 65536: raise ValueError('Body must be 1–65536 bytes')
                    if self.headers.get_content_type() != 'application/json':
                        raise ValueError('Content-Type must be application/json')
                    self.connection.settimeout(3)
                    body = json.loads(self.rfile.read(size))
                    code = body.get('code')
                    if not isinstance(code, str) or not code.strip(): raise ValueError('Provide a nonempty code string')
                except (ValueError, AttributeError, OSError) as exc:
                    self.reply(400, {'error': str(exc)})
                    return
                self.submit('execute', code)

            def submit(self, kind, code):
                with api.lock:
                    if api.closed or api.pending.full():
                        self.reply(503, {'error': 'App closing or request queue full'})
                        return
                    # Retain the most recent 100 jobs; never evict unfinished work.
                    for key in list(api.jobs):
                        if len(api.jobs) < 100: break
                        if api.jobs[key]['state'] in ('done', 'error', 'cancelled'):
                            del api.jobs[key]
                    job_id = uuid.uuid4().hex
                    api.jobs[job_id] = dict(id=job_id, state='queued')
                    done = threading.Event()
                    api.pending.put_nowait((job_id, kind, code, done))
                done.wait(2)
                with api.lock:
                    result = dict(api.jobs[job_id])
                self.reply(200 if done.is_set() else 202, result)

        self.server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        self.server.daemon_threads = True
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.config = Path(directory) / 'api.curl'
        self.config.parent.mkdir(parents=True, exist_ok=True)
        # Recreate with private permissions before writing the per-launch token.
        self.config.unlink(missing_ok=True)
        with self.config.open('x') as file:
            self.config.chmod(0o600)
            file.write(f'header = "Authorization: Bearer {self.token}"\n')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def status(self):
        c = self.app.controller
        return dict(connected=c.connected, nfc_ready=c.reader_ok, mode=c.mode, phase=c.phase,
                    active=c.active, message=c.message, tag_present=c.tag_present,
                    discovered=c.discovered, devices=self.app.db.rows(),
                    roles=self.app.db.roles(), telemetry=c.telemetry, station=c.station, feedback=c.feedback,
                    recent_events=list(self.app.recent_events), logs=list(self.app.recent_logs),
                    zones=self.app.zones.snapshot() if getattr(self.app, 'zones', None) else None)

    def drain(self):
        assert threading.get_ident() == self.owner, 'Execute only on the app thread'
        if self.closed: return
        try:
            job_id, kind, code, done = self.pending.get_nowait()
        except queue.Empty:
            return
        with self.lock:
            self.jobs[job_id]['state'] = 'running'
        output, errors = io.StringIO(), io.StringIO()
        result = {}
        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                if kind == 'status':
                    value = self.status()
                else:
                    tree = ast.parse(code, filename='<app-http>')
                    expression = tree.body.pop() if tree.body and isinstance(tree.body[-1], ast.Expr) else None
                    exec(compile(tree, '<app-http>', 'exec'), self.namespace)
                    value = eval(compile(ast.Expression(expression.value), '<app-http>', 'eval'), self.namespace) if expression else None
                # Snapshot mutable results before handing them to the HTTP thread.
                value = json.loads(json.dumps(value, default=repr, allow_nan=False))
                result = dict(state='done', result=value)
        except BaseException:
            result = dict(state='error', traceback=traceback.format_exc())
        finally:
            result.update(stdout=output.getvalue(), stderr=errors.getvalue())
            with self.lock:
                self.jobs[job_id].update(result)
            done.set()

    def close(self):
        with self.lock:
            if self.closed: return
            self.closed = True
            while True:
                try:
                    job_id, _, _, done = self.pending.get_nowait()
                except queue.Empty:
                    break
                self.jobs[job_id].update(state='cancelled', error='App closing before execution')
                done.set()
        self.server.shutdown()
        self.server.server_close()
        self.config.unlink(missing_ok=True)
