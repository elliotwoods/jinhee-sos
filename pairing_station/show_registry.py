"""Main show distribution to neocubes over an ESP-NOW relay dongle.

The relay only validates and forwards frames: `show_send {mac, hex}` answered by `show_sent {status}`,
and cube replies arrive as `show_frame {mac, rssi, hex}` (General Radio firmware). Every frame is
built and parsed by showfile.py, which mirrors NctShowProtocol.h.

Versions are universal: the web allocates them (show_publish.py) and this computer caches the published
image in metadata. A cube accepts only a higher version (FORCE works on one cube, unicast only), so
nothing here allocates one. A cube never commits while its show runs; distribution also pauses while
the Mainshow controller reports a running show, so the update traffic stays off the air during a show.
"""
import base64
import hashlib
import json
import time
import uuid
from datetime import datetime

import showfile

BROADCAST = 'FF:FF:FF:FF:FF:FF'
CUBE_COLUMNS = ['version', 'crc', 'length', 'source', 'staging_version', 'staging_chunks', 'staging_total', 'cube_id',
                'last_error', 'zone', 'show_running', 'pending_commit', 'uptime_s', 'fw']
META = 'show_'


def _now_iso():
    return datetime.now().astimezone().strftime('%Y-%m-%dT%H:%M:%S%z')


def image_hash(image):
    return hashlib.sha256(image).hexdigest()


class Publication:
    def __init__(self, version, image, doc=None):
        self.version, self.image = int(version), bytes(image)
        self.doc = doc if doc is not None else showfile.unpack(self.image)
        self.crc = showfile.crc32(self.image)
        self.hash = image_hash(self.image)
        self.chunks = showfile.chunks(self.version, self.image)

    @property
    def chunk_count(self):
        return len(self.chunks)

    def announce_frame(self, force=False):
        return showfile.announce(self.version, self.image, force)


class ShowStore:
    """Published show and last-known cube show state, kept in the shared devices.sqlite3."""

    def __init__(self, db, wall=time.time):
        self.db, self.wall, self.conn = db, wall, db.conn
        columns = ', '.join(f'{c} TEXT' if c in ('source', 'fw') else f'{c} INTEGER' for c in CUBE_COLUMNS)
        with self.conn:
            self.conn.execute(f'CREATE TABLE IF NOT EXISTS show_cubes (mac TEXT PRIMARY KEY, {columns}, '
                              'last_seen TEXT, last_seen_epoch REAL)')

    def _meta(self, key, default=None):
        row = self.conn.execute('SELECT value FROM metadata WHERE key=?', (META + key,)).fetchone()
        return row[0] if row else default

    def published(self):
        return dict(version=int(self._meta('version', 0)), hash=self._meta('hash', ''), crc=int(self._meta('crc', 0)),
                    length=int(self._meta('length', 0)), published_at=self._meta('published_at', ''),
                    published_by=self._meta('published_by', ''))

    def current(self):
        """The published show as a Publication. Raises ValueError when none has been pulled or published."""
        image = self._meta('image')
        published = self.published()
        if image is None or not published['version']:
            raise ValueError('No show published yet; publish one from the Show editor')
        source = self._meta('source')
        doc = showfile.validate(json.loads(source)) if source else None
        publication = Publication(published['version'], base64.b64decode(image), doc)
        if publication.crc != published['crc'] or publication.hash != published['hash']:
            raise ValueError('Cached show is inconsistent; pull it again from the web')
        return publication

    def cache(self, doc):
        """Store a web show document (see web/src/lib/show.ts). Never goes back a version."""
        image = base64.b64decode(doc['image_b64'])
        source = showfile.validate(doc['source']) if doc.get('source') else showfile.unpack(image)
        if showfile.pack(source) != image:
            raise ValueError('Web show source does not match its image')
        publication = Publication(int(doc['version']), image, source)
        if (publication.crc, publication.hash, len(image)) != (doc['crc'], doc['hash'], doc['length']):
            raise ValueError('Web show failed verification')
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            if int(self._meta('version', 0)) >= publication.version:
                return False  # already cached, or never go back
            for key, value in [('version', publication.version), ('hash', publication.hash), ('crc', publication.crc),
                               ('length', len(image)), ('published_at', doc.get('published_at') or ''),
                               ('published_by', doc.get('published_by') or ''),
                               ('image', base64.b64encode(image).decode()),
                               ('source', json.dumps(source, separators=(',', ':')))]:
                self.conn.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', (META + key, str(value)))
            self.db.event(None, 'show_cached', f'show version {publication.version}: {len(source["cues"])} cues')
        return True

    def highest_seen(self):
        row = self.conn.execute('SELECT MAX(version) FROM show_cubes').fetchone()
        return int(row[0] or 0)

    def seen(self, mac, status):
        values = [status.get(c) for c in CUBE_COLUMNS]
        with self.conn:
            self.conn.execute(
                f'INSERT INTO show_cubes (mac, {", ".join(CUBE_COLUMNS)}, last_seen, last_seen_epoch) '
                f'VALUES (?, {", ".join("?" * len(CUBE_COLUMNS))}, ?, ?) '
                f'ON CONFLICT(mac) DO UPDATE SET {", ".join(f"{c}=excluded.{c}" for c in CUBE_COLUMNS)}, '
                'last_seen=excluded.last_seen, last_seen_epoch=excluded.last_seen_epoch',
                [mac] + values + [_now_iso(), self.wall()])

    def cubes(self):
        return [dict(r) for r in self.conn.execute('SELECT * FROM show_cubes ORDER BY cube_id, mac')]


class ShowRegistry:
    QUERY_INTERVAL = 30
    AUTO_QUERY_INTERVAL = 5
    REPLY_JITTER_MS = 2000   # ~140 cubes answer a broadcast query spread over this window
    IN_RANGE = 20            # seconds since a cube last answered
    CYCLE_PAUSE = 1.0
    PUBLISH_TIMEOUT = 180
    WALK_TIMEOUT = 45
    WALK_BACKOFF = 30
    RECENT_CUBE = 15 * 60
    ACK_TIMEOUT = 1.0        # one relay command at a time

    def __init__(self, db, send, log=print, clock=time.monotonic, wall=time.time, auto_refresh=False):
        self.store = ShowStore(db, wall)
        self.db = db
        self.send, self.log, self.clock, self.wall = send, log, clock, wall
        self.auto_refresh = auto_refresh
        self.walkaround = False
        self.backoff = {}
        self.requests = {}
        self.rssi = {}
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
        self.held = False
        self.message = ''

    # ---- commands ----
    def _emit(self, mac, frame, purpose):
        request = uuid.uuid4().hex
        self.requests[request] = purpose
        if len(self.requests) > 500:
            for key in list(self.requests)[:250]:
                del self.requests[key]
        self.send(dict(cmd='show_send', id=request, mac=mac, hex=frame.hex().upper()))
        return request

    def publish(self, target=None, force=False, expected=None, timeout=None):
        """Send the published show until the expected cubes confirm it.

        Expected cubes: `target` alone, the given set, or every cube heard in the last 15 minutes.
        """
        if force and not target:
            raise ValueError('A forced (rollback) show update must target a single cube')
        self.publication = self.store.current()
        self.publish_target, self.publish_force = target, force
        self.publish_started = self.clock()
        self.publish_timeout = timeout or self.PUBLISH_TIMEOUT
        self.walk_run = False
        cutoff = self.wall() - self.RECENT_CUBE
        self.expected = ({target} if target else set(expected) if expected is not None else
                         {c['mac'] for c in self.store.cubes() if (c['last_seen_epoch'] or 0) >= cutoff})
        self.queue, self.next_cycle, self.cycles, self.send_failures = [], 0, 0, 0
        p = self.publication
        self.message = f'Sending show v{p.version} ({len(p.image)} bytes, {p.chunk_count} chunks)'
        self.log(self.message + (f' to {target}' if target else f'; waiting for {len(self.expected)} cube(s)'))
        return p

    def update(self, mac):
        return self.publish(target=mac, timeout=self.WALK_TIMEOUT)

    def set_auto_refresh(self, enabled):
        self.auto_refresh = bool(enabled)
        self.next_query = 0

    def set_walkaround(self, enabled):
        self.walkaround = bool(enabled)
        self.backoff.clear()
        self.next_query = 0
        if not enabled and self.walk_run:
            self.stop('Auto update stopped')

    def stop(self, reason='Show update stopped'):
        if self.publication:
            self.message = reason
            self.log(reason)
        self.publication, self.queue, self.expected, self.walk_run = None, [], set(), False

    def query(self, mac=BROADCAST):
        self.next_query = self.clock() + (self.AUTO_QUERY_INTERVAL if self.auto_refresh or self.walkaround else self.QUERY_INTERVAL)
        return self._emit(mac, showfile.query(int(self.wall()) & 0xFFFFFFFF, self.REPLY_JITTER_MS), 'query')

    # ---- progress ----
    def classify(self, cube, published):
        """current / behind / ahead / updating / pending / unpublished."""
        if not published['version']:
            return 'unpublished'
        if cube['version'] == published['version'] and cube['crc'] == published['crc']:
            return 'current'
        if cube['staging_version'] == published['version'] and cube['pending_commit']:
            return 'pending'   # complete; commits when the cube's show ends
        if cube['staging_version'] == published['version'] and cube['staging_total']:
            return 'updating'
        if (cube['version'] or 0) < published['version']:
            return 'behind'
        return 'ahead'

    def cube_rows(self):
        published = self.store.published()
        numbers = {r['mac']: r['cube_id'] for r in self.db.rows()}
        now = self.wall()
        rows = []
        for c in self.store.cubes():
            c = dict(c)
            c['number'] = numbers.get(c['mac'], c['cube_id'] or None)
            c['age_s'] = None if c['last_seen_epoch'] is None else max(0, now - c['last_seen_epoch'])
            c['in_range'] = c['age_s'] is not None and c['age_s'] <= self.IN_RANGE
            c['state'] = self.classify(c, published)
            c['error_text'] = showfile.ERRORS.get(c['last_error'] or 0, f'error {c["last_error"]}')
            c['rssi'] = self.rssi.get(c['mac'])
            rows.append(c)
        return rows

    def publishing_state(self):
        if not self.publication:
            return None
        pending = sorted(self.expected - self._updated())
        return dict(version=self.publication.version, target=self.publish_target, force=self.publish_force,
                    walk=self.walk_run, cycles=self.cycles, expected=sorted(self.expected), pending=pending,
                    elapsed_s=round(self.clock() - self.publish_started, 1), send_failures=self.send_failures,
                    held=self.held)

    def snapshot(self):
        return dict(published=self.store.published(), publishing=self.publishing_state(), cubes=self.cube_rows(),
                    message=self.message, auto_refresh=self.auto_refresh, walkaround=self.walkaround)

    def _updated(self):
        p = self.publication
        return {c['mac'] for c in self.store.cubes() if p and c['version'] == p.version and c['crc'] == p.crc}

    # ---- relay events ----
    def event(self, e):
        """Returns True when the event belonged to the show registry."""
        kind = e.get('event')
        if kind == 'show_frame':
            try:
                data = bytes.fromhex(e.get('hex', ''))
                if isinstance(e.get('rssi'), int) and -127 <= e['rssi'] < 0:
                    previous = self.rssi.get(e['mac'])
                    self.rssi[e['mac']] = e['rssi'] if previous is None else 0.7 * previous + 0.3 * e['rssi']
                if showfile.frame_type(data) == showfile.SHOW_STATUS:
                    self._status(e['mac'], showfile.parse_status(data))
            except (ValueError, KeyError) as exc:
                self.log(f'Ignored malformed show frame: {exc}')
            return True
        if kind == 'show_sent':
            if e.get('id') == self.inflight:
                self.inflight = None
            if e.get('status') not in ('delivered',) and e.get('mac', BROADCAST) != BROADCAST:
                self.send_failures += 1
            return True
        if kind == 'error' and e.get('id') in self.requests:
            if e.get('id') == self.inflight:
                self.inflight = None
            self.log(f'Show command rejected by the radio: {e.get("detail")}')
            return True
        return False

    def _status(self, mac, status):
        previous = next((c for c in self.store.cubes() if c['mac'] == mac), None)
        self.store.seen(mac, status)
        label = f'Cube #{status["cube_id"]}' if status['cube_id'] else f'Cube {mac}'
        if previous and previous['version'] != status['version']:
            self.log(f'{label}: show v{previous["version"]} → v{status["version"]}')
        if status['error'] and (not previous or previous['last_error'] != status['error']):
            self.log(f'{label}: {status["error_text"]}')
        if self.publication and not self.publish_target and (status['version'] or 0) < self.publication.version:
            self.expected.add(mac)  # a cube that came into range and needs this show joins the run

    def walk_candidates(self):
        now = self.clock()
        return sorted(c['mac'] for c in self.cube_rows()
                      if c['in_range'] and c['state'] == 'behind' and self.backoff.get(c['mac'], 0) <= now)

    def tick(self, connected, show_running=False):
        """Drive distribution. `show_running`: the Mainshow controller says a show is on; hold everything."""
        if not connected:
            if self.publication:
                self.stop('Show update paused: radio disconnected')
            return
        now = self.clock()
        self.held = bool(show_running)
        if self.held:
            if self.publication:
                # The run's timeout keeps counting: a 5 minute show outlasts it, and the operator restarts.
                self.message = f'Show v{self.publication.version}: waiting, a show is running'
            return
        if self.publication:
            p = self.publication
            if self.cycles and self.expected and not (self.expected - self._updated()):
                self.stop(f'Show v{p.version} confirmed on {len(self.expected)} cube(s)')
            elif now - self.publish_started > self.publish_timeout:
                missing = sorted(self.expected - self._updated())
                if self.walk_run:
                    for mac in missing:
                        self.backoff[mac] = now + self.WALK_BACKOFF
                self.stop(f'Show v{p.version} timed out; not confirmed: {", ".join(missing) or "no cubes answered"}')
            else:
                if not self.queue and now >= self.next_cycle:
                    self.queue = ['announce'] + list(range(p.chunk_count)) + ['query']
                if self.inflight and now - self.inflight_at >= self.ACK_TIMEOUT:
                    self.inflight = None
                    self.send_failures += 1
                if self.queue and not self.inflight:
                    item = self.queue.pop(0)
                    if item == 'query':
                        self.inflight = self.query(self.publish_target or BROADCAST)
                        # The replies need the jitter window before the next cycle.
                        self.next_cycle = now + max(self.CYCLE_PAUSE, self.REPLY_JITTER_MS / 1000 + 0.5)
                        self.cycles += 1
                    elif item == 'announce':
                        self.inflight = self._emit(self.publish_target or BROADCAST, p.announce_frame(self.publish_force), 'publish')
                    else:
                        self.inflight = self._emit(BROADCAST, p.chunks[item], 'publish')
                    self.inflight_at = now
                pending = len(self.expected - self._updated())
                self.message = f'Sending show v{p.version}: cycle {self.cycles + 1}, {pending} cube(s) pending'
            return
        if self.walkaround and not self.inflight:
            candidates = self.walk_candidates()
            if candidates:
                try:
                    self.publish(expected=candidates, timeout=self.WALK_TIMEOUT)
                except ValueError as exc:
                    self.message = str(exc)
                else:
                    self.walk_run = True
                    self.message = f'Auto update: sending show v{self.publication.version} to {len(candidates)} cube(s)'
                    return
        if now >= self.next_query and not self.inflight:
            self.inflight = self.query()
            self.inflight_at = now
