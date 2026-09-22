#!/usr/bin/env python3
"""NCT zone flasher: detect, flash (manual or automatic) and test zone boards, with a live neocube monitor."""
import argparse
import math
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

import serial

import zone_build
import zone_detect
from zone_flash import DEFAULT_DATABASE, ZoneFlasher, Runner, ports, Database, ZoneStore, PortLock, WORKSPACE
from zone_monitor import MonitorState
import zonedb

sys.path.insert(0, str(WORKSPACE / 'flashing_station'))
from core import Scheduler  # noqa: E402  (armed intake with reconnect debounce)
import hostos  # noqa: E402
from sync_widget import SyncWidget  # noqa: E402  (universal web Sync: inventory + zone database)

BG, CARD, FG, MUTED = '#101720', '#1b2633', '#e9f0f7', '#9aafc4'
GREEN, AMBER, RED, BLUE = '#54d6a0', '#ffc16b', '#ff7a8a', '#82b8fa'
PORT_COLUMNS = [('port', 'USB port', 170), ('mac', 'MAC', 135), ('detected', 'Detected', 210), ('identity', 'Zone identity', 150),
                ('firmware', 'Firmware', 110), ('rx_gain', 'RX gain', 80), ('database', 'Database', 110),
                ('plan', 'Plan / result', 330)]
HISTORY_COLUMNS = [('time', 'Time', 70), ('cube', 'Neocube', 80), ('uid', 'NFC UID', 170), ('mac', 'MAC', 140),
                   ('result', 'Zone command', 150), ('held', 'On plate', 80), ('registry', 'Registry', 170)]


class SerialMonitor:
    """Owns the zone's serial port while the cube monitor is connected."""

    def __init__(self, emit):
        self.emit = emit
        self.port = None
        self.outbox = queue.Queue()
        self.stop = threading.Event()
        self.thread = None

    def connect(self, path):
        self.disconnect()
        self.stop = threading.Event()
        self.outbox = queue.Queue()
        self.port = path
        self.thread = threading.Thread(target=self._run, args=(path, self.stop, self.outbox), daemon=True)
        self.thread.start()

    def disconnect(self):
        self.stop.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)
        self.thread = self.port = None

    def send(self, line):
        if not self.port:
            raise ValueError('Connect the cube monitor to a zone first')
        self.outbox.put(line)

    def _run(self, path, stop, outbox):
        try:
            with PortLock(path):
                conn = serial.Serial(port=None, baudrate=115200, timeout=.1, exclusive=True)
                conn.dtr = True   # esp-idf-monitor ordering: opening must not reset a native-USB ESP32-C3
                conn.rts = True
                conn.port = path
                conn.open()
                conn.rts = False
                conn.dtr = False
                with conn:
                    self.emit('monitor', ('connected', path))
                    conn.write(b'?\n')
                    buffer = b''
                    while not stop.is_set():
                        try:
                            conn.write((outbox.get_nowait() + '\n').encode())
                        except queue.Empty:
                            pass
                        buffer += conn.read(4096)
                        while b'\n' in buffer:
                            line, _, buffer = buffer.partition(b'\n')
                            self.emit('zone_line', line.decode(errors='replace').rstrip('\r'))
        except Exception as exc:
            self.emit('monitor', ('error', str(exc)))
        finally:
            self.emit('monitor', ('disconnected', path))


class App:
    def __init__(self, root, database):
        self.root, self.database = root, database
        self.events = queue.Queue()
        self.busy = False
        self.closing = False
        self.port_rows, self.detections, self.results = {}, {}, {}
        self.scheduler = Scheduler()
        self.pending_detect = set()
        self.remembered, self.port_keys = {}, {}
        self.last_scan = 0
        self.state = MonitorState()
        self.monitor = SerialMonitor(self.emit)
        self.monitor_port = None
        self.resume_monitor = None
        self.monitor_off = set()   # ports the operator disconnected by hand: no auto-connect until replugged/reflashed
        self.monitor_failed_at = 0
        self.last_nfc_query = 0
        self.registry = {}
        self.history_rows = {}
        root.title('NCT · Zone Flasher')
        root.geometry('1280x900')
        root.minsize(1100, 760)
        root.configure(bg=BG)
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('.', background=BG, foreground=FG, font=('Helvetica', 11))
        style.configure('TButton', background='#263749', padding=(12, 8), borderwidth=0)
        style.map('TButton', background=[('active', '#39536e')], foreground=[('disabled', '#65778a')])
        style.configure('Armed.TButton', background='#1f6b4f')
        style.configure('TCombobox', fieldbackground='#263749', foreground=FG)
        style.map('TCombobox', fieldbackground=[('readonly', '#263749')], foreground=[('readonly', FG)])
        style.configure('TEntry', fieldbackground='#263749', foreground=FG)
        style.configure('TCheckbutton', background=BG, foreground=FG)
        style.configure('TNotebook', background=BG, borderwidth=0)
        style.configure('TNotebook.Tab', background='#1b2633', foreground=MUTED, padding=(18, 8))
        style.map('TNotebook.Tab', background=[('selected', '#263749')], foreground=[('selected', FG)])
        style.configure('Treeview', background=CARD, fieldbackground=CARD, foreground=FG, rowheight=28, borderwidth=0)
        style.configure('Treeview.Heading', background='#263749', foreground=MUTED, padding=5)
        style.map('Treeview', background=[('selected', '#315575')])
        outer = ttk.Frame(root, padding=18)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='ZONES / FLASHER', font=('Helvetica', 24, 'bold')).pack(anchor='w')
        self.info = tk.StringVar()
        ttk.Label(outer, textvariable=self.info, foreground=MUTED).pack(anchor='w', pady=(4, 0))
        self.web_status = SyncWidget(outer, self.database, 'Zone flasher', on_synced=lambda _: self.refresh_info())
        self.web_status.pack(anchor='w', fill='x', pady=(2, 10))
        self.tabs = ttk.Notebook(outer)
        self.tabs.pack(fill='both', expand=True)
        self.build_flash_tab()
        self.build_monitor_tab()
        self.profile_changed()
        self.refresh_info()
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.poll)

    # ------------------------------------------------------------------ flash tab
    def build_flash_tab(self):
        tab = ttk.Frame(self.tabs, padding=14)
        self.tabs.add(tab, text='Flash zones')
        self.status = tk.StringVar(value='Plug in a zone board. It is identified automatically.')
        self.status_label = tk.Label(tab, textvariable=self.status, bg=CARD, fg=BLUE, font=('Helvetica', 15, 'bold'),
                                     anchor='w', padx=14, pady=11, wraplength=1180, justify='left')
        self.status_label.pack(fill='x')
        form = ttk.Frame(tab)
        form.pack(fill='x', pady=12)
        self.labels = {p['label']: key for key, p in zone_build.PROFILES.items()}
        self.profile_label = tk.StringVar(value=zone_build.PROFILES['preshow']['label'])
        self.point = tk.IntVar(value=1)
        self.name = tk.StringVar()
        ttk.Label(form, text='Zone').grid(row=0, column=0, sticky='w', padx=(0, 8))
        profiles = ttk.Combobox(form, textvariable=self.profile_label, values=list(self.labels), state='readonly', width=32)
        profiles.grid(row=0, column=1, sticky='w')
        ttk.Label(form, text='Point / ID').grid(row=0, column=2, sticky='w', padx=(18, 8))
        self.points = ttk.Combobox(form, textvariable=self.point, state='readonly', width=4)
        self.points.grid(row=0, column=3, sticky='w')
        ttk.Label(form, text='Name').grid(row=0, column=4, sticky='w', padx=(18, 8))
        ttk.Entry(form, textvariable=self.name, width=18).grid(row=0, column=5, sticky='w')
        # PN532 receiver gain stored in zcfg; the Zone Database Manager can also change it over the air.
        self.rx_gain = tk.StringVar(value=str(zonedb.RX_GAIN_DEFAULT))
        ttk.Label(form, text='RX gain').grid(row=0, column=6, sticky='w', padx=(18, 8))
        self.rx_gain_box = ttk.Combobox(form, textvariable=self.rx_gain, values=[str(g) for g in zonedb.RX_GAINS],
                                        state='readonly', width=4)
        self.rx_gain_box.grid(row=0, column=7, sticky='w')
        ttk.Label(form, text='dB', foreground=MUTED).grid(row=0, column=8, sticky='w', padx=(4, 0))
        self.rx_gain_box.bind('<<ComboboxSelected>>', lambda _: self.refresh_plans())
        self.param_vars, self.param_widgets = [tk.StringVar(), tk.StringVar()], []
        for i, var in enumerate(self.param_vars):
            label = ttk.Label(form, text='')
            entry = ttk.Entry(form, textvariable=var, width=8)
            label.grid(row=1, column=i * 2, columnspan=1 if i == 0 else 2, sticky='w', pady=(10, 0), padx=(0 if i == 0 else 18, 8))
            entry.grid(row=1, column=1 if i == 0 else 4, sticky='w', pady=(10, 0))
            self.param_widgets.append((label, entry))
        profiles.bind('<<ComboboxSelected>>', lambda _: self.profile_changed())
        self.points.bind('<<ComboboxSelected>>', lambda _: self.point_changed())

        controls = ttk.Frame(tab)
        controls.pack(fill='x')
        self.buttons = []
        for label, action in [('Flash selected', self.flash_selected), ('Detect again', self.detect_selected),
                              ('Check report', self.check_selected), ('Build all firmware', self.build_all)]:
            b = ttk.Button(controls, text=label, command=action)
            b.pack(side='left', padx=(0, 8))
            self.buttons.append(b)
        self.auto_button = ttk.Button(controls, text='▶ Arm auto-flash', command=self.toggle_auto)
        self.auto_button.pack(side='right')
        self.advance = tk.BooleanVar(value=True)
        self.unidentified = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls, text='Flash unidentified boards as the selected zone', variable=self.unidentified).pack(side='right', padx=12)
        ttk.Checkbutton(controls, text='Next point after each new board', variable=self.advance).pack(side='right', padx=12)
        ttk.Label(tab, foreground=MUTED, wraplength=1180, justify='left', text=(
            'Auto-flash: boards that already carry a zone identity are updated in place (same zone, point, name). Legacy '
            'sketches are recognised from their firmware and flashed when they match the selected zone. Neocubes, the pairing '
            'station and non-zone controllers are never written automatically; "Flash selected" on a refused board offers a '
            'confirmed force-flash (never for the known pairing station); force-flashing a registered neocube unregisters it '
            '(number and NFC tag released).')).pack(anchor='w', pady=(10, 6))
        self.port_tree = ttk.Treeview(tab, columns=[c[0] for c in PORT_COLUMNS], show='headings', height=6, selectmode='browse')
        for key, title, width in PORT_COLUMNS:
            self.port_tree.heading(key, text=title)
            self.port_tree.column(key, width=width, anchor='w')
        for tag, color in [('ok', GREEN), ('warn', AMBER), ('bad', RED), ('muted', MUTED)]:
            self.port_tree.tag_configure(tag, foreground=color)
        self.port_tree.pack(fill='x', pady=(4, 10))
        self.port_tree.bind('<<TreeviewSelect>>', lambda _: self.port_selected())
        self.log = tk.Text(tab, bg='#0b1119', fg=MUTED, relief='flat', font=(hostos.MONO_FONT, 10), state='disabled', wrap='none', height=12)
        self.log.pack(fill='both', expand=True)

    def profile_key(self):
        return self.labels[self.profile_label.get()]

    def profile_changed(self):
        profile = zone_build.PROFILES[self.profile_key()]
        self.points['values'] = profile['points']
        if self.point.get() not in profile['points']:
            self.point.set(profile['points'][0])
        for i, (label, entry) in enumerate(self.param_widgets):
            if i < len(profile['params']):
                label.configure(text=profile['params'][i][0])
                if not self.param_vars[i].get():
                    self.param_vars[i].set(str(profile['params'][i][1]))
                label.grid()
                entry.grid()
            else:
                self.param_vars[i].set('')
                label.grid_remove()
                entry.grid_remove()
        self.point_changed()

    def point_changed(self):
        self.name.set(zone_build.PROFILES[self.profile_key()]['name'].format(point=self.point.get()))
        self.refresh_plans()

    def form(self):
        profile = zone_build.PROFILES[self.profile_key()]
        params = []
        for var, (label, _, scale) in zip(self.param_vars, profile['params']):
            try:
                params.append(round(float(var.get()) * scale))
            except ValueError:
                raise ValueError(f'Enter a number for "{label}"')
        return dict(profile=self.profile_key(), point=self.point.get(), name=self.name.get().strip(), params=params,
                    rx_gain=int(self.rx_gain.get()))

    def fill_form(self, detection):
        if not detection.get('profile'):
            return
        profile = zone_build.PROFILES[detection['profile']]
        self.profile_label.set(profile['label'])
        self.profile_changed()
        if detection.get('point') in profile['points']:
            self.point.set(detection['point'])
            self.point_changed()
        if detection.get('name'):
            self.name.set(detection['name'])
        for var, value, spec in zip(self.param_vars, detection.get('params') or [], profile['params']):
            var.set(str(value / spec[2]))
        self.rx_gain.set(str(detection.get('rx_gain') or zonedb.RX_GAIN_DEFAULT))

    # ------------------------------------------------------------------ ports, detection, plans
    def manifests(self):
        result = {}
        for sketch in zone_build.SKETCHES:
            try:
                result[sketch] = zone_build.load_manifest(sketch)
            except Exception:
                pass
        return result

    def published(self):
        db = Database(self.database, recover_pending=False)
        try:
            return ZoneStore(db).published()
        finally:
            db.close()

    def refresh_info(self):
        manifests = self.manifests()
        missing = [s for s in zone_build.SKETCHES if s not in manifests]
        builds = ' · '.join(m['version'] for m in manifests.values()) or 'none'
        try:
            db = Database(self.database, recover_pending=False)
            try:
                store = ZoneStore(db)
                published, records, differs = store.published(), len(store.records()), store.local_differs()
                self.registry = {r['cube_id']: r for r in db.rows() if r['cube_id'] is not None}
            finally:
                db.close()
            database = (f'cube database v{published["version"]} published · {records} committed mappings now' +
                        (' · LOCAL CHANGES NOT PUBLISHED (Zone Database Manager)' if differs else ''))
        except Exception as exc:
            database = f'database: {exc}'
        self.info.set(f'Firmware builds: {builds}' + (f' · NEEDS BUILD: {", ".join(missing)}' if missing else '') + f'   ·   {database}')

    def scan_ports(self):
        # ESP32 USB devices only (the protected pairing station is listed so it is visibly refused).
        found = [p for p in ports() if p['candidate'] or (p.get('serial') or '').upper() in zone_detect.PROTECTED]
        self.port_rows = {p['port']: p for p in found}
        # Identifying or flashing reboots the board, so its USB port vanishes for a moment. Remember what we know
        # by USB identity (an ESP32-C3's serial number is its MAC) instead of identifying again in a loop.
        now = time.monotonic()
        for gone in set(self.detections) - set(self.port_rows):
            self.remembered[self.port_keys.get(gone)] = (self.detections.pop(gone), self.results.pop(gone, None), now)
        self.remembered = {k: v for k, v in self.remembered.items() if k and now - v[2] < v[0].get('remember_s', 15)}
        self.scheduler.scan(found, self.busy)
        for p in found:
            self.port_keys[p['port']] = p['key']
            if p['port'] in self.detections or p['port'] in self.pending_detect or p['port'] == self.monitor.port:
                continue
            if p['key'] in self.remembered:
                detection, result, _ = self.remembered.pop(p['key'])
                self.detections[p['port']] = detection
                if result:
                    self.results[p['port']] = result
            else:
                self.pending_detect.add(p['port'])
        self.render_ports()

    def plan_for(self, port, auto=None, force=False):
        detection = self.detections.get(port)
        if not detection:
            return None
        try:
            form = self.form()
        except ValueError as exc:
            return dict(action='ask', reason=str(exc))
        return zone_detect.plan(detection, form, self.manifests(), self.published(),
                                auto=self.scheduler.armed if auto is None else auto, allow_unidentified=self.unidentified.get(),
                                force=force)

    def refresh_plans(self):
        if hasattr(self, 'port_tree'):
            self.render_ports()

    def render_ports(self):
        selected = self.port_tree.selection()
        existing = set(self.port_tree.get_children())
        for port in existing - set(self.port_rows):
            self.port_tree.delete(port)
        for port, info in self.port_rows.items():
            d = self.detections.get(port)
            plan = self.plan_for(port) if d else None
            result = self.results.get(port)
            if port == self.monitor.port and not d:
                values, tag = dict(detected='In use by the cube monitor', plan=''), 'muted'
            elif not d:
                values, tag = dict(detected='Identifying…' if port in self.pending_detect else '—', plan=''), 'muted'
            else:
                identity = f'{d.get("name")} · point {d.get("point")}' if d.get('configured') or d.get('name') else '—'
                gain = d.get('rx_gain')
                values = dict(mac=d.get('mac') or '', detected=d['label'], identity=identity, firmware=d.get('firmware') or '—',
                              rx_gain=('—' if not gain else f'{gain} dB' if d.get('source') != 'serial report'
                                       or d.get('rx_gain_applied') == gain else f'{gain} dB (not applied)'),
                              database=f'v{d["db_version"]} · {d["db_count"]} rec' if 'db_version' in d else '—',
                              plan=(result or (plan['action'].upper() + ' · ' + plan['reason'])))
                tag = ('ok' if result and result.startswith('SUCCESS') else 'bad' if result else
                       {'flash': 'ok', 'skip': 'muted', 'refuse': 'bad', 'ask': 'warn'}[plan['action']])
            row = [values.get(c[0], '') if c[0] != 'port' else f'{port.replace("/dev/cu.", "")}' for c in PORT_COLUMNS]
            if port in existing:
                self.port_tree.item(port, values=row, tags=(tag,))
            else:
                self.port_tree.insert('', 'end', iid=port, values=row, tags=(tag,))
        if not selected and len(self.port_rows) and not self.port_tree.selection():
            flashable = [p for p, d in self.detections.items() if d['kind'] not in zone_detect.NOT_FLASHABLE]
            if flashable:
                self.port_tree.selection_set(flashable[0])
        zone_ports = [p for p, d in self.detections.items() if d['kind'] == 'nctzone']
        if self.monitor.port and self.monitor.port not in zone_ports:
            zone_ports.append(self.monitor.port)
        self.monitor_ports['values'] = zone_ports
        if zone_ports and self.monitor_choice.get() not in zone_ports:
            self.monitor_choice.set(zone_ports[0])

    def port_selected(self):
        port = self.selected_port(required=False)
        if port and port in self.detections and not self.scheduler.armed:
            self.fill_form(self.detections[port])

    def selected_port(self, required=True):
        selection = self.port_tree.selection()
        if not selection:
            if required:
                raise ValueError('Select a USB port in the table')
            return None
        return selection[0]

    # ------------------------------------------------------------------ work
    def emit(self, kind, value):
        self.events.put((kind, value))

    def run(self, title, work, port=None):
        if self.busy:
            return False
        if port and self.monitor.port == port:
            self.resume_monitor = port
            self.monitor.disconnect()
        self.busy = True
        for b in self.buttons:
            b.configure(state='disabled')
        self.set_status(title, BLUE)

        def target():
            try:
                work()
            except Exception as exc:
                self.emit('error', str(exc))
            finally:
                self.emit('done', port)
        threading.Thread(target=target, daemon=True).start()
        return True

    def detect(self, port):
        info = self.port_rows.get(port)
        if not info:
            self.pending_detect.discard(port)
            return False

        def work():
            try:
                detection = ZoneFlasher(self.database, self.emit).detect(info)
            except Exception as exc:
                detection = dict(kind='unknown', label=f'Could not identify: {exc}', profile=None)
            self.emit('detected', (port, detection))
        return self.run(f'Identifying {port}…', work, port)

    def detect_selected(self):
        try:
            port = self.selected_port()
        except ValueError as exc:
            return messagebox.showerror('Zone flasher', str(exc), parent=self.root)
        self.detections.pop(port, None)
        self.results.pop(port, None)
        self.remembered.pop(self.port_keys.get(port), None)
        self.pending_detect.add(port)

    def flash(self, port, plan, auto=False):
        info = self.port_rows[port]

        def work():
            record = ZoneFlasher(self.database, self.emit).execute(info, plan['profile'], plan['point'], plan['name'], plan['params'],
                                                                   force=plan.get('force', False),
                                                                   rx_gain=plan.get('rx_gain', zonedb.RX_GAIN_DEFAULT))
            self.emit('flashed', (port, record, auto))
        return self.run(f'{"FORCE-f" if plan.get("force") else "F"}lashing "{plan["name"]}" on {port}…', work, port)

    def flash_selected(self):
        try:
            port = self.selected_port()
            plan = self.plan_for(port, auto=False)
            if not plan:
                raise ValueError('This port has not been identified yet')
            detection = self.detections[port]
            unregister = ''
            if plan['action'] == 'refuse' and self.port_rows[port].get('candidate') and zone_detect.forceable(detection):
                if detection['kind'] == 'cube':
                    unregister = (f'\n\n{detection["label"].replace(" (database)", "")} will be UNREGISTERED: its number and NFC '
                                  'tag are released in the device database (run Sync afterwards).')
                if not messagebox.askyesno('Force flash?', f'REFUSED: {plan["reason"]}\n\n{port} ({detection.get("mac", "?")}) was '
                                           f'identified as: {detection["label"]}.\n\nOverwrite it with zone firmware anyway? '
                                           f'Its current firmware is replaced (no backup is taken).{unregister}',
                                           icon='warning', default='no', parent=self.root):
                    return
                plan = self.plan_for(port, auto=False, force=True)
            if plan['action'] != 'flash':
                raise ValueError(plan['reason'])
            sketch = zone_build.PROFILES[plan['profile']]['sketch']
            zone_build.load_manifest(sketch)
        except Exception as exc:
            return messagebox.showerror('Zone flasher', str(exc), parent=self.root)
        profile = zone_build.PROFILES[plan['profile']]
        warning = f'\n\nFORCED: overriding the refusal above.{unregister}' if plan.get('force') else ''
        if detection.get('profile') and detection['profile'] != plan['profile']:
            warning += f'\n\nNOTE: this board was identified as "{zone_build.PROFILES[detection["profile"]]["label"]}".'
        if messagebox.askokcancel('Flash zone', f'Flash {profile["label"]} as "{plan["name"]}" (point {plan["point"]}, '
                                  f'RX gain {plan.get("rx_gain", zonedb.RX_GAIN_DEFAULT)} dB) on\n'
                                  f'{port} ({detection.get("mac", "?")})?{warning}', parent=self.root):
            self.flash(port, plan)

    def check_selected(self):
        try:
            port = self.selected_port()
        except ValueError as exc:
            return messagebox.showerror('Zone flasher', str(exc), parent=self.root)
        info = self.port_rows[port]

        def work():
            report = ZoneFlasher(self.database, self.emit).boot_report(info, Runner(self.emit), timeout=6)
            if report:
                self.emit('detected', (port, zone_detect.from_report(report)))
                self.emit('status', (f'{report.get("name", "unconfigured")} · {report["firmware"]} · channel {report["channel"]} · '
                                     f'database v{report["db_version"]} ({report["db_count"]} records)', GREEN))
            else:
                self.emit('status', ('No zone report received (not NctZone firmware, or still booting)', AMBER))
        self.run('Reading zone report…', work, port)

    def build_all(self):
        def work():
            for sketch in zone_build.SKETCHES:
                self.emit('stage', f'Build {sketch}')
                zone_build.build(sketch, Runner(self.emit))
            self.emit('status', ('All zone firmware built', GREEN))
        self.run('Building firmware…', work)

    def toggle_auto(self):
        if not self.scheduler.armed:
            try:
                self.form()
                missing = [s for s in zone_build.SKETCHES if s not in self.manifests()]
                if missing:
                    raise ValueError('Build firmware first: ' + ', '.join(missing))
            except ValueError as exc:
                return messagebox.showerror('Zone flasher', str(exc), parent=self.root)
        self.scheduler.armed = not self.scheduler.armed
        self.scheduler.attempted = set() if self.scheduler.armed else self.scheduler.attempted
        self.auto_button.configure(text='■ Stop auto-flash' if self.scheduler.armed else '▶ Arm auto-flash',
                                   style='Armed.TButton' if self.scheduler.armed else 'TButton')
        self.set_status('AUTO-FLASH ARMED · plug in zone boards one after another' if self.scheduler.armed else 'Auto-flash stopped', GREEN if self.scheduler.armed else BLUE)
        self.render_ports()

    def auto_step(self):
        if not self.scheduler.armed or self.busy:
            return
        for port, info in self.port_rows.items():
            if info['key'] in self.scheduler.attempted or port not in self.detections:
                continue
            plan = self.plan_for(port, auto=True)
            self.scheduler.mark(info)
            if plan['action'] == 'flash':
                try:
                    zone_build.load_manifest(zone_build.PROFILES[plan['profile']]['sketch'])
                except Exception as exc:
                    self.results[port] = f'NOT FLASHED · {exc}'
                    continue
                self.flash(port, plan, auto=True)
                return
            self.results[port] = None if plan['action'] != 'skip' else f'SUCCESS · {plan["reason"]}'

    # ------------------------------------------------------------------ cube monitor tab
    def build_monitor_tab(self):
        tab = ttk.Frame(self.tabs, padding=14)
        self.tabs.add(tab, text='Cube monitor')
        top = ttk.Frame(tab)
        top.pack(fill='x')
        ttk.Label(top, text='Zone on USB').pack(side='left')
        self.monitor_choice = tk.StringVar()
        self.monitor_ports = ttk.Combobox(top, textvariable=self.monitor_choice, state='readonly', width=30)
        self.monitor_ports.pack(side='left', padx=8)
        self.connect_button = ttk.Button(top, text='Connect', command=self.toggle_monitor)
        self.connect_button.pack(side='left')
        self.auto_monitor = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text='Connect automatically', variable=self.auto_monitor).pack(side='left', padx=(10, 0))
        self.zone_info = tk.StringVar(value='Not connected. Flash or plug in a zone, then Connect.')
        ttk.Label(top, textvariable=self.zone_info, foreground=BLUE).pack(side='left', padx=14)
        self.reader_info = tk.StringVar(value='')
        self.reader_label = ttk.Label(tab, textvariable=self.reader_info, foreground=MUTED)
        self.reader_label.pack(anchor='w', pady=(8, 0))
        middle = ttk.Frame(tab)
        middle.pack(fill='x', pady=14)
        self.cube_canvas = tk.Canvas(middle, width=300, height=250, bg=CARD, highlightthickness=0)
        self.cube_canvas.pack(side='left')
        detail = ttk.Frame(middle, padding=(18, 0))
        detail.pack(side='left', fill='both', expand=True)
        self.cube_title = tk.StringVar(value='No neocube on the plate')
        ttk.Label(detail, textvariable=self.cube_title, font=('Helvetica', 26, 'bold')).pack(anchor='w')
        self.cube_detail = tk.Text(detail, height=8, bg=BG, fg=FG, relief='flat', highlightthickness=0, font=(hostos.MONO_FONT, 12), state='disabled')
        self.cube_detail.pack(fill='x', pady=(8, 8))
        actions = ttk.Frame(detail)
        actions.pack(anchor='w')
        self.cube_buttons = []
        for label, command in [('Flash 5 s', lambda c: f'flash {c} 5'), ('Clear (idle white)', lambda c: f'clear {c}'),
                               ('Preshow', lambda c: f'zone {c} 1'), ('Desert', lambda c: f'zone {c} 2'),
                               ('Pool', lambda c: f'zone {c} 3'), ('Mainshow', lambda c: f'zone {c} 4')]:
            b = ttk.Button(actions, text=label, command=lambda make=command: self.cube_action(make))
            b.pack(side='left', padx=(0, 6))
            self.cube_buttons.append(b)
        ttk.Button(actions, text='Stop flashing', command=lambda: self.monitor_send('stop', None)).pack(side='left', padx=(12, 0))
        self.action_target = tk.StringVar(value='Actions apply to the neocube on the plate, or to the selected history row.')
        ttk.Label(detail, textvariable=self.action_target, foreground=MUTED).pack(anchor='w', pady=(8, 0))
        ttk.Label(tab, text='HISTORY', foreground=MUTED).pack(anchor='w')
        self.history_tree = ttk.Treeview(tab, columns=[c[0] for c in HISTORY_COLUMNS], show='headings', height=9, selectmode='browse')
        for key, title, width in HISTORY_COLUMNS:
            self.history_tree.heading(key, text=title)
            self.history_tree.column(key, width=width, anchor='w')
        for tag, color in [('ok', GREEN), ('warn', AMBER), ('bad', RED)]:
            self.history_tree.tag_configure(tag, foreground=color)
        self.history_tree.pack(fill='both', expand=True, pady=(4, 8))
        self.history_tree.bind('<<TreeviewSelect>>', lambda _: self.render_monitor())
        self.zone_log = tk.Text(tab, bg='#0b1119', fg=MUTED, relief='flat', font=(hostos.MONO_FONT, 10), state='disabled', wrap='none', height=6)
        self.zone_log.pack(fill='x')

    def toggle_monitor(self):
        if self.monitor.port:
            self.monitor_off.add(self.monitor.port)
            self.monitor.disconnect()
            return
        port = self.monitor_choice.get()
        self.monitor_off.discard(port)
        if not port:
            return messagebox.showerror('Cube monitor', 'No NctZone board detected on USB yet.', parent=self.root)
        if self.busy:
            return messagebox.showerror('Cube monitor', 'Wait for the current flash/detect to finish.', parent=self.root)
        self.monitor.connect(port)

    def auto_connect_monitor(self, now):
        """Listen to a detected zone without being asked, so a tap always shows up."""
        self.monitor_off &= set(self.port_rows)
        if self.busy or self.monitor.port or not self.auto_monitor.get() or now - self.monitor_failed_at < 5:
            return
        port = next((p for p, d in self.detections.items() if d['kind'] == 'nctzone' and p in self.port_rows and
                     p not in self.monitor_off and p not in self.pending_detect), None)
        if port:
            self.monitor_choice.set(port)
            self.monitor.connect(port)

    def show_tap(self, line):
        entry = self.state.current
        if line.startswith('EVT TAG') and entry:
            who = f'Neocube #{entry["cube_id"]}' if entry['cube_id'] else f'Unknown NFC tag {entry["uid"]}'
            if not self.busy:
                self.set_status(f'{who} on the plate', BLUE if entry['cube_id'] else AMBER)
                if not self.scheduler.armed:
                    self.tabs.select(1)
        elif line.startswith('EVT SENT') and entry and entry['cube_id'] and not self.busy:
            zone = zonedb.ZONE_COLORS.get(entry['zone'], ('?',))[0]
            ok = entry['state'] == 'delivered'
            if entry['state'] != 'pending':
                self.set_status(f'Neocube #{entry["cube_id"]} → {zone}: ' + ('acknowledged by the cube' if ok else 'NOT acknowledged'),
                                GREEN if ok else RED)

    def target_cube(self):
        if self.state.current and self.state.current['cube_id']:
            return self.state.current['cube_id']
        selection = self.history_tree.selection()
        if selection:
            entry = self.history_rows.get(selection[0])
            if entry and entry['cube_id']:
                return entry['cube_id']
        return None

    def cube_action(self, make):
        cube = self.target_cube()
        if not cube:
            return messagebox.showerror('Cube monitor', 'Put a registered neocube on the plate or select one in the history.', parent=self.root)
        self.monitor_send(make(cube), cube)

    def monitor_send(self, line, cube):
        try:
            self.monitor.send(line)
        except ValueError as exc:
            return messagebox.showerror('Cube monitor', str(exc), parent=self.root)
        self.state.command_sent(line.split()[0], cube)
        self.append(self.zone_log, '> ' + line)
        self.render_monitor()

    def registry_text(self, cube_id):
        row = self.registry.get(cube_id)
        return f'#{cube_id} · {row["status"]}' if row else 'not in registry'

    def render_monitor(self):
        state = self.state
        zone = state.zone
        if self.monitor.port and zone:
            self.zone_info.set(f'{zone.get("name", "unconfigured")} · {zone["firmware"]} · database v{zone["db_version"]} '
                               f'({zone["db_count"]} cubes) · channel {zone["channel"]}')
        elif self.monitor.port:
            self.zone_info.set(f'Connected to {self.monitor.port}; waiting for the zone report…')
        if self.monitor.port:
            text, level = state.reader_text()
            self.reader_info.set(text + ('' if level != 'ok' or state.current else ' · nothing on the plate is being detected right now'))
            self.reader_label.configure(foreground={'ok': GREEN, 'warn': AMBER, 'bad': RED}[level])
        else:
            self.reader_info.set('')
        current = state.current
        cube_id = self.target_cube()
        canvas = self.cube_canvas
        canvas.delete('all')
        label, colour, note = state.display_zone(cube_id) if cube_id else ('', '#2a3849', '')
        blink = cube_id and state.cubes.get(cube_id, {}).get('flashing') and int(time.monotonic() * 2) % 2
        if blink:
            colour = zonedb.ZONE_COLORS[3][1]
        for k in range(8):  # the cube's 8-LED ring, in the colour it was last commanded to show
            angle = k * math.pi / 4
            x, y = 150 + math.cos(angle) * 78, 118 + math.sin(angle) * 78
            canvas.create_oval(x - 17, y - 17, x + 17, y + 17, fill=colour, outline='')
        canvas.create_text(150, 108, text=f'#{cube_id}' if cube_id else '—', fill=FG, font=('Helvetica', 34, 'bold'))
        canvas.create_text(150, 146, text=label.upper(), fill=MUTED, font=('Helvetica', 12, 'bold'))
        canvas.create_text(150, 232, text='LED ring = last commanded zone colour', fill=MUTED, font=('Helvetica', 9))
        if current:
            self.cube_title.set(f'Neocube #{current["cube_id"]} on the plate' if current['cube_id'] else 'Unknown NFC tag on the plate')
        else:
            self.cube_title.set('No neocube on the plate' if not cube_id else f'Neocube #{cube_id} (selected from history)')
        lines = []
        entry = current or (self.history_rows.get(self.history_tree.selection()[0]) if self.history_tree.selection() else None)
        if entry:
            cube = state.cubes.get(entry['cube_id'], {})
            lines = [f'NFC UID    {entry["uid"]}', f'MAC        {entry["mac"] or "— (not in this zone\'s database)"}',
                     f'Zone sent  {zonedb.ZONE_COLORS.get(entry["zone"], ("?",))[0]} → {entry["state"]}',
                     f'Cube shows {label} ({note})' if entry['cube_id'] else 'Cube shows —  (unknown tags are ignored by zones)',
                     f'Taps       {cube.get("taps", 0)} this session',
                     f'Registry   {self.registry_text(entry["cube_id"]) if entry["cube_id"] else "—"}']
            if not entry['cube_id']:
                lines.append('→ Pair this tag in the pairing station, then Publish database.')
        text = '\n'.join(lines)
        if self.cube_detail.get('1.0', 'end-1c') != text:
            self.cube_detail.configure(state='normal')
            self.cube_detail.delete('1.0', 'end')
            self.cube_detail.insert('1.0', text)
            self.cube_detail.configure(state='disabled')
        self.action_target.set(f'Actions apply to neocube #{cube_id}.' if cube_id else
                               'Actions apply to the neocube on the plate, or to the selected history row.')
        for b in self.cube_buttons:
            b.configure(state='normal' if cube_id and self.monitor.port else 'disabled')
        self.connect_button.configure(text='Disconnect' if self.monitor.port else 'Connect')
        self.render_history()

    def render_history(self):
        selection = self.history_tree.selection()
        self.history_rows = {}
        rows = []
        for entry in self.state.history:
            iid = f'{entry["time"]:.3f}'
            self.history_rows[iid] = entry
            held = 'on plate' if entry['held_ms'] is None else f'{entry["held_ms"] / 1000:.1f} s'
            values = [time.strftime('%H:%M:%S', time.localtime(entry['time'])), f'#{entry["cube_id"]}' if entry['cube_id'] else 'unknown',
                      entry['uid'], entry['mac'] or '—', f'{zonedb.ZONE_COLORS.get(entry["zone"], ("?",))[0]} · {entry["state"]}', held,
                      self.registry_text(entry['cube_id']) if entry['cube_id'] else '—']
            tag = {'delivered': 'ok', 'pending': 'warn', 'not acknowledged': 'bad', 'unknown tag': 'warn'}[entry['state']]
            rows.append((iid, values, tag))
        existing = list(self.history_tree.get_children())
        if existing != [r[0] for r in rows]:
            self.history_tree.delete(*existing)
            for iid, values, tag in rows:
                self.history_tree.insert('', 'end', iid=iid, values=values, tags=(tag,))
            if selection and selection[0] in self.history_rows:
                self.history_tree.selection_set(selection[0])
        else:
            for iid, values, tag in rows:
                self.history_tree.item(iid, values=values, tags=(tag,))

    # ------------------------------------------------------------------ UI loop
    def set_status(self, text, color):
        self.status.set(text)
        self.status_label.configure(fg=color)

    def append(self, widget, line):
        widget.configure(state='normal')
        widget.insert('end', time.strftime('%H:%M:%S  ') + line + '\n')
        if int(widget.index('end-1c').split('.')[0]) > 3000:
            widget.delete('1.0', '1000.0')
        widget.see('end')
        widget.configure(state='disabled')

    def handle(self, kind, value):
        if kind == 'log':
            self.append(self.log, value)
        elif kind == 'stage':
            self.set_status(value + '…', BLUE)
            self.append(self.log, '== ' + value)
        elif kind == 'status':
            self.set_status(*value)
        elif kind == 'error':
            self.set_status(value, RED)
            self.append(self.log, 'ERROR: ' + value)
        elif kind == 'detected':
            port, detection = value
            self.pending_detect.discard(port)
            if port in self.port_rows or port in self.port_keys:
                detection['remember_s'] = 600 if (self.port_rows.get(port) or {}).get('serial') or detection.get('mac') else 15
            if port not in self.port_rows and self.port_keys.get(port):
                self.remembered[self.port_keys[port]] = (detection, None, time.monotonic())
                self.append(self.log, f'{port}: {detection["label"]} ({detection.get("source", "")}); waiting for the board to reconnect')
            if port in self.port_rows:
                self.detections[port] = detection
                self.append(self.log, f'{port}: {detection["label"]} ({detection.get("source", "")})')
                if not self.scheduler.armed and self.port_tree.selection() in ((), (port,)):
                    self.fill_form(detection)
                if port not in self.results:
                    self.set_status(f'{detection["label"]}' + (f' · {detection["name"]}' if detection.get('name') else ''), BLUE)
        elif kind == 'flashed':
            port, record, auto = value
            ok = record['result'] == 'success'
            self.results[port] = f'{record["result"].upper()} · {record.get("detail", "")}'
            self.set_status(self.results[port], GREEN if ok else AMBER if record['result'] != 'failed' else RED)
            self.monitor_off.discard(port)
            self.detections.pop(port, None)   # identify again: shows the new firmware/identity
            self.pending_detect.add(port)
            if record.get('unregistered'):
                self.refresh_info()  # registry and "local changes not published" note
            if ok and auto and self.advance.get() and record['profile'] == self.profile_key():
                points = zone_build.PROFILES[record['profile']]['points']
                later = [p for p in points if p > record['point_id']]
                if later and record['point_id'] == self.point.get():
                    self.point.set(later[0])
                    self.point_changed()
        elif kind == 'done':
            self.busy = False
            for b in self.buttons:
                b.configure(state='normal')
            self.refresh_info()
            if self.resume_monitor and value == self.resume_monitor and self.resume_monitor in self.port_rows and not self.pending_detect:
                self.monitor.connect(self.resume_monitor)
                self.resume_monitor = None
        elif kind == 'monitor':
            event, detail = value
            if event == 'connected':
                self.state.zone = self.state.nfc = None
                self.append(self.zone_log, f'Connected to {detail}')
            elif event == 'error':
                self.monitor_failed_at = time.monotonic()
                self.append(self.zone_log, 'ERROR: ' + detail)
                self.zone_info.set(detail)
            else:
                if self.monitor.port == detail:
                    self.monitor.port = None
                self.zone_info.set('Not connected.')
            self.render_monitor()
        elif kind == 'zone_line':
            if value.strip() and not value.startswith(('FW:', 'MAC:', 'CHANNEL:', 'ZONE:', 'DB:', 'STATS:', 'NFC:', 'POOL:', 'READY')):
                self.append(self.zone_log, value)
            if value.startswith('DB UPDATE: committed'):
                self.monitor.outbox.put('?')
            if self.state.feed(value):
                self.render_monitor()
                self.show_tap(value)

    def poll(self):
        if self.closing:
            return
        for _ in range(500):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            self.handle(kind, value)
        now = time.monotonic()
        if now - self.last_scan > 1:
            self.last_scan = now
            self.scan_ports()
        if not self.busy:
            waiting = next((p for p in self.pending_detect if p in self.port_rows and p != self.monitor.port), None)
            self.pending_detect &= set(self.port_rows)
            if waiting:
                self.detect(waiting)
            else:
                if self.resume_monitor and self.resume_monitor in self.port_rows:
                    self.monitor.connect(self.resume_monitor)
                    self.resume_monitor = None
                self.auto_step()
                self.auto_connect_monitor(now)
        if self.monitor.port and now - self.last_nfc_query > 2:
            self.last_nfc_query = now
            self.monitor.outbox.put('nfc')
        if any(c.get('flashing') for c in self.state.cubes.values()):
            self.render_monitor()
        self.root.after(100, self.poll)

    def close(self):
        self.closing = True
        self.monitor.disconnect()
        self.root.destroy()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    root = tk.Tk()
    App(root, args.database)
    root.mainloop()
