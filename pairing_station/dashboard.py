"""Device grid and detail inspector; displayed LEDs are command estimates."""
import math
import time
import tkinter as tk
from tkinter import ttk
from database import Database

ORIGINAL_NUMBERS = {r["mac"]: r["cube_id"] for r in Database.originals()}

BG = '#101720'
CARD = '#1b2633'
TEXT = '#e9f0f7'
MUTED = '#a5b5c8'
COLORS = {'needs_number': '#a5b5c8', 'acknowledged': '#54d6a0', 'unconfirmed': '#ffc16b', 'pending': '#c9a0ff',
          'not_transmitted': '#82b8fa', 'awaiting_tag': '#c9a0ff', 'discovered': '#a5b5c8'}
LABELS = {'needs_number': 'Needs number', 'acknowledged': 'Registered · ACK', 'unconfirmed': 'Unconfirmed', 'pending': 'Registering',
          'not_transmitted': 'Saved · not sent', 'awaiting_tag': 'Needs NFC tag', 'discovered': 'Unregistered'}


def inventory(app):
    c = app.controller
    rows = {r['mac']: dict(r) for r in app.db.rows()}
    for mac in set(c.discovered) | set(app.db.roles()):
        rows.setdefault(mac, dict(mac=mac, cube_id=None, uid=None, pending_uid=None,
                                  status='discovered', source='radio', detail='', updated_at='—'))
    roles = app.db.roles()
    now = c.clock()
    nfc_seen = {r[0] for r in app.db.conn.execute("SELECT DISTINCT mac FROM events WHERE action='nfc_seen'")}
    for mac, row in rows.items():
        age = now - c.discovered[mac] if mac in c.discovered else None
        row['usb_firmware'] = getattr(app, 'usb_firmware', {}).get(mac)
        row.update(original_number=ORIGINAL_NUMBERS.get(mac), nfc_seen=mac in nfc_seen, age=age, recent=c.connected and age is not None and age < 10,
                   role=roles.get(mac, 'auto'), telemetry=c.telemetry.get(mac, {}))
        row['kind'] = ('Reader / base · excluded' if row['role'] == 'excluded' else
                       'LED · manually assigned' if row['role'] == 'led' else
                       'Cube protocol responder' if age is not None else 'Saved cube mapping')
    return sorted(rows.values(), key=lambda r: (r['cube_id'] is None, r['cube_id'] or 0, r['mac']))


def matches(row, choice, query):
    if choice != 'All incl. excluded' and row['role'] == 'excluded': return False
    if choice == 'Seen recently' and not row['recent']: return False
    if choice == 'Has original number and connected' and (row.get('original_number') is None or not row['recent']): return False
    if choice == 'Registered (ACK)' and row['status'] != 'acknowledged': return False
    if choice == 'Unregistered' and (row['uid'] or row['pending_uid']): return False
    if choice == 'Needs attention' and row['status'] not in ('unconfirmed', 'pending', 'not_transmitted'): return False
    return query.lower() in ' '.join(str(row.get(k) or '') for k in ('mac', 'cube_id', 'original_number', 'uid', 'pending_uid')).lower()


def led_state(row, connected):
    t = row['telemetry']
    if not connected or not t.get('command'): return 'Unknown LEDs', '#637184'
    if t['command'] == 'identify':
        return 'Flash command', '#ff647d' if int(time.monotonic()*2) % 2 else '#559dff'
    if t['command'] == 'register': return 'Register command', '#c9a0ff'
    return 'Static command', '#e4edf6'


class Dashboard:
    def __init__(self, app):
        self.app = app
        self.selected_mac = None
        self.last_render = 0
        self.last_feedback_token = None
        self.rows = []
        self.hitboxes = []
        root = app.root
        root.configure(bg=BG)
        root.geometry('1380x940')
        root.minsize(1120, 820)
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('.', font=('Helvetica', 11), background=BG, foreground=TEXT)
        style.configure('TFrame', background=BG)
        style.configure('TLabel', background=BG, foreground=TEXT)
        style.configure('Title.TLabel', font=('Helvetica', 25, 'bold'))
        style.configure('Muted.TLabel', foreground=MUTED)
        style.configure('TButton', padding=(10, 7), background='#263749', borderwidth=0)
        style.map('TButton', background=[('active', '#39536e'), ('disabled', '#19232e')],
                  foreground=[('disabled', '#65778a')])
        style.configure('Register.TButton', font=('Helvetica', 14, 'bold'), padding=(14, 13),
                        background='#2879e8', foreground='white')
        style.map('Register.TButton', background=[('disabled','#243749'),('active','#4594ff'),('!disabled','#2879e8')],
                  foreground=[('disabled','#8496aa'),('!disabled','white')])
        style.configure('TCombobox', fieldbackground='#263749', foreground=TEXT, arrowcolor=TEXT)
        style.map('TCombobox', fieldbackground=[('readonly', '#263749')], foreground=[('readonly', TEXT)])
        style.configure('TEntry', fieldbackground='#263749', foreground=TEXT)
        frame = ttk.Frame(root, padding=20)
        frame.pack(fill='both', expand=True)
        header = ttk.Frame(frame); header.pack(fill='x')
        ttk.Label(header, text='NEOCORE / DEVICE STUDIO', style='Title.TLabel').pack(side='left')
        self.summary = tk.StringVar()
        ttk.Label(header, textvariable=self.summary, foreground='#54d6a0').pack(side='right')
        intro = ttk.Frame(frame); intro.pack(fill='x', pady=(5, 12))
        ttk.Label(intro, text='Select a device to inspect, identify with lights, or pair its NFC tag.', style='Muted.TLabel').pack(side='left')
        self.auto_flash = tk.BooleanVar(value=True)
        ttk.Checkbutton(intro, text='Auto-flash selection (1s)', variable=self.auto_flash,
                        command=self.toggle_auto_flash).pack(side='right')
        connection = ttk.Frame(frame); connection.pack(fill='x')
        app.port = tk.StringVar()
        app.ports = ttk.Combobox(connection, textvariable=app.port, width=27, state='readonly')
        app.ports.pack(side='left')
        for label, action in [('Refresh ports', app.refresh_ports), ('Connect', app.connect), ('Disconnect', app.disconnect)]:
            self.button(connection, label, action).pack(side='left', padx=4)
        app.connection = tk.StringVar()
        ttk.Label(connection, textvariable=app.connection, foreground='#82b8fa').pack(side='left', padx=10)
        usb_row = ttk.Frame(frame); usb_row.pack(fill='x', pady=(8, 0))
        self.usb_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(usb_row, text='Identify cubes over USB', variable=self.usb_enabled,
                        command=lambda: app.action(app.toggle_usb_identification)).pack(side='left')
        self.usb_status = tk.StringVar(value='USB identification off')
        ttk.Label(usb_row, textvariable=self.usb_status, style='Muted.TLabel').pack(side='left', padx=10)
        self.unlock_button = self.button(usb_row, 'Unlock selection', app.unlock_usb)
        self.unlock_button.pack(side='right')
        app.status = tk.StringVar()
        self.banner = tk.Label(frame, textvariable=app.status, wraplength=1200, font=('Helvetica', 12, 'bold'),
                               bg='#1b2633', fg=TEXT, anchor='w', justify='left', padx=12, pady=8)
        self.banner.pack(fill='x', pady=(10, 4))
        self.station_status = tk.StringVar()
        ttk.Label(frame, textvariable=self.station_status, style='Muted.TLabel').pack(anchor='w', pady=(0, 12))
        toolbar = ttk.Frame(frame); toolbar.pack(fill='x', pady=4)
        self.idle_buttons = []
        self.reader_buttons = []
        for label, action, reader in [('Discover now', app.controller.discover, False),
                ('Auto-pair new', app.controller.start_pair, True),
                ('Transmit existing 32', lambda: app.controller.transmit([r for r in app.db.original_batch() if not app.db.excluded(r['mac'])]), False),
                ('Retry unconfirmed', lambda: app.controller.transmit([r for r in app.db.rows() if r['status']=='unconfirmed' and not app.db.excluded(r['mac'])]), False),
                ('Flash all in grid', self.flash_visible, False)]:
            b = self.button(toolbar, label, action); b.pack(side='left', padx=(0, 6))
            (self.reader_buttons if reader else self.idle_buttons).append(b)
        self.button(toolbar, '■ Stop / static', app.controller.stop).pack(side='right')
        filters = ttk.Frame(frame); filters.pack(fill='x', pady=10)
        self.filter = tk.StringVar(value='LED candidates')
        ttk.Combobox(filters, state='readonly', textvariable=self.filter, width=34,
            values=['LED candidates', 'Seen recently', 'Has original number and connected', 'Registered (ACK)', 'Unregistered', 'Needs attention', 'All incl. excluded']).pack(side='left')
        ttk.Label(filters, text='  Search ID / MAC / UID  ', style='Muted.TLabel').pack(side='left')
        self.search = tk.StringVar()
        ttk.Entry(filters, textvariable=self.search, width=25).pack(side='left')
        for label, color in [('○ Not seen', MUTED), ('● Attention  ', '#ffc16b'), ('● Saved  ', '#82b8fa'), ('● ACK  ', '#54d6a0')]:
            ttk.Label(filters, text=label, foreground=color).pack(side='right')
        middle = ttk.Frame(frame); middle.pack(fill='both', expand=True)
        grid_frame = ttk.Frame(middle); grid_frame.pack(side='left', fill='both', expand=True)
        self.canvas = tk.Canvas(grid_frame, bg=BG, highlightthickness=0, width=760, height=360)
        scroll = ttk.Scrollbar(grid_frame, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y'); self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Button-1>', self.click)
        self.canvas.bind('<MouseWheel>', lambda e: self.canvas.yview_scroll(-int(e.delta), 'units'))
        self.canvas.bind('<Key-Right>', lambda e: self.move(1))
        self.canvas.bind('<Key-Left>', lambda e: self.move(-1))
        self.canvas.configure(takefocus=True)
        inspector = ttk.Frame(middle, padding=(18, 0, 0, 0), width=345)
        inspector.pack(side='right', fill='y'); inspector.pack_propagate(False)
        self.detail_title = tk.StringVar(value='Select a device')
        ttk.Label(inspector, textvariable=self.detail_title, font=('Helvetica', 20, 'bold')).pack(anchor='w')
        detail_frame = ttk.Frame(inspector)
        detail_frame.pack(fill='both', expand=True, pady=8)
        self.detail = tk.Text(detail_frame, bg=BG, fg=TEXT, relief='flat', borderwidth=0, highlightthickness=0,
                              font=('Menlo', 10), wrap='word', height=6, state='disabled')
        detail_scroll = ttk.Scrollbar(detail_frame, command=self.detail.yview)
        self.detail.configure(yscrollcommand=detail_scroll.set)
        detail_scroll.pack(side='right', fill='y')
        self.detail.pack(fill='both', expand=True)
        self.selected_buttons = []
        for label, callback in [('REGISTER DEVICE', app.repair),
                                ('Transmit saved mapping', lambda: app.controller.transmit([app.selected_registered()])),
                                ('Flash selected', lambda: app.controller.flash([app.selected()]))]:
            b=self.button(inspector, label, callback)
            if not self.selected_buttons: b.configure(style='Register.TButton')
            b.pack(fill='x', pady=3); self.selected_buttons.append(b)
        self.registration_hint = tk.StringVar()
        ttk.Label(inspector, textvariable=self.registration_hint, wraplength=310, style='Muted.TLabel').pack(fill='x', pady=(0,4))
        self.rename_button = self.button(inspector, 'Rename device…', app.rename)
        self.rename_button.pack(fill='x', pady=3)
        row = ttk.Frame(inspector); row.pack(fill='x', pady=3)
        self.retry_button = self.button(row, 'Retry paused', app.controller.retry); self.retry_button.pack(side='left', expand=True, fill='x')
        self.skip_button = self.button(row, 'Skip', app.controller.skip); self.skip_button.pack(side='left', expand=True, fill='x', padx=(6,0))
        ttk.Label(inspector, text='Device role override', style='Muted.TLabel').pack(anchor='w', pady=(8,3))
        role_row = ttk.Frame(inspector); role_row.pack(fill='x')
        self.role = tk.StringVar(value='Auto / protocol')
        self.roles = {'Auto / protocol':'auto', 'LED module':'led', 'Reader / base station':'excluded'}
        ttk.Combobox(role_row, textvariable=self.role, values=list(self.roles), state='readonly', width=21).pack(side='left', fill='x', expand=True)
        self.role_button=self.button(role_row, 'Save', self.save_role); self.role_button.pack(side='right', padx=(6,0))
        footer = ttk.Frame(frame); footer.pack(fill='x', pady=(10,6))
        app.progress = tk.StringVar()
        ttk.Label(footer, textvariable=app.progress, style='Muted.TLabel').pack(side='left')
        app.web_label = ttk.Label(footer, style='Muted.TLabel'); app.web_label.pack(side='left', padx=(14,0))
        self.button(footer, 'Zones…', app.open_zones).pack(side='right', padx=(6,0))
        self.button(footer, 'Export reader table', app.export_header).pack(side='right')
        self.button(footer, 'Export CSV', app.export_csv).pack(side='right', padx=6)
        ttk.Label(frame, text='LED rings show commands, not measured light output. Discovery identifies protocol compatibility, not exact firmware.', style='Muted.TLabel').pack(anchor='w')
        app.logbox = tk.Text(frame, height=5, bg='#0b1119', fg=MUTED, insertbackground=TEXT,
                             relief='flat', highlightthickness=0, state='disabled', wrap='word', font=('Menlo', 10))
        app.logbox.pack(fill='x', pady=(8,0))
        self.filter.trace_add('write', lambda *_: self.reset_scroll())
        self.search.trace_add('write', lambda *_: self.reset_scroll())

    def button(self, parent, label, callback):
        return ttk.Button(parent, text=label, command=lambda: self.app.action(callback))

    def reset_scroll(self):
        self.canvas.yview_moveto(0)
        self.render(force=True)

    def click(self, event):
        self.canvas.focus_set()
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        for a,b,c,d,mac in self.hitboxes:
            if a <= x <= c and b <= y <= d:
                self.select(mac); break

    def move(self, delta):
        if not self.rows: return
        ids = [r['mac'] for r in self.rows]
        index = ids.index(self.selected_mac) if self.selected_mac in ids else 0
        self.select(ids[max(0, min(len(ids)-1, index+delta))])

    def select(self, mac):
        locked = self.app.usb_locked_mac
        if locked and mac != locked:
            self.usb_status.set('Selection pinned by USB · click Unlock selection to choose another device')
            return
        changed = mac != self.selected_mac
        self.selected_mac = mac
        role = self.app.db.roles().get(mac, 'auto')
        self.role.set(next(k for k,v in self.roles.items() if v == role))
        if changed and self.auto_flash.get():
            try:
                self.app.controller.preview(mac)
            except Exception as exc:
                self.app.log('Selection flash failed: '+str(exc))
        self.render(force=True)

    def toggle_auto_flash(self):
        if not self.auto_flash.get() and self.app.controller.mode == 'preview':
            self.app.action(self.app.controller.stop)

    def save_role(self):
        row = self.app.selected()
        if self.app.controller.mode: raise ValueError('Stop the current operation before changing device roles')
        self.app.db.set_role(row['mac'], self.roles[self.role.get()])
        self.app.log(f"Device role saved: {row['mac']} → {self.role.get()}")

    def flash_visible(self):
        self.app.controller.flash([r for r in self.rows if r['role'] != 'excluded'], sequential=True)

    def render(self, force=False):
        now = time.monotonic()
        if not force and now-self.last_render < .25: return
        self.last_render = now
        app, c = self.app, self.app.controller
        all_rows = inventory(app)
        locked = app.usb_locked_mac
        self.rows = [r for r in all_rows if r['mac']==locked or matches(r, self.filter.get(), self.search.get())]
        self.rows.sort(key=lambda r: r['mac'] != locked)
        self.unlock_button.configure(state='normal' if locked else 'disabled')
        feedback = c.feedback
        app.status.set(feedback['title']+'\n'+feedback['detail'] if feedback else c.message)
        self.banner.configure(bg={'scan':'#243d60','sending':'#51401d','success':'#174c39','error':'#652d35'}.get(feedback.get('kind'), CARD),
                              wraplength=max(700, app.root.winfo_width()-80))
        if feedback.get('token') != self.last_feedback_token:
            self.last_feedback_token = feedback.get('token')
            if feedback.get('kind') == 'success': app.root.bell()
        app.connection.set(('● Connected   /   NFC '+('ready' if c.reader_ok else 'unavailable')) if c.connected else '○ Disconnected')
        seen = sum(r['recent'] for r in all_rows)
        ack = sum(r['status']=='acknowledged' for r in all_rows)
        unreg = sum(not (r['uid'] or r['pending_uid']) for r in all_rows if r['role']!='excluded')
        self.summary.set(f'{seen} RECENT    /    {ack} ACK    /    {unreg} UNREGISTERED')
        s = c.station
        rx = f'{int(now-app.last_rx)}s ago' if app.last_rx else 'never'
        self.station_status.set(f"Station {s.get('mac','—')}   ·   Channel {s.get('channel','—')}   ·   Tag {'present / remove to arm' if c.tag_present else 'clear'}   ·   USB RX {rx}   ·   {c.phase or 'Idle'}")
        app.progress.set(f'{len(self.rows)} shown / {len(all_rows)} known · {len(c.discovered)} discovered this session' + (f' · {c.progress}/{c.total}' if c.mode in ('bulk','flash_all') else '') + (' · CSV export failed' if app.db.export_error else ''))
        canvas=self.canvas; canvas.delete('all'); self.hitboxes=[]
        width=max(canvas.winfo_width(), 400); columns=max(2, width//192)
        tile=(width-12)/columns; height=190
        for i,row in enumerate(self.rows):
            x=(i%columns)*tile+3; y=(i//columns)*height+3
            selected=row['mac']==self.selected_mac
            active=bool(c.active and c.active['mac']==row['mac'])
            color='#68788b' if row['role']=='excluded' else COLORS.get(row['status'],MUTED)
            canvas.create_rectangle(x,y,x+tile-10,y+height-10,fill='#24364a' if selected else CARD,
                                    outline='#92c5ff' if selected else '#c9a0ff' if active else '#2a3849',width=2 if selected or active else 1)
            canvas.create_rectangle(x,y,x+4,y+height-10,fill=color,outline='')
            title=f"Neocore {row['cube_id']:02}" if row['cube_id'] else 'New device'
            if row['mac']==locked: title='📌 '+title
            canvas.create_text(x+14,y+17,text=title,anchor='w',fill=TEXT,font=('Helvetica',13,'bold'))
            canvas.create_oval(x+tile-32,y+12,x+tile-24,y+20,fill='#54d6a0' if row['recent'] else '#536174',outline='')
            label, led = led_state(row,c.connected)
            for k in range(8):
                angle=k*math.pi/4
                cx=x+34+math.cos(angle)*17; cy=y+58+math.sin(angle)*17
                canvas.create_oval(cx-3,cy-3,cx+3,cy+3,fill=led,outline='')
            canvas.create_text(x+65,y+49,text=LABELS.get(row['status'],row['status']) if row['role']!='excluded' else 'Excluded',anchor='w',fill=color,font=('Helvetica',10))
            canvas.create_text(x+65,y+67,text=label,anchor='w',fill=MUTED,font=('Helvetica',9))
            canvas.create_text(x+14,y+96,text=row['mac'],anchor='w',fill=TEXT,font=('Menlo',10))
            age='Not seen' if row['age'] is None else f"Seen {int(row['age'])}s ago"
            canvas.create_text(x+14,y+119,text=('● ACTIVE  ·  ' if active else '')+age,anchor='w',fill=MUTED,font=('Helvetica',10))
            if row['original_number'] is not None:
                original = f"Original #{row['original_number']} · " + ('NFC scanned' if row['nfc_seen'] else 'NFC unseen')
                canvas.create_text(x+14,y+143,text=original,anchor='w',fill=MUTED if row['nfc_seen'] else '#ffc16b',font=('Helvetica',9))
            if row.get('usb_firmware'):
                fw=row['usb_firmware']
                canvas.create_text(x+14,y+165,text='Firmware: '+fw['status'],anchor='w',fill='#54d6a0' if fw['status']=='current' else '#ffc16b',font=('Helvetica',10))
            self.hitboxes.append((x,y,x+tile-10,y+height-10,row['mac']))
        if not self.rows:
            canvas.create_text(width/2,80,text='No devices match this view.\nTry Discover now or change the filter.',fill=MUTED,font=('Helvetica',14),justify='center')
        canvas.configure(scrollregion=(0,0,width,max(height*math.ceil(len(self.rows)/columns),160)))
        row = next((r for r in all_rows if r['mac']==self.selected_mac), None)
        idle=c.connected and not c.mode
        for b in self.idle_buttons: b.configure(state='normal' if idle else 'disabled')
        for b in self.reader_buttons: b.configure(state='normal' if idle and c.reader_ok else 'disabled')
        usable=idle and row and row['role']!='excluded'
        for i,b in enumerate(self.selected_buttons):
            if i == 0:
                enabled = c.connected and c.reader_ok and row and row['role']!='excluded' and (not c.mode or (c.mode=='preview' and c.phase=='flashing'))
            else:
                enabled=usable and (bool(row['cube_id'] is not None and (row['uid'] or row['pending_uid'])) if i==1 else True)
            b.configure(state='normal' if enabled else 'disabled')
        reason = ('Connect the NFC station to register. Cube USB identification alone is not enough.' if not c.connected else
                  'NFC reader is unavailable; check the station/reader connection.' if not c.reader_ok else
                  'Select a device to register.' if not row else
                  'This device is excluded as a reader/base station.' if row['role']=='excluded' else
                  'An operation is active. Use Stop / static before registering.' if c.mode and not (c.mode=='preview' and c.phase=='flashing') else '')
        self.registration_hint.set(reason)
        self.rename_button.configure(state='normal' if row and row['role']!='excluded' and (not row['pending_uid'] or row['cube_id'] is None) and (not c.mode or (c.mode=='preview' and c.phase=='flashing')) else 'disabled')
        self.role_button.configure(state='normal' if row and not c.mode else 'disabled')
        self.retry_button.configure(state='normal' if c.phase=='paused' else 'disabled')
        self.skip_button.configure(state='normal' if c.mode in ('pair','repair') else 'disabled')
        if row:
            self.detail_title.set(f"Neocore {row['cube_id']:02}" if row['cube_id'] else 'Unnumbered device')
            t=row['telemetry']; age='Never in this session' if row['age'] is None else f"{int(row['age'])} seconds ago"
            original = f"#{row['original_number']} (original hardcoded table)" if row['original_number'] is not None else 'No original table entry'
            scan = 'Scanned at this station' if row['nfc_seen'] else 'Not yet scanned at this station'
            firmware = row.get('usb_firmware')
            firmware_detail = (f"USB FIRMWARE\nReported: {firmware.get('version') or 'Unknown'}\nLatest local build: {firmware.get('expected') or 'Unknown'}\nStatus: {firmware['status']}\n{firmware['detail']}\n\n" if firmware else '')
            detail=firmware_detail+f"NUMBERS / NFC HISTORY\nAssigned: {row['cube_id'] or 'None'}\nOriginal: {original}\n{scan}\n\nMAC\n{row['mac']}\n\nCLASSIFICATION\n{row['kind']}\n\nREGISTRATION\n{LABELS.get(row['status'],row['status'])}\nUID: {row['uid'] or '—'}\nPending: {row['pending_uid'] or '—'}\n\nRADIO / LIGHTS\nDiscovery: {age}\nLast delivery: {t.get('delivery','unknown')}\nLED: {led_state(row,c.connected)[0]}\n\nDATABASE\nSource: {row['source']}\nUpdated: {row['updated_at']}\n{row['detail']}"
        else:
            self.detail_title.set('Select a device')
            detail='Click a card to inspect its MAC address, NFC mapping, radio delivery and LED command.\n\nGreen means a registration ACK was received. Amber needs attention. Grey radio dots mean no recent discovery reply.\n\nReaders which do not answer cube discovery never appear here. Exact firmware and physical LED state are not reported by the legacy protocol.'
        if self.detail.get('1.0','end-1c') != detail:
            self.detail.configure(state='normal'); self.detail.delete('1.0','end'); self.detail.insert('1.0',detail); self.detail.configure(state='disabled')
