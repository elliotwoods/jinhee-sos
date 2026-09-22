#!/usr/bin/env python3
"""Mainshow Controller: make a cube mainshow-ready and trigger the main show over ESP-NOW.

The controller is an ESP32-C3 running zones/firmware/MainshowController ("Flash controller
firmware…" installs it on a spare dongle board). Cube firmware is unchanged: MSG_SET_ZONE 4 makes a
cube mainshow-ready (neon), and MSG_SHOW_START with a fresh showId starts its local timeline, but
only on cubes that are ready. The board's BOOT button and trigger input start the show without this
app; their triggers appear in the log. A Workstation (or a legacy General Radio) answers the same
verbs from this app, but has no physical trigger and is never recorded as the controller.

Threading: serial I/O runs in Transport's worker and flashing in a worker thread. Tk widgets and
SQLite are only touched from the Tk poll callback.
"""
import argparse
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
import hostos  # noqa: E402
from database import Database  # noqa: E402
from transport import Transport  # noqa: E402
from zone_registry import ZoneStore  # noqa: E402
import showfile  # noqa: E402
sys.path.insert(0, str(ROOT / 'zones/dbmanager'))
import dongle  # noqa: E402  (adds flashing_station to the path: import it last)

BG = '#101720'; CARD = '#1b2633'; FG = '#e9f0f7'; MUTED = '#9aafc4'
GREEN = '#54d6a0'; BLUE = '#82b8fa'; AMBER = '#ffc16b'; RED = '#ff7b7b'; NEON = '#d4ff2a'
DATA = ROOT / 'pairing_station' / 'data'
FIRMWARE = dongle.MAINSHOW.version
ZONE_NAMES = {0: 'idle', 1: 'preshow', 2: 'desert', 3: 'pool', 4: 'mainshow'}
DEFAULT_CUBE = 44

# The cubes' show as (end in ms since SHOW_START, what the cube shows), from the show document
# (shows/mainshow.json; the cube firmware's compiled-in DefaultShow.h is generated from it). The cube
# reports nothing back, so the app can only show where the cube *should* be. A cube holding a newer
# published show (Show editor) follows that one; the console reads the published copy.
TIMELINE = showfile.summary(showfile.load())
SHOW_LENGTH_MS = TIMELINE[-1][0]


def segment_at(ms):
    """What the cube should be showing `ms` after SHOW_START."""
    for end, label in TIMELINE:
        if ms < end:
            return label
    return 'Ended: LEDs off (the cube leaves mainshow-ready)'


def clock_text(seconds):
    seconds = max(0, int(seconds))
    return f'{seconds // 60}:{seconds % 60:02d}'


def find_cube(db, number):
    """(mac, row) for cube `number` in the inventory; raises ValueError with an operator-readable reason."""
    roles = db.roles()
    row = next((r for r in db.rows() if r['cube_id'] == number), None)
    if row is None:
        raise ValueError(f'No cube #{number} in the inventory')
    if roles.get(row['mac']) == 'excluded':
        raise ValueError(f'#{number} ({row["mac"]}) is excluded from the inventory (a station or dongle), not a cube')
    return row['mac'], dict(row)


class Session:
    """The controller link and its state, without Tk: testable with a fake send and clock."""
    HEARTBEAT, HELLO_RETRY, SILENCE, REPLY_TIMEOUT = 1.0, 3.0, 8.0, 3.0

    def __init__(self, send, log, clock=time.monotonic):
        self.send, self.log, self.clock = send, log, clock
        self.reset()
        self.show = None  # dict(show_id, target, source, started): the last show this controller started

    def reset(self):
        self.info, self.connected, self.pending = {}, False, None
        self.opened = False
        self.opened_at = self.last_rx = self.last_ping = self.last_hello = 0
        self.problem = None
        self.names = {}  # mac -> '#44' for the log

    def open(self):
        self.reset()
        self.opened = True
        now = self.clock()
        self.opened_at = self.last_rx = self.last_hello = now
        self.send(dict(cmd='hello', id=uuid.uuid4().hex))

    def close(self):
        self.reset()

    def usable(self):
        return self.connected and self.info.get('radio_ok') and dongle.show_capable(self.info)

    def busy(self):
        if self.pending and self.clock() - self.pending['sent'] > self.REPLY_TIMEOUT:
            self.log(f'No reply to {self.pending["cmd"]} from the controller; not retried automatically')
            self.pending = None
        return self.pending is not None

    def request(self, cmd, **fields):
        if not self.usable():
            raise ValueError('Connect the Mainshow controller first')
        if self.busy():
            raise ValueError('Wait for the controller to answer the previous command')
        request_id = uuid.uuid4().hex[:12]
        self.pending = dict(id=request_id, cmd=cmd, sent=self.clock())
        self.send(dict(cmd=cmd, id=request_id, **fields))
        return request_id

    def set_zone(self, mac, zone, name):
        self.names[mac] = name
        return self.request('set_zone', mac=mac, zone=zone)

    def trigger(self, target, name='all cubes'):
        self.names[target] = name
        return self.request('show_start', target=target)

    def heartbeat(self):
        if not self.opened:
            return
        now = self.clock()
        if self.connected and now - self.last_ping >= self.HEARTBEAT:
            self.send(dict(cmd='ping', id=uuid.uuid4().hex))
            self.last_ping = now
        if not self.connected and now - self.last_hello >= self.HELLO_RETRY:
            self.send(dict(cmd='hello', id=uuid.uuid4().hex))
            self.last_hello = now
            if now - self.opened_at > 2 * self.HELLO_RETRY + 1 and not self.problem:
                self.problem = ('No reply from the Mainshow controller firmware on this port. '
                                'If this board is a dongle, use Flash controller firmware….')
        if self.connected and now - self.last_rx > self.SILENCE:
            self.connected = False
            self.last_hello = 0
            self.problem = 'Controller stopped answering; re-handshaking (nothing is resent)'
            self.log(self.problem)

    def handle(self, event):
        """Apply one event from the controller. Returns the event kind for the caller's bookkeeping."""
        self.last_rx = self.clock()
        kind = event.get('event')
        answered = self.pending and event.get('id') == self.pending['id']
        if answered:
            self.pending = None
        if kind == 'hello':
            self.info = event
            firmware = event.get('firmware', '?')
            self.connected = True
            if not dongle.show_capable(event):
                self.problem = (f'This board runs {firmware}: it is not the Mainshow controller. '
                                'Use Flash controller firmware… to convert a spare dongle.')
            elif not event.get('radio_ok'):
                self.problem = 'The controller\'s radio did not start; reset the board'
            elif event.get('channel') != 2:
                self.problem = f'The controller is on channel {event.get("channel")}; cubes use 2'
            else:
                self.problem = None
        elif kind == 'zone_sent':
            name = self.names.get(event.get('mac'), event.get('mac'))
            zone = ZONE_NAMES.get(event.get('zone'), event.get('zone'))
            status = event.get('status')
            if status == 'delivered':
                self.log(f'{name} → {zone}: delivered (radio ACK only; watch the cube)')
            else:
                self.log(f'{name} → {zone}: {status}, no radio ACK. Is the cube on, in range and on channel 2?')
        elif kind == 'show_start':
            target = event.get('target')
            source = event.get('source')
            self.show = dict(show_id=event.get('show_id'), target=target, source=source, started=self.clock(),
                             name='all cubes' if target == 'broadcast' else self.names.get(target, target))
            how = {'usb': 'from this app', 'button': 'by the BOOT button', 'pin': 'by the trigger input'}.get(source, source)
            if target == 'broadcast':
                detail = f'broadcast ×{event.get("sent")} (no ACK). Only mainshow-ready cubes start'
            else:
                detail = (f'{self.show["name"]}: {event.get("delivered")}/{event.get("repeats")} delivered (radio ACK); '
                          'starts only if the cube is mainshow-ready')
            self.log(f'SHOW START {how}, show {event.get("show_id")}: {detail}')
        elif kind == 'locked':
            self.log(f'Trigger ignored ({event.get("source")}): the controller is locked for another '
                     f'{event.get("retry_ms", 0) / 1000:.1f} s after the last trigger')
        elif kind == 'ignored':
            self.log(f'Trigger input closed again after only {event.get("open_ms")} ms open: treated as a dropout '
                     f'and ignored (it must be open {event.get("rearm_ms")} ms before it can start a new show)')
        elif kind == 'show_config':  # mainshow-1.3.0: the show length that bounds the timecode
            self.info = dict(self.info, show_length_ms=event.get('length_ms'), show_version=event.get('version'),
                             show_crc=event.get('crc'))
            self.log(f'Controller: show v{event.get("version")} ({event.get("length_ms", 0) / 1000:.1f} s) stored; '
                     'timecode follows it')
        elif kind == 'show_stop':
            self.log('Controller: show timecode stopped (cubes keep playing until idle)')
        elif kind == 'error':
            self.log('Controller: ' + str(event.get('detail')))
        return kind

    def show_state(self):
        """(elapsed seconds, expected segment) for the last show, or None."""
        if not self.show:
            return None
        elapsed = self.clock() - self.show['started']
        return elapsed, segment_at(elapsed * 1000)

    def forget_show(self, mac=None):
        """Idle ends the show on that cube; a broadcast show keeps running on the others."""
        if self.show and (mac is None or self.show['target'] == mac):
            self.show = None


class App:
    def __init__(self, root, database, port=None, connect=False, cube=DEFAULT_CUBE):
        self.root, self.database = root, Path(database)
        self.db = Database(self.database, recover_pending=False)
        self.transport = Transport()
        self.session = Session(self.send, self.log)
        self.events = queue.Queue()
        self.busy = None  # 'flash' while the controller firmware is being written
        self.expect_firmware = False
        self.link_lost = None
        self.cube = None  # (number, mac) once looked up
        self.closing = False
        self.setup_ui(cube)
        self.scan_ports(prefer=port)
        self.lookup_cube(quiet=True)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.poll)
        if connect and self.port.get():
            root.after(300, lambda: self.action(self.connect))

    # ---------- UI ----------
    def setup_ui(self, cube):
        r = self.root
        r.title('NCT · Mainshow Controller')
        r.geometry('980x760'); r.minsize(860, 640); r.configure(bg=BG)
        style = ttk.Style(); style.theme_use('clam')
        style.configure('.', background=BG, foreground=FG, font=('Helvetica', 11))
        style.configure('TButton', background='#263749', padding=(10, 7), borderwidth=0)
        style.map('TButton', background=[('active', '#39536e')], foreground=[('disabled', '#65778a')])
        style.configure('Big.TButton', font=('Helvetica', 15, 'bold'), padding=(18, 14))
        style.configure('Ready.TButton', background='#4a5a1c', font=('Helvetica', 15, 'bold'), padding=(18, 14))
        style.map('Ready.TButton', background=[('active', '#627824'), ('disabled', '#263749')])
        style.configure('Go.TButton', background='#2f6b52', font=('Helvetica', 15, 'bold'), padding=(18, 14))
        style.map('Go.TButton', background=[('active', '#3b8766'), ('disabled', '#263749')])
        style.configure('Card.TFrame', background=CARD)
        style.configure('Card.TLabel', background=CARD, foreground=FG)
        style.configure('CardMuted.TLabel', background=CARD, foreground=MUTED)
        style.configure('Card.TRadiobutton', background=CARD, foreground=FG)
        style.map('Card.TRadiobutton', background=[('active', CARD)])
        style.configure('TEntry', fieldbackground='#263749', foreground=FG, insertcolor=FG)
        style.configure('TCombobox', fieldbackground='#263749', background='#263749', foreground=FG, arrowcolor=FG)
        style.map('TCombobox', fieldbackground=[('readonly', '#263749')], foreground=[('readonly', FG)],
                  selectbackground=[('readonly', '#263749')], selectforeground=[('readonly', FG)])

        outer = ttk.Frame(r, padding=18); outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='NCT / MAINSHOW', font=('Helvetica', 22, 'bold')).pack(anchor='w')
        ttk.Label(outer, foreground=MUTED, text=f'Controller firmware {FIRMWARE} · local {self.database}').pack(anchor='w', pady=(2, 10))

        # Controller card
        card = ttk.Frame(outer, style='Card.TFrame', padding=12); card.pack(fill='x')
        ttk.Label(card, text='MAINSHOW CONTROLLER', style='CardMuted.TLabel', font=('Helvetica', 10, 'bold')).pack(anchor='w')
        row = ttk.Frame(card, style='Card.TFrame'); row.pack(fill='x', pady=6)
        self.port = tk.StringVar()
        self.ports_box = ttk.Combobox(row, textvariable=self.port, width=48, state='readonly')
        self.ports_box.pack(side='left')
        self.rescan_button = ttk.Button(row, text='Rescan', command=lambda: self.action(self.scan_ports))
        self.rescan_button.pack(side='left', padx=6)
        self.connect_button = ttk.Button(row, text='Connect', command=lambda: self.action(self.toggle_connection))
        self.connect_button.pack(side='left')
        self.flash_button = ttk.Button(row, text='Flash controller firmware…', command=lambda: self.action(self.flash_controller))
        self.flash_button.pack(side='left', padx=6)
        self.link_status = ttk.Label(card, text='Not connected', style='CardMuted.TLabel', wraplength=900, justify='left')
        self.link_status.pack(anchor='w')
        self.progress = ttk.Progressbar(card, maximum=100, length=300)

        # Cube and actions
        show = ttk.Frame(outer, style='Card.TFrame', padding=12); show.pack(fill='x', pady=(10, 0))
        ttk.Label(show, text='CUBE', style='CardMuted.TLabel', font=('Helvetica', 10, 'bold')).pack(anchor='w')
        row = ttk.Frame(show, style='Card.TFrame'); row.pack(fill='x', pady=6)
        ttk.Label(row, text='Cube #', style='Card.TLabel', font=('Helvetica', 14, 'bold')).pack(side='left')
        self.cube_var = tk.StringVar(value=str(cube))
        entry = ttk.Entry(row, textvariable=self.cube_var, width=6, font=('Helvetica', 14))
        entry.pack(side='left', padx=6)
        entry.bind('<Return>', lambda _: self.action(self.lookup_cube))
        entry.bind('<FocusOut>', lambda _: self.lookup_cube(quiet=True))
        self.cube_label = ttk.Label(row, text='', style='CardMuted.TLabel')
        self.cube_label.pack(side='left', padx=8)

        buttons = ttk.Frame(show, style='Card.TFrame'); buttons.pack(fill='x', pady=(8, 4))
        self.ready_button = ttk.Button(buttons, text='① Mainshow ready', style='Ready.TButton',
                                       command=lambda: self.action(self.make_ready))
        self.ready_button.pack(side='left')
        self.trigger_button = ttk.Button(buttons, text='② Trigger mainshow', style='Go.TButton',
                                         command=lambda: self.action(self.trigger))
        self.trigger_button.pack(side='left', padx=10)
        self.idle_button = ttk.Button(buttons, text='Stop → idle', style='Big.TButton', command=lambda: self.action(self.make_idle))
        self.idle_button.pack(side='left')
        row = ttk.Frame(show, style='Card.TFrame'); row.pack(fill='x', pady=(6, 0))
        ttk.Label(row, text='Trigger sends SHOW_START to:', style='CardMuted.TLabel').pack(side='left')
        self.target = tk.StringVar(value='cube')
        self.target_cube = ttk.Radiobutton(row, text='this cube only', value='cube', variable=self.target, style='Card.TRadiobutton')
        self.target_cube.pack(side='left', padx=(8, 0))
        ttk.Radiobutton(row, text='all cubes (broadcast, like the show)', value='broadcast', variable=self.target,
                        style='Card.TRadiobutton').pack(side='left', padx=(8, 0))
        ttk.Label(show, style='CardMuted.TLabel', wraplength=900, justify='left', text=(
            'A cube only starts the show if it is mainshow-ready (neon). Stop → idle ends the show on this cube. '
            'The controller\'s BOOT button and trigger input (D1 to GND) always broadcast.')).pack(anchor='w', pady=(8, 0))

        # Show clock
        clock = ttk.Frame(outer, style='Card.TFrame', padding=12); clock.pack(fill='x', pady=(10, 0))
        ttk.Label(clock, text='SHOW CLOCK (EXPECTED: CUBES DO NOT REPORT BACK)', style='CardMuted.TLabel',
                  font=('Helvetica', 10, 'bold')).pack(anchor='w')
        row = ttk.Frame(clock, style='Card.TFrame'); row.pack(fill='x')
        self.clock_label = tk.Label(row, text='—', bg=CARD, fg=MUTED, font=(hostos.MONO_FONT, 30, 'bold'))
        self.clock_label.pack(side='left')
        self.segment_label = tk.Label(row, text='No show started', bg=CARD, fg=MUTED, font=('Helvetica', 15, 'bold'),
                                      anchor='w', justify='left', wraplength=620)
        self.segment_label.pack(side='left', padx=16)
        self.show_bar = ttk.Progressbar(clock, maximum=SHOW_LENGTH_MS, length=900)
        self.show_bar.pack(fill='x', pady=(6, 0))
        self.show_info = ttk.Label(clock, text='', style='CardMuted.TLabel')
        self.show_info.pack(anchor='w')

        self.status = tk.StringVar(value='Connect the Mainshow controller.')
        self.status_label = tk.Label(outer, textvariable=self.status, bg=CARD, fg=BLUE, font=('Helvetica', 14, 'bold'),
                                     anchor='w', padx=14, pady=8, wraplength=920, justify='left')
        self.status_label.pack(fill='x', pady=(10, 8))
        self.logbox = tk.Text(outer, height=10, bg=CARD, fg=MUTED, relief='flat', font=(hostos.MONO_FONT, 10), state='disabled')
        self.logbox.pack(fill='both', expand=True)

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
            messagebox.showerror('Mainshow Controller', str(exc), parent=self.root)
        self.render()

    # ---------- controller link ----------
    def scan_ports(self, prefer=None):
        controllers = dongle.controllers(self.db)
        excluded = {mac for mac, role in self.db.roles().items() if role == 'excluded'}
        self.port_rows = {}
        for p in dongle.ports():
            serial = (p.get('serial') or '').upper()
            mark = (' · Mainshow controller' if serial in controllers else ' · pairing station' if serial in dongle.PROTECTED
                    else ' · dongle / spare' if serial in excluded else '')
            self.port_rows[f'{p["port"]} — {serial or p.get("description") or "USB serial"}{mark}'] = p
        labels = list(self.port_rows)
        self.ports_box['values'] = labels
        if prefer:
            label = next((l for l, p in self.port_rows.items() if p['port'] == prefer), None)
            if label is None:
                label = prefer
                self.port_rows[label] = dict(port=prefer, key=prefer, candidate=True, serial=None)
            self.port.set(label)
        elif self.port.get() not in self.port_rows:
            self.port.set(next((l for l in labels if 'Mainshow controller' in l), ''))

    def selected_port(self):
        return self.port_rows.get(self.port.get())

    def toggle_connection(self):
        if self.transport.port:
            self.disconnect('Disconnected')
        else:
            self.connect()

    def connect(self):
        port = self.selected_port()
        if not port:
            raise ValueError('Choose the controller\'s USB port (Rescan after plugging it in)')
        if self.busy:
            raise ValueError('Wait for the flash to finish')
        self.transport.open(port['port'])  # PortLock: refuses a port the Zone DB Manager or a flasher holds
        self.session.open()
        self.link_status.configure(text=f'Opened {port["port"]}; waiting for the controller…', foreground=AMBER)
        self.log('Opened ' + port['port'])

    def disconnect(self, reason):
        self.transport.close()
        self.session.close()
        self.link_status.configure(text=reason, foreground=MUTED)
        self.log(reason)

    def send(self, message):
        try:
            self.transport.send(message)
        except ValueError:
            self.link_lost = self.link_lost or 'Controller USB connection lost'

    def on_hello(self):
        info = self.session.info
        firmware, mac = info.get('firmware', '?'), info.get('mac')
        if self.session.problem:
            self.link_status.configure(text=f'{mac} · {self.session.problem}', foreground=RED)
            return
        dongle_board = not dongle.is_controller(firmware)
        # A Workstation or General Radio also answers ① and ②, but it is a dongle, not the show trigger:
        # it is not recorded as the controller (that record would lock it out of every other firmware).
        if mac and not dongle_board and mac not in dongle.controllers(self.db):
            dongle.set_controller(self.db, mac, True)  # so the dongle flasher leaves it alone
            self.log(f'Recorded {mac} as the Mainshow controller')
        old = not dongle.current(firmware)
        inputs = (f' · no physical trigger ({dongle.label(info).lower()})' if info.get('button_pin') is None else
                  f' · BOOT button GPIO{info.get("button_pin")} · trigger input GPIO{info.get("trigger_pin")} (XIAO D1)')
        self.link_status.configure(foreground=AMBER if old else GREEN, text=(
            f'Connected · {mac} · {firmware} · channel {info.get("channel")}{inputs} · {info.get("shows", 0)} show(s) since boot' +
            (f' · Flash controller firmware… updates it to {FIRMWARE}' if old else '')))
        if self.expect_firmware:
            self.expect_firmware = False
            self.set_status(f'Controller flashed and verified: {mac} reports {firmware}' if not old else
                            f'Controller answers but reports {firmware}, expected {FIRMWARE}', GREEN if not old else AMBER)
        else:
            self.set_status('Controller ready. ① makes the cube mainshow-ready, ② starts the show.', GREEN)

    def flash_controller(self):
        port = self.selected_port()
        if not port:
            raise ValueError('Choose the board to convert and Rescan first')
        if self.busy:
            raise ValueError('Wait for the current operation to finish')
        if self.transport.port:
            self.disconnect('Disconnected to flash the controller')
        serial = (port.get('serial') or '?').upper()
        if not messagebox.askokcancel('Flash Mainshow controller', (
                f'Write the Mainshow controller firmware ({FIRMWARE}) to\n{port["port"]} ({serial})?\n\n'
                'This replaces whatever the board runs now (for a spare dongle, its pairing-station relay: the Zone '
                'Database Manager will need the other dongle). Cubes, zone boards and the installed pairing station are '
                'refused automatically; a port the Zone Database Manager has open is refused; NVS is preserved. '
                f'Build: {dongle.build_state(dongle.MAINSHOW)} (rebuilt first if needed).'), parent=self.root):
            return
        known = dongle.known_boards(self.db, ZoneStore(self.db).zones())
        folder = DATA / 'mainshow' / time.strftime('%Y%m%d-%H%M%S')
        self.busy = 'flash'
        self.progress.pack(anchor='w', pady=(6, 0)); self.progress['value'] = 0
        self.set_status(f'Flashing the controller on {port["port"]}…')

        def work():
            try:
                mac = dongle.flash(port, known, folder, lambda kind, value: self.events.put(('flash', kind, value)),
                                   firmware=dongle.MAINSHOW)
                self.events.put(('flash_done', port, mac, None))
            except Exception as exc:
                self.events.put(('flash_done', port, None, exc))
        threading.Thread(target=work, daemon=True).start()

    def flash_done(self, port, mac, error):
        self.busy = None
        self.progress.pack_forget()
        if error:
            self.set_status(f'Controller not flashed: {error}', RED)
            self.log(f'Controller flash failed: {error}')
            return
        self.db.set_role(mac, 'excluded')  # never a cube: the cube and zone flashers leave it alone
        dongle.set_controller(self.db, mac, True)
        self.log(f'Controller {mac} flashed; recorded as the Mainshow controller')
        self.set_status(f'Controller {mac} written; connecting to verify…', AMBER)
        self.expect_firmware = True
        self.root.after(2500, lambda: self.action(lambda: (self.scan_ports(prefer=port['port']), self.connect())))

    # ---------- cube and show ----------
    def lookup_cube(self, quiet=False):
        try:
            number = int(self.cube_var.get().strip().lstrip('#'))
            mac, row = find_cube(self.db, number)
        except ValueError as exc:
            self.cube = None
            self.cube_label.configure(text=str(exc) if 'invalid literal' not in str(exc) else 'Enter a cube number',
                                      foreground=RED)
            if not quiet:
                raise
            return
        self.cube = (number, mac)
        self.cube_label.configure(text=f'{mac} · {row.get("status") or "—"}', foreground=FG)

    def require_cube(self):
        self.lookup_cube()
        return self.cube

    def make_ready(self):
        number, mac = self.require_cube()
        self.session.set_zone(mac, 4, f'#{number}')

    def make_idle(self):
        number, mac = self.require_cube()
        self.session.set_zone(mac, 0, f'#{number}')
        self.session.forget_show(mac)

    def trigger(self):
        if self.target.get() == 'broadcast':
            if not messagebox.askokcancel('Trigger mainshow', 'Broadcast SHOW_START to every cube in range?\n\n'
                                          'Every mainshow-ready cube starts the show.', parent=self.root):
                return
            self.session.trigger('broadcast')
        else:
            number, mac = self.require_cube()
            self.session.trigger(mac, f'#{number}')

    # ---------- loop ----------
    def poll(self):
        if self.closing:
            return
        try:
            for _ in range(200):
                try:
                    event = self.transport.inbox.get_nowait()
                except queue.Empty:
                    break
                if event.get('event') == 'disconnected':
                    self.link_lost = 'Controller disconnected'
                    break
                if event.get('event') == 'boot_log':
                    continue  # the plain-text banner at boot
                if self.session.handle(event) == 'hello':
                    self.on_hello()
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
                        self.set_status('Flashing controller: ' + value); self.log(value)
                    elif kind == 'log' and 'rror' in value:
                        self.log(value)
                elif item[0] == 'flash_done':
                    self.flash_done(*item[1:])
            if self.link_lost:
                reason, self.link_lost = self.link_lost, None
                if self.transport.port:
                    self.disconnect(reason)
            was = self.session.connected
            self.session.heartbeat()
            if self.transport.port and self.session.problem and not self.session.usable():
                self.link_status.configure(text=self.session.problem, foreground=RED)
            elif was and not self.session.connected:
                self.link_status.configure(text=self.session.problem or 'Controller stopped answering', foreground=AMBER)
            self.render()
        except Exception as exc:  # never let one bad event stop the poll loop
            self.log(f'Internal error: {exc}')
        self.root.after(100, self.poll)

    def render(self):
        usable = bool(self.transport.port) and self.session.usable() and not self.session.busy()
        for button in (self.ready_button, self.trigger_button, self.idle_button):
            button.state(['!disabled'] if usable else ['disabled'])
        self.connect_button.configure(text='Disconnect' if self.transport.port else 'Connect')
        idle = not self.busy
        for button in (self.flash_button, self.rescan_button, self.connect_button):
            button.state(['!disabled'] if idle else ['disabled'])
        state = self.session.show_state()
        if state is None:
            self.clock_label.configure(text='—', fg=MUTED)
            self.segment_label.configure(text='No show started', fg=MUTED)
            self.show_bar['value'] = 0
            self.show_info.configure(text='')
            return
        elapsed, segment = state
        running = elapsed * 1000 < SHOW_LENGTH_MS
        self.clock_label.configure(text=clock_text(elapsed), fg=NEON if running else MUTED)
        self.segment_label.configure(text=segment, fg=FG if running else MUTED)
        self.show_bar['value'] = min(elapsed * 1000, SHOW_LENGTH_MS)
        show = self.session.show
        self.show_info.configure(text=f'Show {show["show_id"]} · {show["name"]} · started by {show["source"]} · '
                                      f'ends at {clock_text(SHOW_LENGTH_MS / 1000)}')

    def close(self):
        if self.busy and not messagebox.askokcancel('Mainshow Controller', 'A flash is running. Quit anyway?', parent=self.root):
            return
        self.closing = True
        self.transport.close()
        self.db.close()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--database', type=Path, default=DATA / 'devices.sqlite3')
    parser.add_argument('--port', help='Controller serial port (default: the recorded Mainshow controller)')
    parser.add_argument('--connect', action='store_true', help='Connect to the controller at launch')
    parser.add_argument('--cube', type=int, default=DEFAULT_CUBE, help=f'Cube number to start with (default {DEFAULT_CUBE})')
    args = parser.parse_args()
    args.database.parent.mkdir(parents=True, exist_ok=True)
    instance_lock = args.database.with_suffix('.mainshow.lock').open('a')
    root = tk.Tk()
    try:
        hostos.lock_file(instance_lock)
    except BlockingIOError:
        root.withdraw()
        messagebox.showerror('Mainshow Controller', 'The Mainshow Controller is already open for this database.')
        raise SystemExit(1)
    App(root, args.database, args.port, args.connect or bool(args.port), args.cube)
    root.mainloop()


if __name__ == '__main__':
    main()
