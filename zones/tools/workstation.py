"""Workstation: the Python side of zones/firmware/Workstation.

One ESP32-C3 dongle that performs every ESP-NOW host function: the pairing-station relay
(discover / identify / register cubes, relay zone-management frames) with the station's PN532
reader, the Mainshow controller's verbs (set a cube's zone, start the main show), one emulated
pool slider radio (hold a pool lamp through the pool central) and an emulated preshow plate (a
TouchDesigner cue through the media bridge). The board speaks one JSON object per line at 115200;
every request carries an `id` and its reply echoes it. See zones/firmware/Workstation/README.md
for the protocol. A legacy General Radio (general-radio-1.x, the same protocol without the reader)
is driven the same way; what a board can do is read from its hello (`roles`, `nfc_ok`, `show`),
never from the firmware name.

`Workstation` is a synchronous client over pairing_station/transport.py (its serial worker, the
no-reset open sequence and the advisory port lock). It is meant for scripts and for the GUI that
will come later; the Zone Database Manager, the pairing app and the Mainshow app keep driving the
board through their own sessions. The board leases its pool and preshow outputs on the host's
heartbeat: keep calling `ping()` (or use `keepalive()`) while holding a lamp or a cue, and they
are released about 1.5 s after the host goes quiet.

Run as a script for bench checks and for putting the Workstation firmware on a spare board:

    pairing_station/.venv/bin/python zones/tools/workstation.py --port <port> hello
    ... discover | zones | set-zone <cube#|MAC|broadcast> <0-4> | show-start [<cube#|MAC|broadcast>]
    ... pool <member> [--hold S] | preshow <1-4> on|off [--hold S] | listen [--seconds S] | flash

zones/tools/general_radio.py is kept as an alias of this module (it was the General Radio CLI).
"""
import argparse
import json
import queue
import re
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pairing_station'))
import hostos  # noqa: E402
from database import Database  # noqa: E402
from transport import Transport  # noqa: E402
from zone_registry import BROADCAST, ZoneStore  # noqa: E402
sys.path.insert(0, str(ROOT / 'zones/tools'))
import zonedb  # noqa: E402
sys.path.insert(0, str(ROOT / 'zones/dbmanager'))
import dongle  # noqa: E402  (adds flashing_station to the path: import it last)

DATA = ROOT / 'pairing_station' / 'data'
MAC_RE = re.compile(r'^[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}$')
ZONES = {0: 'idle', 1: 'preshow', 2: 'desert', 3: 'pool', 4: 'mainshow'}
is_general = dongle.is_general


class RadioError(RuntimeError):
    """The dongle refused a request, did not answer, or is not the firmware the request needs."""


class Workstation:
    """Synchronous client: one request at a time, replies matched by id, other events to `on_event`."""
    HEARTBEAT = 1.0   # the dongle wants a hello/ping within 5 s; its pool/preshow leases within 1.5 s
    REPLY_TIMEOUT = 3.0

    def __init__(self, transport=None, clock=time.monotonic, on_event=None):
        self.transport = transport or Transport()
        self.clock = clock
        self.on_event = on_event
        self.info = {}
        self.last_ping = 0.0
        self.pool_held = False
        self.preshow_held = None  # point held ON
        self._collector = None    # (keep, kept) while collect() runs: events a request drains go there first

    # ---- link ----
    def open(self, port):
        """Open the port (no reset) and handshake. Returns the hello."""
        self.transport.open(port)
        return self.hello()

    def close(self):
        self.transport.close()

    @property
    def firmware(self):
        return self.info.get('firmware', '')

    @property
    def general(self):
        """A Workstation or a legacy General Radio: the multi-role protocol (status, pool, preshow, ...)."""
        return dongle.is_general(self.firmware) or dongle.is_workstation(self.firmware)

    @property
    def roles(self):
        """What the board's hello says it does (cube, zone, pool, preshow, nfc); [] before hello or on a plain relay."""
        return dongle.radio_roles(self.info)

    def _dispatch(self, event):
        if event.get('event') == 'hello' and event.get('id') == '':
            self.info = event  # the board restarted
        if self._collector and self._collector[0](event):
            self._collector[1].append(event)
        elif self.on_event:
            self.on_event(event)

    def _take(self, timeout):
        """One event from the dongle, or None after `timeout` (a fake clock still returns promptly)."""
        try:
            return self.transport.inbox.get(timeout=min(max(timeout, 0.0), 0.2))
        except queue.Empty:
            return None

    def request(self, cmd, timeout=None, **fields):
        """Send one command and return its reply. Raises RadioError on an error reply, silence or disconnection."""
        timeout = self.REPLY_TIMEOUT if timeout is None else timeout
        request_id = uuid.uuid4().hex[:12]
        self.transport.send(dict(cmd=cmd, id=request_id, **fields))
        deadline = self.clock() + timeout
        while True:
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise RadioError(f'No reply to {cmd} from the radio within {timeout:g} s (not retried)')
            event = self._take(remaining)
            if event is None:
                continue
            if event.get('event') == 'disconnected':
                raise RadioError(f'Radio disconnected: {event.get("detail", "")}')
            if event.get('id') != request_id:
                self._dispatch(event)
                continue
            if event.get('event') == 'error':
                raise RadioError(event.get('detail', 'error'))
            return event

    def collect(self, seconds, keep=lambda event: True, ping=True):
        """Drain events for `seconds`, pinging as needed; return the ones `keep` accepts (others go to on_event)."""
        kept = []
        end = self.clock() + seconds
        self._collector = (keep, kept)
        try:
            while True:
                remaining = end - self.clock()
                if remaining <= 0:
                    return kept
                if ping and self.clock() - self.last_ping >= self.HEARTBEAT:
                    self.ping()  # events it drains on the way to the pong still land in `kept`
                event = self._take(remaining)
                if event is None:
                    continue
                if event.get('event') == 'disconnected':
                    raise RadioError(f'Radio disconnected: {event.get("detail", "")}')
                self._dispatch(event)
        finally:
            self._collector = None

    # ---- the pairing-station protocol ----
    def hello(self):
        self.info = self.request('hello')
        self.last_ping = self.clock()
        return self.info

    def status(self):
        """The board state without side effects; a plain relay (no `roles` in hello) only has hello for that."""
        return self.request('status') if self.roles else self.hello()

    def ping(self):
        self.last_ping = self.clock()
        return self.request('ping')

    def stop(self):
        return self.request('stop')

    def discover(self, wait=2.0):
        """Broadcast DISCOVER and return the unicast MACs that answered within `wait` seconds."""
        self.request('discover')
        found = self.collect(wait, lambda e: e.get('event') == 'device')
        macs = sorted({e['mac'].upper() for e in found if MAC_RE.match(e.get('mac', '')) and not int(e['mac'][:2], 16) & 1})
        return macs

    def identify(self, mac, duration_ms):
        return self.request('identify', mac=mac, duration_ms=int(duration_ms))

    def register(self, mac, cube_id, uid):
        return self.request('register', mac=mac, cube_id=int(cube_id), uid=uid)

    def zone_send(self, mac, frame):
        return self.request('zone_send', mac=mac, hex=bytes(frame).hex().upper())

    def zone_query(self, mac=BROADCAST, wait=2.0):
        """Ask zones for their status (all of them by default); one dict per answering zone, with its RSSI."""
        nonce = int(self.clock()) & 0xFFFFFFFF
        self.zone_send(mac, zonedb.query_frame(zonedb.QUERY_STATUS, nonce))

        def is_status(event):
            if event.get('event') != 'zone_frame':
                return False
            try:
                return zonedb.frame_kind(bytes.fromhex(event.get('hex', ''))) == zonedb.ZONE_STATUS
            except ValueError:
                return False
        zones = []
        for event in self.collect(wait, is_status):
            zone = zonedb.parse_status(bytes.fromhex(event['hex']))
            zone.update(mac=event.get('mac', '').upper(), rssi=event.get('rssi'))
            zones.append(zone)
        return zones

    # ---- the Mainshow verbs ----
    def _needs(self, what, ok):
        if not ok:
            raise RadioError(f'{what} needs a Workstation ({dongle.WORKSTATION.version}) or the general radio firmware; '
                             f'this board runs {self.firmware or "unknown firmware"}')

    def _show_capable(self):
        # The hello's `roles` decide; the firmware name only stands in when no hello has been read.
        return dongle.show_capable(self.info or self.firmware)

    def set_zone(self, target, zone):
        """MSG_SET_ZONE to one cube (MAC) or, spelled out, to 'broadcast' (every cube in range)."""
        self._needs('set_zone', self._show_capable())
        if int(zone) not in ZONES:
            raise RadioError('Zone must be 0-4')
        mac = 'broadcast' if str(target).lower() in ('broadcast', BROADCAST.lower()) else target
        return self.request('set_zone', mac=mac, zone=int(zone))

    def show_start(self, target='broadcast'):
        self._needs('show_start', self._show_capable())
        return self.request('show_start', target=target)

    # ---- the Workstation's own roles ----
    def pool(self, member, radio_id=None):
        """Hold pool lamp `member` (1-23) through the pool central; 0 releases. One lamp at a time per dongle."""
        self._needs('pool', 'pool' in self.roles or self.general)
        fields = dict(member=int(member))
        if radio_id is not None:
            fields['radio_id'] = int(radio_id)
        reply = self.request('pool', **fields)
        self.pool_held = int(member) != 0
        return reply

    def preshow(self, point, state):
        """Raise (state 1) or clear (state 0) TouchDesigner cue `point` (1-4) through the media bridge."""
        self._needs('preshow', 'preshow' in self.roles or self.general)
        reply = self.request('preshow', point=int(point), state=1 if state else 0)
        self.preshow_held = int(point) if state else None
        return reply

    def led_test(self, on):
        return self.request('led_test', on=1 if on else 0)

    def release(self):
        """Let go of whatever this client holds (a lamp, a cue). Safe to call when nothing is held."""
        errors = []
        for held, call in ((self.pool_held, lambda: self.pool(0)), (self.preshow_held, lambda: self.preshow(self.preshow_held, 0))):
            if held:
                try:
                    call()
                except RadioError as exc:
                    errors.append(str(exc))
        if errors:
            raise RadioError('; '.join(errors))

    def keepalive(self, seconds, release=True):
        """Keep the host lease alive for `seconds` (None: until interrupted), then release what is held."""
        nothing = lambda event: False  # everything the dongle says goes to on_event
        try:
            if seconds is None:
                while True:
                    self.collect(60, nothing)
            else:
                self.collect(seconds, nothing)
        finally:
            if release:
                self.release()


GeneralRadio = Workstation  # the client's name before the Workstation firmware


def resolve_target(db, text):
    """'broadcast', a MAC, or a cube number ('44' / '#44') looked up in the inventory -> MAC text."""
    text = str(text).strip()
    if text.lower() == 'broadcast':
        return 'broadcast'
    if MAC_RE.match(text):
        return text.upper()
    try:
        number = int(text.lstrip('#'))
    except ValueError:
        raise RadioError(f'{text!r} is not "broadcast", a MAC, or a cube number') from None
    roles = db.roles()
    row = next((r for r in db.rows() if r['cube_id'] == number), None)
    if row is None:
        raise RadioError(f'No cube #{number} in the inventory')
    if roles.get(row['mac']) == 'excluded':
        raise RadioError(f'#{number} ({row["mac"]}) is excluded from the inventory (a station or dongle), not a cube')
    return row['mac']


def find_port(path):
    """The port entry dongle.flash needs, or a RadioError naming what is attached."""
    wanted = hostos.canonical_port(path)
    ports = dongle.ports()
    for port in ports:
        if hostos.canonical_port(port['port']) == wanted:
            return port
    raise RadioError(f'{path} is not attached; ports: ' + (', '.join(p['port'] for p in ports) or 'none'))


def flash_workstation(path, database, emit=print, backup='always'):
    """Put the Workstation firmware on the spare ESP32-C3 at `path` (never a cube, zone or the station).

    Full-flash backup first, NVS untouched, then the board is recorded as `excluded` so the cube
    and zone flashers leave it alone. Returns the board's MAC.
    """
    port = find_port(path)
    db = Database(database, recover_pending=False)
    try:
        known = dongle.known_boards(db, ZoneStore(db).zones())
        folder = DATA / 'dongle' / time.strftime('%Y%m%d-%H%M%S')
        mac = dongle.flash(port, known, folder, lambda kind, value: emit(f'{kind}: {value}'), firmware=dongle.WORKSTATION, backup=backup)
        db.set_role(mac, 'excluded')
    finally:
        db.close()
    return mac


flash_general = flash_workstation  # the entry point's name before the Workstation firmware


# ---- command line ----

def parser():
    p = argparse.ArgumentParser(description='Drive a Workstation dongle (zones/firmware/Workstation; a legacy General Radio too).')
    p.add_argument('--port', required=True, help='serial port of the dongle')
    p.add_argument('--database', type=Path, default=DATA / 'devices.sqlite3', help='inventory for cube numbers')
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('hello', help='handshake and print the hello')
    sub.add_parser('status', help='print the board state without side effects')
    d = sub.add_parser('discover', help='which cubes answer DISCOVER')
    d.add_argument('--wait', type=float, default=2.0)
    z = sub.add_parser('zones', help='which zones answer a status query')
    z.add_argument('--wait', type=float, default=2.0)
    z.add_argument('--mac', default=BROADCAST)
    s = sub.add_parser('set-zone', help='MSG_SET_ZONE to a cube (number or MAC) or "broadcast"')
    s.add_argument('target')
    s.add_argument('zone', type=int, choices=sorted(ZONES))
    t = sub.add_parser('show-start', help='MSG_SHOW_START to a cube or "broadcast" (only mainshow-ready cubes start)')
    t.add_argument('target', nargs='?', default='broadcast')
    q = sub.add_parser('pool', help='hold one pool lamp (0 releases)')
    q.add_argument('member', type=int)
    q.add_argument('--radio-id', type=int, default=None)
    q.add_argument('--hold', type=float, default=None, help='seconds to keep the lamp, then release')
    w = sub.add_parser('preshow', help='a TouchDesigner cue through the media bridge')
    w.add_argument('point', type=int, choices=[1, 2, 3, 4])
    w.add_argument('state', choices=['on', 'off'])
    w.add_argument('--hold', type=float, default=None, help='seconds to hold the cue ON, then turn it off')
    li = sub.add_parser('listen', help='print every event while keeping the lease alive')
    li.add_argument('--seconds', type=float, default=None)
    f = sub.add_parser('flash', help='write the Workstation firmware to the spare board on --port')
    f.add_argument('--backup', choices=['first', 'always'], default='always')
    return p


def run(args, radio, db, out=print):
    """Execute one parsed command against an open `radio` (its hello done) and an open `db`."""
    if args.command == 'hello':
        out(json.dumps(radio.info))
        return
    if args.command == 'status':
        out(json.dumps(radio.status()))
        return
    if args.command == 'discover':
        out(json.dumps(dict(cubes=radio.discover(args.wait))))
        return
    if args.command == 'zones':
        out(json.dumps(dict(zones=radio.zone_query(args.mac, args.wait))))
        return
    if args.command == 'set-zone':
        out(json.dumps(radio.set_zone(resolve_target(db, args.target), args.zone)))
        radio.collect(0.6, lambda e: False)  # let the plate-style repeats go out before the port closes
        return
    if args.command == 'show-start':
        out(json.dumps(radio.show_start(resolve_target(db, args.target))))
        return
    if args.command == 'pool':
        out(json.dumps(radio.pool(args.member, args.radio_id)))
        if args.hold and args.member:
            radio.keepalive(args.hold)
            out(json.dumps(dict(released=True)))
        return
    if args.command == 'preshow':
        out(json.dumps(radio.preshow(args.point, args.state == 'on')))
        if args.hold and args.state == 'on':
            radio.keepalive(args.hold)
            out(json.dumps(dict(released=True)))
        return
    if args.command == 'listen':
        radio.keepalive(args.seconds, release=False)
        return
    raise RadioError(f'Unknown command {args.command}')


def main(argv=None, radio=None, db=None, out=print):
    args = parser().parse_args(argv)
    try:
        if args.command == 'flash':
            mac = flash_workstation(args.port, args.database, emit=out, backup=args.backup)
            out(json.dumps(dict(flashed=mac, firmware=dongle.WORKSTATION.version, role='excluded')))
            return 0
        own_radio, own_db = radio is None, db is None
        radio = radio or Workstation(on_event=lambda e: out(json.dumps(e)))
        db = db or Database(args.database, recover_pending=False)
        try:
            if own_radio:
                radio.open(args.port)
            run(args, radio, db, out)
        finally:
            if own_radio:
                radio.close()
            if own_db:
                db.close()
        return 0
    except (RadioError, RuntimeError, OSError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
