"""The pool central controller: passive status telemetry plus explicit RECOVER / OUT commands."""
import paths  # noqa: F401
import json

from linetransport import LineTransport

from sessions.base import Session


class PoolCentralSession(Session):
    kind = 'poolcentral'
    SILENCE = 6.0

    def __init__(self, hub, device):
        super().__init__(hub, device)
        self.transport = hub.make_transport("line", self)
        self.status = {}
        self.radios = {}
        self.last_status = 0.0

    def open(self):
        self.transport.open(self.device.port)
        self.opened_at = self.last_rx = self.clock()
        self.send('STATUS')

    def close(self, reason='closed'):
        super().close(reason)
        self.transport.close()

    def send(self, line):
        self.transport.send(line)
        self.saw(line, 'tx')

    def console(self, line):
        if not line.split()[0].upper() in ('STATUS', 'RECOVER', 'OUT', 'TEST_SLEEP'):
            raise ValueError('Pool central commands: STATUS, RECOVER, OUT DUMP, OUT ARM|DISARM, OUT <1-23|ALL> ON|OFF')
        self.send(line)

    def handle(self, line):
        if line.startswith('{'):
            try:
                data = json.loads(line)
            except ValueError:
                data = None
            if isinstance(data, dict) and data.get('device') == 'PoolCentral':
                self.last_rx = self.clock()
                if data.get('type') == 'status':
                    self.status, self.last_status = data, self.clock()
                    if data.get('mac'):
                        self.device.mac = data['mac'].upper()
                elif data.get('type') == 'radio':
                    self.radios[data.get('mac', '?')] = data
                return
        self.saw(line)

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

    def stop_active(self):
        if self.transport.is_open:
            self.send('OUT DISARM')

    def snapshot(self):
        return dict(super().snapshot(), device=self.device.id, port=self.device.port, status=self.status,
                    radios=list(self.radios.values()), status_age_s=round(self.clock() - self.last_status, 1) if self.last_status else None)
