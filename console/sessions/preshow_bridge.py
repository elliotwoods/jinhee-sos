"""The TouchDesigner media bridge: status/point/plate telemetry plus TEST cues."""
import paths  # noqa: F401
import json

from linetransport import LineTransport

from sessions.base import Session


class PreshowBridgeSession(Session):
    kind = 'preshowbridge'
    STATUS_EVERY = 2.0
    SILENCE = 10.0

    def __init__(self, hub, device):
        super().__init__(hub, device)
        self.transport = hub.make_transport("line", self)
        self.status = {}
        self.points = {}
        self.plates = {}
        self.cues = []
        self.last_status = 0.0

    def open(self):
        self.transport.open(self.device.port)
        self.opened_at = self.last_rx = self.last_status = self.clock()
        self.send('STATUS')

    def close(self, reason='closed'):
        super().close(reason)
        self.transport.close()

    def send(self, line):
        self.transport.send(line)
        self.saw(line, 'tx')

    def test(self, point, on):
        self.send(f'TEST {int(point)} {"ON" if on else "OFF"}')

    def console(self, line):
        if line.split()[0].upper() not in ('STATUS', 'TEST', 'HELP', '?'):
            raise ValueError('Bridge commands: STATUS, TEST <n> ON|OFF, help')
        self.send(line)

    def handle(self, line):
        if line.startswith('{'):
            try:
                data = json.loads(line)
            except ValueError:
                data = None
            if isinstance(data, dict):
                self.last_rx = self.clock()
                kind = data.get('type')
                if kind == 'status':
                    self.status = data
                    if data.get('mac'):
                        self.device.mac = data['mac'].upper()
                elif kind == 'point':
                    self.points[str(data.get('point'))] = data
                elif kind == 'plate':
                    self.plates[data.get('mac', '?')] = data
                return
        tag = self.saw(line)
        if tag and tag['tag'] == 'bridge.cue':
            self.cues.append(dict(t=self.hub.wall(), **tag['fields']))
            self.cues = self.cues[-50:]

    def pump(self):
        for _ in range(300):
            try:
                kind, value = self.transport.inbox.get_nowait()
            except Exception:
                break
            if kind == 'disconnected':
                self.hub.close_session(self, value)
                return
            self.handle(value)

    def tick(self, now):
        super().tick(now)
        if self.transport.is_open and now - self.last_status >= self.STATUS_EVERY:
            self.last_status = now
            self.send('STATUS')

    def snapshot(self):
        return dict(super().snapshot(), device=self.device.id, port=self.device.port, status=self.status,
                    points=self.points, plates=list(self.plates.values()), cues=self.cues[-20:])
