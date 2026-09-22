"""A cube on USB: a passive line monitor (the cube only ever answers a bare '?')."""
import paths  # noqa: F401

from linetransport import LineTransport
from usb_identify import firmware_result

from sessions.base import Session


class CubeConsoleSession(Session):
    kind = 'cube'
    REPORT_EVERY = 15.0

    def __init__(self, hub, device):
        super().__init__(hub, device)
        self.transport = hub.make_transport("line", self)
        self.text = ''
        self.last_report = 0.0
        self.flags = dict(unregistered=None, espnow_init_error=None, show_start_ignored=None, zone=None,
                          registered=None, show_start=None, channel=None)

    def open(self):
        self.transport.open(self.device.port)
        self.opened_at = self.last_rx = self.last_report = self.clock()
        self.send('?')

    def close(self, reason='closed'):
        super().close(reason)
        self.transport.close()

    def send(self, line):
        self.transport.send(line)
        self.saw(line, 'tx')

    def console(self, line):
        if line.strip() != '?':
            raise ValueError('A cube answers only "?" over USB; everything else is ESP-NOW')
        self.send('?')

    def handle(self, line):
        tag = self.saw(line)
        self.text = (self.text + line + '\n')[-8192:]
        if tag:
            when = self.hub.wall()
            key = tag['tag'].split('.', 1)[1]
            if key in self.flags:
                self.flags[key] = dict(at=when, **tag['fields'])
        if 'Cube READY' in line and self.device.mac:
            expected = self.hub.builds.get('cube', {}).get('version')
            result = firmware_result(self.text, self.device.mac, expected)
            if result:
                self.device.fw_status = result
                self.device.firmware = result['version']
                self.hub.mark_dirty('devices')

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
        if self.transport.is_open and now - self.last_report >= self.REPORT_EVERY:
            self.last_report = now
            self.send('?')

    def snapshot(self):
        return dict(super().snapshot(), device=self.device.id, port=self.device.port, flags=self.flags,
                    fw_status=self.device.fw_status)
