"""Turns a zone board's serial output into cube-monitor state (current cube on the plate + history)."""
import re
import time
from collections import deque

import zonedb
from zone_flash import parse_report

EVT = re.compile(r'^EVT (\w+) (.*)$')


def fields(text):
    return dict(part.split('=', 1) for part in text.split() if '=' in part)


class MonitorState:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.current = None        # dict(uid, cube_id, mac, zone, state, since)
        self.history = deque(maxlen=300)
        self.cubes = {}            # cube_id -> dict(mac, uid, taps, last_seen, zone, zone_ok, flashing)
        self.zone = None           # parsed "?" report
        self.notes = deque(maxlen=50)
        self.nfc = None            # live reader health from the zone's "NFC:" line
        self._report = ''

    def _cube(self, cube_id, **values):
        cube = self.cubes.setdefault(cube_id, dict(cube_id=cube_id, mac=None, uid=None, taps=0, last_seen=None, zone=None,
                                                  zone_ok=None, flashing=False))
        cube.update(values)
        return cube

    def feed(self, line):
        """Returns True when the display should refresh."""
        line = line.strip()
        if not line:
            return False
        now = self.clock()
        if line.startswith('NFC:'):
            data = fields(line[4:])
            try:
                self.nfc = dict(ok=data.get('ok') == '1', polls=int(data.get('polls', 0)), found=int(data.get('found', 0)),
                                last_ms=int(data.get('last_ms', 0)), fast_fail=int(data.get('fast_fail', 0)),
                                recoveries=int(data.get('recoveries', 0)), sda=data.get('sda'), scl=data.get('scl'), time=now)
            except ValueError:
                return False
            if self._report:
                self._report += line + '\n'
            return True
        if line.startswith(('FW:', 'MAC:', 'CHANNEL:', 'ZONE:', 'DB:', 'STATS:', 'POOL:', 'STAGING:', 'READY')):
            self._report += line + '\n'
            if line == 'READY':
                self.zone = parse_report(self._report) or self.zone
                self._report = ''
                return True
            return False
        if line.startswith('DB UPDATE:'):
            self.notes.append((now, line))
            return True
        match = EVT.match(line)
        if not match:
            return False
        kind, data = match[1], fields(match[2])
        if kind == 'TAG':
            cube_id = int(data.get('cube', 0))
            entry = dict(time=now, uid=data.get('uid', ''), cube_id=cube_id or None, mac=None if data.get('mac') == '-' else data.get('mac'),
                         zone=int(data.get('zone', 0)), state='pending' if cube_id else 'unknown tag', held_ms=None)
            self.current = entry
            self.history.appendleft(entry)
            if cube_id:
                cube = self._cube(cube_id, mac=entry['mac'], uid=entry['uid'], last_seen=now)
                cube['taps'] += 1
        elif kind == 'SENT':
            cube_id, ok, value = int(data['cube']), data.get('ok') == '1', int(data.get('value', 0))
            if int(data.get('type', 0)) == 6:
                self._cube(cube_id, zone=value, zone_ok=ok)
                entry = next((h for h in self.history if h['cube_id'] == cube_id and h['state'] == 'pending' and h['zone'] == value), None)
                if entry:
                    entry['state'] = 'delivered' if ok else 'not acknowledged'
        elif kind == 'LEAVE':
            entry = next((h for h in self.history if h['uid'] == data.get('uid') and h['held_ms'] is None), None)
            if entry:
                entry['held_ms'] = int(data.get('held_ms', 0))
                if entry['state'] == 'pending':  # the zone never reported a delivery result for this tap
                    entry['state'] = 'not acknowledged'
            if self.current and self.current['uid'] == data.get('uid'):
                self.current = None
        elif kind == 'FLASH':
            self._cube(int(data['cube']), flashing=False)
        else:
            return False
        return True

    def command_sent(self, command, cube_id):
        if command == 'flash':
            self._cube(cube_id, flashing=True)
        elif command in ('clear', 'zone', 'stop'):
            self._cube(cube_id, flashing=False) if cube_id else [c.update(flashing=False) for c in self.cubes.values()]

    def reader_text(self):
        """(text, level) describing the zone's NFC reader, level in ok|warn|bad."""
        n = self.nfc
        if not n:
            return 'NFC reader: no status yet', 'warn'
        if not n['ok']:
            lines = '' if (n['sda'], n['scl']) == ('1', '1') else f' · I2C lines SDA={n["sda"]} SCL={n["scl"]} (should both be 1)'
            return f'NFC reader NOT RESPONDING · recovering automatically (attempt {n["recoveries"]}){lines}', 'bad'
        if n['fast_fail']:
            return f'NFC reader answering, but {n["fast_fail"]} scan commands failed on I2C · {n["polls"]} scans, {n["found"]} with a tag', 'warn'
        return (f'NFC reader scanning normally · {n["polls"]} scans, {n["found"]} with a tag in the field · last scan {n["last_ms"]} ms' +
                (f' · recovered {n["recoveries"]}×' if n['recoveries'] else '')), 'ok'

    def display_zone(self, cube_id):
        """(label, colour, note) of what the cube should be showing, from acknowledged commands."""
        cube = self.cubes.get(cube_id)
        if not cube or cube['zone'] is None:
            return 'unknown', '#536174', 'no command sent yet'
        label, colour = zonedb.ZONE_COLORS.get(cube['zone'], ('?', '#536174'))
        if cube['flashing']:
            return 'flashing', colour, 'test flash running'
        return label, colour if cube['zone_ok'] else '#536174', 'cube acknowledged' if cube['zone_ok'] else 'NOT acknowledged by cube'
