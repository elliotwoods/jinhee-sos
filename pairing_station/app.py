#!/usr/bin/env python3
import argparse
from collections import deque
from http_api import AppAPI
from dashboard import Dashboard
import queue
import subprocess
import sys
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from pathlib import Path
from serial.tools import list_ports
from database import Database, ROOT
from controller import Controller
from transport import Transport
from usb_identify import UsbIdentifier
from sync_widget import SyncWidget
import hostos
import sightings

class App:
    def __init__(self, root, database, api_port=8765):
        self.recent_events = deque(maxlen=300)
        self.recent_logs = deque(maxlen=300)
        self.root = root
        self.db = Database(database)
        self.transport = Transport()
        self.controller = Controller(self.db, self.transport.send, self.log)
        self.last_ping = 0
        self.last_hello_retry = 0
        self.last_rx = 0
        self.opened_at = 0
        self.closing = False
        self.usb_identifier = UsbIdentifier()
        self.usb_firmware = {}
        self.usb_locked_mac = None
        self.usb_locked_key = None
        self.usb_pending = None
        self.usb_prompt_active = False
        root.title('NCT · NFC Pairing Station')
        self.dashboard = Dashboard(self)
        # Read-only web inventory comparison; never blocks or fails the station.
        # Universal Sync: this app holds the pairing lock itself, so web changes apply only while it is idle.
        self.web_status = SyncWidget(self.sync_slot, database, 'Pairing app', held=('.lock',),
                                     can_apply=lambda: not self.controller.mode, on_synced=lambda _: self.render())
        self.web_status.pack(side='left')
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
        zones_menu.add_command(label='Zone Database Manager…', command=lambda: self.action(self.open_zones))
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
            # ESP32 native USB: named usbmodem on macOS, but only the vendor ID says so on Windows (COMn).
            native = next((p.device for p in found if 'usbmodem' in p.device or p.vid == 0x303A), None)
            self.port.set(known or native or (ports[0] if ports else ''))

    def connect(self):
        if self.transport.port:
            raise ValueError('Disconnect the current station first')
        self.transport.open(self.port.get())
        self.opened_at = self.last_rx = time.monotonic()
        self.controller.emit('hello')
        self.last_hello_retry = self.opened_at
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
                suggested = self.db.suggested_number()
                number = simpledialog.askinteger('Register device — number',
                    f"Device {row['mac']}\n\nSuggested free ID: {suggested} (above 32).\nPress Enter to accept, or type the number on its label:",
                    initialvalue=suggested, minvalue=1, maxvalue=0xFFFFFFFF, parent=self.root)
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
        suggested = row['cube_id'] or self.db.suggested_number()
        number = simpledialog.askinteger('Rename device',
            f"Device {row['mac']}\nCurrent number: {row['cube_id'] or 'Unnumbered'}\n\nPress Enter to accept {suggested}, or type the number on its label:",
            initialvalue=suggested, minvalue=1, maxvalue=0xFFFFFFFF, parent=self.root)
        if number is not None:
            self.controller.rename(row['mac'], number)

    def toggle_usb_identification(self):
        if self.dashboard.usb_enabled.get():
            blocked = {mac for mac, role in self.db.roles().items() if role == 'excluded'}
            if self.controller.station.get('mac'): blocked.add(self.controller.station['mac'])
            try:
                self.usb_identifier.start(blocked, {self.transport.port.port} if self.transport.port else set())
            except Exception:
                self.dashboard.usb_enabled.set(False)
                raise
            self.dashboard.usb_status.set('Watching USB for a cube…')
        else:
            self.usb_identifier.stop()
            self.usb_pending = None
            self.dashboard.usb_status.set('USB identification off; selection remains pinned' if self.usb_locked_mac else 'USB identification off')

    def unlock_usb(self):
        self.usb_locked_mac = self.usb_locked_key = self.usb_pending = None
        self.dashboard.usb_status.set('Unlocked · waiting for a new USB connection' if self.dashboard.usb_enabled.get() else 'USB identification off')
        self.dashboard.render(force=True)

    def poll_usb(self):
        if self.usb_prompt_active: return
        while True:
            try: event = self.usb_identifier.events.get_nowait()
            except queue.Empty: break
            if event['generation'] != self.usb_identifier.generation: continue
            if event['kind'] == 'identified':
                if self.db.excluded(event['mac']) or event['mac'] == self.controller.station.get('mac'): continue
                self.usb_pending = event
                self.usb_firmware[event['mac']] = dict(status='checking', version=None, expected=None, detail='Checking firmware over USB…')
                self.log(f"USB identified {event['mac']} · {event['source']}")
                if self.controller.mode and self.controller.phase != 'stopping':
                    self.controller.stop()
            elif event['kind'] == 'firmware':
                self.usb_firmware[event['mac']] = event['firmware']
                sightings.record(self.db.conn, event['mac'], 'usb', event['firmware'].get('version') or event['firmware'].get('status', ''))
                self.log(f"USB firmware {event['mac']}: {event['firmware']}")
                fw = event['firmware']
                if fw['status'] == 'different':
                    self.controller.notify('error', 'CUBE FIRMWARE UPDATE NEEDED',
                        f"{event['mac']} · Installed: {fw['version']} · Latest local build: {fw['expected']}. Update this cube with USB Flash Station.")
                elif fw['status'] == 'unknown':
                    self.controller.notify('sending', 'CUBE FIRMWARE NOT VERIFIED',
                        f"{event['mac']} · {fw['detail']}. Latest local build: {fw.get('expected') or 'unknown'}.")
                if self.usb_locked_mac == event['mac']:
                    self.dashboard.usb_status.set(f"Pinned {event['mac']} · Firmware {event['firmware']['status']} (see details)")
            elif event['kind'] == 'removed' and event['key'] == self.usb_locked_key:
                self.dashboard.usb_status.set(f'USB removed · {self.usb_locked_mac} stays pinned for registration')
            elif event['kind'] == 'error':
                self.dashboard.usb_status.set('USB: '+event['detail'])
                self.log('USB identification: '+event['detail'])
        if not self.usb_pending or self.controller.mode: return
        event, self.usb_pending = self.usb_pending, None
        mac = event['mac']
        previously_known = self.db.get(mac) is not None
        self.db.reserve(mac, source='usb')
        self.usb_locked_mac, self.usb_locked_key = mac, event['key']
        self.dashboard.usb_status.set(f'Pinned {mac} · unplugging keeps selection')
        self.dashboard.select(mac)
        self.dashboard.reset_scroll()
        row = self.db.get(mac)
        if not previously_known or row['cube_id'] is None:
            self.usb_prompt_active = True
            try:
                while True:
                    suggested = self.db.get(mac)['cube_id'] or self.db.suggested_number()
                    number = simpledialog.askinteger('USB cube — number',
                        f"USB cube {mac}\nSuggested ID: {suggested}.\nPress Enter to accept, or type the number on its label:",
                        initialvalue=suggested, minvalue=1, maxvalue=0xFFFFFFFF, parent=self.root)
                    if number is None: break
                    try:
                        self.db.rename(mac, number, fresh_scan=True)
                        self.log(f'USB cube {mac} assigned #{number}; ready for NFC registration')
                        break
                    except ValueError as exc:
                        messagebox.showerror('Number unavailable', str(exc), parent=self.root)
            finally:
                self.usb_prompt_active = False
            self.dashboard.render(force=True)

    def export_csv(self):
        path = filedialog.asksaveasfilename(defaultextension='.csv', initialfile='devices.csv')
        if path: self.db.export_csv(path); self.log('Exported '+path)

    def export_header(self):
        path = filedialog.asksaveasfilename(defaultextension='.h', initialfile='CubeTable.h')
        if path: self.db.export_header(path); self.log('Exported '+path+'; pending replacement UIDs excluded')

    def open_zones(self):
        """Zone databases are managed by their own app (zones/dbmanager), over its own ESP-NOW dongle."""
        if self.transport.port and not messagebox.askokcancel('Zone Database Manager',
                'The manager needs its own ESP-NOW dongle (an ESP32-C3 with the pairing-station firmware).\n\n'
                'To use this station as the dongle instead, disconnect it here first.\n\nOpen the manager now?',
                parent=self.root):
            return
        subprocess.Popen([sys.executable, str(ROOT.parent / 'zones' / 'dbmanager' / 'app.py'),
                          '--database', str(self.db.path)], **hostos.detached_kwargs())
        self.log('Opened the Zone Database Manager')

    def render(self):
        self.dashboard.render()

    def recover_station_connection(self, now):
        # Logical disconnection can leave a healthy USB handle open (e.g. a
        # command timeout). Re-handshake; never restart the interrupted action.
        if self.transport.port and not self.controller.connected and now-self.last_hello_retry>=3:
            self.controller.emit('hello')
            self.last_hello_retry = now
            self.controller.message = 'Reconnecting to the NFC station…'

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
                    if kind in ('zone_frame', 'zone_sent'):
                        continue  # zone traffic belongs to the Zone Database Manager
                    self.controller.event(event)
                    if kind == 'hello' and self.controller.connected and not was_connected:
                        self.controller.discover()
                    if kind not in ('pong','device','discover_sent') and not (kind=='radio' and event.get('type')==1) and not (kind=='nfc_i2c' and event.get('status')==0):
                        self.log(event)
            now = time.monotonic()
            if self.transport.port and self.controller.connected and now-self.last_ping>=1:
                self.controller.emit('ping')
                self.last_ping = now
            self.recover_station_connection(now)
            if self.transport.port and now-self.last_rx>(8 if self.controller.connected else 30):
                self.finish_disconnect()
                self.log('Station stopped responding; reconnect.')
            if self.api: self.api.drain()
            self.poll_usb()
            self.controller.tick()
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
        self.usb_identifier.stop()
        self.web_status.stop()
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
        hostos.lock_file(instance_lock)
    except BlockingIOError:
        root.withdraw()
        messagebox.showerror('Pairing station', 'This database is already open in another pairing window.')
        raise SystemExit(1)
    app = App(root, args.database, args.api_port)
    if args.connect and app.port.get():
        root.after(200, lambda: app.action(app.connect))
    root.mainloop()
