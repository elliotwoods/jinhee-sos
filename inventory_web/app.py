#!/usr/bin/env python3
"""Web inventory sync: keep local SQLite and the shared web inventory in step.
Network I/O runs on worker threads."""
import argparse
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox, simpledialog

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pairing_station'))
import web_client  # noqa: E402
from web_client import DEFAULT_DATASET, DEFAULT_SERVER, Unauthorized, WebClient  # noqa: E402
import web_sync  # noqa: E402

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
        # The password is asked for, kept in memory for this session only, never saved.
        self.web = WebClient(server, None, dataset, client=web_client.client_name('Web Sync'))
        self.server, self.dataset = self.web.server, self.web.dataset
        self.events = queue.Queue()
        self.busy = False
        self.plan = None
        self.resolutions = {}
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

        controls = ttk.Frame(outer); controls.pack(fill='x', pady=12)
        self.check_button = ttk.Button(controls, text='Check', command=lambda: self.start('check'))
        self.check_button.pack(side='left', padx=(0, 8))
        self.sync_button = ttk.Button(controls, text='Sync now', command=lambda: self.start('sync'))
        self.sync_button.pack(side='left')
        self.take_web = ttk.Button(controls, text='Conflict: take web', command=lambda: self.resolve('remote'))
        self.keep_local = ttk.Button(controls, text='Conflict: keep local', command=lambda: self.resolve('local'))
        self.keep_local.pack(side='right'); self.take_web.pack(side='right', padx=8)
        ttk.Label(outer, foreground=MUTED, wraplength=1000, text=(
            'Sync uploads local changes and downloads web changes. Web changes are written to this computer only '
            'while the pairing and cube-flasher apps are closed; otherwise they wait for the next sync. '
            'Conflicts are never resolved automatically: select them and choose which side to keep.')).pack(anchor='w')

        middle = ttk.Frame(outer); middle.pack(fill='both', expand=True, pady=(12, 0))
        self.tree = ttk.Treeview(middle, columns=('change', 'mac', 'local', 'web', 'choice'), show='headings', height=10)
        for col, label, width in [('change', 'Change', 120), ('mac', 'MAC', 150), ('local', 'This computer', 260),
                                  ('web', 'Web', 260), ('choice', 'Resolution', 110)]:
            self.tree.heading(col, text=label); self.tree.column(col, width=width, stretch=col in ('local', 'web'))
        self.tree.tag_configure('conflict', foreground=RED)
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
        for button, ok in ((self.check_button, idle), (self.sync_button, idle)):
            button.state(['!disabled'] if ok else ['disabled'])
        conflicts = bool(self.plan and self.plan['conflicts']) and idle
        for button in (self.take_web, self.keep_local):
            button.state(['!disabled'] if conflicts else ['disabled'])

    # ---------- check / sync ----------
    def ask_password(self):
        password = simpledialog.askstring('Web inventory password', 'Enter the shared web inventory password:',
                                          show='•', parent=self.root)
        self.web.password = password or None
        return bool(password)

    def start(self, job):
        if self.busy:
            return
        if not self.web.password and not self.ask_password():
            self.set_status('No password entered — click Check to enter it', AMBER)
            return
        self.busy = True; self.update_buttons()
        self.set_status({'check': 'Checking web inventory…', 'sync': 'Synchronizing…'}[job])
        threading.Thread(target=self.worker, args=(job, dict(self.resolutions)), daemon=True).start()

    def worker(self, job, resolutions):
        try:
            if job == 'check':
                result = web_sync.check(self.database, self.web)
            else:
                result = web_sync.run(self.database, self.web, web_client.client_name(), resolutions)
            self.events.put(('done', (job, result, None)))
        except Exception as exc:  # reported in the UI
            self.events.put(('done', (job, None, exc)))

    def finished(self, job, result, error):
        self.busy = False
        if isinstance(error, Unauthorized):
            self.web.password = None  # ask again on the next Check / Sync
            self.set_status('The web inventory rejected the password — click Check to enter it again', RED)
            self.log(str(error)); self.update_buttons()
            return
        if error:
            self.set_status(f'{job.capitalize()} stopped: {error}', RED); self.log(f'{job} failed: {error}')
            self.update_buttons()
            return
        self.plan = result
        self.resolutions = {mac: side for mac, side in self.resolutions.items() if mac in result['conflicts']}
        self.show_plan()
        up, down, conflicts = len(result['upload']), len(result['download']), len(result['conflicts'])
        if job == 'check':
            if conflicts:
                self.set_status(f'{conflicts} conflict(s) need a decision · {up} to upload · {down} to download', RED)
            elif up or down:
                self.set_status(f'{up} local change(s) to upload · {down} web change(s) to download — Sync now', AMBER)
            else:
                self.set_status(f"Up to date with web revision {result['revision']}", GREEN)
            self.log(f"Checked revision {result['revision']}: upload {up}, download {down}, conflicts {conflicts}")
        else:
            if conflicts:
                self.set_status(f'Nothing changed: {conflicts} conflict(s) need a decision, then Sync again', RED)
            elif result['unapplied']:
                self.set_status(f"Uploaded {up}. {result['unapplied']} web change(s) wait until the pairing and "
                                'flasher apps are closed — then Sync again', AMBER)
            else:
                self.set_status(f"Synchronized: uploaded {up}, applied {down if result['applied'] else 0} · "
                                f"revision {result['revision']}", GREEN)
            self.log(f"Sync revision {result['revision']}: uploaded {up}, applied "
                     f"{down if result['applied'] else 0}, waiting {result['unapplied']}, conflicts {conflicts}")
            if not conflicts:
                # List only what remains: web changes still waiting for the apps to close.
                self.resolutions = {}
                self.plan = dict(result, upload=[], download=[] if result['applied'] or not result['unapplied']
                                 else result['download'])
                self.show_plan()
        self.update_buttons()

    def show_plan(self):
        self.tree.delete(*self.tree.get_children())
        if not self.plan:
            return
        plan = self.plan
        rows = [(mac, 'conflict') for mac in plan['conflicts']]
        rows += [(mac, 'upload') for mac in plan['upload']] + [(mac, 'download') for mac in plan['download'] if mac not in plan['upload']]
        for mac, kind in rows:
            choice = {'local': 'keep local', 'remote': 'take web'}.get(self.resolutions.get(mac), '')
            label = {'conflict': '⚠ Conflict', 'upload': '↑ Upload', 'download': '↓ Download'}[kind]
            self.tree.insert('', 'end', iid=mac, values=(label, mac, describe(plan['local'].get(mac)),
                             describe(plan['remote'].get(mac)), choice), tags=(kind,))

    def show_detail(self):
        selection = self.tree.selection()
        text = ''
        if self.plan and selection:
            mac = selection[0]
            local, remote = self.plan['local'].get(mac) or {}, self.plan['remote'].get(mac) or {}
            text = mac + '\n\n'
            for field in SHOWN:
                a, b = local.get(field, '—'), remote.get(field, '—')
                marker = '≠' if a != b else ' '
                text += f'{marker} {field}\n   here: {a}\n   web:  {b}\n'
        self.detail.configure(state='normal'); self.detail.delete('1.0', 'end')
        self.detail.insert('1.0', text); self.detail.configure(state='disabled')

    def resolve(self, side):
        chosen = [mac for mac in self.tree.selection() if self.plan and mac in self.plan['conflicts']]
        if not chosen:
            messagebox.showinfo('Resolve conflict', 'Select one or more conflict rows first.')
            return
        for mac in chosen:
            self.resolutions[mac] = side
        self.show_plan()
        left = [mac for mac in self.plan['conflicts'] if mac not in self.resolutions]
        self.set_status(f'{len(chosen)} resolution(s) chosen · {len(left)} conflict(s) left'
                        + ('' if left else ' — Sync now to apply them'), AMBER if left else BLUE)

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
