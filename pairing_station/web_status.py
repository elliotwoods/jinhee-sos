"""Background, read-only check of local inventory against the web inventory.

Apps show `WebStatus.text` in an existing label. The worker uses its own read-only SQLite
connection and short timeouts; any failure becomes a quiet status line, never an exception
in the app, and nothing is written locally or remotely.

The password is never stored, so the host apps' status line compares only against the
last sync on this computer. The web itself is checked when a client with a password is
passed (Web Sync app, `scripts/web_sync.py status`).
"""
import json
import sqlite3
import threading
from pathlib import Path
from inventory_sync import snapshot_conn
from web_client import Unauthorized, Unreachable, WebClient, client_name
from web_sync import KEY, load_state


def summarize(database, client=None, app='status line'):
    """Return (level, text). level: 'ok', 'warn' or 'muted'. Without a password, local only."""
    offline = client is None or not client.password
    client = client or WebClient(timeout=3, client=client_name(app))
    conn = sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True, timeout=1)
    try:
        state = load_state(conn)
        saved = conn.execute('SELECT value FROM metadata WHERE key=?', (KEY,)).fetchone()
        if not saved or (state.get('server'), state.get('dataset')) != (client.server, client.dataset):
            return 'warn', 'Web inventory: never synced on this computer — run Web Sync'
        baseline = json.loads(saved[0])
        local = snapshot_conn(conn)
    finally:
        conn.close()
    changed = sum(1 for mac in local.keys() | baseline.keys() if local.get(mac) != baseline.get(mac))
    local_note = f'{changed} local change{"s" if changed != 1 else ""} not uploaded' if changed else ''
    if offline:
        if changed:
            return 'warn', 'Web inventory: ' + local_note + ' — run Web Sync'
        if state.get('unapplied'):
            return 'warn', 'Web inventory: downloaded changes waiting — close the apps and run Web Sync'
        return 'muted', f"Web inventory: no local changes since last sync ({state.get('synced_at', 'never')})"
    try:
        head = client.head()
    except Unauthorized:
        return 'warn', 'Web inventory rejected the password'
    except Unreachable:
        text = f"Web inventory offline (last synced {state.get('synced_at', 'never')})"
        return ('warn' if changed else 'muted'), text + (' · ' + local_note if changed else '')
    newer = head.get('revision') != state.get('revision') or state.get('unapplied')
    if newer:
        return 'warn', 'Web inventory has newer changes — run Web Sync' + (' · ' + local_note if changed else '')
    if changed:
        return 'warn', 'Web inventory: ' + local_note + ' — run Web Sync'
    return 'ok', 'Web inventory: up to date'


class WebStatus:
    def __init__(self, database, interval=300, start=True, app='status line'):
        self.database = Path(database)
        self.app = app
        self.interval = interval
        self.status = ('muted', 'Web inventory: checking…')  # replaced whole, read from the Tk thread
        self._wake = threading.Event()
        self._stop = threading.Event()
        if start:
            threading.Thread(target=self._loop, name='web-status', daemon=True).start()

    def refresh(self):
        self._wake.set()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def check(self):
        try:
            result = summarize(self.database, app=self.app)
        except Exception as exc:  # status only: never disturb the host app
            result = ('muted', f'Web inventory status unavailable ({type(exc).__name__})')
        self.status = result
        return result

    @property
    def level(self):
        return self.status[0]

    @property
    def text(self):
        return self.status[1]

    def bind(self, root, label, colors):
        """Mirror the status into a Tk/ttk label from the Tk thread. colors: level -> colour."""
        shown = None

        def update():
            nonlocal shown
            try:
                if self.status != shown:
                    shown = self.status
                    label.configure(text=shown[1], foreground=colors.get(shown[0], colors.get('muted')))
                root.after(1000, update)
            except Exception:  # label destroyed while closing
                pass
        update()
        return self

    def _loop(self):
        while not self._stop.is_set():
            self.check()
            self._wake.wait(self.interval)
            self._wake.clear()
