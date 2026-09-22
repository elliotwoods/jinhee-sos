"""The PoolRadioTest bridge: emulates all six pool radios. Everything it holds is released on close."""
import paths  # noqa: F401
import json

from linetransport import LineTransport

from sessions.base import Session


def toggle_member(slots, member):
    """The light-test rule from poolzone_test/app.py: at most six held members, one slot each."""
    slots = list(slots)
    if member in slots:
        slots[slots.index(member)] = 0
        return slots
    if 0 not in slots:
        raise ValueError('All six radio slots are in use; release one first')
    slots[slots.index(0)] = member
    return slots


class PoolTestBridgeSession(Session):
    kind = 'pooltest'
    PING, SILENCE = 0.35, 4.0

    def __init__(self, hub, device):
        super().__init__(hub, device)
        self.transport = hub.make_transport("line", self)
        self.status = {}
        self.ready = False
        self.slots = [0] * 6
        self.last_ping = 0.0
        self.channel_pending = False
        self.scanning = False
        self.scan_member = 0
        self.next_scan = 0.0
        self.interval = 1.0
        self.notice = ''

    def open(self):
        self.transport.open(self.device.port)
        self.opened_at = self.last_rx = self.clock()
        self.send('STATUS')

    def close(self, reason='closed'):
        super().close(reason)
        self.scanning = False
        if self.transport.is_open:
            self.transport.close(farewell='OFF')
        else:
            self.transport.close()

    def send(self, line):
        self.transport.send(line)
        self.saw(line, 'tx')

    def stop_active(self):
        self.all_off()

    def set_slots(self, slots):
        if not self.ready:
            raise ValueError('The test bridge is not ready')
        slots = [int(s) for s in slots]
        if len(slots) != 6 or any(not 0 <= s <= 23 for s in slots):
            raise ValueError('Six member numbers 0-23')
        self.send('SET ' + ' '.join(map(str, slots)))
        self.slots = slots

    def toggle(self, member):
        self.scanning = False
        self.set_slots(toggle_member(self.slots, int(member)))
        self.notice = f'Light {int(member):02d} ' + ('selected' if int(member) in self.slots else 'released')

    def all_off(self):
        self.scanning = False
        if self.transport.is_open and self.ready:
            self.send('OFF')
        self.slots = [0] * 6
        self.notice = 'All six radio slots released'

    def set_channel(self, channel):
        if any(self.slots):
            raise ValueError('Press All Off before changing the channel')
        self.channel_pending = True
        self.send(f'CHANNEL {int(channel)}')

    def sequential(self, on, interval=None):
        if interval:
            self.interval = max(0.2, float(interval))
        if not on:
            self.all_off()
            return
        if not self.ready:
            raise ValueError('The test bridge is not ready')
        self.scanning, self.scan_member, self.next_scan = True, 0, 0.0

    def handle(self, line):
        if line.startswith('{'):
            try:
                status = json.loads(line)
            except ValueError:
                status = None
            if isinstance(status, dict) and status.get('device') == 'PoolRadioTest':
                slots = status.get('members')
                if not isinstance(slots, list) or len(slots) != 6:
                    return
                self.last_rx = self.clock()
                was_ready = self.ready
                self.ready = status.get('ready') is True
                self.status = status
                if status.get('mac'):
                    self.device.mac = status['mac'].upper()
                if self.ready and not was_ready:
                    self.send('OFF')
                    self.hub.log(f'Pool test bridge verified · {status.get("mac")} · channel {status.get("channel")}', 'info', self.device.id)
                self.channel_pending = False
                self.slots = [int(s) for s in slots]
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

    def tick(self, now):
        super().tick(now)
        if not self.transport.is_open:
            return
        if now - self.last_ping >= self.PING:
            self.last_ping = now
            self.send('PING' if self.ready else 'STATUS')
        if self.ready and self.scanning and now >= self.next_scan:
            self.scan_member = self.scan_member % 23 + 1
            self.set_slots([self.scan_member, 0, 0, 0, 0, 0])
            self.next_scan = now + self.interval
            self.notice = f'Sequential test · light {self.scan_member:02d} / 23'

    def snapshot(self):
        return dict(super().snapshot(), device=self.device.id, port=self.device.port, status=self.status, ready=self.ready,
                    slots=self.slots, scanning=self.scanning, scan_member=self.scan_member, interval=self.interval,
                    notice=self.notice, channel_pending=self.channel_pending)
