#!/usr/bin/env python3
"""Poolzone USB / ESP-NOW light test console."""
import argparse
import json
import sys
import time
import tkinter as tk
from tkinter import ttk
import serial
from serial.tools import list_ports

BG, PANEL, TEXT, MUTED, ACCENT = '#101820', '#1c2833', '#eff7fa', '#a7bac7', '#52e0bd'
# Standalone app (no shared modules on its path): the monospace face per host OS.
MONO = 'Menlo' if sys.platform == 'darwin' else 'Consolas' if sys.platform == 'win32' else 'DejaVu Sans Mono'


def toggle_member(slots, member):
    result = list(slots)
    if member in result:
        result[result.index(member)] = 0
    elif 0 in result:
        result[result.index(0)] = member
    else:
        raise ValueError('Six lights are already selected. Switch one off first.')
    return result


class App:
    def __init__(self, root, port=None, central=None):
        self.root = root
        self.serial = None
        self.central_port = central
        self.central_serial = None
        self.central_buffer = b''
        self.central_status = {}
        self.last_central = self.central_retry = 0
        self.ready = False
        self.slots = [0]*6
        self.buffer = b''
        self.last_rx = self.last_ping = self.opened = 0
        self.scanning = False
        self.next_scan = 0
        self.scan_member = 0
        self.channel_pending = False
        root.title('Poolzone · Light test')
        root.geometry('1000x790')
        root.configure(bg=BG)
        root.minsize(880, 740)
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TCombobox', padding=6)
        style.configure('Action.TButton', background=PANEL, foreground=TEXT, padding=(12, 9), font=('Helvetica',11,'bold'), borderwidth=0)
        style.map('Action.TButton', background=[('active', '#304858')])
        style.configure('Stop.TButton', background='#513631', foreground='#ffd5cc', padding=(12,9), font=('Helvetica',11,'bold'))
        style.configure('Light.TButton', background=PANEL, foreground=TEXT, padding=(12,6), font=('Helvetica',15,'bold'), anchor='center', borderwidth=0)
        style.map('Light.TButton', background=[('active','#304858')], foreground=[('disabled', MUTED)])
        style.configure('On.Light.TButton', background=ACCENT, foreground=BG)
        style.map('On.Light.TButton', background=[('active','#7cf1d5')], foreground=[('active',BG)])
        outer = tk.Frame(root, bg=BG, padx=28, pady=22)
        outer.pack(fill='both', expand=True)
        self.label(outer, 'POOLZONE / RADIO LAB', 11, ACCENT).pack(anchor='w')
        self.label(outer, 'Central controller lights', 27, TEXT).pack(anchor='w', pady=(6, 4))
        self.label(outer, 'USB → ESP32 → ESP-NOW  •  23 member frames  •  6 radio slots', 12).pack(anchor='w')
        connection = tk.Frame(outer, bg=PANEL, padx=14, pady=12)
        connection.pack(fill='x', pady=18)
        self.port = tk.StringVar(value=port or '')
        self.ports = ttk.Combobox(connection, textvariable=self.port, width=28)
        self.ports.pack(side='left', padx=(0, 8))
        self.button(connection, 'Refresh', self.refresh_ports).pack(side='left', padx=4)
        self.connect_button = self.button(connection, 'Connect', self.connect)
        self.connect_button.pack(side='left', padx=4)
        self.label(connection, 'Channel', 11).pack(side='left', padx=(20, 6))
        self.channel = tk.StringVar(value='2')
        self.channel_box = ttk.Combobox(connection, textvariable=self.channel, values=list(range(1,14)), width=3, state='readonly')
        self.channel_box.pack(side='left')
        self.button(connection, 'Apply', self.apply_channel).pack(side='left', padx=6)
        self.state = self.label(outer, 'DISCONNECTED', 13, ACCENT)
        self.state.pack(anchor='w')
        self.detail = self.label(outer, 'Connect the ESP32 test bridge to begin.', 11)
        self.detail.pack(anchor='w', pady=(4, 14))
        self.grid = tk.Frame(outer, bg=BG)
        self.grid.pack(fill='x')
        self.buttons = {}
        for member in range(1,24):
            button = ttk.Button(self.grid, text=f'{member:02d}\nOFF', command=lambda m=member: self.toggle(m), style='Light.TButton')
            button.grid(row=(member-1)//6, column=(member-1)%6, padx=4, pady=4, sticky='nsew')
            self.buttons[member] = button
        for i in range(6): self.grid.columnconfigure(i, weight=1)
        self.slot_label = self.label(outer, '', 11)
        self.slot_label.pack(anchor='w', pady=(14,8))
        actions = tk.Frame(outer, bg=BG)
        actions.pack(fill='x')
        self.button(actions, 'ALL OFF  /  Esc', self.all_off, '#f5b1a5').pack(side='left', padx=(0,12))
        self.scan_button = self.button(actions, '▶ Sequential test', self.scan)
        self.scan_button.pack(side='left')
        self.label(actions, 'Seconds per light', 11).pack(side='left', padx=(16,6))
        self.interval = tk.StringVar(value='1.0')
        ttk.Combobox(actions, textvariable=self.interval, values=['0.5','1.0','2.0','3.0'], width=4, state='readonly').pack(side='left')
        self.notice = self.label(outer, 'Select up to six lights. Each button controls one member frame.', 11, ACCENT)
        self.notice.pack(anchor='w', pady=(14,6))
        self.receiver_note = self.label(outer, 'Commanded state only — receiver USB diagnostics not connected.\nPower off other Poolzone radios during testing: this bridge uses radio IDs 1–6.', 11)
        self.receiver_note.pack(anchor='w')
        self.log = tk.Text(outer, height=4, bg=PANEL, fg=MUTED, font=(MONO,10), relief='flat', state='disabled')
        self.log.pack(fill='both', expand=True, pady=(14,0))
        root.bind('<Escape>', lambda e: self.all_off())
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh_ports()
        self.render()
        root.after(40, self.poll)
        if port: root.after(300, self.connect)

    def label(self, parent, text, size=12, color=MUTED):
        return tk.Label(parent, text=text, bg=parent.cget('bg'), fg=color, font=('Helvetica',size), justify='left')

    def button(self, parent, text, command, color=TEXT):
        return ttk.Button(parent, text=text, command=command, style='Stop.TButton' if color != TEXT else 'Action.TButton')

    def record(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', time.strftime('%H:%M:%S')+'  '+text+'\n')
        if int(self.log.index('end-1c').split('.')[0]) > 150: self.log.delete('1.0','30.0')
        self.log.see('end')
        self.log.configure(state='disabled')

    def refresh_ports(self):
        ports = [p.device for p in list_ports.comports() if p.vid is not None]
        self.ports['values'] = ports
        if not self.port.get() and ports: self.port.set(ports[0])

    def connect(self):
        if self.serial:
            self.disconnect()
            return
        try:
            self.serial = serial.Serial(self.port.get(), 115200, timeout=0, write_timeout=0.15, exclusive=True)
            self.buffer = b''
            self.opened = self.last_rx = time.monotonic()
            self.ready = False
            self.connect_button.configure(text='Disconnect')
            self.state.configure(text='CONNECTING · waiting for test firmware')
            self.record('Opened '+self.port.get())
            self.send('STATUS')
        except (serial.SerialException, OSError) as exc:
            self.record(str(exc))
            self.disconnect()

    def send(self, command):
        if not self.serial: return False
        try:
            data = (command+'\n').encode('ascii')
            if self.serial.write(data) != len(data): raise serial.SerialException('Incomplete USB write')
            return True
        except (serial.SerialException, OSError) as exc:
            self.record(str(exc))
            self.disconnect(send_off=False)
            return False

    def disconnect(self, send_off=True):
        connection, self.serial = self.serial, None
        if connection:
            try:
                if send_off: connection.write(b'OFF\n')
            except (serial.SerialException, OSError): pass
            finally: connection.close()
        self.ready = self.scanning = self.channel_pending = False
        self.slots = [0]*6
        self.connect_button.configure(text='Connect')
        self.state.configure(text='DISCONNECTED')
        self.detail.configure(text='USB watchdog releases selections after 1.5 seconds without the app.')
        self.render()

    def render(self):
        for member, button in self.buttons.items():
            on = member in self.slots
            button.configure(text=f'{member:02d}\n'+('ON' if on else 'OFF'), style='On.Light.TButton' if on else 'Light.TButton',
                             state='normal' if self.ready else 'disabled')
        self.slot_label.configure(text='RADIO SLOTS   '+ '     '.join(f'{i+1}: {m:02d}' if m else f'{i+1}: —' for i,m in enumerate(self.slots)))
        self.scan_button.configure(text='■ Stop test' if self.scanning else '▶ Sequential test')

    def set_slots(self, slots):
        if self.ready and self.send('SET '+' '.join(map(str, slots))):
            self.slots = list(slots)
            self.render()
            return True
        return False

    def toggle(self, member):
        self.scanning = False
        try:
            if self.set_slots(toggle_member(self.slots, member)):
                self.notice.configure(text=f'Light {member:02d} '+('selected.' if member in self.slots else 'released.'))
        except ValueError as exc: self.notice.configure(text=str(exc))
        self.render()

    def all_off(self):
        self.scanning = False
        if self.ready: self.send('OFF')
        self.slots = [0]*6
        self.notice.configure(text='All six radio slots released.')
        self.render()

    def apply_channel(self):
        if not self.ready: return
        if any(self.slots):
            self.notice.configure(text='Press All Off before changing the channel.')
            return
        self.channel_pending = True
        self.send('CHANNEL '+self.channel.get())

    def scan(self):
        if self.scanning:
            self.all_off()
        elif self.ready:
            self.scanning = True
            self.scan_member = 0
            self.next_scan = 0
            self.render()

    def handle(self, line):
        try: status = json.loads(line)
        except (ValueError, TypeError):
            if line: self.record(line)
            return
        if not isinstance(status, dict) or status.get('device') != 'PoolRadioTest': return
        slots = status.get('members')
        if not isinstance(slots, list) or len(slots) != 6 or any(type(m) is not int or not 0 <= m <= 23 for m in slots): return
        self.last_rx = time.monotonic()
        was_ready = self.ready
        self.ready = status.get('ready') is True
        if self.ready and not was_ready:
            self.channel.set(str(status['channel']))
            self.send('OFF')
            self.record('Test bridge verified · '+status['mac'])
        if self.channel_pending:
            self.channel.set(str(status['channel']))
            self.channel_pending = False
        self.slots = slots
        self.state.configure(text=('CONNECTED' if self.ready else 'RADIO INIT FAILED')+f" · channel {status['channel']} · {status['mac']}")
        feedback = 'Receiver feedback below' if self.central_port else 'Central receipt: unconfirmed'
        self.detail.configure(text=f"Packets queued: {status['queued']:,}     Send errors: {status['errors']:,}     {feedback}")
        self.render()

    def poll_central(self, now):
        if not self.central_port:
            return
        if self.central_serial is None and now-self.central_retry > 3:
            self.central_retry = now
            try:
                self.central_serial = serial.Serial(self.central_port, 115200, timeout=0, write_timeout=.15, exclusive=True)
                self.central_buffer = b''
                self.central_serial.write(b'STATUS\n')
            except (serial.SerialException, OSError):
                if self.central_serial: self.central_serial.close()
                self.central_serial = None
        if self.central_serial:
            try:
                self.central_buffer += self.central_serial.read(8192)
                if len(self.central_buffer)>32768: self.central_buffer=b''
                while b'\n' in self.central_buffer:
                    raw, self.central_buffer = self.central_buffer.split(b'\n', 1)
                    line = raw.decode(errors='replace').strip()
                    try: data = json.loads(line)
                    except ValueError:
                        if line.startswith(('I2C ERROR', 'I2C MODE', 'I2C READY', 'RADIO TIMEOUT')): self.record(line)
                        continue
                    if isinstance(data, dict) and data.get('device')=='PoolCentral' and data.get('type')=='status':
                        self.central_status=data
                        self.last_central=now
            except (serial.SerialException, OSError) as exc:
                self.record('Receiver USB: '+str(exc))
                self.central_serial.close()
                self.central_serial=None
        state=self.central_status
        if not state or now-self.last_central>3:
            text='Receiver diagnostics unavailable — output state unconfirmed.'
            color='#f5b1a5'
        else:
            healthy=all(b.get('online') for b in state.get('boards', [])) and state.get('known')==0x7fffff
            requested=sum(1<<(m-1) for m in set(self.slots) if m)
            matched=healthy and state.get('verified')==state.get('desired')==requested
            text=('I²C 0x40 + 0x41: registers verified' if matched else 'Receiver: waiting for matching outputs / check I²C')
            text+=f"  •  RX {state.get('rx_packets',0):,}  •  errors {state.get('i2c_errors',0)}  •  recoveries {state.get('recoveries',0)}"
            color=ACCENT if matched else '#f5b1a5'
        self.receiver_note.configure(text=text+'\nRegister readback confirms driver commands; physical light emission is not measured.', fg=color)

    def poll(self):
        now = time.monotonic()
        if self.serial:
            try:
                self.buffer += self.serial.read(4096)
                if len(self.buffer) > 16384: self.buffer = b''
                while b'\n' in self.buffer:
                    line, self.buffer = self.buffer.split(b'\n',1)
                    self.handle(line.decode('utf-8',errors='replace').strip())
            except (serial.SerialException, OSError) as exc:
                self.record(str(exc))
                self.disconnect(send_off=False)
            if self.serial and now-self.last_rx > 4:
                self.record('No bridge status for 4 seconds. Disconnecting.')
                self.disconnect()
            elif self.serial and now-self.last_ping >= 0.35:
                self.last_ping = now
                self.send('PING' if self.ready else 'STATUS')
        if self.ready and self.scanning and now >= self.next_scan:
            self.scan_member = self.scan_member % 23 + 1
            self.set_slots([self.scan_member,0,0,0,0,0])
            self.next_scan = now + float(self.interval.get())
            self.notice.configure(text=f'Sequential test · light {self.scan_member:02d} / 23')
        self.poll_central(now)
        self.root.after(40, self.poll)

    def close(self):
        self.disconnect()
        if self.central_serial: self.central_serial.close()
        self.root.destroy()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', help='USB serial port to connect automatically')
    parser.add_argument('--central', help='Optional central controller USB port for live I2C verification')
    args = parser.parse_args()
    root = tk.Tk()
    App(root, args.port, args.central)
    root.mainloop()
