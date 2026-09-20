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
import recording as rec

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
        # Tuning and guided recording state. The recording buffer is deliberately
        # unbounded: `samples` above is a short window for control-point capture.
        self.tuning = None
        self.tuning_defaults = None
        self.tuning_saved = False
        self.tuning_dirty = False
        self.tuning_vars = {}
        self.record_state = None
        self.record_steps = []
        self.record_step = 0
        self.record_buffer = []
        self.record_started = 0.0
        self.record_phase_at = 0.0
        self.recording = None
        self.analysis = None
        self.proposal = None
        self.index_changes = deque(maxlen=200)
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
        work = self.work_tab = tk.Frame(tabs, bg=BG)
        tabs.add(work, text='Calibration')
        tune = self.tune_tab = tk.Frame(tabs, bg=BG, padx=18, pady=12)
        tabs.add(tune, text='Tuning & recording')
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
        database_panel = tk.Frame(firmware_tab, bg=PANEL, padx=14, pady=10)
        database_panel.pack(fill='x', pady=10)
        self.label(database_panel, 'Cube database  ·  NeoCube UID → ID mappings', 15, FG).pack(anchor='w')
        self.database_label = self.label(database_panel, 'Cube database: waiting for board', 11, GOLD)
        self.database_label.configure(wraplength=900)
        self.database_label.pack(anchor='w', pady=4)
        self.database_detail = self.label(database_panel, 'Board — · Local master —', 11)
        self.database_detail.configure(wraplength=900)
        self.database_detail.pack(anchor='w')
        db_row = tk.Frame(database_panel, bg=PANEL)
        db_row.pack(anchor='w', pady=6)
        self.database_check_button = ttk.Button(db_row, text='Check master database', command=self.check_firmware)
        self.database_check_button.pack(side='left')
        self.database_button = ttk.Button(db_row, text='Update cube database', command=self.start_database)
        self.database_button.pack(side='left', padx=8)
        registry_panel = tk.Frame(firmware_tab, bg=PANEL, padx=14, pady=10)
        registry_panel.pack(fill='x', pady=(0,10))
        self.label(registry_panel, 'Zone status registry', 15, FG).pack(anchor='w')
        self.label(registry_panel, 'The shared zones table the pairing station and flashers read. '
                   'A firmware or database update writes this automatically; update it on its own '
                   'to record a board you only inspected or tuned.', 11).pack(anchor='w', pady=4)
        self.registry_label = self.label(registry_panel, 'Registry: connect to read board identity', 11)
        self.registry_label.configure(wraplength=900)
        self.registry_label.pack(anchor='w')
        self.registry_button = ttk.Button(registry_panel, text='Update zone status in registry', command=self.update_registry)
        self.registry_button.pack(anchor='w', pady=6)
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
        self.filter_label.configure(wraplength=900)
        self.filter_label.pack(anchor='w', pady=5)
        # Flicker has to be measurable before and after a tuning change, not judged by eye.
        self.stability_label = self.label(debug, 'Output stability · waiting for telemetry', 13, GREEN)
        self.stability_label.pack(anchor='w')
        self.label(debug, '150 ms heartbeat · 700 ms tag removal · 1.5 s override watchdog\nCentral packets are broadcasts: queued does not confirm receipt or physical illumination.', 11).pack(anchor='w', pady=8)
        self.event_log = tk.Text(debug, height=5, bg=PANEL, fg=DIM, font=('Menlo',10), state='disabled', relief='flat')
        self.event_log.pack(fill='both', expand=True)
        # ---- Tuning & recording tab ----
        self.label(tune, 'Guided recording and filter tuning', 20, FG).pack(anchor='w')
        self.label(tune, 'Records the slider at a series of positions, then measures the sensor noise and\n'
                   'proposes filter and hysteresis settings that stop the output flickering.', 12).pack(anchor='w', pady=6)
        plan_row = tk.Frame(tune, bg=BG)
        plan_row.pack(anchor='w', pady=4)
        self.stride_var = tk.StringVar(value='4')
        self.settle_var = tk.StringVar(value='3')
        self.hold_var = tk.StringVar(value='5')
        for text, var, width in [('Every Nth tick', self.stride_var, 4), ('Move time (s)', self.settle_var, 4), ('Hold time (s)', self.hold_var, 4)]:
            self.label(plan_row, text+':', 11).pack(side='left', padx=(0,4))
            ttk.Entry(plan_row, textvariable=var, width=width).pack(side='left', padx=(0,12))
        self.record_button = ttk.Button(plan_row, text='Start guided recording', command=self.start_recording)
        self.record_button.pack(side='left')
        self.record_abort = ttk.Button(plan_row, text='Abort', command=self.stop_recording)
        self.record_abort.pack(side='left', padx=8)
        self.record_prompt = self.label(tune, 'Endpoints plus every Nth tick. Both ends are always included.', 22, DIM)
        self.record_prompt.pack(anchor='w', pady=10)
        panes = tk.Frame(tune, bg=BG)
        panes.pack(fill='both', expand=True)
        left = tk.Frame(panes, bg=BG)
        left.pack(side='left', fill='y')
        self.result_table = ttk.Treeview(left, columns=('tick','mm','noise','ok'), show='headings', height=9, selectmode='none')
        for key, text, width in [('tick','Tick',50), ('mm','Measured (mm)',110), ('noise','Noise (mm)',90), ('ok','',40)]:
            self.result_table.heading(key, text=text)
            self.result_table.column(key, width=width, anchor='center')
        self.result_table.pack(side='left', fill='y')
        right = tk.Frame(panes, bg=BG, padx=16)
        right.pack(side='left', fill='both', expand=True)
        self.result_note = self.label(right, 'Run a guided recording to measure the slider and propose tuning.', 11)
        self.result_note.configure(wraplength=560, justify='left')
        self.result_note.pack(anchor='w')
        apply_row = tk.Frame(right, bg=BG)
        apply_row.pack(anchor='w', pady=8)
        ttk.Button(apply_row, text='Use recording as calibration', command=self.apply_recording_calibration).pack(side='left')
        ttk.Button(apply_row, text='Apply & save tuning', command=lambda: self.apply_recommended_tuning(True)).pack(side='left', padx=8)
        fields = tk.Frame(right, bg=PANEL, padx=12, pady=10)
        fields.pack(fill='x', pady=6)
        self.tune_state = self.label(fields, 'Device tuning · waiting for board', 13, GOLD)
        self.tune_state.grid(row=0, column=0, columnspan=4, sticky='w', pady=(0,6))
        for i, (key, (text, whole, low, high)) in enumerate(rec.FIELDS.items()):
            var = tk.StringVar()
            self.tuning_vars[key] = var
            self.label(fields, text, 10).grid(row=1+i//2, column=(i%2)*2, sticky='w', padx=(0,6), pady=1)
            ttk.Entry(fields, textvariable=var, width=9).grid(row=1+i//2, column=(i%2)*2+1, sticky='w', padx=(0,18), pady=1)
        button_row = tk.Frame(right, bg=BG)
        button_row.pack(anchor='w', pady=4)
        ttk.Button(button_row, text='Apply live', command=lambda: self.apply_tuning_fields(False)).pack(side='left')
        ttk.Button(button_row, text='Apply & save to flash', command=lambda: self.apply_tuning_fields(True)).pack(side='left', padx=8)
        ttk.Button(button_row, text='Reload saved', command=self.load_tuning).pack(side='left')
        ttk.Button(button_row, text='Firmware defaults', command=self.default_tuning).pack(side='left', padx=8)
        self.tune_note = self.label(right, 'Apply live to judge a change before committing it to flash.', 11, GOLD)
        self.tune_note.configure(wraplength=560)
        self.tune_note.pack(anchor='w', pady=4)
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

    # ---------------- tuning and guided recording ----------------

    def note_index(self, index, now):
        """Track confirmed-index changes so flicker is measurable, not judged by eye."""
        if self.index_changes and self.index_changes[-1][1] == index: return
        self.index_changes.append((now, index))

    def stability_text(self, now):
        recent = [t for t, _ in self.index_changes if now - t <= 10]
        changes = max(0, len(recent) - 1)
        if not self.index_changes: return 'Output stability · waiting for telemetry'
        held = now - self.index_changes[-1][0]
        return f'Output stability · {changes} index changes in the last 10 s · steady for {held:.1f} s'

    def absorb_tuning(self, data):
        values = {}
        for key, name in rec.JSON_KEYS.items():
            value = data.get(name)
            if type(value) in (int, float) and math.isfinite(value):
                values[key] = int(value) if rec.FIELDS[key][1] else float(value)
        if len(values) != len(rec.JSON_KEYS): return
        self.tuning = values
        self.tuning_saved = bool(data.get('saved'))
        defaults = data.get('defaults')
        if isinstance(defaults, dict):
            self.tuning_defaults = {k: defaults.get(n) for k, n in rec.JSON_KEYS.items()}
        if self.pending and self.pending[0].startswith(('TUNE SET ', 'TUNE SAVE', 'TUNE LOAD', 'TUNE DEFAULTS')):
            cmd = self.pending[0]
            if cmd.startswith('TUNE SET '):
                _, _, key, value = cmd.split()
                got = values.get(key)
                if got is None or abs(float(got) - float(value)) > max(1e-4, abs(float(value)) * 1e-3):
                    self.tune_note.configure(text=f'Device did not accept {key}; tuning left unchanged.')
                    self.queue.clear(); self.pending = None; self.refresh_tuning(); return
            elif cmd == 'TUNE SAVE' and not self.tuning_saved:
                self.tune_note.configure(text='Tuning save was not confirmed by the device.')
                self.queue.clear(); self.pending = None; self.refresh_tuning(); return
            elif cmd == 'TUNE SAVE':
                self.tuning_dirty = False
                self.tune_note.configure(text='Tuning saved to device flash and verified.')
            self.pending = None
        self.refresh_tuning()

    def refresh_tuning(self):
        for key, var in self.tuning_vars.items():
            if self.tuning and not var.get().strip():
                var.set(self.format_field(key, self.tuning[key]))
        if self.tuning:
            state = 'saved to flash' if self.tuning_saved else 'live only, not saved'
            self.tune_state.configure(text=f'Device tuning · {state}', fg=GREEN if self.tuning_saved else GOLD)
        self.draw_tuning_table()

    @staticmethod
    def format_field(key, value):
        return str(int(value)) if rec.FIELDS[key][1] else f'{float(value):g}'

    def send_tuning(self, values, save):
        """Queue TUNE SET for each changed field, verified one reply at a time."""
        reason = rec.valid(values)
        if reason:
            messagebox.showerror('Tuning', reason); return
        current = self.tuning or {}
        queue = [f'TUNE SET {k} {self.format_field(k, v)}' for k, v in values.items()
                 if current.get(k) is None or abs(float(current[k]) - float(v)) > 1e-6]
        if not queue and not save:
            self.tune_note.configure(text='Tuning already matches the device.'); return
        if save: queue.append('TUNE SAVE')
        self.queue.extend(queue)
        self.tuning_dirty = True
        self.tune_note.configure(text=f'Applying {len(queue)} tuning command(s)…')

    def read_tuning_fields(self):
        values = {}
        for key, var in self.tuning_vars.items():
            text = var.get().strip()
            try: value = float(text)
            except ValueError:
                messagebox.showerror('Tuning', f'{rec.FIELDS[key][0]}: "{text}" is not a number'); return None
            values[key] = int(round(value)) if rec.FIELDS[key][1] else value
        return values

    def apply_tuning_fields(self, save):
        values = self.read_tuning_fields()
        if values is not None: self.send_tuning(values, save)

    def load_tuning(self):
        self.queue.append('TUNE LOAD')
        for var in self.tuning_vars.values(): var.set('')
        self.tune_note.configure(text='Reloading saved tuning from the device…')

    def default_tuning(self):
        self.queue.append('TUNE DEFAULTS')
        for var in self.tuning_vars.values(): var.set('')
        self.tune_note.configure(text='Applying firmware defaults live (not saved).')

    # ---- guided recording ----

    def start_recording(self):
        if not self.ready:
            messagebox.showerror('Recording', 'Connect to a PoolZone first.'); return
        if self.dirty and not messagebox.askyesno('Recording', 'An unsaved calibration draft will be replaced by the recording. Continue?'):
            return
        try:
            stride = int(self.stride_var.get()); settle = float(self.settle_var.get()); hold = float(self.hold_var.get())
            self.record_steps = rec.plan_steps(stride, settle, hold)
        except ValueError as exc:
            messagebox.showerror('Recording', str(exc)); return
        self.recording = self.analysis = self.proposal = None
        self.record_buffer = []
        self.record_step = 0
        self.record_state = 'move'
        self.record_started = time.monotonic()
        self.record_phase_at = self.record_started
        self.record_steps_data = []
        self.send('RAW ON')
        self.log_event(f'EVENT recording started · {len(self.record_steps)} positions')

    def stop_recording(self, reason='Recording aborted.'):
        if self.record_state is None: return
        self.record_state = None
        self.send('RAW OFF')
        self.record_prompt.configure(text=reason)
        self.draw_tuning_table()

    def collect_raw(self, data, now):
        if self.record_state is None: return
        t = data.get('t')
        if type(t) not in (int, float): return
        mm = data.get('mm')
        if type(mm) not in (int, float) or not math.isfinite(mm): mm = None
        self.record_buffer.append(dict(t=int(t), mm=mm, st=data.get('st', 0)))

    def advance_recording(self, now):
        """Drive the move/hold schedule from the Tk poll callback (never blocks)."""
        if self.record_state is None: return
        if not self.connection: self.stop_recording('Disconnected during recording.'); return
        step = self.record_steps[self.record_step]
        elapsed = now - self.record_phase_at
        if self.record_state == 'move':
            remaining = step['settle'] - elapsed
            self.record_prompt.configure(
                text=f"MOVE TO {step['tick']}          {max(0.0, remaining):.1f} s", fg=GOLD)
            if remaining <= 0:
                self.record_state = 'hold'
                self.record_phase_at = now
                self.record_hold_from = self.record_buffer[-1]['t'] if self.record_buffer else 0
        else:
            remaining = step['hold'] - elapsed
            self.record_prompt.configure(
                text=f"HOLD AT {step['tick']}          {max(0.0, remaining):.1f} s", fg=GREEN)
            if remaining <= 0:
                self.record_steps_data.append(dict(tick=step['tick'], hold_from=self.record_hold_from,
                                                   samples=self.record_buffer))
                self.record_buffer = []
                self.record_step += 1
                if self.record_step >= len(self.record_steps):
                    self.finish_recording(); return
                self.record_state = 'move'
                self.record_phase_at = now

    def finish_recording(self):
        self.record_state = None
        self.send('RAW OFF')
        self.recording = dict(steps=self.record_steps_data, ticks=23,
                              created=time.strftime('%Y-%m-%d %H:%M:%S'),
                              firmware=(self.monitor.zone or {}).get('firmware'))
        try:
            self.analysis = rec.analyse(self.recording)
            proposal = rec.recommend(self.analysis, current=self.tuning)
            fitted = rec.fit_budget(self.recording, self.analysis, proposal['tuning'])
            proposal['tuning'] = fitted['tuning']
            proposal['fit'] = fitted
            proposal['before'] = rec.simulate(self.recording, self.tuning or rec.DEFAULTS, self.analysis['ticks'])
            proposal['after'] = rec.simulate(self.recording, fitted['tuning'], self.analysis['ticks'])
            self.proposal = proposal
        except ValueError as exc:
            self.record_prompt.configure(text=f'Recording unusable: {exc}', fg=GOLD)
            self.analysis = self.proposal = None
            return
        try:
            path = rec.save(self.recording, Path(__file__).resolve().parent / 'build/recordings')
            self.log_event(f'EVENT recording saved {path.name}')
        except OSError as exc:
            self.log_event(f'EVENT recording not saved: {exc}')
        self.record_prompt.configure(text='Recording complete. Review below, then apply.', fg=GREEN)
        self.draw_tuning_table()

    def draw_tuning_table(self):
        table = self.result_table
        for row in table.get_children(): table.delete(row)
        if not self.analysis:
            self.result_note.configure(text='Run a guided recording to measure the slider and propose tuning.')
            return
        for entry in self.analysis['steps']:
            table.insert('', 'end', values=(
                entry['tick'],
                '—' if entry['mm'] is None else f"{entry['mm']:.2f}",
                '—' if entry['noise'] is None else f"{entry['noise']:.2f}",
                '⚠' if entry['warnings'] else 'ok'))
        p = self.proposal
        if not p: return
        lines = [f"Raw noise {self.analysis['noise']:.2f} mm · tightest tick gap {self.analysis['min_gap']:.1f} mm · "
                 f"sample period {self.analysis['sample_period_ms']:.0f} ms"]
        before, after = p['before'], p['after']
        lines.append(f"Predicted: {before['flicker']} output changes while held now → {after['flicker']} after tuning "
                     f"(settles in {after['settle_ms']} ms, budget {p['settle_budget_ms']} ms)")
        if not p['fit']['budget_met']:
            lines.append('No setting met the settling budget; the least-flicker option is shown.')
        lines += ['• ' + n for n in p['notes']]
        lines += ['⚠ ' + w for w in p['warnings']]
        self.result_note.configure(text='\n'.join(lines))

    def apply_recording_calibration(self):
        if not self.analysis: return
        try:
            self.points = dict(self.analysis['points'])
            self.ticks = validate(rec.interpolate_ticks(self.points))
        except ValueError as exc:
            messagebox.showerror('Calibration', str(exc)); return
        self.dirty = True
        self.tabs.select(self.work_tab)
        self.note.configure(text='Calibration drafted from the recording. Review, then Apply & save to flash.')
        self.draw()

    def apply_recommended_tuning(self, save):
        if not self.proposal: return
        values = self.proposal['tuning']
        for key, var in self.tuning_vars.items(): var.set(self.format_field(key, values[key]))
        self.send_tuning(values, save)

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
        self.tuning = None
        self.index_changes.clear()
        if self.record_state is not None: self.stop_recording('Disconnected during recording.')
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
        zone = self.monitor.zone or {}
        def version(source, prefix):
            parts = [f"{prefix} v{source.get('db_version','?')}", f"{source.get('db_count','?')} mappings"]
            crc = source.get('db_crc')
            if crc is not None: parts.append(f'CRC {int(crc):08X}' if isinstance(crc,int) else f'CRC {crc}')
            return ' · '.join(parts)
        try:
            local = firmware.local_database()
            master = f"Local master v{local.version} · {local.count} mappings · CRC {local.crc:08X}"
        except Exception as exc:
            master = 'Local master unavailable: '+str(exc)
        self.database_detail.configure(text=(version(zone,'Board') if zone else 'Board — (not connected)')+'     '+master)
        self.registry_label.configure(
            text=(f"{zone.get('name','?')} · point {zone.get('point_id','?')} · {zone.get('firmware','?')} · "
                  f"{zone.get('mac','?')} · {version(zone,'database')}") if zone else
                 'Registry: connect to read board identity')
        self.draw()

    def start_database(self):
        """Update only the board's cube database, leaving a current application alone."""
        if self.flashing or not self.ready or not self.connection: return
        if self.database_state == 'ahead':
            self.flash_status.configure(text='The board database is newer than the local master; resolve that first.')
            return
        if self.database_state != 'update':
            self.flash_status.configure(text='Cube database is already current on this board.')
            return
        self.start_flash(database_only=True)

    def update_registry(self):
        """Record this board in the shared zones table without flashing anything."""
        zone = self.monitor.zone
        if self.flashing or not zone or not zone.get('mac'):
            self.registry_label.configure(text='Connect and wait for the board report before updating the registry.')
            return
        detail = None
        if self.tuning:
            detail = 'tuning ' + ('saved' if self.tuning_saved else 'live') + ': ' + ', '.join(
                f'{k}={self.format_field(k, v)}' for k, v in self.tuning.items())
        try:
            firmware.record_zone_status(zone, detail=detail)
        except Exception as exc:
            self.registry_label.configure(text='Registry update failed: '+str(exc)); return
        self.registry_label.configure(text=f"Registry updated for {zone.get('name','?')} ({zone.get('mac')}) at {time.strftime('%H:%M:%S')}.")
        self.log_event('EVENT zone status written to registry')

    def start_flash(self, database_only=False):
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
        self.flash_status.configure(text='Checking cube database…' if database_only else 'Checking connected board and existing build…')
        def worker():
            try:
                result=firmware.flash(port,lambda kind,value: self.flash_events.put((kind,value)),database_only=database_only)
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
            self.note_index(self.index, now)
        elif data.get('type') == 'raw':
            self.collect_raw(data, now)
        elif data.get('type') == 'tuning':
            self.absorb_tuning(data)
        self.draw()

    def draw(self):
        self.flash_button.configure(text='Firmware & database up to date' if self.firmware_state=='current' and self.database_state=='current' else 'Update firmware & database', state='normal' if self.ready and not self.flashing and self.firmware_state in ('current','update') and self.database_state in ('current','update') and (self.firmware_state=='update' or self.database_state=='update') else 'disabled')
        self.check_firmware_button.configure(state='normal' if self.connection and not self.flashing else 'disabled')
        idle = bool(self.connection) and not self.flashing
        self.database_check_button.configure(state='normal' if idle else 'disabled')
        self.database_button.configure(
            text='Cube database up to date' if self.database_state=='current' else 'Update cube database',
            state='normal' if idle and self.ready and self.database_state=='update' else 'disabled')
        self.registry_button.configure(state='normal' if idle and self.monitor.zone else 'disabled')
        recording_now = self.record_state is not None
        self.record_button.configure(state='disabled' if recording_now or not self.ready or self.flashing else 'normal')
        self.record_abort.configure(state='normal' if recording_now else 'disabled')
        self.connect_button.configure(state='disabled' if self.flashing else 'normal')
        if self.record_state is not None and not self.connection: self.stop_recording('Disconnected during recording.')
        self.ports.configure(state='disabled' if self.flashing else 'normal')
        self.draw_interaction()
        reading = (f'One Euro · raw {self.raw_distance:.1f} mm → filtered {self.distance:.2f} mm'
                   if self.distance is not None and self.raw_distance is not None else 'One Euro · no valid sensor reading')
        # Read the live parameters from the board: they are tunable, so a fixed label would lie.
        if self.tuning:
            reading += (f" · min {self.tuning['mincutoff']:g} Hz / beta {self.tuning['beta']:g}"
                        f" / median {self.tuning['median']} · enter {self.tuning['enter']:g} / exit {self.tuning['exit']:g}")
        self.filter_label.configure(text=reading)
        self.stability_label.configure(text=self.stability_text(time.monotonic()))
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
            elif self.connection and self.ready and self.tuning is None and now-self.last_query>1:
                self.last_query=now; self.send('TUNE GET')
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
        self.advance_recording(now)
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
