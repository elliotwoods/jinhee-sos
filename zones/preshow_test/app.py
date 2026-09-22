#!/usr/bin/env python3
"""Preshow plate link test: raise TouchDesigner cues by hand, with no reader attached.

Drives PreshowZone's leased host override (`HOST ARM` / `HOST PING` / `HOST ON [n]` /
`HOST OFF` / `HOST DISARM`), the same shape the pool calibration app uses. The firmware
watchdog is 1.5 s, so this pings at 0.35 s and disarms the moment telemetry goes quiet —
a closed window or an unplugged laptop must never leave a cue latched ON in the show.
"""
import argparse
import json
import sys
import time
import tkinter as tk
from tkinter import ttk
from pathlib import Path

import serial
from serial.tools import list_ports

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'rangetest'))
sys.path.insert(0, str(ROOT / 'pairing_station'))
from serial_open import open_serial          # noqa: E402  native USB-JTAG safe open
from port_lock import PortLock               # noqa: E402
import hostos                                # noqa: E402

BG, PANEL, TEXT, MUTED, ACCENT = '#101820', '#1c2833', '#eff7fa', '#a7bac7', '#52e0bd'
WARN, ALERT = '#e0c352', '#e08a7a'
POINTS = (1, 2, 3, 4)
PING_INTERVAL = 0.35      # against the firmware's 1500 ms lease
STALE_AFTER = 1.0         # no telemetry for this long: assume the link is gone and disarm
SWITCH_DELAY = 300        # ms between OFF and ON when moving to another point, so each edge
                          # gets its own burst and retry window


class App:
    def __init__(self, root, port=None):
        self.root = root
        self.serial = None
        self.lock = None
        self.buffer = b''
        self.status = {}
        self.last_rx = self.last_ping = self.opened = self.last_scan = 0.0
        self.armed = False
        self.pending_on = None
        # These boards drop off USB when they are power-cycled, and their native USB-JTAG
        # peripheral can wedge until replugged — which happens constantly while carrying one
        # around to test range. Reconnect by ourselves unless the operator said to stop.
        self.autoconnect = True
        root.title('Preshow · Link test')
        root.geometry('760x680')
        root.minsize(700, 620)
        root.configure(bg=BG)
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TCombobox', padding=6)
        style.configure('Action.TButton', background=PANEL, foreground=TEXT, padding=(12, 9),
                        font=('Helvetica', 11, 'bold'), borderwidth=0)
        style.map('Action.TButton', background=[('active', '#304858')])
        style.configure('Cue.TButton', background=PANEL, foreground=TEXT, padding=(10, 8),
                        font=('Helvetica', 13, 'bold'), borderwidth=0)
        style.map('Cue.TButton', background=[('active', '#304858')], foreground=[('disabled', MUTED)])
        style.configure('On.Cue.TButton', background=ACCENT, foreground=BG)
        style.map('On.Cue.TButton', background=[('active', '#7cf1d5')], foreground=[('active', BG)])

        outer = tk.Frame(root, bg=BG, padx=26, pady=20)
        outer.pack(fill='both', expand=True)
        self.label(outer, 'PRESHOW / LINK TEST', 11, ACCENT).pack(anchor='w')
        self.label(outer, 'TouchDesigner cues, by hand', 25, TEXT).pack(anchor='w', pady=(6, 4))
        self.label(outer, 'USB → plate → ESP-NOW ch 2 → media bridge → Serial DAT', 12).pack(anchor='w')

        bar = tk.Frame(outer, bg=BG)
        bar.pack(fill='x', pady=(16, 10))
        self.port = tk.StringVar(value=port or '')
        self.ports = ttk.Combobox(bar, textvariable=self.port, width=30, state='readonly')
        self.ports.pack(side='left')
        ttk.Button(bar, text='Refresh', command=self.refresh_ports, style='Action.TButton').pack(side='left', padx=8)
        self.connect_button = ttk.Button(bar, text='Connect', command=self.connect, style='Action.TButton')
        self.connect_button.pack(side='left')

        self.state = self.label(outer, 'DISCONNECTED', 15, TEXT)
        self.state.pack(anchor='w')
        self.detail = self.label(outer, 'The plate drops any held cue 1.5 s after this app stops talking.', 11)
        self.detail.pack(anchor='w', pady=(2, 12))

        cues = tk.Frame(outer, bg=BG)
        cues.pack(fill='x')
        self.buttons = {}
        for point in POINTS:
            cell = tk.Frame(cues, bg=BG)
            cell.pack(side='left', expand=True, fill='x', padx=(0, 10))
            self.label(cell, f'POINT {point}', 11, MUTED).pack(anchor='w')
            button = ttk.Button(cell, text='OFF', style='Cue.TButton',
                                command=lambda p=point: self.toggle(p))
            button.pack(fill='x', pady=(4, 0))
            self.buttons[point] = button

        panel = tk.Frame(outer, bg=PANEL, padx=16, pady=14)
        panel.pack(fill='x', pady=(18, 0))
        self.link = self.label(panel, '', 12, TEXT)
        self.link.pack(anchor='w')
        self.counters = self.label(panel, '', 11)
        self.counters.pack(anchor='w', pady=(4, 0))
        self.bridge = self.label(panel, '', 11)
        self.bridge.pack(anchor='w', pady=(4, 0))

        self.log = tk.Text(outer, height=12, bg=PANEL, fg=MUTED, font=(hostos.MONO_FONT, 10),
                           relief='flat', state='disabled')
        self.log.pack(fill='both', expand=True, pady=(16, 0))
        self.log.tag_configure('cue', foreground=ACCENT)
        self.log.tag_configure('warn', foreground=WARN)
        self.log.tag_configure('quiet', foreground='#55707f')

        root.bind('<Escape>', lambda e: self.all_off())
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh_ports()
        self.render()
        root.after(40, self.poll)
        # Connect by itself when there is no ambiguity about which board is meant.
        if port or len(self.ports['values']) == 1:
            root.after(300, self.connect)

    # ---- chrome ----

    def label(self, parent, text, size=12, color=MUTED):
        return tk.Label(parent, text=text, bg=parent.cget('bg'), fg=color,
                        font=('Helvetica', size), justify='left')

    def record(self, text, tag=None):
        self.log.configure(state='normal')
        self.log.insert('end', time.strftime('%H:%M:%S') + '  ' + text + '\n', tag or ())
        if int(self.log.index('end-1c').split('.')[0]) > 400:
            self.log.delete('1.0', '100.0')
        self.log.see('end')
        self.log.configure(state='disabled')

    def refresh_ports(self):
        ports = [p.device for p in list_ports.comports() if p.vid is not None]
        self.ports['values'] = ports
        if not self.port.get() and ports:
            self.port.set(ports[0])

    # ---- link ----

    def connect(self):
        if self.serial:
            self.autoconnect = False  # an explicit Disconnect means stay disconnected
            self.disconnect()
            return
        self.autoconnect = True
        path = self.port.get()
        if not path:
            self.record('Pick a port first')
            return
        try:
            self.lock = PortLock(path)
            self.serial = open_serial(path)
        except (serial.SerialException, OSError, RuntimeError) as exc:
            self.record(str(exc), 'warn')
            self.release()
            return
        self.buffer = b''
        self.status = {}
        self.opened = self.last_rx = time.monotonic()
        self.armed = False
        self.pending_on = None
        self.connect_button.configure(text='Disconnect')
        self.state.configure(text='CONNECTING · arming the plate')
        self.record('Opened ' + path)
        self.send('HOST ARM')
        self.send('HOST STATUS')
        self.render()

    def send(self, command):
        if not self.serial:
            return False
        try:
            data = (command + '\n').encode('ascii')
            if self.serial.write(data) != len(data):
                raise serial.SerialException('Incomplete USB write')
            return True
        except (serial.SerialException, OSError) as exc:
            self.record(str(exc), 'warn')
            self.disconnect(release_cue=False)
            return False

    def release(self):
        if self.lock:
            self.lock.close()
            self.lock = None

    def disconnect(self, release_cue=True):
        connection, self.serial = self.serial, None
        if connection:
            try:
                # Explicitly, rather than trusting the 1.5 s lease: the cue should go out
                # now, while the port is still open to carry it.
                if release_cue:
                    connection.write(b'HOST DISARM\n')
                    connection.flush()
            except (serial.SerialException, OSError):
                pass
            finally:
                connection.close()
        self.release()
        self.armed = False
        self.status = {}
        self.pending_on = None
        self.connect_button.configure(text='Connect')
        self.state.configure(text='DISCONNECTED')
        self.render()

    def close(self):
        self.disconnect()
        self.root.destroy()

    # ---- cues ----

    def held(self):
        """The point the plate is currently holding ON, or None."""
        if self.status.get('state') != 'ON':
            return None
        point = self.status.get('point')
        return point if point in POINTS else None

    def toggle(self, point):
        if not self.armed:
            self.record('Not armed yet', 'warn')
            return
        current = self.held()
        if current == point:
            self.send('HOST OFF')
            return
        if current is not None:
            # Two commands, spaced: the firmware refuses an implicit switch so that each
            # edge gets its own burst and retry window rather than being overwritten.
            self.send('HOST OFF')
            self.pending_on = point
            self.root.after(SWITCH_DELAY, self.flush_pending)
            return
        self.send(f'HOST ON {point}')

    def flush_pending(self):
        point, self.pending_on = self.pending_on, None
        if point is not None and self.armed:
            self.send(f'HOST ON {point}')

    def all_off(self):
        self.pending_on = None
        if self.armed:
            self.send('HOST OFF')

    # ---- telemetry ----

    def handle(self, line):
        if line.startswith('{') and '"type":"host"' in line:
            try:
                self.status = json.loads(line)
            except ValueError:
                return
            self.armed = bool(self.status.get('armed'))
            self.render()
            return
        if line.startswith('MEDIA -> '):
            self.record(line, 'cue')
        elif line.startswith('MEDIA ACK'):
            self.record(line, 'cue')
        elif line.startswith('MEDIA FAIL') or line.startswith('ERR '):
            self.record(line, 'warn')
        elif line.startswith('PN532') or line.startswith('NFC:'):
            # Expected until a reader is wired to this board; kept visible but quiet.
            self.record(line, 'quiet')
        elif line.startswith('MEDIA') or line.startswith('EVENT') or line.startswith('EVT'):
            self.record(line)

    def render(self):
        held = self.held()
        for point, button in self.buttons.items():
            on = held == point
            button.configure(text='ON' if on else 'OFF',
                             style='On.Cue.TButton' if on else 'Cue.TButton',
                             state='normal' if self.armed else 'disabled')
        # Driven by the telemetry rather than by the port, so the panel says only what the
        # plate has actually told us. `status` is cleared on disconnect.
        if not self.status:
            self.detail.configure(text='The plate drops any held cue 1.5 s after this app stops talking.')
            self.link.configure(text='')
            self.counters.configure(text='')
            self.bridge.configure(text='')
            if self.serial:
                self.state.configure(text='CONNECTING · waiting for the plate')
            return
        mode = self.status.get('mode', '?')
        point = self.status.get('configured_point', 0)
        firmware = self.status.get('firmware', '?')
        self.state.configure(text=('ARMED' if self.armed else 'CONNECTED · not armed') +
                                  f'   ·   flashed point {point}   ·   {firmware}')
        if mode == 'legacy':
            self.detail.configure(
                text='LEGACY MODE · no bridge beacon heard, so the plate is also sending the '
                     'old 2-byte packet. That is what the current TouchDesigner bridge reads.')
            acked = 'n/a (the old bridge cannot acknowledge)'
        else:
            self.detail.configure(text='MODERN MODE · a bridge is answering; cues are acknowledged end to end.')
            acked = ('yes, %s ms' % self.status.get('ack_ms', '?')) if self.status.get('acked') else 'NO'
        self.link.configure(text=f'mode {mode}   ·   cue {self.status.get("state", "?")} on point '
                                 f'{self.status.get("point", "?")}   ·   acknowledged {acked}')
        self.counters.configure(
            text='seq %s   ·   sent %s   ·   legacy %s   ·   retries %s   ·   acks %s   ·   failed %s   ·   errors %s'
                 % tuple(self.status.get(k, '?') for k in
                         ('seq', 'sent', 'legacy_sent', 'retries', 'acks', 'failed', 'errors')))
        mac = self.status.get('bridge_mac') or 'not heard from'
        seen = self.status.get('bridge_seen_ms', 0)
        sees = 'yes' if self.status.get('bridge_sees_me') else 'no'
        self.bridge.configure(text=f'bridge {mac}   ·   last beacon {seen} ms ago   ·   bridge sees me: {sees}')

    def poll(self):
        self.root.after(40, self.poll)
        now = time.monotonic()
        if not self.serial:
            # Watch for the board coming back, so a power-cycle or a replug does not need
            # anyone at the laptop.
            if self.autoconnect and now - self.last_scan >= 1.5:
                self.last_scan = now
                known = set(self.ports['values'])
                self.refresh_ports()
                candidates = list(self.ports['values'])
                if len(candidates) == 1:
                    if set(candidates) != known:
                        self.record('Board detected on ' + candidates[0])
                    self.port.set(candidates[0])
                    self.connect()
                elif not candidates:
                    self.state.configure(text='WAITING · no board on USB')
            return
        try:
            chunk = self.serial.read(4096)
        except (serial.SerialException, OSError) as exc:
            self.record(str(exc), 'warn')
            self.disconnect(release_cue=False)
            return
        if chunk:
            self.last_rx = now
            self.buffer += chunk
            if len(self.buffer) > 16384:
                self.buffer = b''
            while b'\n' in self.buffer:
                line, self.buffer = self.buffer.split(b'\n', 1)
                text = line.decode('utf-8', 'replace').strip()
                if text:
                    self.handle(text)
        if now - self.last_ping >= PING_INTERVAL:
            self.last_ping = now
            self.send('HOST PING')
            self.send('HOST STATUS')
        # Telemetry has stopped: let the lease lapse rather than pretending we are in control.
        if self.armed and now - self.last_rx > STALE_AFTER:
            self.record('Plate stopped answering; disarming', 'warn')
            self.disconnect(release_cue=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', help='Serial port of the preshow plate')
    args = parser.parse_args()
    root = tk.Tk()
    App(root, args.port)
    root.mainloop()


if __name__ == '__main__':
    main()
