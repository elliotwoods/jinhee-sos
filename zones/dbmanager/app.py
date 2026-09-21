#!/usr/bin/env python3
"""Zone Database Manager: find zones over ESP-NOW, see their database versions, update them.

The ESP-NOW dongle is any ESP32-C3 running the pairing-station firmware (its zone relay needs no
NFC reader); "Flash dongle…" installs that firmware. Zone firmware is unchanged: updates use the
existing announce/chunk frames, and zones accept only a higher database version. Versions are
universal, allocated by the web inventory when a new database is published (zone_publish.py).

Threading: serial I/O runs in Transport's worker, web and flashing in worker threads. Tk widgets
and SQLite are only touched from the Tk poll callback.
"""
import argparse
import fcntl
import queue
import sys
import threading
import time
import tkinter as tk
import uuid
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pairing_station'))
from database import Database  # noqa: E402
from transport import Transport  # noqa: E402
from web_client import DEFAULT_DATASET, DEFAULT_SERVER, Unauthorized, WebClient, client_name  # noqa: E402
from web_status import WebStatus  # noqa: E402
from zone_registry import ZoneRegistry  # noqa: E402
import web_sync  # noqa: E402
import zone_publish  # noqa: E402
import zonedb  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dongle  # noqa: E402  (adds flashing_station to the path: import it last)

BG = '#101720'; CARD = '#1b2633'; FG = '#e9f0f7'; MUTED = '#9aafc4'
GREEN = '#54d6a0'; BLUE = '#82b8fa'; AMBER = '#ffc16b'; RED = '#ff7b7b'
DATA = ROOT / 'pairing_station' / 'data'
COLUMNS = [('name', 'Zone', 130), ('kind', 'Type · point', 110), ('mac', 'MAC', 145), ('firmware', 'Firmware', 110),
           ('db', 'Database', 170), ('state', 'State', 120), ('staging', 'Update', 90), ('seen', 'Last seen', 90),
           ('error', 'Last error', 170)]
STATE_TEXT = {'current': '✓ current', 'behind': '↑ out of date', 'updating': '… updating', 'ahead': '⚠ newer / differs',
              'unpublished': '— nothing published'}
STATE_COLOR = {'current': GREEN, 'behind': AMBER, 'updating': BLUE, 'ahead': RED, 'unpublished': MUTED}
QUIET_EVENTS = {'pong', 'tag_state', 'radio', 'nfc_i2c', 'nfc_init', 'nfc_error', 'nfc_poll', 'device', 'discover_sent'}


def age_text(age):
    return '—' if age is None else f'{int(age)} s' if age < 120 else f'{int(age // 60)} min' if age < 7200 else f'{int(age // 3600)} h'


class App:
    HEARTBEAT, HELLO_RETRY, SILENCE = 1.0, 3.0, 8.0

    def __init__(self, root, database, port=None, server=DEFAULT_SERVER, dataset=DEFAULT_DATASET, walkaround=False,
                 connect=False):
        self.root, self.database = root, Path(database)
        self.db = Database(self.database, recover_pending=False)
        self.transport = Transport()
        self.zones = ZoneRegistry(self.db, self.send, self.log, auto_refresh=True)
        # The web password is asked for when needed and kept in memory only (never saved).
        self.web = WebClient(server, None, dataset, client=client_name('Zone DB Manager'))
        self.events = queue.Queue()
        self.station, self.connected = {}, False
        self.opened_at = self.last_rx = self.last_ping = self.last_hello = 0
        self.no_reply_warned = False
        self.expect_dongle_firmware = False
        self.busy = None  # 'pull' | 'publish' | 'flash'
        self.last_render = 0
        self.closing = False
        self.setup_ui()
        self.web_status = WebStatus(self.database, app='Zone DB Manager').bind(
            root, self.web_label, {'ok': GREEN, 'warn': AMBER, 'muted': MUTED})
        self.scan_ports(prefer=port)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.poll)
        if connect and self.port.get():
            root.after(300, lambda: self.action(self.connect))
        if walkaround:
            self.walk_var.set(True)
            self.toggle_walkaround()

    # ---------- UI ----------
    def setup_ui(self):
        r = self.root
        r.title('NCT · Zone Database Manager')
        r.geometry('1320x860'); r.minsize(1080, 700); r.configure(bg=BG)
        style = ttk.Style(); style.theme_use('clam')
        style.configure('.', background=BG, foreground=FG, font=('Helvetica', 11))
        style.configure('TButton', background='#263749', padding=(10, 7), borderwidth=0)
        style.map('TButton', background=[('active', '#39536e')], foreground=[('disabled', '#65778a')])
        style.configure('Accent.TButton', background='#2f6b52')
        style.map('Accent.TButton', background=[('active', '#3b8766')])
        style.configure('TCheckbutton', background=BG, foreground=FG)
        style.map('TCheckbutton', background=[('active', BG)])
        style.configure('Card.TFrame', background=CARD)
        style.configure('Card.TLabel', background=CARD, foreground=FG)
        style.configure('CardMuted.TLabel', background=CARD, foreground=MUTED)
        style.configure('Treeview', background=CARD, fieldbackground=CARD, foreground=FG, rowheight=28, borderwidth=0)
        style.configure('Treeview.Heading', background='#263749', foreground=MUTED, padding=6)
        style.map('Treeview', background=[('selected', '#315575')])
        style.configure('TCombobox', fieldbackground='#263749', background='#263749', foreground=FG, arrowcolor=FG)
        style.map('TCombobox', fieldbackground=[('readonly', '#263749')], foreground=[('readonly', FG)],
                  selectbackground=[('readonly', '#263749')], selectforeground=[('readonly', FG)])

        outer = ttk.Frame(r, padding=18); outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='NCT / ZONE DATABASE', font=('Helvetica', 22, 'bold')).pack(anchor='w')
        ttk.Label(outer, foreground=MUTED, text=f'{self.web.server} · dataset {self.web.dataset} · local {self.database}'
                  ).pack(anchor='w', pady=(2, 10))

        cards = ttk.Frame(outer); cards.pack(fill='x')
        # Dongle card
        radio = ttk.Frame(cards, style='Card.TFrame', padding=12); radio.pack(side='left', fill='both', expand=True, padx=(0, 8))
        ttk.Label(radio, text='ESP-NOW DONGLE', style='CardMuted.TLabel', font=('Helvetica', 10, 'bold')).pack(anchor='w')
        row = ttk.Frame(radio, style='Card.TFrame'); row.pack(fill='x', pady=6)
        self.port = tk.StringVar()
        self.ports_box = ttk.Combobox(row, textvariable=self.port, width=34, state='readonly')
        self.ports_box.pack(side='left')
        self.rescan_button = ttk.Button(row, text='Rescan', command=lambda: self.action(self.scan_ports))
        self.rescan_button.pack(side='left', padx=6)
        self.connect_button = ttk.Button(row, text='Connect', command=lambda: self.action(self.toggle_connection))
        self.connect_button.pack(side='left')
        self.flash_button = ttk.Button(row, text='Flash dongle…', command=lambda: self.action(self.flash_dongle))
        self.flash_button.pack(side='left', padx=6)
        self.radio_status = ttk.Label(radio, text='Not connected', style='CardMuted.TLabel', wraplength=560, justify='left')
        self.radio_status.pack(anchor='w')
        self.progress = ttk.Progressbar(radio, maximum=100, length=300)

        # Database card
        card = ttk.Frame(cards, style='Card.TFrame', padding=12); card.pack(side='left', fill='both', expand=True)
        ttk.Label(card, text='ZONE DATABASE', style='CardMuted.TLabel', font=('Helvetica', 10, 'bold')).pack(anchor='w')
        self.published_label = ttk.Label(card, text='', style='Card.TLabel', font=('Helvetica', 14, 'bold'))
        self.published_label.pack(anchor='w', pady=(4, 0))
        self.local_label = ttk.Label(card, text='', style='CardMuted.TLabel', wraplength=560, justify='left')
        self.local_label.pack(anchor='w')
        self.web_label = ttk.Label(card, text='', style='CardMuted.TLabel', wraplength=560, justify='left')
        self.web_label.pack(anchor='w')
        row = ttk.Frame(card, style='Card.TFrame'); row.pack(fill='x', pady=(6, 0))
        self.pull_button = ttk.Button(row, text='Pull from web', command=lambda: self.action(lambda: self.start_web('pull')))
        self.pull_button.pack(side='left')
        self.publish_button = ttk.Button(row, text='Push & publish new version…', style='Accent.TButton',
                                         command=lambda: self.action(lambda: self.start_web('publish')))
        self.publish_button.pack(side='left', padx=6)
        ttk.Button(row, text='Web Sync (conflicts)…', command=lambda: self.action(self.open_web_sync)).pack(side='left')

        self.status = tk.StringVar(value='Connect a dongle to find zones in range.')
        self.status_label = tk.Label(outer, textvariable=self.status, bg=CARD, fg=BLUE, font=('Helvetica', 15, 'bold'),
                                     anchor='w', padx=14, pady=10, wraplength=1250, justify='left')
        self.status_label.pack(fill='x', pady=(10, 8))

        toolbar = ttk.Frame(outer); toolbar.pack(fill='x')
        self.refresh_button = ttk.Button(toolbar, text='Refresh', command=lambda: self.action(self.refresh))
        self.refresh_button.pack(side='left')
        self.auto_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar, text='Auto-refresh', variable=self.auto_var,
                        command=lambda: self.action(self.toggle_auto)).pack(side='left', padx=8)
        self.update_button = ttk.Button(toolbar, text='Update selected', style='Accent.TButton',
                                        command=lambda: self.action(self.update_selected))
        self.update_button.pack(side='left', padx=(8, 0))
        self.walk_var = tk.BooleanVar(value=False)
        self.walk_check = ttk.Checkbutton(toolbar, text='Walkaround', variable=self.walk_var,
                                          command=lambda: self.action(self.toggle_walkaround))
        self.walk_check.pack(side='left', padx=12)
        self.stop_button = ttk.Button(toolbar, text='Stop', command=lambda: self.action(self.stop))
        self.stop_button.pack(side='left')
        self.reboot_button = ttk.Button(toolbar, text='Reboot', command=lambda: self.action(self.reboot))
        self.reboot_button.pack(side='right', padx=(6, 0))
        self.log_button = ttk.Button(toolbar, text='Show log', command=lambda: self.action(self.show_log))
        self.log_button.pack(side='right', padx=(6, 0))
        self.identify_button = ttk.Button(toolbar, text='Identify (10 s)', command=lambda: self.action(self.identify))
        self.identify_button.pack(side='right', padx=(6, 0))
        self.all_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar, text='Show out of range', variable=self.all_var,
                        command=lambda: self.render(force=True)).pack(side='right', padx=12)

        self.summary = ttk.Label(outer, text='', font=('Helvetica', 13, 'bold'))
        self.summary.pack(anchor='w', pady=(10, 0))
        middle = ttk.Frame(outer); middle.pack(fill='both', expand=True, pady=(4, 10))
        self.tree = ttk.Treeview(middle, columns=[c[0] for c in COLUMNS], show='headings', height=12)
        for key, title, width in COLUMNS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor='w', stretch=key in ('name', 'db', 'error'))
        for state, color in STATE_COLOR.items():
            self.tree.tag_configure(state, foreground=color)
        self.tree.tag_configure('far', foreground='#65778a')
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', lambda _: self.render(force=True))

        bottom = ttk.Frame(outer); bottom.pack(fill='x')
        self.detail = tk.Text(bottom, height=8, width=70, bg=CARD, fg=FG, relief='flat', font=('Menlo', 10), state='disabled')
        self.detail.pack(side='left', fill='both', expand=True, padx=(0, 8))
        self.logbox = tk.Text(bottom, height=8, width=70, bg=CARD, fg=MUTED, relief='flat', font=('Menlo', 10), state='disabled')
        self.logbox.pack(side='left', fill='both', expand=True)

    def log(self, text):
        self.logbox.configure(state='normal')
        self.logbox.insert('end', time.strftime('%H:%M:%S  ') + str(text) + '\n')
        if int(self.logbox.index('end-1c').split('.')[0]) > 800:
            self.logbox.delete('1.0', '200.0')
        self.logbox.see('end')
        self.logbox.configure(state='disabled')

    def set_status(self, text, color=BLUE):
        self.status.set(text); self.status_label.configure(fg=color)

    def action(self, callback):
        try:
            callback()
        except Exception as exc:
            self.log(str(exc))
            messagebox.showerror('Zone Database Manager', str(exc), parent=self.root)
        self.render(force=True)

    # ---------- dongle ----------
    def scan_ports(self, prefer=None):
        found = dongle.ports()
        known = {mac for mac, role in self.db.roles().items() if role == 'excluded'} | dongle.PROTECTED
        self.port_rows = {}
        for p in found:
            mark = ' · known dongle/station' if (p.get('serial') or '').upper() in known else ''
            self.port_rows[f'{p["port"]} — {p.get("description") or "USB serial"}{mark}'] = p
        labels = list(self.port_rows)
        self.ports_box['values'] = labels
        current = self.selected_port()
        if prefer:
            label = next((l for l, p in self.port_rows.items() if p['port'] == prefer), None)
            if label is None:  # an explicit port that is not an ESP32 descriptor: still allow it
                label = prefer
                self.port_rows[label] = dict(port=prefer, key=prefer, candidate=True, serial=None)
            self.port.set(label)
        elif not current or current['port'] not in {p['port'] for p in found}:
            best = next((l for l in labels if 'known dongle' in l), None) or next(
                (l for l, p in self.port_rows.items() if p['candidate']), labels[0] if labels else '')
            self.port.set(best)

    def selected_port(self):
        return self.port_rows.get(self.port.get()) if hasattr(self, 'port_rows') else None

    def toggle_connection(self):
        if self.transport.port:
            self.disconnect('Disconnected')
        else:
            self.connect()

    def connect(self):
        port = self.selected_port()
        if not port:
            raise ValueError('Choose the dongle\'s USB port (Rescan after plugging it in)')
        if self.busy == 'flash':
            raise ValueError('Wait for the dongle flash to finish')
        self.transport.open(port['port'])  # PortLock: refuses a port the pairing app or a flasher holds
        now = time.monotonic()
        self.opened_at = self.last_rx = self.last_hello = now
        self.station, self.connected, self.no_reply_warned = {}, False, False
        self.send(dict(cmd='hello', id=uuid.uuid4().hex))
        self.radio_status.configure(text=f'Opened {port["port"]}; waiting for the relay firmware…', foreground=AMBER)
        self.log('Opened ' + port['port'])

    def disconnect(self, reason):
        if self.zones.publication:
            self.zones.stop(reason)
        self.transport.close()
        self.station, self.connected = {}, False
        self.radio_status.configure(text=reason, foreground=MUTED)
        self.log(reason)

    def send(self, message):
        self.transport.send(message)

    def on_hello(self, event):
        self.station = event
        ok = (event.get('radio_ok') and event.get('protocol') == 1 and event.get('channel') == 2
              and event.get('zones') == zonedb.PROTO)
        was = self.connected
        self.connected = bool(ok)
        firmware = event.get('firmware', '?')
        if not ok:
            problem = ('radio failed to start; reset the dongle' if not event.get('radio_ok') else
                       f'channel {event.get("channel")} (zones use 2)' if event.get('channel') != 2 else
                       'firmware has no zone relay; use Flash dongle…')
            self.radio_status.configure(text=f'{event.get("mac")} · {firmware}: {problem}', foreground=RED)
            return
        self.radio_status.configure(text=f'Connected · {event.get("mac")} · {firmware} · channel 2', foreground=GREEN)
        if not was:
            self.log(f'Dongle ready: {event.get("mac")} · {firmware}')
            self.zones.set_auto_refresh(self.auto_var.get())
            self.zones.query()
        if self.expect_dongle_firmware:
            self.expect_dongle_firmware = False
            if firmware == dongle.FIRMWARE:
                self.set_status(f'Dongle flashed and verified: {event.get("mac")} reports {firmware}', GREEN)
            else:
                self.set_status(f'Dongle answers but reports {firmware}, expected {dongle.FIRMWARE}', AMBER)

    def heartbeat(self, now):
        if not self.transport.port:
            return
        if self.connected and now - self.last_ping >= self.HEARTBEAT:
            self.send(dict(cmd='ping', id=uuid.uuid4().hex))
            self.last_ping = now
        if not self.connected and now - self.last_hello >= self.HELLO_RETRY:
            self.send(dict(cmd='hello', id=uuid.uuid4().hex))
            self.last_hello = now
            if now - self.opened_at > 2 * self.HELLO_RETRY + 1 and not self.no_reply_warned:
                self.no_reply_warned = True
                self.radio_status.configure(foreground=RED, text='No reply from the pairing-station relay firmware on this '
                                            'port. If this is a new board, disconnect and use Flash dongle….')
        if self.connected and now - self.last_rx > self.SILENCE:
            self.connected = False
            self.last_hello = 0
            self.radio_status.configure(text='Dongle stopped answering; reconnecting…', foreground=AMBER)
            self.log('Dongle stopped answering; re-handshaking (an interrupted update is not replayed)')
            if self.zones.publication:
                self.zones.stop('Update paused: dongle stopped answering')

    def flash_dongle(self):
        port = self.selected_port()
        if not port:
            raise ValueError('Plug in the ESP32-C3 and Rescan first')
        if self.busy:
            raise ValueError('Wait for the current operation to finish')
        if self.transport.port:
            self.disconnect('Disconnected to flash the dongle')
        if not messagebox.askokcancel('Flash ESP-NOW dongle', (
                f'Write the pairing-station relay firmware ({dongle.FIRMWARE}) to\n{port["port"]}?\n\n'
                'Use a spare ESP32-C3. Known cubes and zone boards are refused automatically; NVS is preserved. '
                f'Build: {dongle.build_state()} (rebuilt first if needed).'), parent=self.root):
            return
        known = dongle.known_boards(self.db, self.zones.store.zones())
        folder = DATA / 'dongle' / time.strftime('%Y%m%d-%H%M%S')
        self.busy = 'flash'
        self.progress.pack(anchor='w', pady=(6, 0)); self.progress['value'] = 0
        self.set_status(f'Flashing dongle on {port["port"]}…')

        def work():
            try:
                mac = dongle.flash(port, known, folder, lambda kind, value: self.events.put(('flash', kind, value)))
                self.events.put(('flash_done', port, mac, None))
            except Exception as exc:
                self.events.put(('flash_done', port, None, exc))
        threading.Thread(target=work, daemon=True).start()

    def flash_done(self, port, mac, error):
        self.busy = None
        self.progress.pack_forget()
        if error:
            self.set_status(f'Dongle not flashed: {error}', RED)
            self.log(f'Dongle flash failed: {error}')
            return
        self.db.set_role(mac, 'excluded')  # the cube and zone flashers will now leave it alone
        self.log(f'Dongle {mac} flashed; recorded as an excluded station role')
        self.set_status(f'Dongle {mac} written; connecting to verify the relay firmware…', AMBER)
        self.expect_dongle_firmware = True
        self.root.after(2500, lambda: self.action(lambda: (self.scan_ports(prefer=port['port']), self.connect())))

    # ---------- zones ----------
    def require_dongle(self):
        if not self.connected:
            raise ValueError('Connect the ESP-NOW dongle first')

    def selected_zone(self):
        selection = self.tree.selection()
        if not selection:
            raise ValueError('Select a zone first')
        return next(z for z in self.zones.zone_rows() if z['mac'] == selection[0])

    def refresh(self):
        self.require_dongle()
        self.zones.query()

    def toggle_auto(self):
        self.zones.set_auto_refresh(self.auto_var.get())
        if not self.auto_var.get() and self.walk_var.get():
            self.walk_var.set(False)
            self.zones.set_walkaround(False)
            self.log('Walkaround off (it needs auto-refresh)')

    def toggle_walkaround(self):
        if self.walk_var.get():
            try:
                self.zones.store.current()
            except ValueError:
                self.walk_var.set(False)
                raise
            self.auto_var.set(True)
            self.zones.set_auto_refresh(True)
        self.zones.set_walkaround(self.walk_var.get())
        self.log('Walkaround ' + ('on: out-of-date zones in range are updated automatically' if self.walk_var.get() else 'off'))

    def update_selected(self):
        self.require_dongle()
        zone = self.selected_zone()
        if self.zones.publication:
            raise ValueError('An update is already running; wait or Stop it first')
        published = self.zones.store.current()
        if zone['state'] == 'current':
            raise ValueError(f'{zone["name"] or zone["mac"]} already has database v{published.version}')
        if zone['state'] == 'ahead':
            raise ValueError(f'{zone["name"] or zone["mac"]} runs v{zone["db_version"]}, which is not older than the '
                             f'published v{published.version}. Zones only accept a higher version: use '
                             '"Push & publish new version" to publish above it.')
        if not zone['in_range']:
            if not messagebox.askokcancel('Update zone', f'{zone["name"] or zone["mac"]} has not answered for '
                                          f'{age_text(zone["age_s"])}. Try anyway?', parent=self.root):
                return
        self.zones.update(zone['mac'])

    def stop(self):
        if self.walk_var.get():
            self.walk_var.set(False)
            self.zones.set_walkaround(False)
        self.zones.stop('Stopped')

    def identify(self):
        self.require_dongle()
        self.zones.identify(self.selected_zone()['mac'], 10)

    def show_log(self):
        self.require_dongle()
        self.zones.request_log(self.selected_zone()['mac'])

    def reboot(self):
        self.require_dongle()
        zone = self.selected_zone()
        if messagebox.askokcancel('Reboot zone', f'Reboot {zone["name"] or zone["mac"]}? Tag handling pauses for a few '
                                  'seconds.', parent=self.root):
            self.zones.reboot(zone['mac'])

    # ---------- web ----------
    def ask_password(self):
        password = simpledialog.askstring('Web inventory password', 'Enter the shared web inventory password:',
                                          show='•', parent=self.root)
        self.web.password = password or None
        return bool(password)

    def start_web(self, job):
        if self.busy:
            raise ValueError('Wait for the current operation to finish')
        if job == 'publish' and not messagebox.askokcancel('Publish zone database', (
                'Upload this computer\'s inventory changes, then publish the cube mappings as a new zone database '
                'version (only if they changed).\n\nThe web allocates the version, so it is higher than on every zone '
                'and every other computer. Zones are updated afterwards with Update selected or Walkaround.'),
                parent=self.root):
            return
        if not self.web.password and not self.ask_password():
            self.set_status('No web password entered', AMBER)
            return
        self.busy = job
        self.set_status({'pull': 'Pulling the published zone database…', 'publish': 'Synchronizing and publishing…'}[job])
        threading.Thread(target=self.web_worker, args=(job,), daemon=True).start()

    def web_worker(self, job):
        try:
            if job == 'pull':
                published, updated = zone_publish.pull(self.database, self.web)
                result = dict(published=published, updated=updated, check=web_sync.check(self.database, self.web))
            else:
                result = zone_publish.publish(self.database, self.web, client_name('Zone DB Manager'))
            self.events.put(('web_done', job, result, None))
        except Exception as exc:  # reported in the UI
            self.events.put(('web_done', job, None, exc))

    def web_done(self, job, result, error):
        self.busy = None
        self.web_status.refresh()
        if isinstance(error, Unauthorized):
            self.web.password = None
            self.set_status('The web inventory rejected the password; try again', RED)
            return
        if error:
            self.set_status(f'{"Pull" if job == "pull" else "Publish"} stopped: {error}', RED)
            self.log(f'{job} failed: {error}')
            return
        v = result['published']['version']
        if job == 'pull':
            check = result['check']
            notes = []
            if check['conflicts']:
                notes.append(f'{len(check["conflicts"])} inventory conflict(s)')
            if check['upload']:
                notes.append(f'{len(check["upload"])} local change(s) not uploaded')
            if check['download']:
                notes.append(f'{len(check["download"])} web inventory change(s) not applied here')
            if not v:
                text = 'Nothing is published on the web yet; use Push & publish'
            elif result['updated']:
                text = f'Pulled zone database v{v}'
            else:
                text = f'Zone database v{v} is already the latest here'
            self.set_status(text + (' · ' + ' · '.join(notes) if notes else ''), AMBER if notes else GREEN)
            self.log(text)
        else:
            sync = result['sync']
            text = (f'Published zone database v{v}' if result['changed'] else f'No mapping changes; zone database stays v{v}')
            text += f' · uploaded {len(sync["upload"])} inventory change(s)'
            if sync.get('unapplied'):
                text += f' · {sync["unapplied"]} web change(s) wait until the pairing/flasher apps are closed'
            self.set_status(text, GREEN)
            self.log(text)

    def open_web_sync(self):
        import subprocess
        subprocess.Popen([sys.executable, str(ROOT / 'inventory_web' / 'app.py'), '--database', str(self.database)],
                         start_new_session=True)

    # ---------- loop ----------
    def poll(self):
        if self.closing:
            return
        try:
            for _ in range(300):
                try:
                    event = self.transport.inbox.get_nowait()
                except queue.Empty:
                    break
                self.last_rx = time.monotonic()
                kind = event.get('event')
                if kind == 'disconnected':
                    self.disconnect('Dongle disconnected: ' + str(event.get('detail', '')))
                    break
                if self.zones.event(event):
                    continue
                if kind == 'hello':
                    self.on_hello(event)
                elif kind == 'error':
                    self.log('Dongle: ' + str(event.get('detail')))
                elif kind == 'boot_log':
                    pass  # serial noise while the board boots
                elif kind not in QUIET_EVENTS:
                    self.log(event)
            while True:
                try:
                    item = self.events.get_nowait()
                except queue.Empty:
                    break
                if item[0] == 'flash':
                    _, kind, value = item
                    if kind == 'progress':
                        self.progress['value'] = value
                    elif kind == 'stage':
                        self.set_status('Flashing dongle: ' + value); self.log(value)
                    elif kind == 'log' and ('Error' in value or 'error' in value):
                        self.log(value)
                elif item[0] == 'flash_done':
                    self.flash_done(*item[1:])
                elif item[0] == 'web_done':
                    self.web_done(*item[1:])
            now = time.monotonic()
            self.heartbeat(now)
            before = self.zones.message
            self.zones.tick(self.transport.port is not None and self.connected, self.station)
            if self.zones.message != before and self.zones.message:
                self.set_status(self.zones.message, GREEN if 'confirmed' in self.zones.message else
                                RED if 'timed out' in self.zones.message else BLUE)
            if now - self.last_render >= 0.5:
                self.render()
        except Exception as exc:
            self.log('Paused after an error: ' + str(exc))
            self.zones.stop('Update stopped after an error')
            self.walk_var.set(False)
            self.zones.set_walkaround(False)
        self.root.after(100, self.poll)

    def render(self, force=False):  # force: called after a user action (always the full render)
        self.last_render = time.monotonic()
        store = self.zones.store
        published = store.published()
        if published['version']:
            self.published_label.configure(text=f'Published v{published["version"]} · {published["count"]} cubes · '
                                                f'CRC {published["crc"]:08X}')
            origin = (f'from the web · {published["published_by"] or "?"} · {published["published_at"] or "?"}'
                      if published['universal'] else 'legacy local version (not on the web yet): Push & publish')
        else:
            self.published_label.configure(text='No zone database published')
            origin = 'Pull from web, or Push & publish the inventory'
        differs = store.local_differs()
        self.local_label.configure(foreground=AMBER if differs else MUTED, text=origin + (
            ' · this computer\'s mappings changed since: Push & publish' if differs and published['version'] else ''))

        rows = self.zones.zone_rows()
        shown = sorted((z for z in rows if self.all_var.get() or z['in_range']), key=lambda z: not z['in_range'])
        in_range = [z for z in rows if z['in_range']]
        busy = self.busy is not None
        for button, enabled in [(self.refresh_button, self.connected), (self.update_button, self.connected),
                                (self.identify_button, self.connected), (self.log_button, self.connected),
                                (self.reboot_button, self.connected), (self.stop_button, bool(self.zones.publication or self.walk_var.get())),
                                (self.pull_button, not busy), (self.publish_button, not busy),
                                (self.flash_button, not busy), (self.connect_button, self.busy != 'flash'),
                                (self.rescan_button, self.busy != 'flash')]:
            button.state(['!disabled'] if enabled else ['disabled'])
        self.connect_button.configure(text='Disconnect' if self.transport.port else 'Connect')

        counts = {s: sum(z['state'] == s for z in in_range) for s in STATE_TEXT}
        walking = ' · WALKAROUND ON' if self.walk_var.get() else ''
        self.summary.configure(
            text=(f'{len(in_range)} zone(s) in range: {counts["current"]} current · {counts["behind"]} out of date · '
                  f'{counts["updating"]} updating · {counts["ahead"]} newer/different{walking}   ({len(rows)} known)')
            if self.connected else f'Dongle not connected · {len(rows)} known zone(s), last seen values shown',
            foreground=AMBER if counts['behind'] or counts['ahead'] else GREEN if in_range else MUTED)

        selected = self.tree.selection()
        wanted = {z['mac'] for z in shown}
        for mac in set(self.tree.get_children()) - wanted:
            self.tree.delete(mac)
        for index, z in enumerate(shown):
            values = dict(
                name=z['name'] or '—', kind=f'{z["zone_label"]} · {z["point_id"]}', mac=z['mac'], firmware=z['firmware'] or '—',
                db=f'v{z["db_version"]} · {z["db_count"]} rec · {z["db_crc"] or 0:08X}',
                state=STATE_TEXT.get(z['state'], z['state']),
                staging=(f'v{z["staging_version"]} {z["staging_chunks"]}/{z["staging_total"]}' if z['staging_version'] else '—'),
                seen=age_text(z['age_s']), error=z['error_text'] or '—')
            row = [values[c[0]] for c in COLUMNS]
            tags = (z['state'] if z['in_range'] else 'far',)
            if self.tree.exists(z['mac']):
                self.tree.item(z['mac'], values=row, tags=tags)
                self.tree.move(z['mac'], '', index)
            else:
                self.tree.insert('', index, iid=z['mac'], values=row, tags=tags)

        if selected and selected[0] in wanted:
            z = next(z for z in shown if z['mac'] == selected[0])
            lines = [f'{z["name"] or "—"} · {z["mac"]} · {z["zone_label"]} point {z["point_id"]} · {z["firmware"]}',
                     f'Database v{z["db_version"]} · {z["db_count"]} records · CRC {z["db_crc"] or 0:08X} · slot '
                     f'{"-AB"[z["active_slot"] or 0]} · state {STATE_TEXT.get(z["state"], z["state"])}',
                     f'Uptime {z["uptime"]} s · channel {z["channel"]} · config {"valid" if z["config_valid"] else "INVALID"} · '
                     f'tags {z["tags"]} / unknown {z["unknown_tags"]} / send fail {z["send_fail"]}']
            if z['log']:
                lines.append(f'Recent tags (received {z["log"]["received"]}):')
                lines += [f'  {e["age_s"]:>5} s ago  {e["uid"]:<21} cube {e["cube_id"] or "—":<5} {e["result"]}'
                          for e in z['log']['entries']]
            else:
                lines.append('Show log fetches the recent tags from this zone.')
            text = '\n'.join(lines)
        else:
            text = 'Select a zone for details.'
        if self.detail.get('1.0', 'end-1c') != text:
            self.detail.configure(state='normal')
            self.detail.delete('1.0', 'end')
            self.detail.insert('1.0', text)
            self.detail.configure(state='disabled')

    def close(self):
        if self.busy == 'flash' and not messagebox.askokcancel('Zone Database Manager',
                                                              'A dongle flash is running. Quit anyway?', parent=self.root):
            return
        self.closing = True
        self.web_status.stop()
        self.zones.stop('Closing')
        self.transport.close()
        self.db.close()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--database', type=Path, default=DATA / 'devices.sqlite3')
    parser.add_argument('--port', help='Dongle serial port (default: a known dongle/station, else the first ESP32)')
    parser.add_argument('--connect', action='store_true', help='Connect to the dongle at launch')
    parser.add_argument('--walkaround', action='store_true', help='Start with walkaround mode on')
    parser.add_argument('--server', default=DEFAULT_SERVER)
    parser.add_argument('--dataset', default=DEFAULT_DATASET)
    args = parser.parse_args()
    args.database.parent.mkdir(parents=True, exist_ok=True)
    instance_lock = args.database.with_suffix('.zonedb.lock').open('a')
    root = tk.Tk()
    try:
        fcntl.flock(instance_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        root.withdraw()
        messagebox.showerror('Zone Database Manager', 'The Zone Database Manager is already open for this database.')
        raise SystemExit(1)
    App(root, args.database, args.port, args.server, args.dataset, args.walkaround, args.connect or bool(args.port))
    root.mainloop()


if __name__ == '__main__':
    main()
