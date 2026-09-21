#!/usr/bin/env python3
"""Zone Database Manager: find zones over ESP-NOW, see their database versions, update them.

The ESP-NOW dongle is any ESP32-C3 running the pairing-station firmware (its zone relay needs no
NFC reader); "Flash dongle…" installs that firmware. Updates use the announce/chunk frames, and
zones accept only a higher database version. Set RX gain… stores a zone's PN532 gain (ZONE_SET_CONFIG).
Versions are universal, allocated by the web inventory when a new database is published (zone_publish.py).

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
from tkinter import messagebox, ttk

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pairing_station'))
from database import Database  # noqa: E402
from transport import Transport  # noqa: E402
from sync_widget import SyncWidget  # noqa: E402
from web_client import DEFAULT_DATASET, DEFAULT_SERVER  # noqa: E402
from zone_registry import ZoneRegistry  # noqa: E402
import zonedb  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dongle  # noqa: E402  (adds flashing_station to the path: import it last)

BG = '#101720'; CARD = '#1b2633'; FG = '#e9f0f7'; MUTED = '#9aafc4'
GREEN = '#54d6a0'; BLUE = '#82b8fa'; AMBER = '#ffc16b'; RED = '#ff7b7b'
DATA = ROOT / 'pairing_station' / 'data'
COLUMNS = [('name', 'Zone', 130), ('signal', 'Signal', 120), ('kind', 'Type · point', 110), ('mac', 'MAC', 145),
           ('firmware', 'Firmware', 110), ('rx_gain', 'RX gain', 90),
           ('db', 'Database', 170), ('state', 'State', 120), ('staging', 'Update', 90), ('seen', 'Last seen', 90),
           ('error', 'Last error', 170)]
STATE_TEXT = {'current': '✓ current', 'behind': '↑ out of date', 'updating': '… updating', 'ahead': '⚠ newer / differs',
              'unpublished': '— nothing published'}
STATE_COLOR = {'current': GREEN, 'behind': AMBER, 'updating': BLUE, 'ahead': RED, 'unpublished': MUTED}
QUIET_EVENTS = {'pong', 'tag_state', 'radio', 'nfc_i2c', 'nfc_init', 'nfc_error', 'nfc_poll', 'device', 'discover_sent'}


def signal_text(rssi):
    """Three-level bars from the dongle's RSSI (dBm); '—' when unknown (dongle firmware before 1.7)."""
    if rssi is None:
        return '—'
    bars = '▂▄▆' if rssi >= -67 else '▂▄·' if rssi >= -80 else '▂··'
    return f'{bars} {round(rssi)} dBm'


def gain_text(z):
    """Stored PN532 RX gain; flags a requested change in flight or a reader that has not taken the setting."""
    if z.get('rx_gain_pending') is not None:
        return f'→ {z["rx_gain_pending"]} dB …'
    if z.get('rx_gain') is None:
        return '—'  # zone firmware or dongle too old to report it
    text = f'{z["rx_gain"]} dB'
    return text if z.get('rx_gain_applied') == z['rx_gain'] else text + ' (not applied)'


def age_text(age):
    return '—' if age is None else f'{int(age)} s' if age < 120 else f'{int(age // 60)} min' if age < 7200 else f'{int(age // 3600)} h'


def progress_text(fraction, width=12):
    filled = round(fraction * width)
    return '█' * filled + '░' * (width - filled) + f' {int(fraction * 100):>3}%'


class GainDialog:
    """Modal choice of a zone's PN532 RX gain. `result` is the chosen dB, or None when cancelled."""

    def __init__(self, root, zone_name, current, reported=True):
        self.result = None
        top = self.top = tk.Toplevel(root)
        top.title('Set RX gain')
        top.configure(bg=BG)
        top.transient(root)
        frame = ttk.Frame(top, padding=16); frame.pack(fill='both', expand=True)
        ttk.Label(frame, text=f'NFC reader RX gain for {zone_name}', font=('Helvetica', 14, 'bold')).pack(anchor='w')
        ttk.Label(frame, text=(f'Currently {current} dB.' if reported else 'This zone has not reported a gain yet '
                               '(older firmware ignores the request).') +
                  '\nHigher gain reads weakly coupled tags but also amplifies noise. 48 dB is the default.\n'
                  'The zone stores it and applies it at once; no reboot.', foreground=MUTED, justify='left').pack(anchor='w', pady=(4, 10))
        self.var = tk.StringVar(value=str(current))
        row = ttk.Frame(frame); row.pack(anchor='w')
        self.combo = ttk.Combobox(row, textvariable=self.var, values=[str(g) for g in zonedb.RX_GAINS], width=6, state='readonly')
        self.combo.pack(side='left')
        ttk.Label(row, text='dB').pack(side='left', padx=(4, 0))
        buttons = ttk.Frame(frame); buttons.pack(fill='x', pady=(14, 0))
        ttk.Button(buttons, text='Set', style='Accent.TButton', command=self.ok).pack(side='right')
        ttk.Button(buttons, text='Cancel', command=top.destroy).pack(side='right', padx=(0, 6))
        top.bind('<Return>', lambda _: self.ok())
        top.bind('<Escape>', lambda _: top.destroy())
        top.update_idletasks()
        top.geometry(f'+{root.winfo_rootx() + 80}+{root.winfo_rooty() + 80}')
        try:
            top.grab_set()
        except tk.TclError:
            pass
        root.wait_window(top)

    def ok(self):
        self.result = int(self.var.get())
        self.top.destroy()


class UpdateDialog:
    """Modal progress for one update run. It holds the grab while the run is active so the main window
    (selection, other updates) cannot change underneath it; afterwards it shows the result until closed."""
    AUTO_CLOSE_MS = 2000  # automatic (Auto update all) runs close by themselves; the status line keeps the result

    def __init__(self, app):
        self.app = app
        p = app.zones.publication
        self.version, self.crc, self.auto = p.version, p.crc, app.zones.walk_run
        self.macs = []  # expected zones in order of appearance (zones coming into range join the run)
        self.finished = self.closed = False
        top = self.top = tk.Toplevel(app.root)
        top.title('Updating zones')
        top.configure(bg=BG)
        top.transient(app.root)
        top.protocol('WM_DELETE_WINDOW', self.close_request)
        frame = ttk.Frame(top, padding=16); frame.pack(fill='both', expand=True)
        self.heading = ttk.Label(frame, text='', font=('Helvetica', 16, 'bold'))
        self.heading.pack(anchor='w')
        self.info = ttk.Label(frame, text='', foreground=MUTED)
        self.info.pack(anchor='w', pady=(2, 8))
        self.bar = ttk.Progressbar(frame, maximum=100, length=560)
        self.bar.pack(fill='x')
        self.tree = ttk.Treeview(frame, columns=('zone', 'mac', 'progress', 'state'), show='headings', height=8,
                                 selectmode='none')
        for key, title, width in [('zone', 'Zone', 140), ('mac', 'MAC', 150), ('progress', 'Progress', 170), ('state', 'State', 150)]:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor='w')
        for state, color in [('done', GREEN), ('receiving', BLUE), ('waiting', MUTED), ('failed', RED)]:
            self.tree.tag_configure(state, foreground=color)
        self.tree.pack(fill='both', expand=True, pady=(10, 8))
        self.result = ttk.Label(frame, text='', font=('Helvetica', 12, 'bold'), wraplength=600, justify='left')
        self.result.pack(anchor='w')
        buttons = ttk.Frame(frame); buttons.pack(fill='x', pady=(10, 0))
        self.close_button = ttk.Button(buttons, text='Close', command=self.close)
        self.close_button.pack(side='right')
        self.close_button.state(['disabled'])
        self.stop_button = ttk.Button(buttons, text='Stop' + (' (turns off Auto update all)' if self.auto else ''),
                                      command=lambda: app.action(app.stop))
        self.stop_button.pack(side='right', padx=(0, 6))
        top.update_idletasks()
        x = app.root.winfo_rootx() + max(0, (app.root.winfo_width() - top.winfo_reqwidth()) // 2)
        y = app.root.winfo_rooty() + max(0, (app.root.winfo_height() - top.winfo_reqheight()) // 3)
        top.geometry(f'+{x}+{y}')
        self.grabbed = False

    def grab(self):
        if self.grabbed or self.finished:
            return
        try:
            self.top.grab_set()  # fails until the window is viewable; retried on the next update
            self.grabbed = True
        except tk.TclError:
            pass

    def update(self):
        zones = self.app.zones
        running = zones.publication is not None and not self.finished
        if running:
            state = zones.publishing_state()
            self.macs += [mac for mac in state['expected'] if mac not in self.macs]
        rows = {z['mac']: z for z in zones.zone_rows()}
        fractions, confirmed = [], 0
        for mac in self.macs:
            z = rows.get(mac)
            done = bool(z) and z['db_version'] == self.version and z['db_crc'] == self.crc
            staging = bool(z) and z['staging_version'] == self.version and bool(z['staging_total'])
            fraction = 1.0 if done else (z['staging_chunks'] or 0) / z['staging_total'] if staging else 0.0
            fractions.append(fraction)
            confirmed += done
            tag = 'done' if done else 'receiving' if staging else 'waiting' if running else 'failed'
            text = {'done': 'confirmed ✓', 'receiving': f'receiving {z["staging_chunks"] if staging else 0}/'
                    f'{z["staging_total"] if staging else 0}', 'waiting': 'waiting for zone', 'failed': 'not confirmed'}[tag]
            values = ((z or {}).get('name') or '—', mac, progress_text(fraction), text)
            if self.tree.exists(mac):
                self.tree.item(mac, values=values, tags=(tag,))
            else:
                self.tree.insert('', 'end', iid=mac, values=values, tags=(tag,))
        self.bar['value'] = 100 * sum(fractions) / len(fractions) if fractions else 0
        what = 'Auto update all' if self.auto else 'Updating'
        self.heading.configure(text=f'{what}: {len(self.macs)} zone(s) to database v{self.version}')
        if running:
            self.info.configure(text=f'{confirmed}/{len(self.macs)} confirmed · cycle {state["cycles"] + 1} · '
                                     f'{state["elapsed_s"]:.0f} / {zones.publish_timeout} s · '
                                     f'{state["send_failures"]} send failure(s)')
            self.grab()
        else:
            self.finish(confirmed)

    def finish(self, confirmed):
        if self.finished:
            return
        self.finished = True
        self.info.configure(text=f'{confirmed}/{len(self.macs)} confirmed')
        ok = self.macs and confirmed == len(self.macs)
        self.result.configure(text=self.app.zones.message, foreground=GREEN if ok else AMBER)
        self.stop_button.state(['disabled'])
        self.close_button.state(['!disabled'])
        try:
            self.top.grab_release()
        except tk.TclError:
            pass
        if self.auto:
            self.top.after(self.AUTO_CLOSE_MS, self.close)

    def close_request(self):
        if self.finished:
            self.close()  # while running, only Stop ends the run

    def close(self):
        if not self.closed:
            self.closed = True
            self.top.destroy()


class App:
    HEARTBEAT, HELLO_RETRY, SILENCE = 1.0, 3.0, 8.0

    def __init__(self, root, database, port=None, server=DEFAULT_SERVER, dataset=DEFAULT_DATASET, walkaround=False,
                 connect=False):
        self.root, self.database = root, Path(database)
        self.db = Database(self.database, recover_pending=False)
        self.transport = Transport()
        self.zones = ZoneRegistry(self.db, self.send, self.log, auto_refresh=True)
        self.server, self.dataset = server, dataset
        self.events = queue.Queue()
        self.station, self.connected = {}, False
        self.opened_at = self.last_rx = self.last_ping = self.last_hello = 0
        self.no_reply_warned = False
        self.expect_dongle_firmware = False
        self.link_lost = None       # reason, set when a send finds the USB link gone (handled in poll)
        self.reconnect_to = None    # the dongle to reopen when it reappears after an unexpected drop
        self.last_reconnect_scan = 0
        self.busy = None  # 'flash' while a dongle is being written
        self.last_render = 0
        self.update_dialog = None
        self.closing = False
        self.setup_ui()
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
        ttk.Label(outer, foreground=MUTED, text=f'{self.server} · dataset {self.dataset} · local {self.database}'
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
        # One Sync control: uploads/downloads the inventory and publishes/pulls the zone database.
        self.sync = SyncWidget(card, self.database, 'Zone DB Manager', bg=CARD, muted=MUTED, server=self.server,
                               dataset=self.dataset, on_synced=self.synced)
        self.sync.pack(fill='x', pady=(8, 0))

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
        self.walk_var = tk.BooleanVar(value=False)
        self.walk_check = ttk.Checkbutton(toolbar, text='Auto update all', variable=self.walk_var,
                                          command=lambda: self.action(self.toggle_walkaround))
        self.walk_check.pack(side='left', padx=12)
        self.stop_button = ttk.Button(toolbar, text='Stop', command=lambda: self.action(self.stop))
        self.stop_button.pack(side='left')
        self.all_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar, text='Show out of range', variable=self.all_var,
                        command=lambda: self.render(force=True)).pack(side='right', padx=12)

        self.summary = ttk.Label(outer, text='', font=('Helvetica', 13, 'bold'))
        self.summary.pack(anchor='w', pady=(10, 0))
        middle = ttk.Frame(outer); middle.pack(fill='both', expand=True, pady=(4, 6))
        self.tree = ttk.Treeview(middle, columns=[c[0] for c in COLUMNS], show='headings', height=12)
        for key, title, width in COLUMNS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor='w', stretch=key in ('name', 'db', 'error'))
        self.tree.heading('signal', text='Signal')
        for state, color in STATE_COLOR.items():
            self.tree.tag_configure(state, foreground=color)
        self.tree.tag_configure('far', foreground='#65778a')
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', lambda _: self.render(force=True))

        # Actions for the zone selected in the list, directly beneath it.
        selection = ttk.Frame(outer); selection.pack(fill='x', pady=(0, 8))
        self.selected_label = ttk.Label(selection, text='Selected: —', font=('Helvetica', 12, 'bold'))
        self.selected_label.pack(side='left', padx=(0, 12))
        self.update_button = ttk.Button(selection, text='Update selected', style='Accent.TButton',
                                        command=lambda: self.action(self.update_selected))
        self.update_button.pack(side='left')
        self.update_all_button = ttk.Button(selection, text='Update all', command=lambda: self.action(self.update_all))
        self.update_all_button.pack(side='left', padx=(6, 0))
        self.identify_button = ttk.Button(selection, text='Identify (10 s)', command=lambda: self.action(self.identify))
        self.identify_button.pack(side='left', padx=(6, 0))
        self.log_button = ttk.Button(selection, text='Show log', command=lambda: self.action(self.show_log))
        self.log_button.pack(side='left', padx=(6, 0))
        self.reboot_button = ttk.Button(selection, text='Reboot', command=lambda: self.action(self.reboot))
        self.reboot_button.pack(side='left', padx=(6, 0))
        self.gain_button = ttk.Button(selection, text='Set RX gain…', command=lambda: self.action(self.set_rx_gain))
        self.gain_button.pack(side='left', padx=(6, 0))

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
        self.reconnect_to = None  # an explicit Connect/Disconnect ends automatic reconnection
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
        try:
            self.transport.send(message)
        except ValueError:
            # The USB link went away between polls: handled as a drop-out in poll(), not as an error
            # (an error would switch Auto update all off). The registry times the relay out and carries on.
            self.link_lost = self.link_lost or 'Dongle USB connection lost'

    def lost(self, reason):
        """Unexpected drop-out: stop the running update (zones keep their staging for 60 s), keep Auto update all
        armed, and reconnect automatically when the same dongle reappears."""
        port = self.selected_port()
        self.disconnect(reason + ' — reconnecting automatically when the dongle is back')
        self.reconnect_to = port
        self.link_lost = None

    def try_reconnect(self, now):
        if not self.reconnect_to or self.transport.port or self.busy == 'flash' or now - self.last_reconnect_scan < 2:
            return
        self.last_reconnect_scan = now
        back = next((p for p in dongle.ports() if p['key'] == self.reconnect_to['key']), None)
        if back:
            self.scan_ports(prefer=back['port'])
            try:
                self.connect()
                self.log(f'Dongle back on {back["port"]}; reconnected')
            except Exception as exc:  # e.g. the port is not ready yet: try again shortly
                self.log(f'Reconnect to {back["port"]} failed: {exc}')

    def on_hello(self, event):
        self.station = event
        ok = (event.get('radio_ok') and event.get('protocol') == 1 and event.get('channel') == 2
              and event.get('zones') == zonedb.PROTO)
        was = self.connected
        self.connected = bool(ok)
        firmware = event.get('firmware', '?')
        if firmware.startswith('mainshow-'):
            self.connected = False
            self.radio_status.configure(text=f'{event.get("mac")} is the Mainshow controller ({firmware}), not a dongle: '
                                        'Disconnect and choose the other port', foreground=RED)
            return
        if not ok:
            problem = ('radio failed to start; reset the dongle' if not event.get('radio_ok') else
                       f'channel {event.get("channel")} (zones use 2)' if event.get('channel') != 2 else
                       'firmware has no zone relay; use Flash dongle…')
            self.radio_status.configure(text=f'{event.get("mac")} · {firmware}: {problem}', foreground=RED)
            return
        old = firmware != dongle.FIRMWARE
        self.radio_status.configure(text=f'Connected · {event.get("mac")} · {firmware} · channel 2' +
                                    (f' · older relay (no RX gain control): Flash dongle… updates it to {dongle.FIRMWARE}'
                                     if old else ''),
                                    foreground=AMBER if old else GREEN)
        if not was:
            self.log(f'Dongle ready: {event.get("mac")} · {firmware}')
            self.set_status('Dongle connected: zones in range appear below (select one for its actions)', GREEN)
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
        self.reconnect_to = None
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
            self.log('Auto update all off (it needs auto-refresh)')

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
        self.log('Auto update all ' + ('on: out-of-date zones in range are updated automatically' if self.walk_var.get() else 'off'))

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

    def update_all(self):
        """One broadcast run for every out-of-date zone in range (zones that come into range join it)."""
        self.require_dongle()
        if self.zones.publication:
            raise ValueError('An update is already running; wait or Stop it first')
        published = self.zones.store.current()
        behind = [z for z in self.zones.zone_rows() if z['in_range'] and z['state'] == 'behind']
        if not behind:
            raise ValueError(f'No out-of-date zones in range (published v{published.version})')
        if not messagebox.askokcancel('Update all zones', f'Send database v{published.version} to {len(behind)} '
                                      'out-of-date zone(s) in range?', parent=self.root):
            return
        self.zones.publish(expected={z['mac'] for z in behind})

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

    def set_rx_gain(self):
        self.require_dongle()
        firmware = (self.station or {}).get('firmware', '')
        if firmware != dongle.FIRMWARE:
            raise ValueError(f'The dongle runs {firmware or "unknown firmware"}; setting the RX gain needs '
                             f'{dongle.FIRMWARE}. Use Flash dongle… first.')
        zone = self.selected_zone()
        current = zone.get('rx_gain') or zonedb.RX_GAIN_DEFAULT
        gain = GainDialog(self.root, zone['name'] or zone['mac'], current, reported=zone.get('rx_gain') is not None).result
        if gain is not None:
            self.zones.set_rx_gain(zone['mac'], gain)
            self.set_status(f'RX gain {gain} dB sent to {zone["name"] or zone["mac"]}: waiting for the zone to confirm', BLUE)

    # ---------- web ----------
    def synced(self, result):
        """After a Sync: the published zone database may have changed; show it and log what moved."""
        inventory, zone = result['sync'], result.get('zone')
        text = f'Synced: uploaded {len(inventory.get("uploaded", inventory["upload"]))} inventory change(s)'
        if inventory.get('applied'):
            text += f', applied {len(inventory["download"])}'
        elif inventory.get('unapplied'):
            text += f', {inventory["unapplied"]} web change(s) wait for the pairing/cube-flasher apps'
        if zone:
            v = zone['published']['version']
            text += f' · zone database v{v}' + (' published (new mappings)' if zone['changed'] else '')
        self.set_status(text, GREEN)
        self.log(text)
        self.render(force=True)

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
                    self.lost('Dongle disconnected')
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
            if self.link_lost:
                self.lost(self.link_lost)
            now = time.monotonic()
            self.try_reconnect(now)
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

    def sync_update_dialog(self):
        """Open the progress window when an update run starts; a new run replaces a finished one."""
        dialog, run = self.update_dialog, self.zones.publication
        if dialog and (dialog.closed or (run and dialog.finished)):
            dialog.close()
            self.update_dialog = dialog = None
        if run and not dialog:
            self.update_dialog = dialog = UpdateDialog(self)
        if dialog:
            dialog.update()

    def render(self, force=False):  # force: called after a user action (always the full render)
        self.last_render = time.monotonic()
        self.sync_update_dialog()
        store = self.zones.store
        published = store.published()
        if published['version']:
            self.published_label.configure(text=f'Published v{published["version"]} · {published["count"]} cubes · '
                                                f'CRC {published["crc"]:08X}')
            origin = (f'from the web · {published["published_by"] or "?"} · {published["published_at"] or "?"}'
                      if published['universal'] else 'legacy local version (not on the web yet): Sync to publish')
        else:
            self.published_label.configure(text='No zone database published')
            origin = 'Sync to publish or pull the zone database'
        differs = store.local_differs()
        self.local_label.configure(foreground=AMBER if differs else MUTED, text=origin + (
            ' · this computer\'s mappings changed since: Sync publishes them' if differs and published['version'] else ''))

        rows = self.zones.zone_rows()
        shown = sorted((z for z in rows if self.all_var.get() or z['in_range']), key=lambda z: not z['in_range'])
        in_range = [z for z in rows if z['in_range']]
        busy = self.busy is not None
        selection = self.tree.selection()
        chosen = next((z for z in rows if selection and z['mac'] == selection[0]), None)
        on_air = self.connected and chosen is not None
        self.selected_label.configure(text=f'Selected: {chosen["name"] or chosen["mac"]}' if chosen else 'Selected: —')
        for button, enabled in [(self.refresh_button, self.connected),
                                (self.update_button, on_air and chosen['state'] == 'behind' and not self.zones.publication),
                                (self.update_all_button, self.connected and not self.zones.publication
                                 and any(z['state'] == 'behind' for z in in_range)),
                                (self.identify_button, on_air), (self.log_button, on_air), (self.reboot_button, on_air),
                                (self.gain_button, on_air and chosen['in_range'] and chosen['config_valid']
                                 and chosen.get('rx_gain_pending') is None),
                                (self.stop_button, bool(self.zones.publication or self.walk_var.get())),
                                (self.flash_button, not busy), (self.connect_button, self.busy != 'flash'),
                                (self.rescan_button, self.busy != 'flash')]:
            button.state(['!disabled'] if enabled else ['disabled'])
        self.connect_button.configure(text='Disconnect' if self.transport.port else 'Connect')

        counts = {s: sum(z['state'] == s for z in in_range) for s in STATE_TEXT}
        walking = ' · AUTO UPDATE ALL ON' if self.walk_var.get() else ''
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
                name=z['name'] or '—', signal=signal_text(z.get('rssi')) if z['in_range'] else '—', kind=f'{z["zone_label"]} · {z["point_id"]}', mac=z['mac'], firmware=z['firmware'] or '—',
                rx_gain=gain_text(z),
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
            lines = [f'{z["name"] or "—"} · {z["mac"]} · {z["zone_label"]} point {z["point_id"]} · {z["firmware"]} · '
                     f'signal {signal_text(z.get("rssi"))}',
                     f'Database v{z["db_version"]} · {z["db_count"]} records · CRC {z["db_crc"] or 0:08X} · slot '
                     f'{"-AB"[z["active_slot"] or 0]} · state {STATE_TEXT.get(z["state"], z["state"])}',
                     f'Uptime {z["uptime"]} s · channel {z["channel"]} · config {"valid" if z["config_valid"] else "INVALID"} · '
                     f'tags {z["tags"]} / unknown {z["unknown_tags"]} / send fail {z["send_fail"]}',
                     (f'RX gain {z["rx_gain"]} dB stored · reader '
                      f'{str(z["rx_gain_applied"]) + " dB" if z["rx_gain_applied"] else "not applied"}'
                      + (f' · last change: {zonedb.SET_RESULTS.get(z["set_result"], z["set_result"])}' if z['set_result'] else '')
                      if z['rx_gain'] is not None else
                      'RX gain not reported (zone firmware before 2.4 / pool-3.2 / preshow-3.3, or dongle before 1.8)')]
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
        self.sync.stop()
        self.zones.stop('Closing')
        self.transport.close()
        self.db.close()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--database', type=Path, default=DATA / 'devices.sqlite3')
    parser.add_argument('--port', help='Dongle serial port (default: a known dongle/station, else the first ESP32)')
    parser.add_argument('--connect', action='store_true', help='Connect to the dongle at launch')
    parser.add_argument('--auto-update-all', '--walkaround', dest='walkaround', action='store_true', help='Start with Auto update all on')
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
