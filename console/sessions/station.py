"""Pairing station or ESP-NOW dongle: the pairing Controller and the ZoneRegistry share one JSON
transport. Zone frames are routed to the registry first (the pairing app used to discard them);
everything else goes to the controller. Nothing is ever replayed after a re-handshake."""
import paths  # noqa: F401
import time

from controller import Controller
from transport import Transport
from zone_registry import ZoneRegistry
import zonedb

from sessions.base import Session

QUIET = {'pong', 'device', 'discover_sent', 'zone_sent', 'zone_frame'}


class StationSession(Session):
    kind = 'station'
    PING, HELLO_RETRY = 1.0, 3.0

    def __init__(self, hub, device):
        super().__init__(hub, device)
        self.transport = hub.make_transport("json", self)
        self.controller = Controller(hub.db, self.transport.send, self.log_controller, hub.clock)
        self.zones = ZoneRegistry(hub.db, self.transport.send, self.log_zones, hub.clock, hub.wall,
                                  auto_refresh=True)
        self.last_ping = self.last_hello = 0.0
        self.last_disconnect = None
        self.events = 0

    def log_controller(self, text):
        self.hub.log(str(text), 'info', self.device.id, source='station')

    def log_zones(self, text):
        self.hub.log(str(text), 'info', self.device.id, source='zones')

    def open(self):
        self.transport.open(self.device.port)
        now = self.clock()
        self.opened_at = self.last_rx = self.last_hello = now
        self.controller.emit('hello')
        self.hub.log(f'Station link opened on {self.device.port}; waiting for hello', 'info', self.device.id)

    def close(self, reason='closed'):
        super().close(reason)
        if self.controller.connected or self.controller.mode:
            self.controller.disconnected(reason)
        self.transport.close()

    def prepare_close(self):
        """Ask the station to stop its current operation; the hub keeps pumping for ~1.2 s."""
        try:
            if self.controller.connected and (self.controller.mode or self.controller.active):
                self.controller.stop()
                return True
        except Exception:
            pass
        return False

    def stop_active(self):
        if self.controller.connected:
            if self.zones.publication:
                self.zones.stop('Publishing stopped')
            self.controller.stop()

    def pump(self):
        for _ in range(300):
            try:
                event = self.transport.inbox.get_nowait()
            except Exception:
                break
            self.last_rx = self.clock()
            self.events += 1
            kind = event.get('event')
            if kind == 'disconnected':
                self.last_disconnect = event.get('detail', 'Disconnected')
                self.hub.log(f'Station link lost: {self.last_disconnect}', 'warn', self.device.id)
                self.hub.close_session(self, self.last_disconnect)
                return
            was_connected = self.controller.connected
            if not self.zones.event(event):
                self.controller.event(event)
                if kind == 'hello' and self.controller.connected and not was_connected:
                    self.controller.discover()
                    self.hub.mark_dirty('inventory')
            if kind == 'registered' or kind == 'hello':
                self.hub.mark_dirty('inventory')
            if kind not in QUIET and not (kind == 'radio' and event.get('type') == 1) \
                    and not (kind == 'nfc_i2c' and event.get('status') == 0):
                self.hub.station_event(self.device.id, event)

    def tick(self, now):
        c = self.controller
        if self.transport.port and c.connected and now - self.last_ping >= self.PING:
            c.emit('ping')
            self.last_ping = now
        if self.transport.port and not c.connected and now - self.last_hello >= self.HELLO_RETRY:
            # Logical disconnection with a healthy USB handle: re-handshake, never replay.
            c.emit('hello')
            self.last_hello = now
            c.message = 'Reconnecting to the station…'
        if self.transport.port and self.last_rx and now - self.last_rx > (8 if c.connected else 30):
            self.last_disconnect = 'Station stopped responding'
            self.hub.log('Station stopped responding; link closed. Reconnect to retry.', 'warn', self.device.id)
            self.hub.close_session(self, 'silent')
            return
        c.tick()
        if c.phase in ('identifying', 'registering', 'stopping'):
            self.zones.next_query = max(self.zones.next_query, now + 1.0)
        self.zones.tick(c.connected, c.station, busy=bool(c.mode))

    @property
    def is_dongle(self):
        return self.controller.connected and not self.controller.station.get('nfc_ok')

    def snapshot(self):
        c = self.controller
        now = self.clock()
        return dict(super().snapshot(), device=self.device.id, port=self.device.port, connected=c.connected,
                    reader_ok=c.reader_ok, mode=c.mode, phase=c.phase, active=c.active, message=c.message,
                    feedback=c.feedback, hello=c.station, telemetry=c.telemetry,
                    discovered={mac: round(now - at, 1) for mac, at in c.discovered.items()},
                    tag_present=c.tag_present, progress=c.progress, total=c.total, dongle=self.is_dongle,
                    last_disconnect=self.last_disconnect, zone_support=c.station.get('zones') == zonedb.PROTO,
                    events=self.events)

    def registry_snapshot(self):
        snap = self.zones.snapshot()
        snap['logs'] = self.zones.logs
        snap['device'] = self.device.id
        snap['connected'] = self.controller.connected and self.controller.station.get('zones') == zonedb.PROTO
        return snap
