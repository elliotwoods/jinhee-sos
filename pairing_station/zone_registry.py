"""Zone database distribution and zone monitoring over an ESP-NOW relay (pairing-station firmware).

The station firmware only validates and relays frames (`zone_send` / `zone_frame`); every frame is
built and parsed here with zones/tools/zonedb.py so byte layouts have a single Python definition.

Versions are universal: the web inventory allocates them (zone_publish.py) and this computer caches
the published image in metadata. Zones accept only a higher version, so nothing here allocates one.
"""
import base64
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'zones' / 'tools'))
import zonedb  # noqa: E402
import sightings  # noqa: E402

BROADCAST = 'FF:FF:FF:FF:FF:FF'
ZONE_COLUMNS = ['name', 'zone_type', 'point_id', 'firmware', 'db_version', 'db_count', 'db_crc', 'staging_version',
                'staging_chunks', 'staging_total', 'uptime', 'tags', 'unknown_tags', 'send_fail', 'last_error', 'channel',
                'config_valid', 'active_slot']
# Reported in ZONE_SETTINGS (after each status, zone firmware desert-2.4.0 / tagplate-2.4.0 / pool-3.2.0 /
# preshow-3.3.0 and later, relayed by nct-pairing-1.8-zones). NULL: never reported.
SETTINGS_COLUMNS = ['rx_gain', 'rx_gain_applied', 'set_result']


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
            for column in SETTINGS_COLUMNS:
                if column not in existing:
                    self.conn.execute(f'ALTER TABLE zones ADD COLUMN {column} INTEGER')

    def _meta(self, key, default=None):
        row = self.conn.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
        return row[0] if row else default

    def published(self):
        return dict(version=int(self._meta('zone_db_version', 0)), hash=self._meta('zone_db_hash', ''),
                    count=int(self._meta('zone_db_count', 0)), crc=int(self._meta('zone_db_crc', 0)),
                    published_at=self._meta('zone_db_published_at', ''), published_by=self._meta('zone_db_published_by', ''),
                    universal=self._meta('zone_db_records') is not None)

    def records(self):
        """Committed mappings on this computer (what the next publication would contain)."""
        rows = [r for r in self.db.rows() if not self.db.excluded(r['mac'])]
        return zonedb.records_from_rows(rows)

    def current(self):
        """The published database as a Publication, from the cached web copy.

        Before the first web publication, a legacy local publication is still usable when this
        computer's mappings still match its hash. Raises ValueError when nothing is available.
        """
        cached = self._meta('zone_db_records')
        published = self.published()
        if cached is not None:
            records = zonedb.unpack_records(base64.b64decode(cached))
        elif published['version'] and published['hash']:
            records = self.records()
            if zonedb.content_hash(records) != published['hash']:
                raise ValueError(f'Local mappings changed since database v{published["version"]}; '
                                 'publish a new version in the Zone Database Manager')
        else:
            raise ValueError('No zone database published yet; publish one in the Zone Database Manager')
        publication = zonedb.Publication(published['version'], records)
        if publication.crc != published['crc'] or publication.count != published['count']:
            raise ValueError('Cached zone database is inconsistent; pull it again from the web')
        return publication

    def local_differs(self):
        """True when this computer's mappings differ from the published database."""
        try:
            return zonedb.content_hash(self.records()) != self.published()['hash']
        except ValueError:
            return True

    def cache(self, doc):
        """Store a web zone-database document (see web/src/lib/zonedb.ts) as the published database."""
        body = base64.b64decode(doc['records_b64'])
        records = zonedb.unpack_records(body)
        publication = zonedb.Publication(int(doc['version']), records)
        if (publication.count, publication.crc, zonedb.content_hash(records)) != (doc['count'], doc['crc'], doc['hash']):
            raise ValueError('Web zone database failed verification')
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            if int(self._meta('zone_db_version', 0)) >= publication.version and self._meta('zone_db_hash') == doc['hash'] \
                    and self._meta('zone_db_records') is not None:
                return False  # already cached
            if int(self._meta('zone_db_version', 0)) > publication.version:
                return False  # never go back (also above a legacy local counter: publish to lift the web version)
            for key, value in [('zone_db_version', publication.version), ('zone_db_hash', doc['hash']),
                               ('zone_db_count', publication.count), ('zone_db_crc', publication.crc),
                               ('zone_db_published_at', doc.get('published_at') or ''),
                               ('zone_db_published_by', doc.get('published_by') or ''),
                               ('zone_db_records', base64.b64encode(body).decode())]:
                self.conn.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', (key, str(value)))
            self.db.event(None, 'zone_db_cached', f'version {publication.version}: {publication.count} records')
        return True

    def highest_seen(self):
        """Highest database version any known zone has reported."""
        row = self.conn.execute('SELECT MAX(db_version) FROM zones').fetchone()
        return int(row[0] or 0)

    def seen(self, mac, status, source='radio'):
        values = [status.get(c) for c in ZONE_COLUMNS]
        with self.conn:
            self.conn.execute(
                f'INSERT INTO zones (mac, {", ".join(ZONE_COLUMNS)}, last_seen, last_seen_epoch, source) '
                f'VALUES (?, {", ".join("?" * len(ZONE_COLUMNS))}, ?, ?, ?) '
                f'ON CONFLICT(mac) DO UPDATE SET {", ".join(f"{c}=excluded.{c}" for c in ZONE_COLUMNS)}, '
                'last_seen=excluded.last_seen, last_seen_epoch=excluded.last_seen_epoch, source=excluded.source',
                [mac] + values + [_now_iso(), self.wall(), source])

    def settings(self, mac, settings):
        with self.conn:
            self.conn.execute(f'UPDATE zones SET {", ".join(f"{c}=?" for c in SETTINGS_COLUMNS)} WHERE mac=?',
                              [settings.get(c) for c in SETTINGS_COLUMNS] + [mac])

    def flashed(self, mac, profile, params):
        with self.conn:
            self.conn.execute('UPDATE zones SET profile=?, params=? WHERE mac=?', (profile, ','.join(str(v) for v in params), mac))

    def zones(self):
        return [dict(r) for r in self.conn.execute('SELECT * FROM zones ORDER BY zone_type, point_id, name, mac')]


class ZoneRegistry:
    QUERY_INTERVAL = 30
    AUTO_QUERY_INTERVAL = 3
    IN_RANGE = 20  # seconds since a zone last answered
    CYCLE_PAUSE = 1.0
    PUBLISH_TIMEOUT = 180
    WALK_TIMEOUT = 45
    WALK_BACKOFF = 30
    RECENT_ZONE = 15 * 60
    SET_TIMEOUT = 10  # seconds for a zone to report a requested setting back
    ACK_TIMEOUT = 1.0  # one relay command at a time: bursts overrun the station's USB serial buffer

    def __init__(self, db, send, log=print, clock=time.monotonic, wall=time.time, auto_refresh=False):
        self.store = ZoneStore(db, wall)
        self.send, self.log, self.clock, self.wall = send, log, clock, wall
        self.auto_refresh = auto_refresh
        self.walkaround = False
        self.backoff = {}  # mac -> clock time before walkaround retries it
        self.requests = {}
        self.logs = {}
        self.gain_requests = {}  # mac -> (requested dB, clock) until the zone's ZONE_SETTINGS confirms it
        self.rssi = {}  # mac -> smoothed RSSI (dBm) reported by the dongle (pairing-station firmware 1.7+)
        self.publication = None
        self.publish_target = None
        self.publish_force = False
        self.publish_started = 0
        self.publish_timeout = self.PUBLISH_TIMEOUT
        self.walk_run = False
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
            raise ValueError('Station firmware has no zone support; reflash the pairing station (nct-pairing-1.8-zones)')

    def publish(self, target=None, force=False, expected=None, timeout=None):
        """Broadcast the published database until the expected zones confirm it.

        Expected zones: `target` alone, the given set, or every zone seen in the last 15 minutes.
        """
        if force and not target:
            raise ValueError('Forced (rollback) publishing must target a single zone')
        self.publication = self.store.current()
        self.publish_target, self.publish_force = target, force
        self.publish_started = self.clock()
        self.publish_timeout = timeout or self.PUBLISH_TIMEOUT
        self.walk_run = False
        cutoff = self.wall() - self.RECENT_ZONE
        self.expected = ({target} if target else set(expected) if expected is not None else
                         {z['mac'] for z in self.store.zones() if (z['last_seen_epoch'] or 0) >= cutoff})
        self.queue, self.next_cycle, self.cycles, self.send_failures = [], 0, 0, 0
        p = self.publication
        self.message = f'Publishing database v{p.version} ({p.count} records, {p.chunk_count} chunks)'
        self.log(self.message + (f' to {target}' if target else f'; waiting for {len(self.expected)} zone(s)'))
        return p

    def set_auto_refresh(self, enabled):
        self.auto_refresh = bool(enabled)
        self.next_query = 0  # apply the new interval now

    def set_walkaround(self, enabled):
        self.walkaround = bool(enabled)
        self.backoff.clear()
        self.next_query = 0
        if not enabled and self.walk_run:
            self.stop('Auto update all stopped')

    def update(self, mac):
        """Update one zone (unicast announce; never forced, so a zone never goes back a version)."""
        return self.publish(target=mac, timeout=self.WALK_TIMEOUT)

    def stop(self, reason='Publishing stopped'):
        if self.publication:
            self.message = reason
            self.log(reason)
        self.publication, self.queue, self.expected, self.walk_run = None, [], set(), False

    def query(self, what=zonedb.QUERY_STATUS, mac=BROADCAST):
        self.next_query = self.clock() + (self.AUTO_QUERY_INTERVAL if self.auto_refresh or self.walkaround else self.QUERY_INTERVAL)
        return self._emit(mac, zonedb.query_frame(what, int(self.wall()) & 0xFFFFFFFF), 'query')

    def request_log(self, mac):
        return self.query(zonedb.QUERY_LOG, mac)

    def identify(self, mac, seconds=10):
        return self._emit(mac, zonedb.identify_frame(seconds), 'identify')

    def reboot(self, mac):
        return self._emit(mac, zonedb.reboot_frame(), 'reboot')

    def set_rx_gain(self, mac, rx_gain):
        """Ask one zone to store and apply a PN532 RX gain. Success is only its next ZONE_SETTINGS report."""
        frame = zonedb.set_config_frame(rx_gain)
        self.gain_requests[mac] = (int(rx_gain), self.clock())
        self.log(f'Zone {mac}: set RX gain {rx_gain} dB requested')
        return self._emit(mac, frame, 'set_config')

    # ---- progress ----
    def classify(self, zone, published):
        """current / behind / ahead / updating / unpublished. `ahead` covers a higher version or the same
        version with different content (a legacy per-computer counter); only a new publication fixes it."""
        if not published['version']:
            return 'unpublished'
        if zone['db_version'] == published['version'] and zone['db_crc'] == published['crc']:
            return 'current'
        if zone['staging_version'] == published['version'] and zone['staging_total']:
            return 'updating'
        if (zone['db_version'] or 0) < published['version']:
            return 'behind'
        return 'ahead'

    def zone_rows(self):
        published = self.store.published()
        now = self.wall()
        rows = []
        for z in self.store.zones():
            z = dict(z)
            z['age_s'] = None if z['last_seen_epoch'] is None else max(0, now - z['last_seen_epoch'])
            z['in_range'] = z['age_s'] is not None and z['age_s'] <= self.IN_RANGE and z['source'] == 'radio'
            z['state'] = self.classify(z, published)
            z['current'] = z['state'] == 'current'
            z['error_text'] = zonedb.ERRORS.get(z['last_error'] or 0, f'error {z["last_error"]}')
            z['zone_label'] = zonedb.ZONE_TYPES.get(z['zone_type'], 'unconfigured' if not z['config_valid'] else str(z['zone_type']))
            z['log'] = self.logs.get(z['mac'])
            z['rssi'] = self.rssi.get(z['mac'])
            z['rx_gain_pending'] = self.gain_requests.get(z['mac'], (None,))[0]
            rows.append(z)
        return rows

    def snapshot(self):
        return dict(published=self.store.published(), publishing=self.publishing_state(), zones=self.zone_rows(),
                    message=self.message, auto_refresh=self.auto_refresh, walkaround=self.walkaround)

    def publishing_state(self):
        if not self.publication:
            return None
        pending = sorted(self.expected - self._updated())
        return dict(version=self.publication.version, target=self.publish_target, force=self.publish_force, walk=self.walk_run,
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
                if isinstance(e.get('rssi'), int) and -127 <= e['rssi'] < 0:
                    previous = self.rssi.get(e['mac'])
                    self.rssi[e['mac']] = e['rssi'] if previous is None else 0.7 * previous + 0.3 * e['rssi']
                if frame == zonedb.ZONE_STATUS:
                    self._status(e['mac'], zonedb.parse_status(data))
                elif frame == zonedb.ZONE_SETTINGS:
                    self._settings(e['mac'], zonedb.parse_settings(data))
                elif frame == zonedb.ZONE_LOG:
                    self.logs[e['mac']] = dict(zonedb.parse_log(data), received=_now_iso())
                    self.log(f'Zone {e["mac"]} log: {len(self.logs[e["mac"]]["entries"])} recent tag(s)')
                    # Cube "last seen" at this zone for the web inventory (best effort).
                    sightings.zone_taps(self.store.db.conn, e['mac'], self.logs[e['mac']]['entries'], self.wall())
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

    def _settings(self, mac, settings):
        previous = next((z for z in self.store.zones() if z['mac'] == mac), None)
        if not previous:
            return  # settings follow a status; without one there is no row to annotate yet
        self.store.settings(mac, settings)
        request = self.gain_requests.get(mac)
        if not request:
            return
        result = settings['set_result']
        # The reply to the request itself carries nonce 0; a routine query answered in the same moment carries
        # its own nonce and the old state, so only a matching gain or a nonce-0 failure settles the request.
        stored = settings['rx_gain'] == request[0] and result in (zonedb.SET_OK, zonedb.SET_NOT_APPLIED)
        failed = settings['nonce'] == 0 and result not in (zonedb.SET_NONE, zonedb.SET_OK, zonedb.SET_NOT_APPLIED)
        if stored or failed:
            del self.gain_requests[mac]
            self.log(f'Zone {previous["name"] or mac}: RX gain {request[0]} dB — {zonedb.SET_RESULTS.get(result, result)}'
                     + (f' (still {settings["rx_gain"]} dB)' if failed else ''))

    def _status(self, mac, status):
        previous = next((z for z in self.store.zones() if z['mac'] == mac), None)
        self.store.seen(mac, status)
        if previous and previous['firmware'] != status['firmware']:
            self.store.settings(mac, {})  # a reflashed zone must report its settings again
        if previous and previous['db_version'] != status['db_version']:
            self.log(f'Zone {status["name"] or mac}: database v{previous["db_version"]} → v{status["db_version"]}')
        if status['last_error'] and (not previous or previous['last_error'] != status['last_error']):
            self.log(f'Zone {status["name"] or mac}: {zonedb.ERRORS.get(status["last_error"], status["last_error"])}')
        if self.publication and not self.publish_target and status['db_version'] < self.publication.version:
            self.expected.add(mac)  # a zone that came into range and needs this version joins the run

    def walk_candidates(self):
        now = self.clock()
        return sorted(z['mac'] for z in self.zone_rows()
                      if z['in_range'] and z['state'] == 'behind' and self.backoff.get(z['mac'], 0) <= now)

    def tick(self, connected, station, busy=False):
        if not connected or station.get('zones') != zonedb.PROTO:
            if self.publication:
                self.stop('Publishing paused: station disconnected')
            return
        now = self.clock()
        for mac, (gain, at) in list(self.gain_requests.items()):
            if now - at > self.SET_TIMEOUT:
                del self.gain_requests[mac]
                self.log(f'Zone {mac}: RX gain {gain} dB not confirmed (no answer; zone or dongle firmware may be too old)')
        if self.publication:
            p = self.publication
            if self.cycles and self.expected and not (self.expected - self._updated()):
                self.stop(f'Database v{p.version} confirmed on {len(self.expected)} zone(s)')
            elif now - self.publish_started > self.publish_timeout:
                missing = sorted(self.expected - self._updated())
                if self.walk_run:
                    for mac in missing:
                        self.backoff[mac] = now + self.WALK_BACKOFF
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
        elif self.walkaround and not self.inflight:
            candidates = self.walk_candidates()
            if candidates:
                # One broadcast run updates every out-of-date zone in range at once.
                self.publish(expected=candidates, timeout=self.WALK_TIMEOUT)
                self.walk_run = True
                self.message = f'Auto update all: updating {len(candidates)} zone(s) to v{self.publication.version}'
        if now >= self.next_query and not self.inflight:
            self.query()
