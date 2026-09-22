"""An ESP-NOW range-test board (RX unit): telemetry only, nothing is written to disk."""
import paths  # noqa: F401
from collections import deque

from linetransport import LineTransport

from sessions.base import Session

COMMANDS = ('STATUS', 'ROLE', 'RATE', 'SLEEP', 'VERBOSE', 'MUTE', 'LEDS', 'MARK', 'REBOOT', 'RESET', 'CHANNEL')


def parse_fields(line):
    return {k: v for k, _, v in (t.partition('=') for t in line.split()) if k and v}


def number(fields, key, default=None):
    try:
        return float(fields[key])
    except (KeyError, ValueError, TypeError):
        return default


class RangeTestSession(Session):
    kind = 'rangetest'
    SILENCE = 15.0

    def __init__(self, hub, device):
        super().__init__(hub, device)
        self.transport = hub.make_transport("line", self)
        self.stat = {}
        self.banner = {}
        self.pixels = ['000000'] * 8
        self.packets = deque(maxlen=60 * 25)
        self.samples = deque(maxlen=1800 + 60)
        self.marks = []

    def open(self):
        self.transport.open(self.device.port)
        self.opened_at = self.last_rx = self.clock()
        for command in ('VERBOSE ON', 'LEDS ON', 'STATUS'):
            self.send(command)

    def close(self, reason='closed'):
        super().close(reason)
        if self.transport.is_open:
            self.transport.close(farewell='LEDS OFF')
        else:
            self.transport.close()

    def send(self, line):
        self.transport.send(line)
        self.saw(line, 'tx')

    def console(self, line):
        if line.split()[0].upper() not in COMMANDS:
            raise ValueError('Range test commands: ' + ', '.join(COMMANDS))
        self.send(line)
        if line.upper().startswith('MARK'):
            self.marks.append(dict(t=self.hub.wall(), label=line[5:].strip()))

    def handle(self, line):
        now = self.hub.wall()
        self.saw(line)
        if line.startswith('STAT '):
            self.stat = parse_fields(line)
            loss = number(self.stat, 'loss_pct')
            if loss is not None:
                self.samples.append((now, loss, number(self.stat, 'rssi_avg'), number(self.stat, 'nf_avg')))
        elif line.startswith('PKT '):
            fields = parse_fields(line)
            rssi = number(fields, 'rssi')
            if rssi is not None and rssi != 127:
                self.packets.append((now, rssi, number(fields, 'nf'), number(fields, 'gap', 0)))
        elif line.startswith('LEDS '):
            parts = parse_fields(line).get('px', '').split(',')
            if len(parts) == 8:
                self.pixels = parts
        elif ':' in line and not line.startswith('='):
            key, _, value = line.partition(':')
            self.banner[key.strip()] = value.strip()
            if key.strip().upper() == 'MAC' and len(value.strip()) == 17:
                self.device.mac = value.strip().upper()

    def pump(self):
        for _ in range(600):
            try:
                kind, value = self.transport.inbox.get_nowait()
            except Exception:
                break
            if kind == 'disconnected':
                self.hub.close_session(self, value)
                return
            self.handle(value)

    def snapshot(self):
        return dict(super().snapshot(), device=self.device.id, port=self.device.port, stat=self.stat, banner=self.banner,
                    pixels=self.pixels, packets=[list(p) for p in list(self.packets)[-300:]],
                    samples=[list(s) for s in list(self.samples)[-1860:]], marks=self.marks[-20:])
