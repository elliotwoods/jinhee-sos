#!/usr/bin/env python3
"""Local PoolZone slider calibration. The firmware is authoritative for selection."""
import argparse
from collections import deque
import json
import math
import queue
import threading
from pathlib import Path
import sys
import time
import tkinter as tk
from tkinter import ttk, messagebox

import serial
from serial.tools import list_ports
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'pairing_station'))
from port_lock import PortLock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'flasher'))
from zone_monitor import MonitorState
import firmware

BG, PANEL, FG, DIM, GREEN, GOLD = '#101820', '#1c2833', '#eff7fa', '#9bb2c2', '#52e0bd', '#ffc56b'


def validate(ticks):
    if len(ticks) != 23 or any(not math.isfinite(v) or not 10 <= v <= 1000 for v in ticks):
        raise ValueError('Set control points at ticks 1 and 23 to cover the full range.')
    direction = 1 if ticks[-1] > ticks[0] else -1
    if any((b-a)*direction < 1 for a, b in zip(ticks, ticks[1:])):
        raise ValueError('Ticks must run in one direction, spaced at least 1 mm apart.')
    return ticks


def interpolate(first, last):
    return validate([round(first + (last-first)*i/22, 2) for i in range(23)])


def from_points(points):
    """Interpolate only between known control points; unbounded ticks remain unset."""
    result = [0.0]*23
    ordered = sorted(points.items())
    for i,v in ordered:
        if not 1 <= i <= 23 or not math.isfinite(v) or not 10 <= v <= 1000:
            raise ValueError('Control points require ticks 1–23 and distances 10–1000 mm.')
        result[i-1]=v
    if len(ordered)>1:
        direction = 1 if ordered[-1][1]>ordered[0][1] else -1
        for (a,av),(b,bv) in zip(ordered,ordered[1:]):
            if (bv-av)*direction < b-a:
                raise ValueError('Control points must run in one direction with at least 1 mm per tick.')
            for i in range(a,b+1): result[i-1]=round(av+(bv-av)*(i-a)/(b-a),2)
    return result


def capture_distance(samples, now):
    recent = [d for t,d in samples if 0 <= now-t < .4]
    if not recent:
        raise ValueError('Wait for a fresh filtered reading, then capture.')
    return recent[-1]  # exactly the filtered value most recently shown on screen


class App:
    def __init__(self, root, port=None):
        self.root = root
        self.connection = self.lock = None
        self.buffer = b''
        self.ready = False
        self.monitor = MonitorState()
        self.interaction = {}
        self.arm_requested = False
        self.arm_at = self.last_ping = self.last_interaction = 0
        self.points = {}
        self.ticks = [0.0]*23
        self.hardware_ticks = [0.0]*23
        self.samples = deque(maxlen=30)
        self.raw_distance = None
        self.distance = None
        self.index = -1
        self.last_rx = self.last_sample = self.last_query = self.last_report = 0
        self.queue = deque()
        self.pending = None
        self.dirty = False
        self.flashing = False
        self.firmware_calibration = None
        self.firmware_state = 'unknown'
        self.database_state = 'unknown'
        self.flash_events = queue.Queue()
        root.title('PoolZone · Laser calibration')
        root.geometry('1120x800')
        root.minsize(1020, 740)
        root.configure(bg=BG)
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TButton', padding=(12, 6))
        body = tk.Frame(root, bg=BG, padx=26, pady=16)
        body.pack(fill='both', expand=True)
        self.label(body, 'POOLZONE  /  RADIO & CALIBRATION', 11, GREEN).pack(anchor='w')
        self.label(body, 'Laser → 23 positions', 26, FG).pack(anchor='w', pady=5)
        activation = tk.Frame(body, bg=BG)
        activation.pack(fill='x')
        self.arm_button = ttk.Button(activation, text='Arm without NeoCube', command=self.toggle_arm)
        self.arm_button.pack(side='left')
        self.output_label = self.label(activation, 'Waiting for board · override disarmed', 11, GOLD)
        self.output_label.pack(side='left', padx=12)
        bar = tk.Frame(body, bg=BG)
        bar.pack(fill='x', pady=10)
        self.port = tk.StringVar(value=port or '')
        self.ports = ttk.Combobox(bar, textvariable=self.port, width=30)
        self.ports.pack(side='left')
        ttk.Button(bar, text='Refresh', command=self.refresh).pack(side='left', padx=6)
        self.connect_button = ttk.Button(bar, text='Connect', command=self.connect)
        self.connect_button.pack(side='left')
        self.status = self.label(bar, 'Disconnected', 11, GOLD)
        self.status.pack(side='left', padx=16)
        self.reading = self.label(body, '— mm     INDEX —', 24, GREEN)
        self.reading.pack(anchor='w')
        self.canvas = tk.Canvas(body, height=145, bg=PANEL, highlightthickness=0)
        self.canvas.pack(fill='x', pady=8)
        self.canvas.bind('<Configure>', lambda e: self.draw())
        self.label(body, 'Green bands: ±33% of neighboring tick spacing. Gaps: no selection. Circle: One Euro filtered position.', 11).pack(anchor='w')
        tabs = self.tabs = ttk.Notebook(body)
        tabs.pack(fill='both', expand=True, pady=8)
        work = tk.Frame(tabs, bg=BG)
        tabs.add(work, text='Calibration')
        debug = tk.Frame(tabs, bg=BG, padx=18, pady=12)
        tabs.add(debug, text='NeoCube & output diagnostics')
        firmware_tab = self.firmware_tab = tk.Frame(tabs, bg=BG, padx=18, pady=12)
        tabs.add(firmware_tab, text='Firmware')
        self.label(firmware_tab, 'Update PoolZone firmware', 20, FG).pack(anchor='w')
        self.label(firmware_tab, 'Update firmware and cube mappings; preserve calibration and radio identity.', 12).pack(anchor='w', pady=8)
        self.flash_button = ttk.Button(firmware_tab, text='Update firmware', command=self.start_flash)
        self.flash_button.pack(anchor='w')
        self.check_firmware_button = ttk.Button(firmware_tab, text='Check installed firmware', command=self.check_firmware)
        self.check_firmware_button.pack(anchor='w', pady=4)
        self.flash_status = self.label(firmware_tab, 'Connect to PoolZone to enable firmware updates.', 11, GOLD)
        self.flash_status.configure(wraplength=950)
        self.flash_status.pack(anchor='w', pady=5)
        self.database_label = self.label(firmware_tab, 'Cube database: waiting for board', 11, GOLD)
        self.database_label.configure(wraplength=930)
        self.database_label.pack(anchor='w', pady=4)
        self.flash_progress = ttk.Progressbar(firmware_tab, mode='indeterminate')
        self.flash_progress.pack(fill='x')
        self.flash_log = tk.Text(firmware_tab, height=5, bg=PANEL, fg=DIM, font=('Menlo',10), state='disabled', relief='flat')
        self.flash_log.pack(fill='both', expand=True, pady=(8,0))
        self.cube_label = self.label(debug, 'No NeoCube status yet', 20, FG)
        self.cube_label.pack(anchor='w')
        self.cube_detail = self.label(debug, 'UID —     MAC —', 12)
        self.cube_detail.pack(anchor='w', pady=8)
        self.delivery_label = self.label(debug, 'POOL command: —', 13)
        self.delivery_label.pack(anchor='w')
        self.reader_label = self.label(debug, 'NFC reader: waiting for status', 11)
        self.reader_label.pack(anchor='w', pady=8)
        self.radio_label = self.label(debug, 'Pool central: no status', 11)
        self.radio_label.pack(anchor='w')
        self.database_debug = self.label(debug, 'Database: waiting for report', 11)
        self.database_debug.pack(anchor='w')
        self.filter_label = self.label(debug, 'One Euro filter · waiting for sensor', 11)
        self.filter_label.pack(anchor='w', pady=5)
        self.label(debug, '150 ms heartbeat · 700 ms tag removal · 1.5 s override watchdog\nCentral packets are broadcasts: queued does not confirm receipt or physical illumination.', 11).pack(anchor='w', pady=8)
        self.event_log = tk.Text(debug, height=5, bg=PANEL, fg=DIM, font=('Menlo',10), state='disabled', relief='flat')
        self.event_log.pack(fill='both', expand=True)
        self.table = ttk.Treeview(work, columns=('index','mm','source'), show='headings', height=12, selectmode='browse')
        self.table.heading('index', text='Index')
        self.table.heading('mm', text='Calibration (mm)')
        self.table.heading('source', text='Type')
        self.table.column('source', width=95, anchor='center')
        self.table.column('index', width=60, anchor='center')
        self.table.column('mm', width=135, anchor='center')
        self.table.pack(side='left', fill='y')
        scroll = ttk.Scrollbar(work, orient='vertical', command=self.table.yview)
        scroll.pack(side='left', fill='y')
        self.table.configure(yscrollcommand=scroll.set)
        for i in range(1,24): self.table.insert('', 'end', iid=str(i), values=(i,'—'))
        self.table.selection_set('1')
        self.table.bind('<<TreeviewSelect>>', self.select_row)
        self.table.tag_configure('live', background=GREEN, foreground=BG)
        controls = tk.Frame(work, bg=BG, padx=22)
        controls.pack(side='left', fill='both', expand=True)
        self.target = self.label(controls, 'Control point · tick 1', 18, FG)
        self.target.pack(anchor='w')
        self.label(controls, 'Choose a tick, move the hardware there, then capture.\nTicks between control points are interpolated automatically.', 12).pack(anchor='w', pady=8)
        self.capture_button = ttk.Button(controls, text='Capture control point', command=self.capture)
        self.capture_button.pack(anchor='w')
        row = tk.Frame(controls, bg=BG)
        row.pack(anchor='w', pady=6)
        self.manual = tk.StringVar()
        ttk.Entry(row, textvariable=self.manual, width=10).pack(side='left')
        ttk.Button(row, text='Set control point (mm)', command=self.set_manual).pack(side='left', padx=8)
        ttk.Button(controls, text='Remove selected control point', command=self.remove_point).pack(anchor='w', pady=3)
        row = tk.Frame(controls, bg=BG)
        row.pack(anchor='w', pady=6)
        self.apply_button = ttk.Button(row, text='Apply & save to flash', command=self.save)
        self.apply_button.pack(side='left')
        self.load_button = ttk.Button(row, text='Reload saved ticks', command=self.reload)
        self.load_button.pack(side='left', padx=8)
        self.note = self.label(controls, 'Connect to load calibration from the device.', 12, GOLD)
        self.note.configure(wraplength=640)
        self.note.pack(anchor='w', pady=6)
        self.label(controls, 'Amber = draft. Captures record the displayed filtered value.', 11).pack(anchor='w')
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh()
        self.update_firmware_status()
        self.draw()
        root.after(30, self.poll)
        if port: root.after(200, self.connect)

    def label(self, parent, text, size=12, color=DIM):
        return tk.Label(parent, text=text, font=('Helvetica',size), bg=parent.cget('bg'), fg=color, justify='left')

    def refresh(self):
        if self.flashing: return
        ports = [p.device for p in list_ports.comports() if p.vid is not None]
        self.ports['values'] = ports
        if ports and not self.port.get(): self.port.set(ports[0])

    def connect(self):
        if self.flashing: return
        if self.connection:
            self.disconnect(); return
        try:
            self.lock = PortLock(self.port.get())
            self.connection = serial.Serial(self.port.get(),115200,timeout=0,write_timeout=.2,exclusive=True)
            self.buffer = b''
            self.last_rx = self.last_report = time.monotonic()
            self.connect_button.configure(text='Disconnect')
            self.status.configure(text='Waiting for calibration firmware…')
            self.send('HOST DISARM')
            self.send('CAL GET')
            self.send('?')
        except (OSError, RuntimeError, serial.SerialException) as exc:
            self.disconnect(str(exc))

    def disconnect(self, reason='Disconnected'):
        if self.connection:
            try: self.connection.write(b'HOST DISARM\n')
            except (OSError, serial.SerialException): pass
            self.connection.close()
        self.arm_requested = False
        self.interaction = {}
        self.monitor = MonitorState()
        self.firmware_calibration = None
        self.firmware_state = self.database_state = 'unknown'
        if not self.flashing: self.flash_status.configure(text='Connect to detect firmware and database versions.')
        self.database_label.configure(text='Cube database: disconnected')
        self.database_debug.configure(text='Cube database: disconnected')
        if self.lock: self.lock.close()
        self.connection = self.lock = None
        self.ready = False
        self.raw_distance = None
        self.distance = None
        self.index = -1
        self.samples.clear()
        self.queue.clear()
        self.pending = None
        self.connect_button.configure(text='Connect')
        self.status.configure(text=reason)
        self.draw()

    def send(self, command):
        if not self.connection: return False
        try:
            data = (command+'\n').encode('ascii')
            if self.connection.write(data) != len(data): raise OSError('Incomplete USB write')
            return True
        except (OSError, serial.SerialException) as exc:
            self.disconnect(str(exc)); return False

    def check_firmware(self):
        if not self.connection or self.flashing: return
        self.send('?')
        self.send('CAL GET')
        self.update_firmware_status()

    def update_firmware_status(self):
        if self.flashing: return
        self.firmware_state, detail = firmware.status(self.monitor.zone,self.firmware_calibration)
        self.flash_status.configure(text=detail if self.connection else 'Connect to detect firmware and database versions.')
        try:
            publication=firmware.local_database()
            self.database_state, db_detail=firmware.database_status(self.monitor.zone,publication)
        except Exception as exc:
            self.database_state, db_detail='unknown', 'Local database unavailable: '+str(exc)
        self.database_label.configure(text=db_detail,fg=GREEN if self.database_state=='current' else GOLD)
        self.database_debug.configure(text=db_detail)
        self.draw()

    def start_flash(self):
        if self.flashing or not self.ready or not self.connection: return
        if self.database_state in ('ahead','unknown'):
            self.flash_status.configure(text='Resolve the database status below before updating.')
            return
        if self.dirty or self.pending or self.queue:
            self.flash_status.configure(text='Apply & save your draft calibration, or reload saved ticks, before flashing.')
            return
        port = self.connection.port
        self.flashing = True
        self.disconnect('Firmware update in progress…')
        self.tabs.select(self.firmware_tab)
        self.flash_progress.start(15)
        self.flash_status.configure(text='Checking connected board and existing build…')
        def worker():
            try:
                result=firmware.flash(port,lambda kind,value: self.flash_events.put((kind,value)))
                self.flash_events.put(('done',result))
            except Exception as exc: self.flash_events.put(('failed',str(exc)))
        threading.Thread(target=worker,daemon=False).start()

    def poll_flash(self):
        # All Tk work stays on the UI thread; compiler/uploader runs independently.
        for _ in range(100):
            try: kind,value=self.flash_events.get_nowait()
            except queue.Empty: break
            if kind=='log':
                value=firmware.clean_output(value)
                self.flash_log.configure(state='normal')
                self.flash_log.insert('end',value+'\n')
                if int(self.flash_log.index('end-1c').split('.')[0])>300: self.flash_log.delete('1.0','50.0')
                self.flash_log.see('end'); self.flash_log.configure(state='disabled')
            elif kind=='stage': self.flash_status.configure(text=value)
            elif kind in ('done','failed'):
                self.flashing=False
                self.flash_progress.stop()
                if kind=='done':
                    self.flash_status.configure(text='Already up to date; no flash needed.' if value.get('skipped') else f'Installed {value["version"]}. Calibration preserved. Backup: {value["backup"]}')
                    self.log_event('Firmware: '+str(value))
                    self.port.set(value['port'])
                    self.connect()
                else:
                    self.flash_status.configure(text='Update failed: '+value)
                    self.status.configure(text='Firmware update failed — see Firmware tab')
                self.draw()

    def toggle_arm(self):
        if not self.ready or time.monotonic()-self.last_interaction>.6: return
        self.arm_requested = not (self.arm_requested or self.interaction.get('override'))
        self.arm_at = time.monotonic()
        self.send('HOST ARM' if self.arm_requested else 'HOST DISARM')
        self.draw()

    def log_event(self, line):
        self.event_log.configure(state='normal')
        self.event_log.insert('end',time.strftime('%H:%M:%S')+'  '+line+'\n')
        if int(self.event_log.index('end-1c').split('.')[0])>100: self.event_log.delete('1.0','20.0')
        self.event_log.see('end')
        self.event_log.configure(state='disabled')

    def draw_interaction(self):
        live = self.ready and time.monotonic()-self.last_interaction<.6
        d = self.interaction if live else {}
        armed = d.get('override',False)
        self.arm_button.configure(text='Disarm override' if armed or self.arm_requested else 'Arm without NeoCube', state='normal' if live else 'disabled')
        source = 'NeoCube + override' if d.get('tag') and armed else 'NeoCube' if d.get('tag') else 'Python override' if armed else 'waiting for NeoCube'
        output = d.get('output',0)
        self.output_label.configure(text=(f'{source} · light command {output if output else "OFF"}' if live else 'Output status unavailable · override disarmed'), fg=GREEN if output else GOLD)
        if d.get('tag'):
            self.cube_label.configure(text=f'NeoCube #{d["cube"]} on reader' if d.get('cube') else 'Unknown tag on reader', fg=GREEN if d.get('cube') else GOLD)
            self.cube_detail.configure(text=f'UID {d.get("uid","—")}\nMAC {d.get("mac") or "not registered"}')
            delivery = 'acknowledged' if d.get('delivery')==1 else 'NOT acknowledged' if d.get('delivery')==-1 else 'pending'
            self.delivery_label.configure(text='POOL (blue) · '+delivery if d.get('cube') else 'No cube command: tag not registered; pool interaction remains active.', fg='#64b5ff' if d.get('cube') and d.get('delivery')==1 else GOLD)
        else:
            self.cube_label.configure(text='No NeoCube on reader' if live else 'NeoCube status unavailable',fg=DIM)
            self.cube_detail.configure(text='UID —     MAC —')
            self.delivery_label.configure(text='POOL command: —',fg=DIM)
        reader, level = self.monitor.reader_text()
        self.reader_label.configure(text=reader if live else 'NFC reader: disconnected / stale',fg=GREEN if live and level=='ok' else GOLD)
        self.radio_label.configure(text=(f'Radio {d.get("radio_id","—")} · channel 2 · '+('ready' if d.get('radio') else 'unavailable')+f' · queued {d.get("queued",0)} · send errors {d.get("send_errors",0)}') if live else 'Pool central: output status unavailable')

    def selected(self):
        return int(self.table.selection()[0]) if self.table.selection() else 1

    def select_row(self, _=None):
        i = self.selected()
        self.target.configure(text=f'Control point · tick {i}')
        self.manual.set(f'{self.ticks[i-1]:.2f}' if self.ticks[i-1] else '')

    def update_tick(self, value):
        if self.pending or self.queue: return
        if not math.isfinite(value) or not 10 <= value <= 1000: raise ValueError('Use 10–1000 mm.')
        points = dict(self.points)
        points[self.selected()] = round(value,2)
        ticks = from_points(points)
        self.points, self.ticks = points, ticks
        self.dirty = True
        self.note.configure(text='Draft changed — apply & save when ready.')
        self.draw()

    def capture(self):
        if not self.ready or self.distance is None:
            self.note.configure(text='Wait for a valid live sensor reading.'); return
        try: self.update_tick(capture_distance(self.samples, time.monotonic()))
        except ValueError as exc: self.note.configure(text=str(exc))

    def set_manual(self):
        try: self.update_tick(float(self.manual.get()))
        except ValueError as exc: self.note.configure(text=str(exc))

    def remove_point(self):
        if self.pending or self.queue: return
        self.points.pop(self.selected(),None)
        self.ticks=from_points(self.points)
        self.dirty=True
        self.note.configure(text='Control point removed. Set ticks 1 and 23 before saving.')
        self.draw()

    def save(self):
        if not self.ready or self.pending or self.queue: return
        try: validate(self.ticks)
        except ValueError as exc:
            self.note.configure(text=str(exc)); return
        self.queue = deque([f'CAL SET {i+1} {v:.2f}' for i,v in enumerate(self.ticks)] + [f'CAL ANCHORS {sum(1 << (i-1) for i in self.points)}', 'CAL SAVE'])
        self.note.configure(text='Applying interpolated ticks and control points, then verifying flash…')

    def reload(self):
        if not self.ready or self.pending or self.queue: return
        if self.dirty and not messagebox.askyesno('Discard draft?', 'Replace your unsaved edits with the saved device calibration?'): return
        self.queue.append('CAL LOAD')

    def handle(self, line):
        if line.startswith(('EVT ', 'NFC:', 'FW:', 'MAC:', 'CHANNEL:', 'ZONE:', 'DB:', 'STATS:', 'POOL:', 'READY')):
            try:
                if self.monitor.feed(line) and line=='READY': self.update_firmware_status()
            except (ValueError, KeyError): pass
        if line.startswith(('EVT ', 'EVENT ', 'PN532 ', 'ERR')): self.log_event(line)
        if line.startswith('ERR'):
            self.note.configure(text=line)
            self.pending = None; self.queue.clear()
            return
        try: data = json.loads(line)
        except ValueError: return
        if not isinstance(data,dict) or data.get('device') != 'PoolZoneCalibration': return
        now = time.monotonic()
        self.last_rx = now
        if data.get('type') == 'calibration':
            ticks = data.get('ticks')
            if not isinstance(ticks,list) or len(ticks)!=23 or any(type(v) not in (int,float) or not math.isfinite(v) for v in ticks): return
            self.firmware_calibration = data
            self.hardware_ticks = ticks[:]
            first = not self.ready
            self.ready = True
            if self.pending:
                cmd = self.pending[0]
                if cmd.startswith('CAL SET '):
                    _,_,i,value = cmd.split()
                    if abs(ticks[int(i)-1]-float(value)) > .011:
                        self.note.configure(text='Device calibration did not match the requested tick.')
                        self.queue.clear(); self.pending=None; return
                elif cmd.startswith('CAL ANCHORS '):
                    if data.get('anchors') != int(cmd.split()[-1]):
                        self.note.configure(text='Control point verification failed.')
                        self.queue.clear(); self.pending=None; return
                elif cmd == 'CAL SAVE':
                    if not data.get('saved') or any(abs(a-b)>.011 for a,b in zip(ticks,self.ticks)):
                        self.note.configure(text='Save verification failed. Draft retained.')
                        self.queue.clear(); self.pending=None; return
                    self.dirty = False
                    self.note.configure(text='Saved to device flash and verified. Ready for live tracking.')
                elif cmd == 'CAL LOAD':
                    self.ticks = ticks[:]; self.dirty=False
                    self.points = {i+1:v for i,v in enumerate(ticks) if data.get('anchors',4194305) & (1<<i) and v>0}
                    self.note.configure(text='Saved device calibration loaded.' if data.get('saved') else 'No saved calibration.')
                self.pending = None
            elif first:
                self.ticks=ticks[:]; self.dirty=False
                self.points = {i+1:v for i,v in enumerate(ticks) if data.get('anchors',4194305) & (1<<i) and v>0}
                self.note.configure(text='Loaded saved calibration.' if data.get('saved') else 'Initial calibration is not saved. Set control points, then apply & save.')
            self.status.configure(text='Connected · PoolZone radio')
            self.update_firmware_status()
        elif data.get('type') == 'interaction':
            self.interaction = data
            self.last_interaction = now
            if not data.get('override') and now-self.arm_at>.75: self.arm_requested=False
        elif data.get('type') == 'sample':
            self.last_sample = now
            value = data.get('distance')
            valid = data.get('sensor') is True and type(value) in (float,int) and math.isfinite(value) and 10 <= value <= 1000
            self.distance = value if valid else None
            index = data.get('index',-1)
            self.index = index if valid and type(index) is int and 1 <= index <= 23 else -1
            raw = data.get('raw_distance',value)
            self.raw_distance = raw if valid and type(raw) in (int,float) and math.isfinite(raw) and 10 <= raw <= 1000 else None
            if valid and self.raw_distance is not None: self.samples.append((now,value))
            else: self.samples.clear()
        self.draw()

    def draw(self):
        self.flash_button.configure(text='Firmware & database up to date' if self.firmware_state=='current' and self.database_state=='current' else 'Update firmware & database', state='normal' if self.ready and not self.flashing and self.firmware_state in ('current','update') and self.database_state in ('current','update') and (self.firmware_state=='update' or self.database_state=='update') else 'disabled')
        self.check_firmware_button.configure(state='normal' if self.connection and not self.flashing else 'disabled')
        self.connect_button.configure(state='disabled' if self.flashing else 'normal')
        self.ports.configure(state='disabled' if self.flashing else 'normal')
        self.draw_interaction()
        self.filter_label.configure(text=(f'One Euro · raw {self.raw_distance:.1f} mm → filtered {self.distance:.2f} mm' if self.distance is not None and self.raw_distance is not None else 'One Euro · no valid sensor reading')+' · min 0.8 Hz / beta 0.03')
        c = self.canvas
        c.delete('all')
        w = max(c.winfo_width(), 900)
        ticks = self.hardware_ticks
        values = [v for v in ticks+self.ticks if v>0]
        if self.distance is not None: values.append(self.distance)
        lo,hi = (min(values),max(values)) if len(values)>1 else (10,500)
        span = max(hi-lo,20); lo -= span*.06; hi += span*.06
        # Screen order follows index 1 -> 23, even when the laser distance decreases.
        ordered = [v for v in ticks if v>0]
        if len(ordered)<2: ordered = [v for v in self.ticks if v>0]
        reversed_distance = len(ordered)>1 and ordered[-1]<ordered[0]
        def x(v):
            fraction = (v-lo)/(hi-lo)
            if reversed_distance: fraction=1-fraction
            return 40+fraction*(w-80)
        c.create_line(40,85,w-40,85,fill=DIM,width=3)
        for i,v in enumerate(ticks):
            if v<=0: continue
            prev = ticks[i-1] if i else 2*v-ticks[1]
            nxt = ticks[i+1] if i<22 else 2*v-ticks[21]
            if prev>0 and nxt>0:
                a,b = sorted((v+(prev-v)*.33,v+(nxt-v)*.33))
                c.create_rectangle(x(a),72,x(b),98,fill='#234f46',outline='')
            color = GREEN if self.index==i+1 else DIM
            c.create_line(x(v),68,x(v),102,fill=color,width=4 if self.index==i+1 else 2)
            c.create_text(x(v),118+(i%2)*17,text=str(i+1),fill=color,font=('Helvetica',11,'bold'))
        if self.dirty:
            for i,v in enumerate(self.ticks,1):
                if v>0:
                    c.create_line(x(v),55,x(v),65,fill=GOLD,width=2)
                    if i in self.points: c.create_oval(x(v)-3,49,x(v)+3,55,fill=GOLD,outline='')
        if self.distance is not None:
            xx=x(self.distance)
            c.create_line(xx,40,xx,85,fill=FG,width=2)
            c.create_oval(xx-8,25,xx+8,41,fill=GREEN if self.index>0 else GOLD,outline='')
        self.reading.configure(text=(f'{self.distance:.1f} mm filtered' if self.distance is not None else 'No valid sensor reading')+'     INDEX '+(str(self.index) if self.index>0 else '— (no selection)'))
        for i,v in enumerate(self.ticks,1):
            self.table.item(str(i),values=(i,f'{v:.2f}' if v else '—','Control' if i in self.points else 'Interpolated' if v else 'Unset'),tags=('live',) if self.index==i else ())
        busy = bool(self.pending or self.queue)
        for button in (self.capture_button,self.apply_button,self.load_button):
            button.configure(state='normal' if self.ready and not busy else 'disabled')

    def poll(self):
        self.poll_flash()
        now = time.monotonic()
        if self.connection:
            try:
                self.buffer += self.connection.read(8192)
                if len(self.buffer)>32768: raise OSError('Oversized serial response')
                while b'\n' in self.buffer:
                    line,self.buffer=self.buffer.split(b'\n',1)
                    self.handle(line.decode(errors='replace').strip())
            except (OSError,serial.SerialException) as exc: self.disconnect(str(exc))
            if self.connection and now-self.last_rx>4: self.disconnect('No calibration telemetry — check firmware / USB')
            elif self.connection and not self.ready and now-self.last_query>1:
                self.last_query=now; self.send('CAL GET')
            if self.pending and now-self.pending[1]>2:
                self.pending=None; self.queue.clear()
                self.note.configure(text='Command timed out. Save is unconfirmed; reconnect to inspect device state.')
            if self.connection and self.ready and self.queue and not self.pending:
                cmd=self.queue.popleft()
                if self.send(cmd): self.pending=(cmd,now)
        if self.connection and self.ready and now-self.last_report>=5:
            self.last_report=now
            self.send('?')
        if self.connection and self.arm_requested:
            if now-self.last_interaction>.6 or now-self.last_sample>.6:
                self.arm_requested=False
                self.send('HOST DISARM')
            elif self.interaction.get('override') and now-self.last_ping>=.35:
                self.last_ping=now
                self.send('HOST PING')
        if now-self.last_sample>.6:
            self.raw_distance=None; self.distance=None; self.index=-1; self.samples.clear()
        self.draw()
        self.root.after(40,self.poll)

    def close(self):
        if self.flashing:
            self.tabs.select(self.firmware_tab)
            self.flash_status.configure(text='Firmware update is running. Please wait before closing.')
            return
        self.disconnect(); self.root.destroy()


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--port')
    args=parser.parse_args()
    root=tk.Tk()
    App(root,args.port)
    root.mainloop()
