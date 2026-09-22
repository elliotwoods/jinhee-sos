"""Fake boards for running the console without hardware (--simulate) and for tests.

install(hub) replaces the scanner and prober with scripted ones and makes hub.make_transport()
return FakeTransport objects wired to FakeBoard models. Boards answer the same lines the firmware
prints, so the sessions, the advisor and the UI see realistic traffic.
"""
import paths  # noqa: F401
import json
import queue
import threading
import time
import uuid

import zonedb
from show_sim import FakeShowCube

BOARDS = {}      # port -> FakeBoard


class FakeBoard:
    role = 'unknown'
    kind = 'line'

    def __init__(self, port, mac):
        self.port, self.mac = port, mac
        self.transports = []

    def probe_lines(self):
        return []

    def handle(self, line):
        return []

    def unsolicited(self, now):
        return []

    def emit(self, *lines):
        for transport in list(self.transports):
            for line in lines:
                transport.receive(line)


class FakeCube(FakeBoard):
    role = 'cube'

    def __init__(self, port, mac, number=None, firmware='v1.4.1-USB.2'):
        super().__init__(port, mac)
        self.number, self.firmware = number, firmware
        self.zone = 0

    def report(self):
        return [f'FW: {self.firmware}', f'Cube MAC: {self.mac}', 'ESP-NOW CHANNEL: 2', 'Cube READY']

    def probe_lines(self):
        return self.report()

    def handle(self, line):
        return self.report() if line.strip() == '?' else []


class FakeZone(FakeBoard):
    role = 'zone'

    def __init__(self, port, mac, zone_type=1, point=1, name='Preshow 1', firmware='preshow-3.4.0', db_version=31,
                 db_count=32, db_crc=0x11E2A0F3, records=None, taps=()):
        super().__init__(port, mac)
        self.zone_type, self.point, self.name, self.firmware = zone_type, point, name, firmware
        self.db_version, self.db_count, self.db_crc = db_version, db_count, db_crc
        self.records = dict(records or {})   # uid -> (cube_id, mac)
        self.taps = list(taps)               # (delay_s, uid) scripted taps
        self.started = time.monotonic()
        self.polls = 0
        self.flashing = None
        self.stats = dict(tags=0, unknown=0, send_fail=0)
        self.nfc_ok = True
        self.media_mode = 'legacy'
        self.override = False

    def report(self):
        self.polls += 40
        lines = [f'FW: {self.firmware}', f'MAC: {self.mac}', 'CHANNEL: 2',
                 f'ZONE: type={self.zone_type} point={self.point} name={self.name}',
                 f'DB: version={self.db_version} count={self.db_count} crc={self.db_crc:08X} slot=A capacity=1819',
                 f'STATS: tags={self.stats["tags"]} unknown={self.stats["unknown"]} send_fail={self.stats["send_fail"]} error=0']
        if self.zone_type == 1:
            lines.append(f'MEDIA: mode={self.media_mode} point={self.point} state=none seq=0 acked=- ack_ms=0 bridge_sees_me=no '
                         'bridge_seen_ms=0 epoch=1 sent=0 legacy=0 retries=0 acks=0 failed=0 errors=0 bridge_mac=unknown (broadcast)')
        if self.zone_type == 3:
            lines.append('POOL: radio=%d cal1=383.0 cal23=43.0 laser=ok member=0 tune=saved' % self.point)
        lines.append(f'NFC: ok={1 if self.nfc_ok else 0} fw=00000132 polls={self.polls} found={self.stats["tags"]} last_ms=38 max_ms=52 '
                     f'fast_fail=0 recoveries=0 sda=1 scl=1 pins=4/3')
        lines.append('RXGAIN: stored=48dB applied=48dB')
        lines.append('READY')
        return lines

    def probe_lines(self):
        return self.report()

    def tap(self, uid):
        record = self.records.get(uid)
        self.stats['tags'] += 1
        if record:
            cube_id, mac = record
            return [f'TAG ENTER: {uid}', f'EVT TAG uid={uid} cube={cube_id} mac={mac} zone={self.zone_type}',
                    f'FOUND Cube #{cube_id}', f'Cube #{cube_id} DELIVERED',
                    f'EVT SENT cube={cube_id} type=6 value={self.zone_type} ok=1']
        self.stats['unknown'] += 1
        return [f'TAG ENTER: {uid}', f'EVT TAG uid={uid} cube=0 mac=- zone={self.zone_type}', 'UNKNOWN CUBE']

    def leave(self, uid):
        record = self.records.get(uid)
        return [f'TAG LEAVE: {uid}', f'EVT LEAVE uid={uid} cube={record[0] if record else 0} held_ms=1200']

    def handle(self, line):
        line = line.strip()
        if line == '?':
            return self.report()
        if line == 'nfc':
            return [self.report()[-3]]
        if line == 'nfc recover':
            self.nfc_ok = True
            return ['PN532 LOST: recovery requested', 'PN532 FOUND']
        if line == 'help':
            return ['Commands: ? | nfc | nfc recover | rfcfg | rxgain [18|23|33|38|43|48] | db | log | cube <id> | zone <id> <0-4> | clear <id> | flash <id> [s] | stop | help']
        if line == 'db':
            out = [f'CUBE {cid} uid={uid} mac={mac}' for uid, (cid, mac) in sorted(self.records.items(), key=lambda r: r[1][0])]
            return out + [f'DB END count={len(out)}']
        if line == 'log':
            return ['LOG END']
        if line == 'rfcfg':
            return ['RFCFG: CIU_RFCfg=0x69 rx_gain=48dB level_amp=0 rf_level=9']
        if line.startswith('rxgain'):
            parts = line.split()
            if len(parts) == 2:
                return [f'RXGAIN SET {parts[1]}dB: ok', f'RXGAIN: stored={parts[1]}dB applied={parts[1]}dB']
            return ['RXGAIN: stored=48dB applied=48dB']
        parts = line.split()
        if parts and parts[0] in ('cube', 'zone', 'clear', 'flash'):
            cube_id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            record = next(((uid, r) for uid, r in self.records.items() if r[0] == cube_id), None)
            if not record:
                return [f"ERR cube {cube_id} is not in this zone's database"]
            uid, (cid, mac) = record
            if parts[0] == 'cube':
                return [f'CUBE {cid} uid={uid} mac={mac}']
            if parts[0] == 'zone':
                value = int(parts[2]) if len(parts) > 2 else 0
                return [f'OK zone {cid} {value}', f'Cube #{cid} DELIVERED', f'EVT SENT cube={cid} type=6 value={value} ok=1']
            if parts[0] == 'clear':
                return [f'OK clear {cid}', f'EVT SENT cube={cid} type=6 value=0 ok=1']
            seconds = int(parts[2]) if len(parts) > 2 else 5
            self.flashing = (cid, time.monotonic() + seconds)
            return [f'OK flash {cid} {seconds}s']
        if line == 'stop':
            self.flashing = None
            return ['OK stop']
        if line.startswith('HOST'):
            return self.host(line)
        if line.startswith('CAL') or line.startswith('TUNE') or line.startswith('RAW'):
            return self.pool(line)
        return ['Unknown command; try help']

    def host(self, line):
        if line == 'HOST ARM':
            self.override = True
        elif line == 'HOST DISARM':
            self.override = False
        if self.zone_type == 3:
            return [json.dumps(dict(device='PoolZoneCalibration', type='interaction', override=self.override, active=False,
                                    output=0, radio=True, radio_id=self.point), separators=(',', ':'))]
        if self.zone_type == 1:
            return [json.dumps(dict(device='PreshowZone', type='host', armed=line != 'HOST DISARM', mode=self.media_mode,
                                    configured_point=self.point, firmware=self.firmware, point=self.point, state='OFF',
                                    seq=1, acked=False, ack_ms=0, bridge_sees_me=False, bridge_seen_ms=0, sent=0,
                                    legacy_sent=0, retries=0, acks=0, failed=0, errors=0, bridge_mac=None), separators=(',', ':'))]
        return ['OK']

    def pool(self, line):
        if line == 'CAL GET':
            ticks = [round(383 - i * (340 / 22), 1) for i in range(23)]
            return [json.dumps(dict(device='PoolZoneCalibration', type='calibration', saved=True, valid=True, ticks=ticks,
                                    anchors=(1 << 0) | (1 << 22), build_id='hsimulated'), separators=(',', ':'))]
        if line == 'TUNE GET':
            return [json.dumps(dict(device='PoolZoneCalibration', type='tuning', saved=True, min_cutoff_hz=1.0, beta=0.02,
                                    derivative_cutoff_hz=1.0, median_window=5, enter_frac=0.25, exit_frac=0.4, hold_ms=120,
                                    sample_ms=33, timing_budget_ms=33, inter_ms=0, settle_ms=200), separators=(',', ':'))]
        return ['OK']

    def unsolicited(self, now):
        out = []
        while self.taps and now - self.started >= self.taps[0][0]:
            _, uid = self.taps.pop(0)
            out += self.tap(uid)
            self.taps_pending_leave = (now + 1.5, uid)
        pending = getattr(self, 'taps_pending_leave', None)
        if pending and now >= pending[0]:
            out += self.leave(pending[1])
            self.taps_pending_leave = None
        if self.flashing and now >= self.flashing[1]:
            out.append(f'EVT FLASH cube={self.flashing[0]} done')
            self.flashing = None
        if self.zone_type == 3 and int(now * 10) % 5 == 0:
            distance = 200 + 50 * ((now // 2) % 3)
            out.append(json.dumps(dict(device='PoolZoneCalibration', type='sample', sensor=True, distance=distance,
                                       raw_distance=distance + 1.5, index=int(1 + (383 - distance) / 15.5)), separators=(',', ':')))
            out.append(json.dumps(dict(device='PoolZoneCalibration', type='interaction', override=self.override, active=False, output=0,
                                       tag=False, nfc=True, radio=True, radio_id=self.point, queued=0, send_errors=0, cube=0,
                                       delivery='', seq=12, unicast=True, central_sees_me=True, central_seen_ms=120,
                                       central_mac='AA:BB:CC:DD:EE:01', uid='', mac=self.mac), separators=(',', ':')))
        return out


class FakeStation(FakeBoard):
    role = 'station'
    kind = 'json'

    def __init__(self, port, mac, firmware='nct-pairing-1.8-zones', nfc_ok=True, cubes=(), zones=()):
        super().__init__(port, mac)
        self.firmware, self.nfc_ok = firmware, nfc_ok
        self.cubes = list(cubes)       # MACs that answer discovery
        self.zones = list(zones)       # FakeZone models reachable over the air
        self.identify = None
        self.register = None

    def hello(self, request_id):
        return dict(event='hello', id=request_id, protocol=1, firmware=self.firmware, zones=1, mac=self.mac, channel=2,
                    radio_ok=True, nfc_ok=self.nfc_ok, nfc_polling=self.nfc_ok, nfc_firmware='00000132',
                    nfc_i2c_status=0 if self.nfc_ok else 5, tag_present=False)

    def probe_lines(self):
        return [json.dumps(self.hello('boot'))]

    def handle_json(self, message):
        cmd, rid = message.get('cmd'), message.get('id', '')
        if cmd == 'hello':
            return [self.hello(rid)]
        if cmd == 'ping':
            return [dict(event='pong', id=rid)]
        if cmd == 'discover':
            out = [dict(event='discover_sent', id=rid)]
            out += [dict(event='device', mac=m) for m in self.cubes]
            return out
        if cmd == 'identify':
            self.identify = dict(mac=message.get('mac'), id=rid)
            return [dict(event='identifying', id=rid, mac=message.get('mac')),
                    dict(event='radio', id=rid, mac=message.get('mac'), type=6, status='delivered', detail=0)]
        if cmd == 'stop':
            self.identify = None
            return [dict(event='stopped', id=rid)]
        if cmd == 'register':
            mac = message.get('mac')
            return [dict(event='attempt', id=rid, mac=mac, attempt=1),
                    dict(event='radio', id=rid, mac=mac, type=3, status='delivered', detail=0),
                    dict(event='ack_received', id=rid, mac=mac, detail='Allowing cube confirmation blink to finish'),
                    dict(event='registered', id=rid, mac=mac, cube_id=message.get('cube_id'), acknowledged=True,
                         detail='Cube acknowledged; flash persistence not verified')]
        if cmd == 'nfc_status':
            return [dict(event='nfc_status', id=rid, firmware_now=self.nfc_ok, i2c_status=0 if self.nfc_ok else 5, nfc_polling=self.nfc_ok)]
        if cmd == 'nfc_recover':
            self.nfc_ok = True
            return [dict(event='nfc_recovered', id=rid, i2c_status=0)]
        if cmd == 'zone_send':
            out = [dict(event='zone_sent', id=rid, mac=message.get('mac'), kind=0, status='delivered')]
            try:
                frame = bytes.fromhex(message.get('hex', ''))
            except ValueError:
                return out
            if zonedb.frame_kind(frame) == zonedb.ZONE_QUERY:
                for z in self.zones:
                    out.append(dict(event='zone_frame', mac=z.mac, kind=zonedb.ZONE_STATUS, rssi=-61, hex=self.status_frame(z).hex().upper()))
            return out
        return [dict(event='error', id=rid, detail='Unknown command')]

    def status_frame(self, z):
        return zonedb.STATUS.pack(zonedb.MAGIC, zonedb.PROTO, zonedb.ZONE_STATUS, 0, z.zone_type, z.point, z.name.encode()[:16],
                                  z.firmware.encode()[:16], z.db_version, z.db_count, z.db_crc, 0, 0, 0, int(time.monotonic()),
                                  z.stats['tags'], z.stats['unknown'], z.stats['send_fail'], 0, 2, 1, 1)


class FakeGeneralRadio(FakeStation):
    """zones/firmware/GeneralRadio: the station protocol plus set_zone/show_start/pool/preshow/led_test/status.

    `central` / `bridge` are the MACs of a pool central and a preshow bridge in range: with them the
    board beacons (on hello/status and every 5 s), unicasts, acknowledges cues (`preshow_ack`) and
    reports the radio mask; without a bridge a cue is `preshow_fail`ed after 3 s, as the firmware does.
    Test hooks: `fail_radio()` (the driver stops answering: `fatal`, every later send refused until a
    `reboot()`), `expire_leases()` (the host lease lapsed: `pool_watchdog` / `preshow_watchdog`),
    `dead` (cube MACs whose frames are never acknowledged).
    """
    role = 'generalradio'
    LOCKOUT_S, SHOW_LENGTH_S, FAIL_AFTER_S, BEACON_EVERY_S = 3.0, 298.0, 3.0, 5.0

    def __init__(self, port, mac, cubes=(), zones=(), central=None, bridge=None, clock=time.monotonic):
        super().__init__(port, mac, firmware='general-radio-1.1.0', nfc_ok=False, cubes=cubes, zones=zones)
        self.show_cubes = {c: FakeShowCube(c, cube_id=0) for c in self.cubes}  # v1.5.0 cubes answering show frames
        self.show_length_ms, self.show_version, self.show_crc = 298000, 0, 0
        self.central, self.bridge, self.clock = central, bridge, clock
        self.pool = dict(armed=False, member=0, radio_id=1, central_mac=central or '', unicast=bool(central), radio_mask=0,
                         epoch=1000 if central else 0)
        self.preshow = dict(armed=False, point=0, state=0, seq=0, acked=False, ack_ms=0, bridge_mac=bridge or '', unicast=bool(bridge),
                            mode='modern' if bridge else 'legacy', bridge_sees_me=False)
        self.shows = 0
        self.last_show_id = 0
        self.last_show_at = None
        self.led = False
        self.sent = []
        self.radio_ok = True
        self.dead = set()
        self.unacked_since = None   # a cue ON with no bridge to acknowledge it
        self.last_beacon_at = None
        self.uptime_s = 0

    def hello(self, request_id, event='hello'):
        base = super().hello(request_id)
        now = self.clock()
        running = self.last_show_at is not None and now - self.last_show_at < self.SHOW_LENGTH_S
        base.update(event=event, radio_ok=self.radio_ok, roles=['cube', 'zone', 'pool', 'preshow'], led_pin=10, led_test=self.led,
                    host_fresh=True, busy='identify' if self.identify else 'idle', lockout_ms=3000, last_show_id=self.last_show_id,
                    shows=self.shows, show_running=running, show_length_ms=self.show_length_ms, show=1, timecode=True,
                    show_version=self.show_version, show_crc=self.show_crc,
                    tx=dict(sent=len(self.sent), delivered=len(self.sent), unconfirmed=0, no_result=0, rejected=0),
                    rx=dict(zone=0, zone_dropped=0, serial_overflows=0), pool=dict(self.pool), preshow=dict(self.preshow))
        return base

    def beacons(self):
        self.last_beacon_at = self.clock()
        self.uptime_s += 5
        out = []
        if self.central:
            out.append(dict(event='pool_beacon', id='', mac=self.central, epoch=self.pool['epoch'], uptime_s=self.uptime_s,
                            radio_mask=self.pool['radio_mask'], version=1))
        if self.bridge:
            mask = (1 << (self.preshow['point'] - 1)) if self.preshow['state'] and self.preshow['point'] else 0
            out.append(dict(event='preshow_beacon', id='', mac=self.bridge, epoch=500, uptime_s=self.uptime_s, point_mask=mask, version=1))
        return out

    def unsolicited(self, now):
        out = []
        if self.unacked_since is not None and now - self.unacked_since >= self.FAIL_AFTER_S:
            self.unacked_since = None
            out.append(dict(event='preshow_fail', id='', point=self.preshow['point'], state=self.preshow['state'], seq=self.preshow['seq']))
        if (self.central or self.bridge) and self.last_beacon_at is not None and now - self.last_beacon_at >= self.BEACON_EVERY_S:
            out += self.beacons()
        return out

    # ---- test hooks ----
    def fail_radio(self):
        self.radio_ok = False
        self.pool.update(armed=False, member=0)
        self.preshow.update(armed=False, state=0)
        self.emit(dict(event='fatal', id='', detail='Radio completion timeout; reboot the radio'))

    def reboot(self):
        self.radio_ok = True
        self.emit(self.hello(''))

    def expire_leases(self):
        if self.pool['armed']:
            self.pool.update(armed=False, member=0)
            self.emit(dict(event='pool_watchdog', id='', detail='host lease expired; member released', **self.pool))
        if self.preshow['armed']:
            self.preshow.update(armed=False, state=0, seq=self.preshow['seq'] + 1, acked=False)
            self.emit(dict(event='preshow_watchdog', id='', detail='host lease expired; cue turned off', **self.preshow))

    def handle_json(self, message):
        cmd, rid = message.get('cmd'), message.get('id', '')
        self.sent.append(cmd)
        if cmd == 'hello':
            return [self.hello(rid)] + self.beacons()
        if cmd == 'status':
            return [self.hello(rid, 'status')] + self.beacons()
        if cmd == 'led_test':
            self.led = bool(message.get('on'))
            return [dict(event='led_test', id=rid, on=self.led, pin=10)]
        if cmd.startswith('nfc_'):
            return [dict(event='error', id=rid, detail='No NFC reader on this radio')]
        if cmd in ('ping', 'stop'):
            return super().handle_json(message)
        if not self.radio_ok:
            return [dict(event='error', id=rid, detail='Radio unavailable; reboot the radio')]
        if cmd == 'set_zone':
            mac, zone = message.get('mac'), message.get('zone')
            status = 'unconfirmed' if mac == 'broadcast' or mac in self.dead else 'delivered'
            return [dict(event='zone_sent', id=rid, mac=mac, zone=zone, status=status, repeats=3),
                    dict(event='zone_repeat', id='', mac=mac, zone=zone, n=2, status=status),
                    dict(event='zone_repeat', id='', mac=mac, zone=zone, n=3, status=status)]
        if cmd == 'show_start':
            now = self.clock()
            if self.last_show_at is not None and now - self.last_show_at < self.LOCKOUT_S:
                return [dict(event='locked', id=rid, source='usb', retry_ms=int((self.LOCKOUT_S - (now - self.last_show_at)) * 1000))]
            self.shows += 1
            self.last_show_id += 7
            self.last_show_at = now
            target = message.get('target')
            out = dict(event='show_start', id=rid, source='usb', show_id=self.last_show_id, target=target, sent=5, repeats=5)
            if target != 'broadcast':
                out['delivered'] = 5
            return [out]
        if cmd == 'show_send':  # general-radio-1.1.0: relay to the simulated v1.5.0 cubes
            data = bytes.fromhex(message.get('hex', ''))
            mac = message.get('mac', '')
            out = [dict(event='show_sent', id=rid, mac=mac, kind=data[3] if len(data) > 3 else 0, status='delivered')]
            for cube_mac, cube in self.show_cubes.items():
                if mac in ('FF:FF:FF:FF:FF:FF', cube_mac):
                    out += [dict(event='show_frame', id='', mac=cube_mac, kind=0x53, rssi=-58, hex=reply.hex().upper())
                            for reply in cube.receive(data, broadcast=mac == 'FF:FF:FF:FF:FF:FF')]
            return out
        if cmd == 'show_config':
            self.show_length_ms = int(message.get('length_ms', 298000))
            self.show_version, self.show_crc = int(message.get('version', 0)), int(message.get('crc', 0))
            return [dict(event='show_config', id=rid, length_ms=self.show_length_ms, version=self.show_version, crc=self.show_crc)]
        if cmd == 'show_stop':
            running = self.last_show_at is not None and self.clock() - self.last_show_at < self.show_length_ms / 1000
            self.last_show_at = None
            return [dict(event='show_stop', id=rid, was_running=running, show_id=self.last_show_id)]
        if cmd == 'pool':
            member = int(message.get('member', 0))
            radio_id = int(message.get('radio_id', self.pool['radio_id']))
            self.pool.update(member=member, armed=member != 0, radio_id=radio_id,
                             radio_mask=(1 << (radio_id - 1)) if member and self.central else 0)
            return [dict(event='pool_state', id=rid, **self.pool)]
        if cmd == 'preshow':
            point, state = int(message.get('point', 0)), int(message.get('state', 0))
            if state and self.preshow['state'] and self.preshow['point'] != point:
                return [dict(event='error', id=rid, detail=f'Point {self.preshow["point"]} is still ON; turn it off first')]
            self.preshow.update(point=point, state=state, armed=bool(state) or self.preshow['armed'], seq=self.preshow['seq'] + 1, acked=False)
            out = [dict(event='preshow_state', id=rid, **self.preshow)]
            if self.bridge:
                self.preshow.update(acked=True, ack_ms=4, bridge_sees_me=bool(state))
                out.append(dict(event='preshow_ack', id='', point=point, state=state, seq=self.preshow['seq'], ms=4, applied=True))
                self.unacked_since = None
            else:
                self.unacked_since = self.clock()
            return out
        return super().handle_json(message)


class FakeTransport:
    """Looks like Transport (JSON) or LineTransport (lines) to a session; talks to a FakeBoard."""

    def __init__(self, hub, kind, board):
        self.hub, self.kind, self.board = hub, kind, board
        self.inbox = queue.Queue()
        self.port = None
        self.path = None
        self.stopping = threading.Event()
        self.last_poll = 0.0
        self.farewell = None

    def open(self, path):
        if self.board is None:
            raise RuntimeError(f'No simulated board on {path}')
        self.path, self.port = path, self
        self.is_open = True
        self.board.transports.append(self)
        self.stopping.clear()

    @property
    def is_open(self):
        return self.port is not None and not self.stopping.is_set()

    @is_open.setter
    def is_open(self, value):
        pass

    def receive(self, line):
        if self.kind == 'json':
            self.inbox.put(line if isinstance(line, dict) else dict(event='boot_log', detail=str(line)))
        else:
            self.inbox.put(('line', str(line)))

    def send(self, data):
        if not self.is_open:
            raise ValueError('Serial port is disconnected')
        if self.kind == 'json':
            for reply in self.board.handle_json(data):
                self.receive(reply)
        else:
            for reply in self.board.handle(str(data)):
                self.receive(reply)

    def poll(self, now):
        if self.is_open and now - self.last_poll >= 0.1:
            self.last_poll = now
            for line in self.board.unsolicited(now):
                self.receive(line)

    def write_now(self, line):
        pass

    def close(self, farewell=None):
        self.stopping.set()
        if farewell:
            self.farewell = farewell
        if self.board and self in self.board.transports:
            self.board.transports.remove(self)
        self.port = None


def fake_transport(hub, kind, session):
    board = BOARDS.get(session.device.port)
    transport = FakeTransport(hub, kind, board)
    hub._fake_transports.append(transport)
    return transport


class FakeScanner:
    def __init__(self):
        self.ports = []
        self.pending = True

    def start(self):
        return self

    def rescan(self):
        self.pending = True

    def latest(self):
        if self.pending:
            self.pending = False
            return list(self.ports)
        return None

    def stop(self):
        pass

    def add(self, board, key=None, candidate=True):
        BOARDS[board.port] = board
        self.ports.append(dict(port=board.port, key=key or board.mac, serial=board.mac, description='Simulated ESP32-C3',
                               candidate=candidate, native_usb=True, location=None))
        self.pending = True

    def remove(self, port):
        BOARDS.pop(port, None)
        self.ports = [p for p in self.ports if p['port'] != port]
        self.pending = True


class FakeProber:
    def __init__(self):
        self.results = queue.Queue()
        self.busy_with = None

    def start(self):
        return self

    def request(self, port):
        board = BOARDS.get(port['port'])
        if not board:
            self.results.put((port, None, None, [], 'No simulated board'))
            return
        from probe import classify
        lines = board.probe_lines()
        role, details = classify(lines)
        self.results.put((port, role, details, lines, None))

    def stop(self):
        pass


def install(hub, scenario='default'):
    hub.scanner = FakeScanner()
    hub.prober = FakeProber()
    hub._fake_transports = []
    original_tick = hub.tick

    def tick():
        now = hub.clock()
        for transport in list(hub._fake_transports):
            transport.poll(now)
        original_tick()

    hub.tick = tick
    if scenario == 'default':
        default_scenario(hub)
    elif scenario == 'empty':
        hub._sim = {}
        hub._sim_seed = lambda: None
    return hub


def default_scenario(hub):
    """A cube, a preshow plate holding an older database, a pool radio and a station that sees them."""
    known_uid, known_cube, known_mac = '04:A2:2B:1C:53:80:01', 44, 'A4:CF:12:34:56:78'
    plate = FakeZone('/dev/sim.preshow1', '14:63:93:C0:EC:14', records={'04:11:22:33:44:55:66': (12, '34:85:18:00:00:12')},
                     taps=[(6.0, '04:11:22:33:44:55:66'), (14.0, known_uid)])
    pool = FakeZone('/dev/sim.pool3', '14:63:93:C0:EC:33', zone_type=3, point=3, name='Pool Radio 3', firmware='pool-3.2.0',
                    db_version=32, db_crc=0x5A17C0DE)
    cube = FakeCube('/dev/sim.cube', known_mac, number=known_cube)
    station = FakeStation('/dev/sim.station', '30:ED:A0:5B:6D:D8', cubes=[known_mac, '34:85:18:00:00:12'], zones=[plate, pool])
    # As on the bench: the preshow bridge beacons (cues are acknowledged), no pool central is heard.
    radio = FakeGeneralRadio('/dev/sim.radio', '02:AA:BB:CC:DD:EE', cubes=[known_mac], zones=[plate], bridge='AC:27:6E:83:21:C4',
                             clock=hub.clock)
    for board in (station, plate, pool, cube, radio):
        hub.scanner.add(board)
    hub._sim = dict(known_uid=known_uid, known_cube=known_cube, known_mac=known_mac, plate=plate, pool=pool, cube=cube,
                    station=station, radio=radio)
    hub._sim_seed = lambda: seed_inventory(hub, known_mac, known_cube, known_uid)


def seed_inventory(hub, mac, number, uid):
    """Make the known cube a committed mapping so the unknown-tag rule can fire against the plate's older database."""
    db = hub.db
    row = db.get(mac)
    if not row:
        db.reserve(mac, source='simulated')
    try:
        if not db.get(mac)['cube_id']:
            db.rename(mac, number)
    except ValueError:
        pass
    try:
        db.prepare(mac, uid, take_over=True)
        db.result(mac, True, 'Simulated acknowledgment')
    except ValueError:
        pass
    hub.mark_dirty('inventory')
