"""Zone database publishing and zone monitoring over the pairing station's ESP-NOW relay.

The station firmware only validates and relays frames (`zone_send` / `zone_frame`); every frame is
built and parsed here with zones/tools/zonedb.py so byte layouts have a single Python definition.
"""
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'zones' / 'tools'))
import zonedb  # noqa: E402

BROADCAST = 'FF:FF:FF:FF:FF:FF'
ZONE_COLUMNS = ['name', 'zone_type', 'point_id', 'firmware', 'db_version', 'db_count', 'db_crc', 'staging_version',
                'staging_chunks', 'staging_total', 'uptime', 'tags', 'unknown_tags', 'send_fail', 'last_error', 'channel',
                'config_valid', 'active_slot']


def _now_iso():
    return time.strftime('%Y-%m-%dT%H:%M:%S%z')


class ZoneStore:
    """Published database version and last-known zone state, kept in the shared devices.sqlite3."""

    def __init__(self, db, wall=time.time):
        self.db, self.wall = db, wall
        self.conn = db.conn
        columns = ', '.join(f'{c} INTEGER' if c not in ('name', 'firmware') else f'{c} TEXT' for c in ZONE_COLUMNS)
        with self.conn:
            self.conn.execute(f'CREATE TABLE IF NOT EXISTS zones (mac TEXT PRIMARY KEY, {columns}, '
                              'last_seen TEXT, last_seen_epoch REAL, source TEXT, detail TEXT NOT NULL DEFAULT "")')
            existing = {r['name'] for r in self.conn.execute('PRAGMA table_info(zones)')}
            for column in ('profile', 'params'):  # written by the zone flasher
                if column not in existing:
                    self.conn.execute(f'ALTER TABLE zones ADD COLUMN {column} TEXT')

    def _meta(self, key, default=None):
        row = self.conn.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
        return row[0] if row else default

    def published(self):
        return dict(version=int(self._meta('zone_db_version', 0)), hash=self._meta('zone_db_hash', ''),
                    count=int(self._meta('zone_db_count', 0)), crc=int(self._meta('zone_db_crc', 0)),
                    published_at=self._meta('zone_db_published_at', ''))

    def records(self):
        rows = [r for r in self.db.rows() if not self.db.excluded(r['mac'])]
        return zonedb.records_from_rows(rows)

    def publish(self):
        """Returns a Publication of the current mappings, bumping the version only when content changed."""
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            records = self.records()
            digest = zonedb.content_hash(records)
            version = int(self._meta('zone_db_version', 0))
            if digest != self._meta('zone_db_hash'):
                version += 1
                publication = zonedb.Publication(version, records)
                for key, value in [('zone_db_version', version), ('zone_db_hash', digest), ('zone_db_count', len(records)),
                                   ('zone_db_crc', publication.crc), ('zone_db_published_at', _now_iso())]:
                    self.conn.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', (key, str(value)))
                self.db.event(None, 'zone_db_published', f'version {version}: {len(records)} records')
        return zonedb.Publication(version, records)

    def seen(self, mac, status, source='radio'):
        values = [status.get(c) for c in ZONE_COLUMNS]
        with self.conn:
            self.conn.execute(
                f'INSERT INTO zones (mac, {", ".join(ZONE_COLUMNS)}, last_seen, last_seen_epoch, source) '
                f'VALUES (?, {", ".join("?" * len(ZONE_COLUMNS))}, ?, ?, ?) '
                f'ON CONFLICT(mac) DO UPDATE SET {", ".join(f"{c}=excluded.{c}" for c in ZONE_COLUMNS)}, '
                'last_seen=excluded.last_seen, last_seen_epoch=excluded.last_seen_epoch, source=excluded.source',
                [mac] + values + [_now_iso(), self.wall(), source])

    def flashed(self, mac, profile, params):
        with self.conn:
            self.conn.execute('UPDATE zones SET profile=?, params=? WHERE mac=?', (profile, ','.join(str(v) for v in params), mac))

    def zones(self):
        return [dict(r) for r in self.conn.execute('SELECT * FROM zones ORDER BY zone_type, point_id, name, mac')]


class ZoneRegistry:
    QUERY_INTERVAL = 30
    CYCLE_PAUSE = 1.0
    PUBLISH_TIMEOUT = 180
    RECENT_ZONE = 15 * 60
    ACK_TIMEOUT = 1.0  # one relay command at a time: bursts overrun the station's USB serial buffer

    def __init__(self, db, send, log=print, clock=time.monotonic, wall=time.time):
        self.store = ZoneStore(db, wall)
        self.send, self.log, self.clock, self.wall = send, log, clock, wall
        self.requests = {}
        self.logs = {}
        self.publication = None
        self.publish_target = None
        self.publish_force = False
        self.publish_started = 0
        self.expected = set()
        self.queue = []
        self.next_cycle = 0
        self.next_query = 0
        self.cycles = 0
        self.send_failures = 0
        self.inflight, self.inflight_at = None, 0
        self.message = ''

    # ---- commands ----
    def _emit(self, mac, frame, purpose):
        request = uuid.uuid4().hex
        self.requests[request] = purpose
        if len(self.requests) > 500:
            for key in list(self.requests)[:250]:
                del self.requests[key]
        self.send(dict(cmd='zone_send', id=request, mac=mac, hex=frame.hex().upper()))
        return request

    def require(self, station, connected):
        if not connected:
            raise ValueError('Connect the station first')
        if station.get('zones') != zonedb.PROTO:
            raise ValueError('Station firmware has no zone support; reflash the pairing station (nct-pairing-1.6-zones)')

    def publish(self, target=None, force=False):
        """Broadcast the current database until every recently seen zone (or `target`) has it."""
        if force and not target:
            raise ValueError('Forced (rollback) publishing must target a single zone')
        self.publication = self.store.publish()
        self.publish_target, self.publish_force = target, force
        self.publish_started = self.clock()
        cutoff = self.wall() - self.RECENT_ZONE
        self.expected = ({target} if target else
                         {z['mac'] for z in self.store.zones() if (z['last_seen_epoch'] or 0) >= cutoff})
        self.queue, self.next_cycle, self.cycles, self.send_failures = [], 0, 0, 0
        p = self.publication
        self.message = f'Publishing database v{p.version} ({p.count} records, {p.chunk_count} chunks)'
        self.log(self.message + (f' to {target}' if target else f'; waiting for {len(self.expected)} known zone(s)'))
        return p

    def stop(self, reason='Publishing stopped'):
        if self.publication:
            self.message = reason
            self.log(reason)
        self.publication, self.queue, self.expected = None, [], set()

    def query(self, what=zonedb.QUERY_STATUS, mac=BROADCAST):
        self.next_query = self.clock() + self.QUERY_INTERVAL
        return self._emit(mac, zonedb.query_frame(what, int(self.wall()) & 0xFFFFFFFF), 'query')

    def request_log(self, mac):
        return self.query(zonedb.QUERY_LOG, mac)

    def identify(self, mac, seconds=10):
        return self._emit(mac, zonedb.identify_frame(seconds), 'identify')

    def reboot(self, mac):
        return self._emit(mac, zonedb.reboot_frame(), 'reboot')

    # ---- progress ----
    def zone_rows(self):
        published = self.store.published()
        now = self.wall()
        rows = []
        for z in self.store.zones():
            z = dict(z)
            z['age_s'] = None if z['last_seen_epoch'] is None else max(0, now - z['last_seen_epoch'])
            z['current'] = bool(published['version']) and z['db_version'] == published['version'] and z['db_crc'] == published['crc']
            z['error_text'] = zonedb.ERRORS.get(z['last_error'] or 0, f'error {z["last_error"]}')
            z['zone_label'] = zonedb.ZONE_TYPES.get(z['zone_type'], 'unconfigured' if not z['config_valid'] else str(z['zone_type']))
            z['log'] = self.logs.get(z['mac'])
            rows.append(z)
        return rows

    def snapshot(self):
        return dict(published=self.store.published(), publishing=self.publishing_state(), zones=self.zone_rows(),
                    message=self.message)

    def publishing_state(self):
        if not self.publication:
            return None
        pending = sorted(self.expected - self._updated())
        return dict(version=self.publication.version, target=self.publish_target, force=self.publish_force,
                    cycles=self.cycles, expected=sorted(self.expected), pending=pending,
                    elapsed_s=round(self.clock() - self.publish_started, 1), send_failures=self.send_failures)

    def _updated(self):
        p = self.publication
        return {z['mac'] for z in self.store.zones() if p and z['db_version'] == p.version and z['db_crc'] == p.crc}

    # ---- station events ----
    def event(self, e):
        """Returns True when the event belonged to the zone registry."""
        kind = e.get('event')
        if kind == 'zone_frame':
            try:
                data = bytes.fromhex(e.get('hex', ''))
                frame = zonedb.frame_kind(data)
                if frame == zonedb.ZONE_STATUS:
                    self._status(e['mac'], zonedb.parse_status(data))
                elif frame == zonedb.ZONE_LOG:
                    self.logs[e['mac']] = dict(zonedb.parse_log(data), received=_now_iso())
                    self.log(f'Zone {e["mac"]} log: {len(self.logs[e["mac"]]["entries"])} recent tag(s)')
            except (ValueError, KeyError) as exc:
                self.log(f'Ignored malformed zone frame: {exc}')
            return True
        if kind == 'zone_sent':
            if e.get('id') == self.inflight:
                self.inflight = None
            if e.get('status') not in ('delivered',):
                self.send_failures += 1
            return True
        if kind == 'error' and e.get('id') in self.requests:
            if e.get('id') == self.inflight:
                self.inflight = None
            self.log(f'Zone command rejected by station: {e.get("detail")}')
            return True
        return False

    def _status(self, mac, status):
        previous = next((z for z in self.store.zones() if z['mac'] == mac), None)
        self.store.seen(mac, status)
        if previous and previous['db_version'] != status['db_version']:
            self.log(f'Zone {status["name"] or mac}: database v{previous["db_version"]} → v{status["db_version"]}')
        if status['last_error'] and (not previous or previous['last_error'] != status['last_error']):
            self.log(f'Zone {status["name"] or mac}: {zonedb.ERRORS.get(status["last_error"], status["last_error"])}')
        if self.publication and not self.publish_target:
            self.expected.add(mac)

    def tick(self, connected, station, busy=False):
        if not connected or station.get('zones') != zonedb.PROTO:
            if self.publication:
                self.stop('Publishing paused: station disconnected')
            return
        now = self.clock()
        if self.publication:
            p = self.publication
            if self.cycles and self.expected and not (self.expected - self._updated()):
                self.stop(f'Database v{p.version} confirmed on {len(self.expected)} zone(s)')
            elif now - self.publish_started > self.PUBLISH_TIMEOUT:
                missing = sorted(self.expected - self._updated())
                self.stop(f'Publishing v{p.version} timed out; not confirmed: {", ".join(missing) or "no zones answered"}')
            else:
                if not self.queue and now >= self.next_cycle:
                    self.queue = ['announce'] + list(range(p.chunk_count))
                if self.inflight and now - self.inflight_at >= self.ACK_TIMEOUT:
                    self.inflight = None
                    self.send_failures += 1
                spacing = 0.3 if busy else 0  # stay out of the way of pairing traffic
                if self.queue and not self.inflight and now - self.inflight_at >= spacing:
                    item = self.queue.pop(0)
                    mac = self.publish_target or BROADCAST
                    frame = p.announce_frame(self.publish_force) if item == 'announce' else p.chunk_frame(item)
                    self.inflight = self._emit(mac if item == 'announce' else BROADCAST, frame, 'publish')
                    self.inflight_at = now
                    if not self.queue:
                        self.cycles += 1
                        self.next_cycle = now + self.CYCLE_PAUSE
                pending = len(self.expected - self._updated())
                self.message = f'Publishing v{p.version}: cycle {self.cycles + 1}, {pending} zone(s) pending'
        if now >= self.next_query and not self.inflight:
            self.query()
