"""The General Radio (zones/firmware/GeneralRadio): one dongle for every ESP-NOW host function.

A strict superset of the pairing-station relay protocol, so the pairing Controller and the
ZoneRegistry run on it unchanged (StationSession). On top: the Mainshow verbs (`set_zone` to one
cube or, spelled out, to every cube in range; `show_start`), an emulated pool slider (`pool`)
and an emulated preshow plate (`preshow`), `led_test`, and a `status` report with counters.

Leases: the firmware releases a held pool member / preshow cue when the host stops pinging, and
the station heartbeat pings every second, so on this side a member or cue is held only while the
page keeps touching it (0.6 s), exactly like the PoolZone override. Nothing is held across a
closed window.

Event routing: the firmware answers `set_zone` with `zone_sent` too (with a `zone` field). The
ZoneRegistry would otherwise claim every `zone_sent`, so those, `zone_repeat`, `show_start`,
`locked`, `led_test`, `status` and the pool/preshow events are taken here first. `fatal` (the radio
driver stopped answering: every later send is refused until the board is power-cycled) and
`watchdog` (the held cube was returned to idle) are noted here in the radio's words, then handed to
the pairing Controller, which treats them as a lost link and re-handshakes.
"""
import paths  # noqa: F401
import uuid

from sessions.station import StationSession

mainshow_app = paths.load_app_module('mainshow_app', 'zones/mainshow/app.py')
OWN_EVENTS = {'zone_repeat', 'show_start', 'locked', 'show_config', 'show_stop', 'led_test', 'status', 'pool_state', 'pool_beacon', 'pool_watchdog',
              'preshow_state', 'preshow_beacon', 'preshow_ack', 'preshow_fail', 'preshow_watchdog'}
NOTED_EVENTS = {'fatal', 'watchdog'}  # noted here, then handed to the Controller as well
ZONE_NAMES = {0: 'idle', 1: 'preshow', 2: 'desert', 3: 'pool', 4: 'mainshow'}
COLOUR_REPEATS = 3  # the firmware sends a colour three times, as the tag plates do
FATAL_TEXT = 'Radio driver stopped answering; unplug and replug the General Radio'


class GeneralRadioSession(StationSession):
    kind = 'generalradio'
    TOUCH = 0.6
    STATUS_EVERY = 5.0

    def __init__(self, hub, device):
        super().__init__(hub, device)
        self.status = {}              # the last hello/status body
        self.pool = {}                # firmware pool state (armed, member, radio_id, central_mac, unicast, radio_mask)
        self.preshow = {}             # firmware preshow state (armed, point, state, seq, acked, ack_ms, bridge_mac, mode, bridge_sees_me)
        self.pool_beacon = self.preshow_beacon = None
        self.pool_held = 0            # what this side asked to hold (0 = nothing)
        self.pool_radio_id = 1
        self.preshow_held = 0         # point held ON by this side
        self.last_pool_touch = self.last_preshow_touch = 0.0
        self.show = None              # dict(show_id, target, source, started, name)
        self.sends = {}               # request id -> dict(kind, mac/target, name)
        self.last_status = 0.0
        self.names = {}
        self.recent_acks = []
        self.colour_sends = {}        # mac -> dict(name, zone, zone_name, sent, delivered, at): the last colour per cube
        self.fatal = None             # the radio's `fatal` detail until it answers a hello again

    # ---- verbs shared with the Mainshow controller session ----
    def _request(self, cmd, **fields):
        c = self.controller
        if not c.connected:
            raise ValueError('The General Radio is not answering; wait for hello')
        rid = uuid.uuid4().hex[:12]
        self.transport.send(dict(cmd=cmd, id=rid, **fields))
        self.sends[rid] = dict(cmd=cmd, **fields)
        if len(self.sends) > 200:
            for key in list(self.sends)[:100]:
                del self.sends[key]
        return rid

    def set_zone(self, mac, zone, name=None):
        """SET_ZONE to one cube (unicast MAC) or to every cube in range ('broadcast', spelled out)."""
        zone = int(zone)
        if zone not in ZONE_NAMES:
            raise ValueError('Zone must be 0-4')
        if self.controller.mode and mac != 'broadcast':
            raise ValueError('Stop the pairing operation first; the radio is holding a cube')
        self.names[mac] = name or mac
        return self._request('set_zone', mac=mac, zone=zone)

    def trigger(self, target, name='all cubes'):
        self.names[target] = name
        return self._request('show_start', target=target)

    def led_test(self, on):
        return self._request('led_test', on=1 if on else 0)

    def request_status(self):
        return self._request('status')

    def usable(self):
        return self.controller.connected and not self.fatal

    def problem(self):
        if self.fatal:
            return FATAL_TEXT
        channel = self.controller.station.get('channel') if self.controller.connected else None
        if channel not in (None, 2):
            return f'The radio is on channel {channel}; cubes and zones use 2'
        return None

    def show_relay(self):
        """general-radio-1.1.0 and later relay main-show frames (hello reports show: 1)."""
        return bool(self.usable() and self.status.get('show'))

    def show_state(self):
        if not self.show:
            return None
        elapsed = self.clock() - self.show['started']
        return elapsed, mainshow_app.segment_at(elapsed * 1000)

    def forget_show(self, mac=None):
        if self.show and (mac is None or self.show['target'] == mac):
            self.show = None

    # ---- pool lamp (one member at a time, leased by touches) ----
    def pool_set(self, member, radio_id=None):
        member = int(member)
        if not 0 <= member <= 23:
            raise ValueError('Pool member must be 0 (release) or 1-23')
        if radio_id is not None:
            radio_id = int(radio_id)
            if not 1 <= radio_id <= 6:
                raise ValueError('Radio id must be 1-6')
            self.pool_radio_id = radio_id
        self.pool_held = member
        self.last_pool_touch = self.clock()
        return self._request('pool', member=member, radio_id=self.pool_radio_id)

    def pool_touch(self):
        self.last_pool_touch = self.clock()
        return bool(self.pool.get('armed'))

    # ---- preshow cue (one point at a time, leased by touches) ----
    def preshow_set(self, point, on):
        point = int(point)
        if not 1 <= point <= 4:
            raise ValueError('Preshow point must be 1-4')
        if on and self.preshow_held and self.preshow_held != point:
            raise ValueError(f'Point {self.preshow_held} is still ON; turn it off first')
        self.preshow_held = point if on else 0
        self.last_preshow_touch = self.clock()
        return self._request('preshow', point=point, state=1 if on else 0)

    def preshow_touch(self):
        self.last_preshow_touch = self.clock()
        return bool(self.preshow.get('armed'))

    def preshow_release(self):
        """OFF for the point this side holds; None when nothing is held."""
        if not self.preshow_held:
            return None
        point, self.preshow_held = self.preshow_held, 0
        return self._request('preshow', point=point, state=0)

    def stop_active(self):
        super().stop_active()
        self.release_all()

    def release_all(self):
        if not self.transport.port or not self.controller.connected:
            return
        if self.pool_held:
            self.pool_held = 0
            self._request('pool', member=0, radio_id=self.pool_radio_id)
        if self.preshow_held:
            point, self.preshow_held = self.preshow_held, 0
            self._request('preshow', point=point, state=0)

    def prepare_close(self):
        self.release_all()
        return super().prepare_close()

    # ---- events ----
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
                self.hub.log(f'General Radio link lost: {self.last_disconnect}', 'warn', self.device.id)
                self.hub.close_session(self, self.last_disconnect)
                return
            # general-radio-1.1.0 show relay: the show editor's registry owns these (showedit.py).
            showedit = self.hub.showedit
            if showedit and (kind in ('show_sent', 'show_frame') or
                             (kind == 'error' and event.get('id') in showedit.registry.requests)):
                showedit.event(event)
                continue
            if kind in OWN_EVENTS or (kind == 'zone_sent' and 'zone' in event) or \
                    (kind == 'error' and event.get('id') in self.sends):
                self.own_event(event)
                self.hub.station_event(self.device.id, event)
                continue
            if kind in NOTED_EVENTS:
                self.noted_event(event)
            was_connected = self.controller.connected
            if not self.zones.event(event):
                self.controller.event(event)
                if kind == 'hello':
                    if self.fatal and event.get('radio_ok'):
                        self.fatal = None  # the board came back (power-cycled)
                        self.hub.log('General Radio answers again; its radio is up', 'ok', self.device.id, source='radio')
                    self.status = dict(event)
                    self.pool = dict(event.get('pool') or {})
                    self.preshow = dict(event.get('preshow') or {})
                    if event.get('mac'):
                        self.device.mac = event['mac'].upper()
                        self.hub.record_general_radio(self.device.mac)
                    self.hub.mark_dirty('inventory')
                    if self.controller.connected and not was_connected:
                        self.controller.discover()
            if kind not in ('pong', 'device', 'discover_sent', 'zone_sent', 'zone_frame') and \
                    not (kind == 'radio' and event.get('type') == 1):
                self.hub.station_event(self.device.id, event)

    def noted_event(self, e):
        """`fatal` / `watchdog`: say what happened to this board, in the radio's terms, before the Controller sees it."""
        if e.get('event') == 'fatal':
            self.fatal = e.get('detail') or FATAL_TEXT
            self.pool_held = self.preshow_held = 0  # nothing can be released or re-asserted from here on
            self.hub.log(f'{FATAL_TEXT} ({e.get("detail")}). Anything it held (lamp, cue, cube) is released by its own leases.',
                         'bad', self.device.id, source='radio')
        else:
            self.hub.log(f'The radio returned the held cube to idle: {e.get("detail")}', 'warn', self.device.id, source='radio')

    def own_event(self, e):
        kind = e.get('event')
        sent = self.sends.pop(e.get('id'), None) if e.get('id') else None
        if kind == 'status':
            self.status = dict(e)
            self.pool = dict(e.get('pool') or {})
            self.preshow = dict(e.get('preshow') or {})
        elif kind == 'zone_sent':
            name = self.names.get(e.get('mac'), e.get('mac'))
            zone = ZONE_NAMES.get(e.get('zone'), e.get('zone'))
            delivered = e.get('status') == 'delivered'
            self.colour_sends[e.get('mac')] = dict(name=name, zone=e.get('zone'), zone_name=zone, sent=1, delivered=int(delivered),
                                                   repeats=e.get('repeats') or COLOUR_REPEATS, at=self.hub.wall())
            if len(self.colour_sends) > 8:
                del self.colour_sends[next(iter(self.colour_sends))]
            if e.get('mac') == 'broadcast':
                self.hub.log(f'every cube in range → {zone}: broadcast ×{e.get("repeats")} (never acknowledged)', 'info', self.device.id, source='radio')
            elif delivered:
                self.hub.log(f'{name} → {zone}: delivered (radio ACK only; watch the cube)', 'info', self.device.id, source='radio')
            else:
                self.hub.log(f'{name} → {zone}: {e.get("status")}, no radio ACK. Is the cube on, in range and on channel 2?', 'warn',
                             self.device.id, source='radio')
        elif kind == 'zone_repeat':
            # The colour's second and third frames (the cube's mailbox holds one frame at a time).
            entry = self.colour_sends.get(e.get('mac'))
            if entry is not None and entry['zone'] == e.get('zone'):
                entry['sent'] = max(entry['sent'], int(e.get('n') or entry['sent'] + 1))
                entry['delivered'] += int(e.get('status') == 'delivered')
            if e.get('status') != 'delivered' and e.get('mac') != 'broadcast':
                name = self.names.get(e.get('mac'), e.get('mac'))
                self.hub.log(f'{name} → {ZONE_NAMES.get(e.get("zone"), e.get("zone"))}: repeat {e.get("n")} {e.get("status")}', 'warn',
                             self.device.id, source='radio')
        elif kind == 'show_config':
            self.status = dict(self.status, show_length_ms=e.get('length_ms'), show_version=e.get('version'), show_crc=e.get('crc'))
            self.hub.log(f'General Radio: show v{e.get("version")} ({(e.get("length_ms") or 0) / 1000:.1f} s) set for its timecode',
                         'info', self.device.id, source='radio')
        elif kind == 'show_stop':
            self.show = None
            self.hub.log('General Radio: show timecode stopped (cubes keep playing until idle)', 'info', self.device.id, source='radio')
        elif kind == 'show_start':
            target = e.get('target')
            self.show = dict(show_id=e.get('show_id'), target=target, source=e.get('source'), started=self.clock(),
                             name='all cubes' if target == 'broadcast' else self.names.get(target, target))
            detail = (f'broadcast ×{e.get("sent")} (no ACK). Only mainshow-ready cubes start' if target == 'broadcast' else
                      f'{self.show["name"]}: {e.get("delivered")}/{e.get("repeats")} delivered (radio ACK); starts only if the cube is mainshow-ready')
            self.hub.log(f'SHOW START from the General Radio, show {e.get("show_id")}: {detail}', 'ok', self.device.id, source='radio')
        elif kind == 'locked':
            self.hub.log(f'Trigger ignored: the radio is locked for another {e.get("retry_ms", 0) / 1000:.1f} s after the last show start',
                         'warn', self.device.id, source='radio')
        elif kind == 'pool_state':
            self.pool = {k: v for k, v in e.items() if k not in ('event', 'id')}
        elif kind == 'pool_beacon':
            self.pool_beacon = dict(e, at=self.hub.wall())
        elif kind == 'pool_watchdog':
            self.pool = {k: v for k, v in e.items() if k not in ('event', 'id', 'detail')}
            self.pool_held = 0
            self.hub.log(f'Pool lamp released by the radio: {e.get("detail")}', 'warn', self.device.id, source='radio')
        elif kind == 'preshow_state':
            self.preshow = {k: v for k, v in e.items() if k not in ('event', 'id')}
        elif kind == 'preshow_beacon':
            self.preshow_beacon = dict(e, at=self.hub.wall())
        elif kind == 'preshow_ack':
            self.recent_acks = (self.recent_acks + [dict(e, at=self.hub.wall())])[-10:]
            self.preshow['acked'] = True
            self.preshow['ack_ms'] = e.get('ms')
        elif kind == 'preshow_fail':
            self.hub.log(f'Preshow cue point {e.get("point")} {"ON" if e.get("state") else "OFF"} not acknowledged by the bridge after 3 s '
                         '(still re-asserted every second)', 'warn', self.device.id, source='radio')
        elif kind == 'preshow_watchdog':
            self.preshow = {k: v for k, v in e.items() if k not in ('event', 'id', 'detail')}
            self.preshow_held = 0
            self.hub.log(f'Preshow cue dropped by the radio: {e.get("detail")}', 'warn', self.device.id, source='radio')
        elif kind == 'led_test':
            self.status['led_test'] = e.get('on')
        elif kind == 'error':
            self.hub.log(f'General Radio refused {sent.get("cmd") if sent else "a command"}: {e.get("detail")}', 'warn', self.device.id,
                         source='radio')

    def tick(self, now):
        super().tick(now)
        if not self.transport.port or not self.controller.connected:
            return
        if self.pool_held and now - self.last_pool_touch > self.TOUCH:
            self.pool_held = 0
            self._request('pool', member=0, radio_id=self.pool_radio_id)
            self.hub.log('Pool lamp released: the page stopped holding it', 'info', self.device.id, source='radio')
        if self.preshow_held and now - self.last_preshow_touch > self.TOUCH:
            point, self.preshow_held = self.preshow_held, 0
            self._request('preshow', point=point, state=0)
            self.hub.log(f'Preshow cue {point} turned off: the page stopped holding it', 'info', self.device.id, source='radio')
        if now - self.last_status >= self.STATUS_EVERY and not self.controller.mode:
            self.last_status = now
            self._request('status')

    def snapshot(self):
        base = super().snapshot()
        show = self.show_state()
        st = self.status
        return dict(base, kind='generalradio', roles=st.get('roles') or [], busy=st.get('busy'), tx=st.get('tx') or {},
                    rx=st.get('rx') or {}, host_fresh=st.get('host_fresh'), led_test=st.get('led_test'),
                    shows=st.get('shows'), last_show_id=st.get('last_show_id'), show_running=st.get('show_running'),
                    lockout_ms=st.get('lockout_ms'), pool=self.pool, pool_held=self.pool_held, pool_radio_id=self.pool_radio_id,
                    pool_beacon=self.pool_beacon, preshow=self.preshow, preshow_held=self.preshow_held,
                    preshow_beacon=self.preshow_beacon, recent_acks=self.recent_acks,
                    colour_sends=list(self.colour_sends.values()), fatal=self.fatal,
                    show=dict(elapsed_s=round(show[0], 1), segment=show[1], length_ms=mainshow_app.SHOW_LENGTH_MS,
                              **{k: v for k, v in self.show.items() if k != 'started'}) if show else None,
                    timeline=mainshow_app.TIMELINE, usable=self.usable(), info=st, problem=self.problem())
