"""The Mainshow controller board: reuses zones/mainshow/app.py's Tk-free Session."""
import paths  # noqa: F401

from transport import Transport
import dongle

from sessions.base import Session

mainshow_app = paths.load_app_module('mainshow_app', 'zones/mainshow/app.py')


class MainshowSession(Session):
    kind = 'mainshow'

    def __init__(self, hub, device):
        super().__init__(hub, device)
        self.transport = hub.make_transport("json", self)
        self.session = mainshow_app.Session(self.transport.send, self.log, hub.clock)
        self.recorded = False

    def log(self, text):
        self.hub.log(str(text), 'info', self.device.id, source='mainshow')

    def open(self):
        self.transport.open(self.device.port)
        self.opened_at = self.last_rx = self.clock()
        self.session.open()

    def close(self, reason='closed'):
        super().close(reason)
        self.session.close()
        self.transport.close()

    def pump(self):
        for _ in range(300):
            try:
                event = self.transport.inbox.get_nowait()
            except Exception:
                break
            self.last_rx = self.clock()
            kind = event.get('event')
            if kind == 'disconnected':
                self.hub.log(f'Mainshow controller link lost: {event.get("detail")}', 'warn', self.device.id)
                self.hub.close_session(self, event.get('detail', 'disconnected'))
                return
            if kind == 'boot_log':
                self.saw(str(event.get('detail')))
                continue
            self.session.handle(event)
            self.hub.station_event(self.device.id, event)
            if kind == 'hello' and self.session.usable() and not self.recorded and event.get('mac'):
                dongle.set_controller(self.hub.db, event['mac'].upper(), True)
                self.device.mac = event['mac'].upper()
                self.recorded = True
                self.hub.mark_dirty('inventory')

    def tick(self, now):
        self.session.heartbeat()
        if self.session.opened and self.session.connected is False and now - self.opened_at > 12 and self.session.problem \
                and not self.transport.port:
            return

    def set_zone(self, mac, zone, name):
        return self.session.set_zone(mac, int(zone), name)

    def trigger(self, target, name='all cubes'):
        return self.session.trigger(target, name)

    def led_test(self, on):
        return self.session.request('led_test', on=1 if on else 0)

    def stop_active(self):
        pass  # a show cannot be stopped from the controller; Stop -> idle is an explicit set_zone 0

    def snapshot(self):
        s = self.session
        show = s.show_state()
        return dict(super().snapshot(), device=self.device.id, port=self.device.port, connected=s.connected,
                    usable=bool(s.usable()), info=s.info, problem=s.problem, pending=s.pending,
                    show=dict(elapsed_s=round(show[0], 1), segment=show[1], length_ms=mainshow_app.SHOW_LENGTH_MS,
                              **{k: v for k, v in s.show.items() if k != 'started'}) if show else None,
                    timeline=mainshow_app.TIMELINE)
