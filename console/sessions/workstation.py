"""The Workstation link: one session for every board that speaks the pairing-station JSON protocol.

Four firmware families answer it, and the console tells them apart by what `hello` reports, never by
the firmware name (zones/dbmanager/dongle.py holds the capability helpers):
  - the Workstation (workstation-1.x, zones/firmware/Workstation): the General Radio's protocol plus
    the station's PN532 reader; `roles` = cube, zone, pool, preshow, nfc.
  - the legacy pairing station (nct-pairing-1.x, frozen): reader + pairing + zone relay, no `roles`.
    It must see no new traffic: no `status` polls, no Mainshow verbs, not recorded as a Workstation.
  - the legacy ESP-NOW dongle: the same firmware without a reader (`nfc_ok` false).
  - the legacy General Radio (general-radio-1.x): everything but the reader; `roles` without nfc.

The pairing Controller and the ZoneRegistry share the transport. Zone frames are routed to the
registry first (the pairing app used to discard them); everything else goes to the controller.
Nothing is ever replayed after a re-handshake. On top, for boards whose `roles` say so: the Mainshow
verbs (`set_zone` to one cube or, spelled out, to every cube in range; `show_start`), an emulated
pool slider (`pool`), an emulated preshow plate (`preshow`), `led_test`, and a `status` report with
counters, polled every 5 s. Each verb checks its role first (`require_role`), so a legacy station
refuses them here instead of answering "Unknown command".

Leases: the firmware releases a held pool member / preshow cue when the host stops pinging, and
the station heartbeat pings every second, so on this side a member or cue is held only while the
page keeps touching it (0.6 s), exactly like the PoolZone override. Nothing is held across a
closed window.

Event routing: the firmware answers `set_zone` with `zone_sent` too (with a `zone` field). The
ZoneRegistry would otherwise claim every `zone_sent`, so those, `zone_repeat`, `show_start`,
`locked`, `led_test`, `status` and the pool/preshow events are taken here first. `fatal` (the radio
driver stopped answering: every later send is refused until the board is power-cycled) and
`watchdog` (the held cube was returned to idle) are noted here in the radio's words, then handed to
the pairing Controller, which treats them as a lost link and re-handshakes. Show frames
(`show_sent` / `show_frame`) belong to the show editor's registry (showedit.py).

The tag on the reader (`reader`, `reader_history`): the page's view of the cube lying on this board's
reader, as a zone plate's Monitor shows the cube on the plate. `tag_state` says only present/absent, so
once the link is idle the UID is read back with `nfc_poll enabled:true` (it answers `tag_present` and the
last UID; polling stays on, as the Controller already asked). An identify's `tag` event carries it too.
Observation only: nothing is written to the database (not an `nfc_seen` scan) and the Controller still
sees every one of these events.

Tag-read action (settings `reader_flash`, default on, and `reader_action`): on a Workstation (the `nfc` role; never
the legacy station), whether or not its page is open, each tag placed on the reader makes the cube that owns it
either do a two-second identify flash (`flash`, the default: the operator sees tag -> inventory -> MAC -> radio work)
or receive one SET_ZONE (`zone:0`-`zone:4`). It never gets in anyone's way:
  - it acts only when this Controller is idle, no other link is working with that cube and no main show is known to
    run (SET_ZONE, and so an identify, ends the show on that cube); otherwise it quietly does nothing;
  - the flash is the Controller's background flash (mode `reader_flash`): any other operation, a colour send or a zone
    update takes over at once (a `stop` goes first); a cube plugged in over USB leaves it running (it has no
    registration to protect: hub.identified() skips it, and whatever starts next takes it over); an error or a missing
    `flash_done` just ends it, and it never touches the registration feedback;
  - a UID acted on is not acted on again until it is seen leaving the reader outside that flash (the identify's own
    synthetic `tag_state` gaps must not look like a fresh placement) and a re-handshake does not re-arm it.
No cube firmware change: the identify and SET_ZONE are what every cube since v1.3 answers.
"""
import paths  # noqa: F401
import re
import uuid

from controller import Controller
from database import hex_bytes
from zone_registry import ZoneRegistry
import dongle
import zonedb

from sessions.base import Session

mainshow_app = paths.load_app_module('mainshow_app', 'zones/mainshow/app.py')
QUIET = {'pong', 'device', 'discover_sent', 'zone_sent', 'zone_frame'}  # never shown on the timeline
OWN_EVENTS = {'zone_repeat', 'show_start', 'locked', 'show_config', 'show_stop', 'led_test', 'status', 'pool_state', 'pool_beacon', 'pool_watchdog',
              'preshow_state', 'preshow_beacon', 'preshow_ack', 'preshow_fail', 'preshow_watchdog'}
NOTED_EVENTS = {'fatal', 'watchdog'}  # noted here, then handed to the Controller as well
ZONE_NAMES = {0: 'idle', 1: 'preshow', 2: 'desert', 3: 'pool', 4: 'mainshow'}
COLOUR_REPEATS = 3  # the firmware sends a colour three times, as the tag plates do
FATAL_TEXT = 'Radio driver stopped answering; unplug and replug the board'
LIVE_GENERAL = (1, 2, 0)  # the first General Radio that knows SHOW_LIVE (the page gates the mirror on this too)
READER_EVENTS = {'tag_state', 'tag', 'nfc_poll_result'}
READER_HISTORY = 20
READER_ACTIONS = ('flash', 'zone:0', 'zone:1', 'zone:2', 'zone:3', 'zone:4')  # what a tag placed on the reader does


def _at_least(firmware, prefix, minimum):
    """Semantic compare of a 'prefix-x.y.z' firmware string, as the page's fwAtLeast does."""
    match = re.match(rf'^{re.escape(prefix)}(\d+)\.(\d+)\.(\d+)', str(firmware or ''))
    return bool(match) and tuple(int(v) for v in match.groups()) >= tuple(minimum)


class WorkstationSession(Session):
    kind = 'workstation'
    PING, HELLO_RETRY = 1.0, 3.0
    TOUCH = 0.6
    STATUS_EVERY = 5.0
    READER_QUERY = 1.0            # ask the reader for an unknown tag's UID at most once a second

    def __init__(self, hub, device):
        super().__init__(hub, device)
        self.transport = hub.make_transport("json", self)
        self.controller = Controller(hub.db, self.transport.send, self.log_controller, hub.clock)
        self.zones = ZoneRegistry(hub.db, self.transport.send, self.log_zones, hub.clock, hub.wall,
                                  auto_refresh=True)
        self.last_ping = self.last_hello = 0.0
        self.last_disconnect = None
        self.events = 0
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
        self.reader = self._no_tag()  # the tag on this board's reader (see the module docstring)
        self.reader_history = []      # newest first: dict(time, uid, mac, cube_id, held_ms)
        self.reader_query = None      # the outstanding nfc_poll request id
        self.last_reader_query = 0.0
        self.reader_flash_uid = None  # the UID last acted on, until it is seen leaving the reader (module docstring)
        self.reader_flash_last = None # dict(uid, mac, cube_id, at, result, action) for the page

    # ---- what the board is, from its hello ----
    @property
    def hello(self):
        return self.controller.station

    @property
    def roles(self):
        return dongle.radio_roles(self.hello)

    @property
    def label(self):
        # Before the first hello the probe's answer (a hello or a banner) already names the family.
        return dongle.label(self.hello if self.hello.get('firmware') else self.device.details)

    @property
    def has_reader(self):
        return self.controller.connected and dongle.has_reader(self.hello)

    @property
    def relay_capable(self):
        return self.controller.connected and dongle.relay_capable(self.hello)

    @property
    def show_verbs(self):
        return self.usable() and 'cube' in self.roles

    @property
    def is_dongle(self):
        return self.controller.connected and not self.controller.station.get('nfc_ok')

    def require_role(self, role):
        if role not in self.roles:
            raise ValueError(f'{self.label} has no {role} role; connect a Workstation')

    def capabilities(self):
        hello = self.hello
        live = dongle.is_workstation(hello) or (dongle.is_general(hello) and _at_least(hello.get('firmware'), 'general-radio-', LIVE_GENERAL))
        return dict(reader=self.has_reader, relay=self.relay_capable, show_verbs=self.show_verbs, show_relay=self.show_relay(),
                    pool='pool' in self.roles, preshow='preshow' in self.roles, live=bool(live))

    # ---- lifecycle ----
    def log_controller(self, text):
        self.hub.log(str(text), 'info', self.device.id, source='station')

    def log_zones(self, text):
        self.hub.log(str(text), 'info', self.device.id, source='zones')

    def open(self):
        self.transport.open(self.device.port)
        now = self.clock()
        self.opened_at = self.last_rx = self.last_hello = now
        self.controller.emit('hello')
        self.hub.log(f'{self.label} link opened on {self.device.port}; waiting for hello', 'info', self.device.id)

    def close(self, reason='closed'):
        super().close(reason)
        if self.controller.connected or self.controller.mode:
            self.controller.disconnected(reason)
        self.transport.close()

    def prepare_close(self):
        """Release what is held and ask the station to stop its current operation; the hub keeps pumping for ~1.2 s."""
        self.release_all()
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
        self.release_all()

    # ---- verbs shared with the Mainshow controller session ----
    def _request(self, cmd, **fields):
        c = self.controller
        if not c.connected:
            raise ValueError(f'{self.label} is not answering; wait for hello')
        rid = uuid.uuid4().hex[:12]
        self.transport.send(dict(cmd=cmd, id=rid, **fields))
        self.sends[rid] = dict(cmd=cmd, **fields)
        if len(self.sends) > 200:
            for key in list(self.sends)[:100]:
                del self.sends[key]
        return rid

    def set_zone(self, mac, zone, name=None):
        """SET_ZONE to one cube (unicast MAC) or to every cube in range ('broadcast', spelled out)."""
        self.require_role('cube')
        zone = int(zone)
        if zone not in ZONE_NAMES:
            raise ValueError('Zone must be 0-4')
        if mac != 'broadcast':
            self.controller.yield_background()  # the tag-read flash gives way to an operator's colour
        if self.controller.mode and mac != 'broadcast':
            raise ValueError('Stop the pairing operation first; the radio is holding a cube')
        self.names[mac] = name or mac
        return self._request('set_zone', mac=mac, zone=zone)

    def trigger(self, target, name='all cubes'):
        self.require_role('cube')
        self.names[target] = name
        return self._request('show_start', target=target)

    def led_test(self, on):
        self.require_role('cube')
        return self._request('led_test', on=1 if on else 0)

    def request_status(self):
        self.require_role('cube')
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
        """Relays main-show frames: hello reports show:1 (general-radio-1.1.0 and later, every Workstation)."""
        return bool(self.usable() and dongle.show_relay(self.hello))

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
        self.require_role('pool')
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
        self.require_role('preshow')
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

    def release_all(self):
        if not self.transport.port or not self.controller.connected:
            return
        if self.pool_held:
            self.pool_held = 0
            self._request('pool', member=0, radio_id=self.pool_radio_id)
        if self.preshow_held:
            point, self.preshow_held = self.preshow_held, 0
            self._request('preshow', point=point, state=0)

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
            if kind in READER_EVENTS:
                self.reader_event(event)   # observed only; routed on below as before
            if kind == 'disconnected':
                self.last_disconnect = event.get('detail', 'Disconnected')
                self.hub.log(f'{self.label} link lost: {self.last_disconnect}', 'warn', self.device.id)
                self.hub.close_session(self, self.last_disconnect)
                return
            # Show relay: the show editor's registry owns these (showedit.py).
            showedit = self.hub.showedit
            if showedit and (kind in ('show_sent', 'show_frame') or
                             (kind == 'error' and event.get('id') in showedit.registry.requests)):
                showedit.event(event, via=self)
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
                    self.hello_event(event, was_connected)
            if kind == 'registered' or kind == 'hello':
                self.hub.mark_dirty('inventory')
            # A reader reports its I²C status with every poll; only a fault is worth a timeline line.
            if kind not in QUIET and not (kind == 'radio' and event.get('type') == 1) \
                    and not (kind == 'nfc_i2c' and event.get('status') == 0):
                self.hub.station_event(self.device.id, event)

    def hello_event(self, event, was_connected):
        if self.fatal and event.get('radio_ok'):
            self.fatal = None  # the board came back (power-cycled)
            self.hub.log(f'{self.label} answers again; its radio is up', 'ok', self.device.id, source='radio')
        self.status = dict(event)
        self._tag_left(observed=False)  # a (re-)handshake: re-read what lies on the reader, without re-acting on it
        self.pool = dict(event.get('pool') or {})
        self.preshow = dict(event.get('preshow') or {})
        if event.get('mac'):
            self.device.mac = event['mac'].upper()
            if self.roles:  # a legacy station is never recorded as a Workstation
                self.hub.record_workstation(self.device.mac)
        if self.controller.connected and not was_connected:
            self.controller.discover()

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
            self.colour_sends[e.get('mac')] = dict(mac=e.get('mac'), name=name, zone=e.get('zone'), zone_name=zone, sent=1, delivered=int(delivered),
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
            self.hub.log(f'{self.label}: show v{e.get("version")} ({(e.get("length_ms") or 0) / 1000:.1f} s) set for its timecode',
                         'info', self.device.id, source='radio')
        elif kind == 'show_stop':
            self.show = None
            self.hub.log(f'{self.label}: show timecode stopped (cubes keep playing until idle)', 'info', self.device.id, source='radio')
        elif kind == 'show_start':
            target = e.get('target')
            self.show = dict(show_id=e.get('show_id'), target=target, source=e.get('source'), started=self.clock(),
                             name='all cubes' if target == 'broadcast' else self.names.get(target, target))
            detail = (f'broadcast ×{e.get("sent")} (no ACK). Only mainshow-ready cubes start' if target == 'broadcast' else
                      f'{self.show["name"]}: {e.get("delivered")}/{e.get("repeats")} delivered (radio ACK); starts only if the cube is mainshow-ready')
            self.hub.log(f'SHOW START from the {self.label}, show {e.get("show_id")}: {detail}', 'ok', self.device.id, source='radio')
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
            self.hub.log(f'{self.label} refused {sent.get("cmd") if sent else "a command"}: {e.get("detail")}', 'warn', self.device.id,
                         source='radio')

    # ---- the tag on the reader ----
    @staticmethod
    def _no_tag():
        return dict(present=False, uid=None, since=None, confirmed=True)

    def reader_event(self, e):
        kind, r = e.get('event'), self.reader
        if kind == 'tag_state':
            if not e.get('present'):
                self._tag_left()
            elif not (self.controller.mode and not r['present']):
                # An identify opens with a synthetic present:true (the reader must see a clear interval);
                # while an operation runs only a real `tag` event says a tag arrived.
                if not r['present']:
                    r['since'] = self.hub.wall()
                r.update(present=True, confirmed=False)  # arrived or changed: read the UID once idle
        elif kind == 'nfc_poll_result':
            if e.get('id') == self.reader_query:
                self.reader_query = None
            if e.get('tag_present'):
                self._tag_seen(e.get('uid'))
            else:
                self._tag_left()
        elif kind == 'tag' and e.get('uid'):
            self._tag_seen(e['uid'])

    def _tag_seen(self, uid):
        r = self.reader
        try:
            uid = hex_bytes(str(uid), {4, 7}) if uid else None
        except ValueError:
            uid = None
        if uid and uid != r['uid']:
            fresh = bool(r['uid']) or not r['present']
            if r['uid']:
                self._tag_left()  # another tag replaced it without a clear interval
            r = self.reader
            if fresh or not r['since']:
                r['since'] = self.hub.wall()
            r['uid'] = uid
            self._tag_placed(uid, r['since'])
        elif not r['present']:
            r['since'] = self.hub.wall()
        r.update(present=True, confirmed=True)

    def _tag_placed(self, uid, since):
        mac, cube_id = self.cube_for_uid(uid)
        self.reader_history.insert(0, dict(time=since, uid=uid, mac=mac, cube_id=cube_id, held_ms=None))
        del self.reader_history[READER_HISTORY:]
        who = f'cube #{cube_id}' if cube_id is not None else mac or 'a tag the inventory does not know'
        self.hub.log(f'Tag {uid} on the {self.label} reader: {who}', 'info', self.device.id, source='reader')
        if self.reader_flash:
            try:
                self._reader_action(uid, mac, cube_id)
            except Exception as exc:  # runs before the Controller sees this event: never let it fail the pump
                self.hub.log(f'Tag-read action not sent: {exc}', 'warn', self.device.id, source='reader')

    @property
    def reader_flash(self):
        """The tag-read action is on: the console setting (default on) and a Workstation reader (the `nfc` role)."""
        return bool(self.hub.settings.get('reader_flash', True)) and 'nfc' in self.roles and self.has_reader

    @property
    def reader_action(self):
        action = getattr(self.hub, 'reader_action', None) or 'flash'
        return action if action in READER_ACTIONS else 'flash'

    def _reader_action(self, uid, mac, cube_id):
        """Signal the cube owning a tag just placed on the reader: the two-second identify flash (a background flash
        that anything else takes over) or one SET_ZONE. Only when nothing else is using that cube or this radio."""
        if uid == self.reader_flash_uid:
            return  # already done for this placement (see the module docstring)
        c, action = self.controller, self.reader_action
        row = self.hub.db.get(mac) if mac else None
        who = f'cube #{cube_id}' if cube_id is not None else mac
        text = None
        if not row:
            result = 'unknown tag'  # the placement line already says the inventory does not know it
        elif self.hub.db.excluded(mac):
            result, text = 'excluded', f'Tag-read action skipped: {mac} is an excluded device'
        elif c.mode or not c.connected:
            result = 'busy'  # pairing, registration or another flash owns the radio: stay out of its way, quietly
        elif self._held_elsewhere(mac):
            result, text = 'busy', f'Tag-read action skipped: another radio is working with {who}'
        elif self._show_running():
            result, text = 'show running', f'Tag-read action skipped: a main show is running and SET_ZONE would stop it on {who}'
        elif action == 'flash':
            if not c.background_flash(row, 2000):
                result = 'busy'
            else:
                self.reader_flash_uid = uid
                result = 'flashed (pending tag)' if row.get('uid') != uid else 'flashed'
                text = f'Flashing {who} for 2 s: its tag {uid} is on the reader' + (' (pending tag, not yet acknowledged)' if result != 'flashed' else '')
        else:
            zone = int(action.split(':')[1])
            self.set_zone(mac, zone, f'#{cube_id}' if cube_id is not None else mac)
            self.reader_flash_uid = uid
            result = f'zone {zone} sent'
            text = f'Setting {who} to {ZONE_NAMES[zone]} (SET_ZONE {zone}): its tag {uid} is on the reader'
        self.reader_flash_last = dict(uid=uid, mac=mac, cube_id=cube_id, at=self.hub.wall(), result=result, action=action)
        if text:
            self.hub.log(text, 'info', self.device.id, source='reader')

    def _held_elsewhere(self, mac):
        """Another link's Controller is working with this cube (e.g. the primary station registering it)."""
        for s in list(self.hub.sessions.values()):
            other = getattr(s, 'controller', None)
            if s is not self and isinstance(s, WorkstationSession) and other and other.mode and other.mode != 'reader_flash' \
                    and (other.active or {}).get('mac') == mac:
                return True
        return False

    def _show_running(self):
        """A main show the console knows is playing: SET_ZONE (and so an identify) ends it on the cube."""
        try:
            if self.hub.showedit and self.hub.showedit.controller_show_running():
                return True
        except Exception:
            pass
        return bool(self.status.get('show_running'))

    def _tag_left(self, observed=True):
        r, history = self.reader, self.reader_history
        if r['present'] and r['uid'] and history and history[0]['uid'] == r['uid'] and history[0]['held_ms'] is None:
            history[0]['held_ms'] = int(max(0.0, self.hub.wall() - (r['since'] or self.hub.wall())) * 1000)
        if observed and self.controller.mode != 'reader_flash':
            # Seen leaving (not during our own flash, whose identify fakes reader gaps): the next placement acts again.
            self.reader_flash_uid = None
        self.reader = self._no_tag()

    def cube_for_uid(self, uid):
        """(mac, cube_id) of the device owning this tag: its committed tag first, else a pending one."""
        row = self.hub.db.conn.execute('SELECT mac, cube_id FROM devices WHERE uid=? OR pending_uid=? ORDER BY uid=? DESC LIMIT 1',
                                       (uid, uid, uid)).fetchone()
        return (row[0], row[1]) if row else (None, None)

    def reader_tick(self, now):
        """Read back the UID of a tag reported without one, once the link is idle (the reader refuses nfc_poll otherwise)."""
        c, r = self.controller, self.reader
        if not (self.has_reader and c.reader_ok) or c.mode:
            return
        if not ((r['present'] and not r['confirmed']) or (c.tag_present and not r['present'])):
            return
        if now - self.last_reader_query < (3 if self.reader_query else 1) * self.READER_QUERY:
            return
        self.last_reader_query = now
        self.reader_query = c.emit('nfc_poll', enabled=True)

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
        self.zones.tick(c.connected, c.station, busy=bool(c.mode), may_start=self.hub.zone_walk_allowed(self))
        if not self.transport.port or not c.connected:
            return
        if self.pool_held and now - self.last_pool_touch > self.TOUCH:
            self.pool_held = 0
            self._request('pool', member=0, radio_id=self.pool_radio_id)
            self.hub.log('Pool lamp released: the page stopped holding it', 'info', self.device.id, source='radio')
        if self.preshow_held and now - self.last_preshow_touch > self.TOUCH:
            point, self.preshow_held = self.preshow_held, 0
            self._request('preshow', point=point, state=0)
            self.hub.log(f'Preshow cue {point} turned off: the page stopped holding it', 'info', self.device.id, source='radio')
        self.reader_tick(now)
        # Only a board with roles knows `status`; a legacy station would answer "Unknown command" every 5 s.
        if self.roles and now - self.last_status >= self.STATUS_EVERY and not c.mode:
            self.last_status = now
            self._request('status')

    # ---- snapshots ----
    def snapshot(self):
        c = self.controller
        now = self.clock()
        show = self.show_state()
        st = self.status
        return dict(super().snapshot(), device=self.device.id, port=self.device.port, connected=c.connected,
                    reader_ok=c.reader_ok, mode=c.mode, phase=c.phase, active=c.active, message=c.message,
                    feedback=c.feedback, hello=c.station, telemetry=c.telemetry,
                    discovered={mac: round(now - at, 1) for mac, at in c.discovered.items()},
                    tag_present=c.tag_present, progress=c.progress, total=c.total, dongle=self.is_dongle,
                    last_disconnect=self.last_disconnect, zone_support=c.station.get('zones') == zonedb.PROTO,
                    events=self.events,
                    label=self.label, family=dongle.family(c.station), capabilities=self.capabilities(),
                    roles=self.roles, busy=st.get('busy'), tx=st.get('tx') or {},
                    rx=st.get('rx') or {}, host_fresh=st.get('host_fresh'), led_test=st.get('led_test'),
                    shows=st.get('shows'), last_show_id=st.get('last_show_id'), show_running=st.get('show_running'),
                    lockout_ms=st.get('lockout_ms'), pool=self.pool, pool_held=self.pool_held, pool_radio_id=self.pool_radio_id,
                    pool_beacon=self.pool_beacon, preshow=self.preshow, preshow_held=self.preshow_held,
                    preshow_beacon=self.preshow_beacon, recent_acks=self.recent_acks,
                    colour_sends=list(self.colour_sends.values()), fatal=self.fatal,
                    show=dict(elapsed_s=round(show[0], 1), segment=show[1], length_ms=mainshow_app.SHOW_LENGTH_MS,
                              **{k: v for k, v in self.show.items() if k != 'started'}) if show else None,
                    timeline=mainshow_app.TIMELINE, usable=self.usable(), info=st, problem=self.problem(),
                    reader_tag=dict(self.reader) if self.has_reader else None, reader_history=self.reader_history,
                    reader_flash=self.reader_flash, reader_flash_last=self.reader_flash_last,
                    reader_flash_setting=bool(self.hub.settings.get('reader_flash', True)), reader_action=self.reader_action,
                    reader_action_capable='nfc' in self.roles,
                    zone_colors=zonedb.ZONE_COLORS)

    def registry_snapshot(self):
        snap = self.zones.snapshot()
        snap['logs'] = self.zones.logs
        snap['device'] = self.device.id
        snap['connected'] = self.relay_capable
        return snap
