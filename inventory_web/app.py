#!/usr/bin/env python3
"""Web Sync view: the universal Sync control plus the manual operations behind it.

Manual: Check, Sync now, Upload only, Download only, Publish / Pull the zone database. Shows every
record a sync would move, and what the merge decided by itself when two computers changed the same
device (the newest change wins). The password is stored on this computer and shared by every app
(web_client). Network I/O runs on worker threads."""
import argparse
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk, simpledialog

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pairing_station'))
import web_client  # noqa: E402
from sync_widget import SyncWidget  # noqa: E402
from web_client import DEFAULT_DATASET, DEFAULT_SERVER, Unauthorized, WebClient  # noqa: E402
import web_sync  # noqa: E402
import zone_publish  # noqa: E402

BG = '#101720'; CARD = '#1b2633'; FG = '#e9f0f7'; MUTED = '#9aafc4'
GREEN = '#54d6a0'; BLUE = '#82b8fa'; AMBER = '#ffc16b'; RED = '#ff7b7b'
SHOWN = ('cube_id', 'uid', 'pending_uid', 'status', 'role', 'source', 'detail', 'updated_at')


def describe(record):
    if record is None:
        return '—'
    if 'cube_id' not in record:
        return f"role {record['role']}"
    number = '#' + str(record['cube_id']) if record['cube_id'] is not None else 'no number'
    return f"{number} · {record['uid'] or 'no tag'} · {record['status']}"


class App:
    def __init__(self, root, database, server=DEFAULT_SERVER, dataset=DEFAULT_DATASET):
        self.root, self.database = root, Path(database)
        # The stored password (shared by every app); asked for and saved only when missing or rejected.
        self.web = WebClient(server, dataset=dataset, client=web_client.client_name('Web Sync'))
        self.prompted = False
        self.server, self.dataset = self.web.server, self.web.dataset
        self.events = queue.Queue()
        self.busy = False
        self.plan = None
        self.setup_ui()
        root.after(100, self.poll)
        root.after(200, lambda: self.start('check'))

    # ---------- UI ----------
    def setup_ui(self):
        r = self.root
        r.title('NEOCORE · Web Inventory Sync')
        r.geometry('1080x780'); r.minsize(900, 640); r.configure(bg=BG)
        style = ttk.Style(); style.theme_use('clam')
        style.configure('.', background=BG, foreground=FG, font=('Helvetica', 11))
        style.configure('TButton', background='#263749', padding=(12, 8), borderwidth=0)
        style.map('TButton', background=[('active', '#39536e')], foreground=[('disabled', '#65778a')])
        style.configure('Treeview', background=CARD, fieldbackground=CARD, foreground=FG, rowheight=28, borderwidth=0)
        style.configure('Treeview.Heading', background='#263749', foreground=MUTED, padding=6)
        style.map('Treeview', background=[('selected', '#315575')])
        outer = ttk.Frame(r, padding=22); outer.pack(fill='both', expand=True)
        header = ttk.Frame(outer); header.pack(fill='x')
        ttk.Label(header, text='NEOCORE / WEB INVENTORY', font=('Helvetica', 24, 'bold')).pack(side='left')
        ttk.Label(outer, text=f'{self.server} · dataset {self.dataset} · local {self.database}',
                  foreground=MUTED).pack(anchor='w', pady=(6, 14))
        self.status = tk.StringVar(value='Ready')
        self.status_label = tk.Label(outer, textvariable=self.status, bg=CARD, fg=BLUE, font=('Helvetica', 16, 'bold'),
                                     anchor='w', padx=16, pady=14, wraplength=1000, justify='left')
        self.status_label.pack(fill='x')
        self.sync_widget = SyncWidget(outer, self.database, 'Web Sync', manual=False, bg=BG, muted=MUTED,
                                      server=self.server, dataset=self.dataset, on_synced=lambda _: self.start('check'))
        self.sync_widget.pack(fill='x', pady=(10, 0))

        controls = ttk.Frame(outer); controls.pack(fill='x', pady=12)
        self.check_button = ttk.Button(controls, text='Check', command=lambda: self.start('check'))
        self.check_button.pack(side='left', padx=(0, 8))
        self.sync_button = ttk.Button(controls, text='Sync now', command=lambda: self.start('sync'))
        self.sync_button.pack(side='left')
        self.upload_button = ttk.Button(controls, text='Upload only', command=lambda: self.start('upload'))
        self.upload_button.pack(side='left', padx=(8, 0))
        self.download_button = ttk.Button(controls, text='Download only', command=lambda: self.start('download'))
        self.download_button.pack(side='left', padx=(8, 0))
        self.publish_button = ttk.Button(controls, text='Publish zone DB', command=lambda: self.start('publish'))
        self.publish_button.pack(side='left', padx=(16, 0))
        self.pull_button = ttk.Button(controls, text='Pull zone DB', command=lambda: self.start('pull'))
        self.pull_button.pack(side='left', padx=(8, 0))
        ttk.Label(outer, foreground=MUTED, wraplength=1000, text=(
            'The Sync button above does everything (inventory both ways, then the zone database). The manual '
            'operations here do one part each. Web changes are written to this computer only while the pairing and '
            'cube-flasher apps are closed or idle; otherwise they wait for the next sync. Sync never needs a decision: '
            'when two computers changed the same device, the newest change wins, and a number or tag claimed by two '
            'devices stays with the newest claim (rows marked "Decided"; also logged as events). To reverse a '
            'decision, make the change again on either computer and Sync. A new zone database version is created '
            'only when the cube mappings changed.')).pack(anchor='w')

        middle = ttk.Frame(outer); middle.pack(fill='both', expand=True, pady=(12, 0))
        self.tree = ttk.Treeview(middle, columns=('change', 'mac', 'local', 'web', 'merged'), show='headings', height=10)
        for col, label, width in [('change', 'Change', 120), ('mac', 'MAC', 150), ('local', 'This computer', 260),
                                  ('web', 'Web', 240), ('merged', 'After sync', 240)]:
            self.tree.heading(col, text=label); self.tree.column(col, width=width, stretch=col in ('local', 'web', 'merged'))
        self.tree.tag_configure('decided', foreground=AMBER)
        self.tree.tag_configure('upload', foreground=BLUE)
        self.tree.tag_configure('download', foreground=GREEN)
        self.tree.pack(side='left', fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', lambda _: self.show_detail())
        self.detail = tk.Text(middle, width=44, bg=CARD, fg=FG, relief='flat', font=('Menlo', 10), wrap='word', state='disabled')
        self.detail.pack(side='right', fill='y', padx=(12, 0))
        self.logbox = tk.Text(outer, height=7, bg=CARD, fg=MUTED, relief='flat', font=('Menlo', 10), state='disabled')
        self.logbox.pack(fill='x', pady=(12, 0))
        self.update_buttons()

    def log(self, text):
        self.logbox.configure(state='normal')
        self.logbox.insert('end', time.strftime('%H:%M:%S  ') + text + '\n'); self.logbox.see('end')
        self.logbox.configure(state='disabled')

    def set_status(self, text, color=BLUE):
        self.status.set(text); self.status_label.configure(fg=color)

    def update_buttons(self):
        idle = not self.busy
        for button, ok in ((self.check_button, idle), (self.sync_button, idle), (self.upload_button, idle),
                           (self.download_button, idle), (self.publish_button, idle), (self.pull_button, idle)):
            button.state(['!disabled'] if ok else ['disabled'])

    # ---------- check / sync ----------
    def ask_password(self):
        password = simpledialog.askstring('Web inventory password', 'Enter the shared web inventory password:',
                                          show='•', parent=self.root)
        self.web.password = password or None
        self.prompted = bool(password)  # saved once the web accepts it
        return bool(password)

    def start(self, job):
        if self.busy:
            return
        if not self.web.password and not self.ask_password():
            self.set_status('No password entered — click Check to enter it', AMBER)
            return
        self.busy = True; self.update_buttons()
        self.set_status({'check': 'Checking web inventory…', 'sync': 'Synchronizing…', 'upload': 'Uploading local changes…',
                         'download': 'Downloading web changes…', 'publish': 'Publishing the zone database…',
                         'pull': 'Pulling the zone database…'}[job])
        threading.Thread(target=self.worker, args=(job,), daemon=True).start()

    def worker(self, job):
        try:
            name = web_client.client_name('Web Sync')
            if job == 'check':
                result = web_sync.check(self.database, self.web)
            elif job == 'publish':
                result = zone_publish.publish(self.database, self.web, name)
            elif job == 'pull':
                published, status = zone_publish.pull(self.database, self.web)
                result = dict(published=published, status=status)
            else:
                result = web_sync.run(self.database, self.web, name,
                                      upload=job != 'download', download=job != 'upload')
            self.events.put(('done', (job, result, None)))
        except Exception as exc:  # reported in the UI
            self.events.put(('done', (job, None, exc)))

    def finished(self, job, result, error):
        self.busy = False
        if isinstance(error, Unauthorized):
            self.web.password = None  # ask again on the next Check / Sync
            self.prompted = False
            web_client.forget_password()
            self.set_status('The web inventory rejected the password — click Check to enter it again', RED)
            self.log(str(error)); self.update_buttons()
            return
        if isinstance(error, web_sync.SyncBusy):
            self.set_status('Another app on this computer is syncing right now — nothing else is needed', AMBER)
            self.update_buttons()
            return
        if error:
            note = (' — nothing is lost; the next sync checks what the web received' if getattr(error, 'after_push', False)
                    else '')
            self.set_status(f'{job.capitalize()} stopped: {error}{note}', RED); self.log(f'{job} failed: {error}')
            self.update_buttons()
            return
        if self.prompted:
            web_client.save_password(self.web.password)  # accepted: every app can use it now
            self.prompted = False
        self.sync_widget.refresh()
        if job in ('publish', 'pull'):
            self.zone_finished(job, result)
            self.update_buttons()
            return
        self.plan = result
        if result.get('sightings') is not None:
            self.log(f"Reported last-seen data for {result['sightings']} cubes")
        self.show_plan()
        for note in result['notes']:
            self.log('Decided: ' + note['text'])
        for entry in result['lost']:
            self.log('Gives way: ' + entry['text'])
        up, down, decided = len(result['upload']), len(result['download']), len(result['notes'])
        lost = f" · {len(result['lost'])} device(s) here give way to a newer change" if result['lost'] else ''
        if job == 'check':
            if up or down:
                self.set_status(f'{up} local change(s) to upload · {down} web change(s) to download — Sync now{lost}', AMBER)
            else:
                self.set_status(f"Up to date with web revision {result['revision']}", GREEN)
            self.log(f"Checked revision {result['revision']}: upload {up}, download {down}, decided {decided}")
        else:
            up = len(result['uploaded'])
            if job == 'upload':
                self.set_status(f"Uploaded {up}. {result['unapplied']} web change(s) not downloaded (Download only or "
                                'Sync to take them)', AMBER if result['unapplied'] else GREEN)
            elif result['unapplied']:
                self.set_status(f"Uploaded {up}. {result['unapplied']} web change(s) wait ({result['deferred']}) — "
                                f'then Sync again{lost}', AMBER)
            else:
                self.set_status(f"Synchronized: uploaded {up}, applied {down if result['applied'] else 0} · "
                                f"revision {result['revision']}{lost}", AMBER if lost else GREEN)
            self.log(f"Sync revision {result['revision']}: uploaded {up}, applied "
                     f"{down if result['applied'] else 0}, waiting {result['unapplied']}, decided {decided}")
            # List only what remains: web changes still waiting for the apps to close.
            self.plan = dict(result, upload=result.get('waiting_upload', []),
                             download=result['download'] if result['unapplied'] else [])
            self.show_plan()
        self.update_buttons()

    def zone_finished(self, job, result):
        v = result['published']['version']
        if job == 'publish':
            text = f'Published zone database v{v}' if result['changed'] else f'No mapping changes: zone database stays v{v}'
        else:
            text = {'none': 'Nothing is published on the web yet', 'updated': f'Pulled zone database v{v}',
                    'current': f'Zone database v{v} is already the latest here',
                    'legacy_ahead': f'This computer\'s legacy v{v} is above the web version: Publish to lift the web above it'
                    }[result['status']]
        self.set_status(text, GREEN)
        self.log(text)

    def decisions(self, mac):
        return [n['text'] for n in self.plan['notes'] if n['mac'] == mac] + \
               [e['text'] for e in self.plan['lost'] if e['mac'] == mac]

    def show_plan(self):
        self.tree.delete(*self.tree.get_children())
        if not self.plan:
            return
        plan = self.plan
        rows = [(mac, 'upload') for mac in plan['upload']] + [(mac, 'download') for mac in plan['download'] if mac not in plan['upload']]
        for mac, kind in rows:
            label = {'upload': '↑ Upload', 'download': '↓ Download'}[kind] + (' · Decided' if self.decisions(mac) else '')
            self.tree.insert('', 'end', iid=mac, values=(label, mac, describe(plan['local'].get(mac)),
                             describe(plan['remote'].get(mac)), describe(plan['merged'].get(mac))),
                             tags=('decided' if self.decisions(mac) else kind,))

    def show_detail(self):
        selection = self.tree.selection()
        text = ''
        if self.plan and selection:
            mac = selection[0]
            local, remote = self.plan['local'].get(mac) or {}, self.plan['remote'].get(mac) or {}
            merged = self.plan['merged'].get(mac) or {}
            text = mac + '\n\n' + ''.join(line + '\n\n' for line in self.decisions(mac))
            for field in SHOWN:
                a, b, c = local.get(field, '—'), remote.get(field, '—'), merged.get(field, '—')
                marker = '≠' if a != b else ' '
                text += f'{marker} {field}\n   here: {a}\n   web:  {b}\n' + (f'   sync: {c}\n' if a != b else '')
        self.detail.configure(state='normal'); self.detail.delete('1.0', 'end')
        self.detail.insert('1.0', text); self.detail.configure(state='disabled')

    def poll(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == 'done':
                    self.finished(*payload)
                elif kind == 'log':
                    self.log(payload)
        except queue.Empty:
            pass
        except Exception as exc:  # a result this view cannot show must not freeze it
            self.busy = False
            self.set_status(f'Unexpected result: {type(exc).__name__}: {exc}', RED)
            self.update_buttons()
        self.root.after(200, self.poll)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=ROOT / 'pairing_station/data/devices.sqlite3')
    parser.add_argument('--server', default=DEFAULT_SERVER)
    parser.add_argument('--dataset', default=DEFAULT_DATASET)
    args = parser.parse_args()
    root = tk.Tk()
    App(root, args.database, args.server, args.dataset)
    root.mainloop()


if __name__ == '__main__':
    main()
