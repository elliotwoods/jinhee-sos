"""A zone plate on USB: the cube monitor (MonitorState) plus the plate's serial console."""
import paths  # noqa: F401
import json
import re

from linetransport import LineTransport
from zone_monitor import MonitorState
import sightings
import zonedb

from sessions.base import Session

STATS = re.compile(r'^STATS: tags=(\d+) unknown=(\d+) send_fail=(\d+) error=(\d+)')
CUBE_COMMANDS = ('flash', 'clear', 'zone', 'stop', 'cube')
CONSOLE_COMMANDS = ('?', 'nfc', 'nfc recover', 'rfcfg', 'rxgain', 'db', 'log', 'help', 'flash', 'clear', 'zone', 'stop',
                    'cube', 'dist', 'CAL', 'TUNE', 'HOST', 'RAW', 'DESERT')


class ZoneConsoleSession(Session):
    kind = 'zone'
    rules_role = 'zone'
    REPORT_EVERY = 5.0
    SILENCE = 20.0

    def __init__(self, hub, device):
        super().__init__(hub, device)
        self.transport = hub.make_transport("line", self)
        self.state = MonitorState(clock=hub.wall)
        self.stats = {}
        self.last_report = 0.0
        self.db_lines = []       # `db` command output
        self.log_lines = []      # `log` command output
        self.rfcfg = None
        self.collecting = None

    def open(self):
        self.transport.open(self.device.port)
        now = self.clock()
        self.opened_at = self.last_rx = now
        self.send('?')
        self.last_report = now

    def close(self, reason='closed'):
        super().close(reason)
        self.transport.close()

    def send(self, line):
        self.transport.send(line)
        self.saw(line, 'tx')

    def console(self, line):
        line = line.strip()
        if not line:
            raise ValueError('Type a command first (try help)')
        first = line.split()[0]
        if not any(line.startswith(c) for c in CONSOLE_COMMANDS):
            raise ValueError(f'"{first}" is not a zone console command (try help)')
        if line == 'db':
            self.db_lines, self.collecting = [], 'db'
        elif line == 'log':
            self.log_lines, self.collecting = [], 'log'
        self.send(line)
        if first in CUBE_COMMANDS:
            parts = line.split()
            self.state.command_sent(first, int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None)

    def cube_command(self, command, cube_id, value=None):
        """flash <id> [s] | clear <id> | zone <id> <0-4> | stop"""
        if command == 'stop':
            self.console('stop')
        elif command == 'zone':
            self.console(f'zone {int(cube_id)} {int(value)}')
        elif command == 'flash':
            self.console(f'flash {int(cube_id)} {int(value or 5)}')
        elif command == 'clear':
            self.console(f'clear {int(cube_id)}')
        else:
            raise ValueError('Unknown cube command')

    def stop_active(self):
        if self.transport.is_open:
            self.send('stop')

    def handle(self, line):
        tag = self.saw(line)
        if self.collecting == 'db':
            if line.startswith('CUBE '):
                self.db_lines.append(line)
            elif line.startswith('DB END'):
                self.db_lines.append(line)
                self.collecting = None
        elif self.collecting == 'log':
            if line.startswith('TAG '):
                self.log_lines.append(line)
            elif line.startswith('LOG END'):
                self.log_lines.append(line)
                self.collecting = None
        match = STATS.match(line)
        if match:
            self.stats = dict(tags=int(match[1]), unknown=int(match[2]), send_fail=int(match[3]), error=int(match[4]),
                              at=self.hub.wall())
        if line.startswith('RFCFG:'):
            self.rfcfg = line[6:].strip()
        changed = self.state.feed(line)
        if changed and line == 'READY' and self.state.zone:
            self.device.details = dict(self.state.zone)
            self.device.firmware = self.state.zone.get('firmware')
            if self.state.zone.get('mac'):
                self.device.mac = self.state.zone['mac']
            self.hub.zone_report(self.device, self.state.zone, self.stats)
        if tag and tag['tag'] in ('zone.db_committed', 'zone.unknown_cube', 'zone.not_acknowledged'):
            self.send('?')   # refresh DB: / STATS: straight away rather than at the next 5 s report
        if line.startswith('EVT TAG ') and self.state.current and self.state.current.get('mac') and self.device.mac:
            sightings.record(self.hub.db.conn, self.state.current['mac'], 'zone_tap',
                             f'{self.state.zone.get("name") if self.state.zone else self.device.mac} (USB monitor)')

    def pump(self):
        for _ in range(300):
            try:
                kind, value = self.transport.inbox.get_nowait()
            except Exception:
                break
            if kind == 'disconnected':
                self.hub.log(f'{self.label}: {value}', 'warn', self.device.id)
                self.hub.close_session(self, value)
                return
            self.handle(value)

    def tick(self, now):
        super().tick(now)
        if self.transport.is_open and now - self.last_report >= self.REPORT_EVERY:
            self.last_report = now
            self.send('?')

    def snapshot(self):
        s = self.state
        text, level = s.reader_text()
        cubes = {}
        for cube_id, cube in s.cubes.items():
            label, colour, note = s.display_zone(cube_id)
            cubes[str(cube_id)] = dict(cube, display=dict(label=label, colour=colour, note=note))
        return dict(super().snapshot(), device=self.device.id, port=self.device.port, report=s.zone, nfc=s.nfc,
                    reader=dict(text=text, level=level), current=s.current, history=list(s.history)[:100],
                    cubes=cubes, notes=[dict(t=t, text=n) for t, n in list(s.notes)[-20:]], stats=self.stats,
                    rfcfg=self.rfcfg, db_lines=self.db_lines[-60:], log_lines=self.log_lines[-12:],
                    zone_type=(s.zone or {}).get('zone_type'), zone_colors=zonedb.ZONE_COLORS)
