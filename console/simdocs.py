"""Simulation extras for documentation screenshots and the handover verification tests.

Everything here builds on simulate.py without editing it: subclasses of the fake boards that can be
staged into the states the handover chapters describe (a registration held at TAG DETECTED, a
publish run that confirms, a preshow cue that reports ON, a calibration that answers CAL SET),
a fake Mainshow controller, scripted jobs that show a flash in progress without esptool, and
helpers that seed a published zone database or a canned sync status.

`install(hub)` = the "docs" scenario (`app.py --simulate --scenario docs`).
"""
import paths  # noqa: F401
import base64
import json
import threading
import time

import zonedb

import simulate
from jobs.base import Job


class DocStation(simulate.FakeStation):
    """A pairing station whose tag scans and registrations can be scripted step by step."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.hold_register = False
        self.pending_register = None
        self.hold_publish = False
        self.pending_publish = None
        self.tag_present = False

    # ---- NFC scans ----
    def scan_clear(self):
        self.tag_present = False
        self.emit(dict(event='tag_state', id='', present=False))

    def scan(self, uid):
        """A tag arrives on the reader; the `tag` event carries the live identify request id (controller gate)."""
        self.tag_present = True
        self.emit(dict(event='tag_state', id='', present=True))
        rid = (self.identify or {}).get('id', '')
        self.emit(dict(event='tag', id=rid, uid=uid))

    def handle_json(self, message):
        cmd, rid = message.get('cmd'), message.get('id', '')
        if cmd == 'register' and self.hold_register:
            mac = message.get('mac')
            self.pending_register = dict(id=rid, mac=mac, cube_id=message.get('cube_id'))
            return [dict(event='attempt', id=rid, mac=mac, attempt=1),
                    dict(event='radio', id=rid, mac=mac, type=3, status='delivered', detail=0)]
        out = super().handle_json(message)
        if cmd == 'zone_send':
            self._watch_publish(message)
        if cmd == 'hello':
            out[0]['tag_present'] = self.tag_present
        return out

    def release_register(self, ack=True):
        p, self.pending_register = self.pending_register, None
        if not p:
            return
        if ack:
            self.emit(dict(event='ack_received', id=p['id'], mac=p['mac'], detail='Allowing cube confirmation blink to finish'))
        self.emit(dict(event='registered', id=p['id'], mac=p['mac'], cube_id=p['cube_id'], acknowledged=bool(ack),
                       detail='Cube acknowledged; flash persistence not verified' if ack else
                       'No matching acknowledgment after three attempts'))

    # ---- database distribution ----
    def _watch_publish(self, message):
        try:
            frame = bytes.fromhex(message.get('hex', ''))
        except ValueError:
            return
        kind = zonedb.frame_kind(frame)
        if kind == zonedb.DB_ANNOUNCE:
            _, _, _, version, count, chunk_count, per_chunk, flags, crc = zonedb.ANNOUNCE.unpack(frame)
            self.pending_publish = dict(version=version, count=count, chunk_count=chunk_count, crc=crc, chunks=set(),
                                        target=message.get('mac'), force=bool(flags & zonedb.ANNOUNCE_FORCE))
        elif kind == zonedb.DB_CHUNK and self.pending_publish:
            _, _, _, version, index, n = zonedb.CHUNK_HEADER.unpack_from(frame)
            if version == self.pending_publish['version']:
                self.pending_publish['chunks'].add(index)
                if len(self.pending_publish['chunks']) >= self.pending_publish['chunk_count'] and not self.hold_publish:
                    self.release_publish()

    def release_publish(self):
        """The zones that were listening take the announced version (what a real plate does after every chunk arrived)."""
        p, self.pending_publish = self.pending_publish, None
        if not p:
            return
        target = (p.get('target') or '').upper()
        for z in self.zones:
            if target not in ('', 'FF:FF:FF:FF:FF:FF') and z.mac.upper() != target:
                continue
            if z.db_version < p['version'] or p['force']:
                z.db_version, z.db_count, z.db_crc = p['version'], p['count'], p['crc']
                z.emit(f'DB UPDATE: staging version {p["version"]} ({p["count"]} records, {p["chunk_count"]} chunks)',
                       f'DB UPDATE: committed version {p["version"]} ({p["count"]} records, slot B)')


class DocZone(simulate.FakeZone):
    """A plate/radio with a settable preshow cue state, real CAL/TUNE replies and a steady slider reading."""

    def __init__(self, *a, fixed_distance=None, **k):
        super().__init__(*a, **k)
        self.fixed_distance = fixed_distance
        self.host_state, self.host_point, self.host_seq, self.host_armed = 'OFF', 0, 0, False
        self.ticks = [round(383 - i * (340 / 22), 1) for i in range(23)]
        self.anchors = (1 << 0) | (1 << 22)
        self.cal_saved = True
        self.tuning = dict(min_cutoff_hz=0.8, beta=0.03, derivative_cutoff_hz=1.0, enter_frac=0.33, exit_frac=0.45, confirm_ms=50,
                           release_ms=120, dropout_ms=400, timing_budget_ms=20, interval_ms=0, median_window=3)
        self.tuning_saved = True
        self.raw_stream = False
        self.raw_t = 0

    def report(self):
        lines = super().report()
        if self.zone_type == 0:
            lines = [line if not line.startswith('ZONE:') else 'ZONE: unconfigured' for line in lines]
        return lines

    def host(self, line):
        if self.zone_type != 1:
            return super().host(line)
        if line == 'HOST ARM':
            self.host_armed = True
        elif line == 'HOST DISARM':
            self.host_armed = False
            self.host_state = 'OFF'
        elif line.startswith('HOST ON'):
            parts = line.split()
            point = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
            if not self.host_armed:
                return ['ERR HOST: send HOST ARM first']
            if self.host_state == 'ON' and self.host_point != point:
                return [f'ERR HOST: point {self.host_point} is still ON; turn it off first']
            self.host_state, self.host_point, self.host_seq = 'ON', point, self.host_seq + 1
        elif line == 'HOST OFF':
            if self.host_state == 'ON':
                self.host_seq += 1
            self.host_state = 'OFF'
        return [json.dumps(dict(device='PreshowZone', type='host', armed=self.host_armed, mode=self.media_mode,
                                configured_point=self.point, firmware=self.firmware, point=self.host_point or self.point,
                                state=self.host_state, seq=self.host_seq, acked=self.media_mode == 'modern' and self.host_state == 'ON',
                                ack_ms=42 if self.media_mode == 'modern' else 0, bridge_sees_me=self.media_mode == 'modern',
                                bridge_seen_ms=120 if self.media_mode == 'modern' else 0, sent=self.host_seq, legacy_sent=self.host_seq,
                                retries=0, acks=self.host_seq if self.media_mode == 'modern' else 0, failed=0, errors=0,
                                bridge_mac='AA:BB:CC:DD:EE:02' if self.media_mode == 'modern' else None), separators=(',', ':'))]

    def calibration_json(self):
        return json.dumps(dict(device='PoolZoneCalibration', type='calibration', saved=self.cal_saved, valid=True,
                               ticks=list(self.ticks), anchors=self.anchors, build_id='hsimulated'), separators=(',', ':'))

    def tuning_json(self):
        return json.dumps(dict(device='PoolZoneCalibration', type='tuning', saved=self.tuning_saved, defaults=dict(self.tuning),
                               **self.tuning), separators=(',', ':'))

    def pool(self, line):
        parts = line.split()
        if line == 'CAL GET':
            return [self.calibration_json()]
        if parts[0] == 'CAL' and len(parts) >= 2:
            if parts[1] == 'SET' and len(parts) == 4:
                index, mm = int(parts[2]), float(parts[3])
                if not 1 <= index <= 23 or not 10 <= mm <= 1000:
                    return ['ERR CAL SET: index 1-23, distance 10-1000 mm']
                self.ticks[index - 1] = round(mm, 1)
                self.anchors |= 1 << (index - 1)
                self.cal_saved = False
                return [self.calibration_json()]
            if parts[1] == 'SAVE':
                self.cal_saved = True
                return [self.calibration_json()]
            if parts[1] == 'LOAD':
                return [self.calibration_json()]
            if parts[1] == 'ANCHORS' and len(parts) == 3:
                self.anchors = int(parts[2])
                return [self.calibration_json()]
        if parts[0] == 'TUNE':
            if parts[1] == 'GET':
                return [self.tuning_json()]
            if parts[1] == 'SET' and len(parts) == 4:
                import recording as rec
                key = rec.JSON_KEYS.get(parts[2])
                if not key:
                    return ['ERR TUNE SET: unknown key or value out of range']
                value = float(parts[3])
                self.tuning[key] = int(value) if rec.FIELDS[parts[2]][1] else value
                self.tuning_saved = False
                return [self.tuning_json()]
            if parts[1] == 'SAVE':
                self.tuning_saved = True
                return [self.tuning_json()]
            if parts[1] in ('LOAD', 'DEFAULTS'):
                return [self.tuning_json()]
        if parts[0] == 'RAW':
            self.raw_stream = parts[1] == 'ON'
            return [f'OK RAW {"ON" if self.raw_stream else "OFF"} dropped=0']
        return super().pool(line)

    def unsolicited(self, now):
        if self.zone_type != 3 or self.fixed_distance is None:
            return super().unsolicited(now)
        out = [line for line in super().unsolicited(now) if '"type":"sample"' not in line and '"type":"interaction"' not in line]
        distance = float(self.fixed_distance)
        index = self._index(distance)
        out.append(json.dumps(dict(device='PoolZoneCalibration', type='sample', sensor=True, distance=distance,
                                   raw_distance=distance + 0.4, index=index), separators=(',', ':')))
        out.append(json.dumps(dict(device='PoolZoneCalibration', type='interaction', override=self.override, active=self.override,
                                   output=index if self.override else 0, tag=False, nfc=True, radio=True, radio_id=self.point, queued=0,
                                   send_errors=0, cube=0, delivery='', seq=12, unicast=True, central_sees_me=True,
                                   central_seen_ms=120, central_mac='AA:BB:CC:DD:EE:01', uid='', mac=self.mac), separators=(',', ':')))
        if self.raw_stream:
            self.raw_t += 100
            out.append(json.dumps(dict(device='PoolZoneCalibration', type='raw', t=self.raw_t, mm=round(distance + 0.4, 1), st=0),
                                  separators=(',', ':')))
        return out

    def _index(self, distance):
        best = min(range(23), key=lambda i: abs(self.ticks[i] - distance))
        return best + 1


class FakeMainshow(simulate.FakeBoard):
    """zones/firmware/MainshowController: JSON hello, set_zone, show_start, led_test, plus BOOT/trigger events on demand."""
    role = 'mainshow'
    kind = 'json'

    def __init__(self, port, mac, firmware='mainshow-1.2.0'):
        super().__init__(port, mac)
        self.firmware = firmware
        self.shows = 0
        self.last_show_id = 0
        self.led = False
        self.locked_until = 0.0

    def hello(self, rid):
        return dict(event='hello', id=rid, firmware=self.firmware, mac=self.mac, channel=2, radio_ok=True, button_pin=9,
                    trigger_pin=3, lockout_ms=3000, rearm_ms=1000, last_show_id=self.last_show_id, shows=self.shows,
                    led_pin=10, led_test=self.led, show_running=False, show_length_ms=298000)

    def probe_lines(self):
        return [json.dumps(self.hello(''))]

    def handle_json(self, message):
        cmd, rid = message.get('cmd'), message.get('id', '')
        if cmd == 'hello':
            return [self.hello(rid)]
        if cmd == 'ping':
            return [dict(event='pong', id=rid)]
        if cmd == 'led_test':
            self.led = bool(message.get('on'))
            return [dict(event='led_test', id=rid, on=self.led, pin=10)]
        if cmd == 'set_zone':
            return [dict(event='zone_sent', id=rid, mac=message.get('mac'), zone=message.get('zone'), status='delivered')]
        if cmd == 'show_start':
            now = time.monotonic()
            if now < self.locked_until:
                return [dict(event='locked', id=rid, source='usb', retry_ms=int((self.locked_until - now) * 1000))]
            self.locked_until = now + 3.0
            self.shows += 1
            self.last_show_id += 12345
            target = message.get('target')
            out = dict(event='show_start', id=rid, source='usb', show_id=self.last_show_id, target=target, sent=5, repeats=5)
            if target != 'broadcast':
                out['delivered'] = 5
            return [out]
        return [dict(event='error', id=rid, detail='Unknown command')]


# ---------------------------------------------------------------- staging helpers
def scripted_job(hub, device, kind, title, steps, outcome, hold_at=None, after=None, result=None):
    """A job that shows progress like a real flash without touching esptool: `steps` = [(stage, progress, log)],
    pausing at `hold_at` percent until release_job()."""
    job = Job(kind, device.key, title, hardware=True, device=device.id)
    release = threading.Event()
    hub._sim.setdefault('jobs', {})[job.id] = release
    hub.hold_port(device, job)

    def work(emit, cancel):
        for stage, progress, log in steps:
            if stage:
                emit('stage', stage)
            if log:
                emit('log', log)
            emit('progress', progress)
            if hold_at is not None and progress >= hold_at and not release.is_set():
                release.wait(600)
            time.sleep(0.03)
        return result or dict(result='success')

    def done(job):
        job.outcome = outcome
        if after:
            after(hub)
        hub.mark_dirty('devices', 'inventory')

    hub.jobs.start(job, work, done)
    return job


def release_job(hub, job_id=None):
    jobs = hub._sim.get('jobs', {})
    for jid, event in list(jobs.items()):
        if job_id in (None, jid):
            event.set()


def doc_hold(hub, device_id):
    hub._sim.setdefault('holds', set()).add(device_id)


def doc_release(hub, device_id):
    hub._sim.setdefault('holds', set()).discard(device_id)


def seed_publication(hub, version=32):
    """Cache this computer's committed mappings as published version `version` (what a Sync + publish would leave)."""
    records = hub.store.records()
    body = zonedb.pack_records(records)
    publication = zonedb.Publication(version, records)
    doc = dict(version=version, records_b64=base64.b64encode(body).decode(), count=publication.count, crc=publication.crc,
               hash=zonedb.content_hash(records), published_at='2026-09-23T10:00:00+09:00', published_by='documentation pass')
    hub.store.cache(doc)
    hub.mark_dirty('inventory', 'registry')
    return publication


def docs_sync(hub, state='ok', up=0, down=0, inventory_up=0, inventory_down=0, zone_publish=False, zone_pull=False,
              web_version=None, local_version=None, waiting=0, lost=0, message=None, password_known=True):
    status = dict(state=state, up=up, down=down, conflicts=0, lost=lost, inventory_up=inventory_up, inventory_down=inventory_down,
                  zone_publish=zone_publish, zone_pull=zone_pull, waiting=waiting, web_version=web_version,
                  local_version=local_version if local_version is not None else hub.store.published()['version'])
    if message:
        status['message'] = message
    hub.sync.update(status=status, checked_at=hub.wall(), password_known=password_known)
    hub.mark_dirty('sync')


def docs_boards(hub):
    """The documentation bench: station, preshow plate (older database), pool radio, two cubes, a General Radio,
    a Mainshow controller and a blank zone board."""
    known_uid, known_mac = '04:A2:2B:1C:53:80:01', 'A4:CF:12:34:56:78'
    plate = DocZone('/dev/sim.preshow1', '14:63:93:C0:EC:14', records={'04:11:22:33:44:55:66': (12, '34:85:18:00:00:12')})
    pool = DocZone('/dev/sim.pool3', '14:63:93:C0:EC:33', zone_type=3, point=3, name='Pool Radio 3', firmware='pool-3.2.0',
                   db_version=32, db_crc=0x5A17C0DE, fixed_distance=212.0)
    blank = DocZone('/dev/sim.newzone', '14:63:93:C0:EC:50', zone_type=0, point=0, name='', db_version=0, db_count=0, db_crc=0)
    cube = simulate.FakeCube('/dev/sim.cube', known_mac, number=44)
    cube45 = simulate.FakeCube('/dev/sim.cube2', 'A4:CF:12:34:56:79', number=45)
    station = DocStation('/dev/sim.station', '30:ED:A0:5B:6D:D8', cubes=[known_mac, cube45.mac, '34:85:18:00:00:12'],
                         zones=[plate, pool, blank])
    radio = simulate.FakeGeneralRadio('/dev/sim.radio', '02:AA:BB:CC:DD:EE', cubes=[known_mac], zones=[plate])
    mainshow = FakeMainshow('/dev/sim.mainshow', '30:ED:A0:5B:6D:E0')
    for board in (station, plate, pool, cube, cube45, radio, mainshow, blank):
        hub.scanner.add(board)
    hub._sim.update(known_uid=known_uid, known_cube=44, known_mac=known_mac, plate=plate, pool=pool, blank=blank, cube=cube,
                    cube45=cube45, station=station, radio=radio, mainshow=mainshow)


def install(hub):
    """The `docs` scenario: simulate.install(empty) + the documentation bench + lease touches for held panels."""
    simulate.install(hub, 'empty')
    hub._sim = {}
    docs_boards(hub)
    inner = hub.tick

    def tick():
        now = hub.clock()
        for device_id in list(hub._sim.get('holds', ())):
            session = hub.sessions.get(device_id)
            if session is None:
                continue
            if hasattr(session, 'last_touch'):
                session.last_touch = now
            if hasattr(session, 'last_pool_touch'):
                session.last_pool_touch = session.last_preshow_touch = now
        inner()

    hub.tick = tick
    hub._sim_seed = lambda: seed_inventory(hub)
    return hub


def seed_inventory(hub):
    """Cube #44 committed with its tag; cube #45 numbered without a tag (as a label already on the cube)."""
    s = hub._sim
    db = hub.db
    for mac, number in ((s['known_mac'], 44), (s['cube45'].mac, 45)):
        if not db.get(mac):
            db.reserve(mac, source='simulated')
        if db.get(mac)['cube_id'] != number:
            db.rename(mac, number)
    try:
        db.prepare(s['known_mac'], s['known_uid'], take_over=True)
        db.result(s['known_mac'], True, 'Simulated acknowledgment')
    except ValueError:
        pass
    hub.mark_dirty('inventory')
