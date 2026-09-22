"""A PreshowZone plate on USB: zone console + the leased HOST cue override (no reader needed)."""
import paths  # noqa: F401
import json

from sessions.zone_console import ZoneConsoleSession


class PreshowPlateSession(ZoneConsoleSession):
    kind = 'preshow'
    PING, STALE = 0.35, 1.5

    def __init__(self, hub, device):
        super().__init__(hub, device)
        self.host = {}
        self.armed = False
        self.want_armed = False
        self.last_ping = self.last_host = 0.0

    def close(self, reason='closed'):
        self.want_armed = False
        if self.transport.is_open:
            self.transport.close(farewell='HOST DISARM')
        super().close(reason)

    def stop_active(self):
        if self.transport.is_open:
            if self.armed:
                self.send('HOST OFF')
            self.send('HOST DISARM')
            self.send('stop')
        self.want_armed = False

    def arm(self):
        self.want_armed = True
        self.send('HOST ARM')
        self.send('HOST STATUS')

    def disarm(self):
        self.want_armed = False
        self.send('HOST DISARM')

    def cue(self, point, on):
        if not self.armed:
            raise ValueError('Arm the cue override first')
        self.send(f'HOST ON {int(point)}' if on else 'HOST OFF')

    def handle(self, line):
        if line.startswith('{') and '"type":"host"' in line:
            try:
                self.host = json.loads(line)
            except ValueError:
                return
            self.last_rx = self.last_host = self.clock()
            self.armed = bool(self.host.get('armed'))
            self.saw(line)
            return
        super().handle(line)

    def tick(self, now):
        super().tick(now)
        if not self.transport.is_open:
            return
        if self.want_armed and now - self.last_ping >= self.PING:
            self.last_ping = now
            self.send('HOST PING')
            self.send('HOST STATUS')
        if self.armed and self.want_armed and self.last_host and now - self.last_host > self.STALE:
            self.hub.log('Plate stopped answering the override; letting the lease lapse', 'warn', self.device.id)
            self.want_armed = self.armed = False

    def snapshot(self):
        return dict(super().snapshot(), kind='preshow', host=self.host, armed=self.armed, want_armed=self.want_armed)
