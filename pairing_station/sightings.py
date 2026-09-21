"""When and how each cube was last physically seen, for the web inventory's "last seen".

Sightings are telemetry, not inventory records: they never enter the Git/web three-way
merge. `record()` keeps the latest sighting per (MAC, kind) in the `sightings` table;
`collect()` combines it with evidence other tables already hold (NFC scans and radio
acknowledgements in `events`, USB flashes in `flash_runs`) plus zone-board status, and the
web sync uploads the result for this computer.
"""
from datetime import datetime, timezone
import sqlite3
import time
from database import timestamp

RADIO_THROTTLE_S = 60  # the `sightings` table itself is created by Database.__init__


def record(conn, mac, kind, detail='', at=None):
    """Upsert the latest sighting. Caller owns `conn` (the Tk/SQLite thread).

    Best effort: a busy or read-only database must never disturb pairing or flashing.
    """
    at = at or timestamp()
    try:
        with conn:
            conn.execute('INSERT INTO sightings VALUES (?,?,?,?) ON CONFLICT(mac, kind) DO UPDATE SET at=excluded.at, '
                         'detail=excluded.detail WHERE excluded.at >= sightings.at', (mac, kind, at, detail))
        return True
    except sqlite3.Error:
        return False


class RadioThrottle:
    """Radio discovery repeats every few seconds; persist at most once a minute per MAC."""
    def __init__(self, clock=time.monotonic):
        self.clock, self.last = clock, {}

    def due(self, mac):
        now = self.clock()
        if now - self.last.get(mac, -RADIO_THROTTLE_S) < RADIO_THROTTLE_S:
            return False
        self.last[mac] = now
        return True


def utc(value):
    """Normalize ISO timestamps (the zones table uses local time with an offset) to UTC ISO."""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec='seconds')


def _table(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def collect(conn):
    """{'cubes': {mac: {kind: {'at', 'detail'}}}, 'zones': [...]} from everything persisted locally."""
    cubes = {}

    def add(mac, kind, at, detail=''):
        at = utc(at)
        if not mac or not at:
            return
        current = cubes.setdefault(mac, {}).get(kind)
        if current is None or at > current['at']:
            cubes[mac][kind] = {'at': at, 'detail': detail or ''}

    if _table(conn, 'sightings'):
        for mac, kind, at, detail in conn.execute('SELECT mac, kind, at, detail FROM sightings'):
            add(mac, kind, at, detail)
    for mac, action, at, detail in conn.execute(
            "SELECT mac, action, MAX(time), detail FROM events WHERE action IN ('nfc_seen','acknowledged') "
            'AND mac IS NOT NULL GROUP BY mac, action'):
        add(mac, 'nfc' if action == 'nfc_seen' else 'radio_ack', at, detail if action == 'nfc_seen' else '')
    if _table(conn, 'flash_runs'):
        for mac, at, version, result in conn.execute(
                "SELECT mac, MAX(started_at), version, result FROM flash_runs WHERE mac IS NOT NULL "
                "AND result IS NOT NULL AND result != 'failed' GROUP BY mac"):
            add(mac, 'usb_flash', at, f'{version or ""} · {result}'.strip(' ·'))
    zones = []
    if _table(conn, 'zones'):
        conn_row, conn.row_factory = conn.row_factory, sqlite3.Row
        try:
            for z in conn.execute('SELECT * FROM zones'):
                z = dict(z)
                seen = (datetime.fromtimestamp(z['last_seen_epoch'], timezone.utc).isoformat(timespec='seconds')
                        if z.get('last_seen_epoch') else utc(z.get('last_seen')))
                zones.append({k: z.get(k) for k in ('mac', 'name', 'zone_type', 'point_id', 'profile', 'firmware',
                                                    'db_version', 'tags', 'source')} | {'last_seen': seen})
        finally:
            conn.row_factory = conn_row
    return {'cubes': cubes, 'zones': zones}


def zone_taps(conn, zone_mac, entries, received_epoch):
    """Record cube taps from a zone's ZONE_LOG entries (uid, cube_id, result, age_s). Best effort."""
    try:
        _zone_taps(conn, zone_mac, entries, received_epoch)
    except sqlite3.Error:
        pass


def _zone_taps(conn, zone_mac, entries, received_epoch):
    name = conn.execute('SELECT name FROM zones WHERE mac=?', (zone_mac,)).fetchone() if _table(conn, 'zones') else None
    where = (name[0] if name and name[0] else zone_mac)
    for entry in entries:
        row = None
        if entry.get('uid'):
            row = conn.execute('SELECT mac FROM devices WHERE uid=? OR pending_uid=?', (entry['uid'], entry['uid'])).fetchone()
        if not row and entry.get('cube_id'):
            row = conn.execute('SELECT mac FROM devices WHERE cube_id=?', (entry['cube_id'],)).fetchone()
        if not row:
            continue
        at = datetime.fromtimestamp(received_epoch - (entry.get('age_s') or 0), timezone.utc).isoformat(timespec='seconds')
        record(conn, row[0], 'zone_tap', f"{where} · {entry.get('result', '')}".strip(' ·'), at)
