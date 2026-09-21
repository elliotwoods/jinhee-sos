"""The universal Sync control shown by every app that works with the device database.

One click uploads local inventory changes, downloads web changes and publishes/pulls the zone
database (sync_all.sync). The button shows what is pending: "⟳ Sync ↑3 ↓2". The web password is
asked for once, stored owner-only (web_client.save_password) and shared by every app until the web
rejects it. Sync never needs a decision: when two computers changed the same device the newest change
wins, and the operator is told what a local device lost. Manual push/pull and the record-by-record
view live in the Web Sync view (inventory_web/app.py).

Threading: status checks and syncs run on worker threads; results come back through a queue that
the Tk thread polls. Nothing here touches Tk or the host's SQLite connection from a worker.
"""
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
from tkinter import messagebox, simpledialog

import sync_all
import web_client
from web_client import Unauthorized, Unreachable, WebClient, client_name
from web_sync import SyncBusy

ROOT = Path(__file__).resolve().parents[1]
COLORS = dict(ok='#54d6a0', pending='#ffc16b', error='#ff7b7b', muted='#9aafc4', busy='#82b8fa', ink='#101720')


def open_web_sync(database):
    """The manual view: check, upload/download only, publish/pull the zone DB, conflict decisions."""
    subprocess.Popen([sys.executable, str(ROOT / 'inventory_web' / 'app.py'), '--database', str(database)],
                     start_new_session=True)


def describe(status):
    """(button text, colour key, detail text) for a sync_all.status() result."""
    state = status.get('state')
    if state == 'checking':
        return '⟳ Sync …', 'muted', 'Checking the web…'
    if state == 'signin':
        return '⟳ Sync · sign in', 'pending', 'Click Sync and enter the web inventory password (stored on this computer)'
    if state == 'unauthorized':
        return '⟳ Sync · sign in', 'error', 'The web rejected the stored password; click Sync to enter it again'
    if state == 'offline':
        return 'Sync · offline', 'muted', 'Web unreachable; working locally (flashing and zone updates use the last pull)'
    if state == 'error':
        return '⚠ Sync · problem', 'error', f'{status.get("message") or "Sync status unavailable"} — click Sync to try'
    up, down = [], []
    if status['inventory_up']:
        up.append(f'{status["inventory_up"]} inventory change{"s" if status["inventory_up"] != 1 else ""}')
    if status['zone_publish']:
        up.append('new zone mappings to publish')
    if status['inventory_down']:
        down.append(f'{status["inventory_down"]} web change{"s" if status["inventory_down"] != 1 else ""}')
    if status['zone_pull']:
        down.append(f'zone database v{status["web_version"]}')
    notes = []
    if up:
        notes.append('↑ ' + ' + '.join(up))
    if down:
        notes.append('↓ ' + ' + '.join(down))
    if status.get('waiting') and not status['inventory_down']:
        notes.append(f'{status["waiting"]} downloaded change(s) wait for the pairing/cube-flasher apps to be idle')
    if status.get('lost'):
        notes.append(f'{status["lost"]} device(s) here give way to a newer change on another computer')
    if not (status['up'] or status['down']):
        version = status.get('web_version') or status.get('local_version')
        return '✓ Synced', 'ok', f'Up to date · zone database v{version}' if version else 'Up to date'
    arrows = ' '.join(a for a in (f'↑{status["up"]}' if status['up'] else '', f'↓{status["down"]}' if status['down'] else '') if a)
    return f'⟳ Sync  {arrows}', 'pending', ' · '.join(notes)


class SyncWidget(tk.Frame):
    INTERVAL = 60

    def __init__(self, parent, database, app, held=(), can_apply=lambda: True, on_synced=None, bg=None,
                 muted=None, manual=True, start=True, server=None, dataset=None):
        """`held`: instance-lock suffixes the host app holds. `can_apply`: is the host idle, so web changes
        may be written into SQLite underneath it? Asked on the sync worker just before writing, so it
        may only read plain state (no Tk, no SQLite)."""
        bg = bg or _background(parent)
        super().__init__(parent, bg=bg)
        self.database, self.app, self.held = Path(database), app, tuple(held)
        self.can_apply, self.on_synced = can_apply, on_synced
        self.client = WebClient(server or web_client.DEFAULT_SERVER, dataset=dataset or web_client.DEFAULT_DATASET,
                                timeout=8, client=client_name(app))
        self.events = queue.Queue()
        self.busy = False
        self.status = dict(state='checking')
        self.last_sync = None
        self._wake, self._stop = threading.Event(), threading.Event()
        self.button = tk.Label(self, text='⟳ Sync …', bg=COLORS['muted'], fg=COLORS['ink'], padx=12, pady=5,
                               font=('Helvetica', 12, 'bold'), cursor='hand2')
        self.button.pack(side='left')
        self.button.bind('<Button-1>', lambda _: self.click())
        if manual:
            link = tk.Label(self, text='Web Sync…', bg=bg, fg=muted or COLORS['muted'], cursor='hand2',
                            font=('Helvetica', 11, 'underline'))
            link.pack(side='left', padx=(8, 0))
            link.bind('<Button-1>', lambda _: open_web_sync(self.database))
        self.detail = tk.Label(self, text='', bg=bg, fg=muted or COLORS['muted'], anchor='w', justify='left')
        self.detail.pack(side='left', padx=(10, 0), fill='x', expand=True)
        self.render()
        if start:
            threading.Thread(target=self._loop, name='sync-status', daemon=True).start()
        self._after = self.after(300, self._poll)

    # ---- background ----
    def _loop(self):
        while not self._stop.is_set():
            self.events.put(('status', self.check()))
            self._wake.wait(self.INTERVAL)
            self._wake.clear()

    def check(self):
        try:
            if not self.client.password:
                self.client.password = web_client.load_password()  # signed in from another app
            return sync_all.status(self.database, self.client)
        except Exception as exc:  # status only: never disturb the host app
            return dict(state='error', message=f'Sync status unavailable ({type(exc).__name__}: {exc})')

    def refresh(self):
        self._wake.set()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def destroy(self):
        self.stop()
        try:
            self.after_cancel(self._after)
        except (tk.TclError, AttributeError):
            pass
        super().destroy()

    def _poll(self):
        try:
            while True:
                try:
                    kind, payload = self.events.get_nowait()
                except queue.Empty:
                    break
                try:
                    if kind == 'status':
                        if payload.get('state') == 'unauthorized':
                            self.client.password = None
                        self.status = payload
                    elif kind == 'synced':
                        self._synced(*payload)
                except tk.TclError:
                    raise
                except Exception:  # one bad result must not stop the button from working
                    traceback.print_exc()
            self.render()
        except tk.TclError:  # widget destroyed while closing
            return
        self._after = self.after(300, self._poll)

    # ---- display ----
    def render(self):
        if self.busy:
            text, color, detail = 'Syncing…', 'busy', 'Uploading, downloading and publishing the zone database…'
        else:
            text, color, detail = describe(self.status)
            if self.last_sync and color in ('ok', 'pending'):
                detail += f' · last synced {self.last_sync}'
        if self.button['text'] != text or self.detail['text'] != detail:
            self.button.configure(text=text, bg=COLORS[color])
            self.detail.configure(text=detail)

    # ---- sync ----
    def click(self):
        if self.busy:
            return
        if not self.client.password:
            self.client.password = web_client.load_password()
        prompted = False
        if not self.client.password:
            password = simpledialog.askstring('Web inventory password', 'Enter the shared web inventory password.\n'
                                              'It is stored on this computer (owner-only) for every app.',
                                              show='•', parent=self)
            if not password:
                return
            self.client.password, prompted = password, True
        self.busy = True
        self.render()
        threading.Thread(target=self._work, args=(prompted,), daemon=True).start()

    def _work(self, prompted):
        try:
            if prompted:
                self.client.head()  # verify before storing
                web_client.save_password(self.client.password)
            result = sync_all.sync(self.database, self.client, client_name(self.app), held=self.held,
                                   apply_ok=self.can_apply)
            self.events.put(('synced', (result, None)))
        except Exception as exc:  # reported in the widget
            self.events.put(('synced', (None, exc)))
        self.events.put(('status', self.check()))

    def _synced(self, result, error):
        self.busy = False
        self.render()
        if isinstance(error, Unauthorized):
            web_client.forget_password()
            self.client.password = None
            messagebox.showerror('Sync', 'The web rejected the password. Click Sync to enter it again.', parent=self)
            return
        if isinstance(error, SyncBusy):
            messagebox.showinfo('Sync', 'Another app on this computer is syncing right now. Nothing else is needed.',
                                parent=self)
            return
        if error and getattr(error, 'after_push', False):
            messagebox.showwarning('Sync', f'Sync was interrupted while uploading ({error}).\n\nNothing is lost: your '
                                   'changes are safe on this computer, and the next Sync checks what the web received. '
                                   'Click Sync again.', parent=self)
            return
        if isinstance(error, Unreachable):
            messagebox.showwarning('Sync', 'The web is unreachable; nothing changed. Everything keeps working locally.',
                                   parent=self)
            return
        if error:
            messagebox.showerror('Sync', f'Sync stopped: {error}\n\nNothing is lost; click Sync to try again.', parent=self)
            return
        self.last_sync = time.strftime('%H:%M')
        text = summary(result)
        if text:
            messagebox.showwarning('Sync', text, parent=self)
        if self.on_synced:
            self.on_synced(result)


def summary(result):
    """What the operator must hear after a successful sync, or '' when it just worked."""
    inventory, parts = result.get('sync') or {}, []
    lost = inventory.get('lost') or []
    if lost:
        lines = [entry['text'] for entry in lost[:6]] + ([f'… and {len(lost) - 6} more'] if len(lost) > 6 else [])
        waiting = '' if inventory.get('applied', True) else ' (takes effect here once the apps are idle)'
        parts.append('A newer change on another computer took priority over these devices'
                     f'{waiting}:\n\n' + '\n'.join('• ' + line for line in lines) +
                     '\n\nA cube without a number or tag is left out of the zone database until it is set again.')
    if result.get('zone_error'):
        parts.append(f'The inventory synced, but the zone database was not published: {result["zone_error"]}\n'
                     'Click Sync to try again.')
    return '\n\n'.join(parts)


def _background(widget):
    try:
        return widget.cget('background')
    except tk.TclError:  # ttk widgets: use the style's background
        from tkinter import ttk
        return ttk.Style().lookup(widget.winfo_class(), 'background') or '#101720'
