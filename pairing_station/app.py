#!/usr/bin/env python3
import argparse
import fcntl
from collections import deque
from http_api import AppAPI
from dashboard import Dashboard
import queue
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from pathlib import Path
from serial.tools import list_ports
from database import Database, ROOT
from controller import Controller
from transport import Transport
from zone_registry import ZoneRegistry

class App:
    def __init__(self, root, database, api_port=8765):
        self.recent_events = deque(maxlen=300)
        self.recent_logs = deque(maxlen=300)
        self.root = root
        self.db = Database(database)
        self.transport = Transport()
        self.controller = Controller(self.db, self.transport.send, self.log)
        self.zones = ZoneRegistry(self.db, self.transport.send, self.log)
        self.zones_window = None
        self.last_ping = 0
        self.last_rx = 0
        self.opened_at = 0
        self.closing = False
        root.title('NCT · NFC Pairing Station')
        self.dashboard = Dashboard(self)
        # Native menus expose the same actions to keyboard/accessibility users.
        menubar = tk.Menu(root)
        station_menu = tk.Menu(menubar, tearoff=False)
        for label, callback in [
            ('Connect', self.connect), ('Discover', self.controller.discover),
            ('Start pairing new', self.controller.start_pair),
            ('Transmit existing 32', lambda: self.controller.transmit([r for r in self.db.original_batch() if not self.db.excluded(r['mac'])])),
            ('Flash selected', lambda: self.controller.flash([self.selected()])),
            ('Pause / Stop', self.controller.stop)]:
            station_menu.add_command(label=label, command=lambda cb=callback: self.action(cb))
        menubar.add_cascade(label='Station', menu=station_menu)
        zones_menu = tk.Menu(menubar, tearoff=False)
        zones_menu.add_command(label='Zones…', command=lambda: self.action(self.open_zones))
        zones_menu.add_command(label='Publish zone database', command=lambda: self.action(
            lambda: (self.zones.require(self.controller.station, self.controller.connected), self.zones.publish())))
        menubar.add_cascade(label='Zones', menu=zones_menu)
        root.configure(menu=menubar)
        root.bind('<Escape>', lambda _: self.action(self.controller.stop))
        self.refresh_ports()
        self.render()
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.api = AppAPI(self, database.parent, api_port) if api_port else None
        if self.api: self.log('HTTP API: '+self.api.url)
        root.after(100, self.poll)

    def log(self, message):
        self.recent_logs.append(dict(time=time.time(), message=str(message)))
        if not hasattr(self, 'logbox'): return
        self.logbox.configure(state='normal')
        self.logbox.insert('end', time.strftime('%H:%M:%S')+'  '+str(message)+'\n')
        if int(self.logbox.index('end-1c').split('.')[0]) > 500:
            self.logbox.delete('1.0','100.0')
        self.logbox.see('end')
        self.logbox.configure(state='disabled')

    def action(self, callback):
        try:
            callback()
        except Exception as exc:
            self.log(str(exc))
            messagebox.showerror('Pairing station', str(exc), parent=self.root)
        self.render()

    def refresh_ports(self):
        found = [p for p in list_ports.comports() if '/tty.' not in p.device]
        ports = [p.device for p in found]
        self.ports['values'] = ports
        if self.port.get() not in ports:
            # Prefer a known station (its MAC is the USB serial number) over zone boards or cubes on USB.
            stations = {mac for mac, role in self.db.roles().items() if role == 'excluded'}
            known = next((p.device for p in found if (p.serial_number or '').upper() in stations), None)
            self.port.set(known or next((p for p in ports if 'usbmodem' in p), ports[0] if ports else ''))

    def connect(self):
        if self.transport.port:
            raise ValueError('Disconnect the current station first')
        self.transport.open(self.port.get())
        self.opened_at = self.last_rx = time.monotonic()
        self.controller.emit('hello')
        self.log('Opened '+self.port.get())

    def disconnect(self):
        if self.controller.connected:
            self.controller.stop()
            self.root.after(1200, self.finish_disconnect)
        else:
            self.finish_disconnect()

    def finish_disconnect(self):
        self.controller.disconnected('Disconnected; any pending registration can be retried.')
        self.transport.close()
        self.render()

    def selected(self):
        mac = self.dashboard.selected_mac
        if not mac: raise ValueError('Select a device card')
        return self.db.get(mac) or dict(mac=mac, cube_id=None, uid=None, pending_uid=None)

    def selected_registered(self):
        row = self.selected()
        if row['cube_id'] is None: raise ValueError('Pair this discovered device first')
        return row

    def repair(self):
        row = self.selected()
        if row['cube_id'] is None:
            while True:
                number = simpledialog.askinteger('Register device — number',
                    f"Device {row['mac']}\n\nEnter the number on its label to begin NFC registration:",
                    minvalue=1, maxvalue=0xFFFFFFFF, parent=self.root)
                if number is None:
                    return
                try:
                    self.db.validate_number(row['mac'], number)
                except ValueError as exc:
                    messagebox.showerror('Number unavailable', str(exc), parent=self.root)
                    continue
                self.controller.repair(row['mac'], number)
                return
        if not row.get('uid') or messagebox.askokcancel('Re-pair selected device',
                f'Replace the stored NFC pairing for {row["mac"]}?\nIts cube ID will be preserved. Scan only the blinking cube.', parent=self.root):
            self.controller.repair(row['mac'])

    def rename(self):
        row = self.selected()
        number = simpledialog.askinteger('Rename device',
            f"Device {row['mac']}\nCurrent number: {row['cube_id'] or 'Unnumbered'}\n\nEnter the number on its label:",
            initialvalue=row['cube_id'], minvalue=1, maxvalue=0xFFFFFFFF, parent=self.root)
        if number is not None:
            self.controller.rename(row['mac'], number)

    def export_csv(self):
        path = filedialog.asksaveasfilename(defaultextension='.csv', initialfile='devices.csv')
        if path: self.db.export_csv(path); self.log('Exported '+path)

    def export_header(self):
        path = filedialog.asksaveasfilename(defaultextension='.h', initialfile='CubeTable.h')
        if path: self.db.export_header(path); self.log('Exported '+path+'; pending replacement UIDs excluded')

    def open_zones(self):
        from zones_window import ZonesWindow
        if self.zones_window:
            self.zones_window.window.lift()
        else:
            self.zones_window = ZonesWindow(self)

    def render(self):
        self.dashboard.render()
        if self.zones_window:
            self.zones_window.render()

    def poll(self):
        if self.closing: return
        try:
            for _ in range(300):
                try: event = self.transport.inbox.get_nowait()
                except queue.Empty: break
                self.last_rx = time.monotonic()
                self.recent_events.append(dict(time=time.time(), **event))
                kind = event.get('event')
                if kind == 'disconnected':
                    self.controller.disconnected(event.get('detail','Disconnected'))
                    self.transport.close()
                else:
                    was_connected = self.controller.connected
                    if self.zones.event(event):
                        continue
                    self.controller.event(event)
                    if kind == 'hello' and self.controller.connected and not was_connected:
                        self.controller.discover()
                    if kind not in ('pong','device','discover_sent') and not (kind=='radio' and event.get('type')==1) and not (kind=='nfc_i2c' and event.get('status')==0):
                        self.log(event)
            now = time.monotonic()
            if self.transport.port and self.controller.connected and now-self.last_ping>=1:
                self.controller.emit('ping')
                self.last_ping = now
            if self.transport.port and not self.controller.connected and now-self.opened_at>3 and now-self.opened_at<4:
                self.controller.emit('hello')
                self.opened_at = 0
            if self.transport.port and now-self.last_rx>(8 if self.controller.connected else 30):
                self.finish_disconnect()
                self.log('Station stopped responding; reconnect.')
            if self.api: self.api.drain()
            self.controller.tick()
            self.zones.tick(self.transport.port is not None and self.controller.connected, self.controller.station, bool(self.controller.mode))
            self.render()
        except Exception as exc:
            self.log('Operation paused: '+str(exc))
            try: self.controller.stop()
            except Exception: pass
            self.controller.disconnected('Operation stopped after an error. Reconnect to retry.')
            self.transport.close()
        self.root.after(100, self.poll)

    def close(self):
        self.closing = True
        if self.api: self.api.close()
        try:
            if self.controller.connected: self.controller.stop()
        except Exception: pass
        self.root.after(1200, self.finish_close)

    def finish_close(self):
        self.transport.close()
        self.db.close()
        self.root.destroy()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', type=Path, default=ROOT/'data'/'devices.sqlite3')
    parser.add_argument('--connect', action='store_true', help='Connect to the initially selected USB port at launch')
    parser.add_argument('--api-port', type=int, default=8765, help='Loopback HTTP port; 0 disables API')
    args = parser.parse_args()
    args.database.parent.mkdir(parents=True, exist_ok=True)
    instance_lock = args.database.with_suffix('.lock').open('a')
    root = tk.Tk()
    try:
        fcntl.flock(instance_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        root.withdraw()
        messagebox.showerror('Pairing station', 'This database is already open in another pairing window.')
        raise SystemExit(1)
    app = App(root, args.database, args.api_port)
    if args.connect and app.port.get():
        root.after(200, lambda: app.action(app.connect))
    root.mainloop()
