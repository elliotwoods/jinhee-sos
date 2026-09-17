"""Zone database / zone health window."""
import tkinter as tk
from tkinter import ttk, messagebox

from dashboard import BG, TEXT, MUTED

COLUMNS = [('name', 'Zone', 130), ('mac', 'MAC', 140), ('kind', 'Type · point', 110), ('firmware', 'Firmware', 110),
           ('db', 'Database', 150), ('staging', 'Update', 90), ('seen', 'Last seen', 80), ('tags', 'Tags / unknown / fail', 140),
           ('error', 'Last error', 180)]


class ZonesWindow:
    def __init__(self, app):
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.title('NCT · Zones')
        self.window.configure(bg=BG)
        self.window.geometry('1240x520')
        frame = ttk.Frame(self.window, padding=16)
        frame.pack(fill='both', expand=True)
        self.summary = tk.StringVar()
        ttk.Label(frame, textvariable=self.summary, font=('Helvetica', 15, 'bold')).pack(anchor='w')
        self.status = tk.StringVar()
        ttk.Label(frame, textvariable=self.status, style='Muted.TLabel').pack(anchor='w', pady=(2, 10))
        toolbar = ttk.Frame(frame)
        toolbar.pack(fill='x')
        registry = app.zones
        for label, action in [('Publish database', lambda: registry.publish()),
                              ('Stop publishing', lambda: registry.stop()),
                              ('Query zones', lambda: registry.query())]:
            self.button(toolbar, label, action, requires_station=label != 'Stop publishing').pack(side='left', padx=(0, 6))
        for label, action in [('Reboot', self.reboot), ('Show log', self.show_log), ('Identify (10 s)', self.identify)]:
            self.button(toolbar, label, action).pack(side='right', padx=(6, 0))
        self.tree = ttk.Treeview(frame, columns=[c[0] for c in COLUMNS], show='headings', height=12)
        for key, title, width in COLUMNS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor='w')
        self.tree.tag_configure('behind', foreground='#ffc16b')
        self.tree.tag_configure('current', foreground='#54d6a0')
        self.tree.tag_configure('stale', foreground=MUTED)
        self.tree.pack(fill='both', expand=True, pady=10)
        self.detail = tk.Text(frame, height=7, bg='#0b1119', fg=TEXT, relief='flat', font=('Menlo', 10), state='disabled')
        self.detail.pack(fill='x')
        self.tree.bind('<<TreeviewSelect>>', lambda _: self.render())
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.render()

    def button(self, parent, label, action, requires_station=True):
        def run():
            if requires_station:
                self.app.zones.require(self.app.controller.station, self.app.controller.connected)
            action()
        return ttk.Button(parent, text=label, command=lambda: self.app.action(run))

    def selected(self):
        selection = self.tree.selection()
        if not selection:
            raise ValueError('Select a zone first')
        return selection[0]

    def identify(self):
        self.app.zones.identify(self.selected(), 10)

    def show_log(self):
        self.app.zones.request_log(self.selected())

    def reboot(self):
        mac = self.selected()
        if messagebox.askokcancel('Reboot zone', f'Reboot zone {mac}? Tag handling pauses for a few seconds.', parent=self.window):
            self.app.zones.reboot(mac)

    def close(self):
        self.app.zones_window = None
        self.window.destroy()

    def render(self):
        registry = self.app.zones
        published = registry.store.published()
        zones = registry.zone_rows()
        current = sum(z['current'] for z in zones)
        self.summary.set(f'Published database v{published["version"]} · {published["count"]} records · '
                         f'{current}/{len(zones)} zones current')
        state = registry.publishing_state()
        self.status.set(registry.message if state or registry.message else
                        'Publish broadcasts the current mappings until every zone seen in the last 15 minutes confirms them.')
        selected = self.tree.selection()
        known = set(self.tree.get_children())
        for z in zones:
            age = z['age_s']
            values = dict(
                name=z['name'] or '—', mac=z['mac'], kind=f'{z["zone_label"]} · {z["point_id"]}', firmware=z['firmware'],
                db=f'v{z["db_version"]} · {z["db_count"]} rec · slot {"-AB"[z["active_slot"] or 0]}',
                staging=(f'v{z["staging_version"]} {z["staging_chunks"]}/{z["staging_total"]}' if z['staging_version'] else '—'),
                seen='—' if age is None else f'{int(age)} s' if age < 120 else f'{int(age // 60)} min',
                tags=f'{z["tags"]} / {z["unknown_tags"]} / {z["send_fail"]}', error=z['error_text'] or '—')
            tag = 'stale' if age is None or age > registry.RECENT_ZONE else 'current' if z['current'] else 'behind'
            row = [values[c[0]] for c in COLUMNS]
            if z['mac'] in known:
                self.tree.item(z['mac'], values=row, tags=(tag,))
            else:
                self.tree.insert('', 'end', iid=z['mac'], values=row, tags=(tag,))
        if selected and selected[0] in {z['mac'] for z in zones}:
            z = next(z for z in zones if z['mac'] == selected[0])
            lines = [f'{z["mac"]} · {z["name"]} · uptime {z["uptime"]} s · channel {z["channel"]} · config {"valid" if z["config_valid"] else "INVALID"}',
                     f'Database v{z["db_version"]} crc {z["db_crc"] or 0:08X} · published v{published["version"]} crc {published["crc"]:08X}']
            log = z['log']
            if log:
                lines.append(f'Recent tags (received {log["received"]}):')
                lines += [f'  {e["age_s"]:>5} s ago  {e["uid"]:<21} cube {e["cube_id"] or "—":<5} {e["result"]}' for e in log['entries']]
            else:
                lines.append('Use Show log to fetch recent tags from this zone.')
            text = '\n'.join(lines)
        else:
            text = 'Select a zone for details.'
        if self.detail.get('1.0', 'end-1c') != text:
            self.detail.configure(state='normal')
            self.detail.delete('1.0', 'end')
            self.detail.insert('1.0', text)
            self.detail.configure(state='disabled')
