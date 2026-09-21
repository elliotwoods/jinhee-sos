"""Explicit, three-way synchronization between local SQLite and shared device records.

The Git folder (`sync`) and the web database (`web_sync.py`) exchange identical records and
keep separate baselines, so either can run in any order without seeing the other's changes
as conflicts.
"""
from contextlib import contextmanager
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
from database import hex_bytes

KEY = 'git_inventory_baseline_v1'
FIELDS = {'mac', 'cube_id', 'uid', 'pending_uid', 'source', 'status', 'updated_at', 'detail'}
# What a record means. The other fields (status, updated_at, detail, source) are bookkeeping that
# describes these and the latest event (seen, acknowledged, unconfirmed); they never cause a conflict.
IDENTITY = ('cube_id', 'uid', 'pending_uid', 'role')


class Conflict(ValueError):
    """Both sides changed the same MAC since the shared baseline."""
    def __init__(self, macs, where='Git'):
        self.macs = sorted(macs)
        super().__init__(f'Both SQLite and {where} changed ' + ', '.join(self.macs) + '; resolve before syncing')


class AppsOpen(RuntimeError):
    pass


@contextmanager
def app_locks(database, skip=()):
    """Hold the pairing and cube-flasher instance locks; raise AppsOpen if either app runs.

    `skip`: lock suffixes the calling app already holds itself (it vouches that it is idle).
    """
    handles = []
    try:
        for suffix in ('.lock', '.flasher.lock'):
            if suffix in skip:
                continue
            handle = Path(database).with_suffix(suffix).open('a')
            handles.append(handle)
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise AppsOpen('Close the pairing and flashing apps before applying inventory changes.') from None
        yield
    finally:
        for handle in handles:
            handle.close()


def snapshot_conn(conn):
    roles = dict(conn.execute('SELECT mac, role FROM device_roles'))
    columns = sorted(FIELDS)
    rows = {r[0]: dict(zip(columns, r[1:]), role=roles.get(r[0], 'auto'))
            for r in conn.execute('SELECT mac,' + ','.join(columns) + ' FROM devices')}
    for mac, role in roles.items():
        if mac not in rows:
            rows[mac] = {'mac': mac, 'role': role}
    return rows


def snapshot(db):
    return snapshot_conn(db.conn)


def validate(records):
    numbers, tags = {}, {}
    for mac, row in records.items():
        if hex_bytes(mac, {6}) != mac or row.get('mac') != mac:
            raise ValueError('Invalid MAC record: ' + mac)
        if set(row) not in (FIELDS | {'role'}, {'mac', 'role'}):
            raise ValueError('Unexpected fields for ' + mac)
        if row['role'] not in ('auto', 'led', 'excluded'):
            raise ValueError('Invalid role for ' + mac)
        if 'cube_id' not in row:
            continue
        number = row['cube_id']
        if number is not None:
            if type(number) is not int or not 1 <= number <= 0xFFFFFFFF:
                raise ValueError('Invalid number for ' + mac)
            if number in numbers:
                raise ValueError(f'Duplicate number {number}: {numbers[number]} and {mac}; resolve inventory records first')
            numbers[number] = mac
        for field in ('uid', 'pending_uid'):
            uid = row[field]
            if uid is not None:
                if hex_bytes(uid, {4, 7}) != uid:
                    raise ValueError('Invalid tag for ' + mac)
                if uid in tags and tags[uid] != mac:
                    raise ValueError(f'Duplicate NFC {uid}: {tags[uid]} and {mac}; resolve inventory records first')
                tags[uid] = mac
        if not all(isinstance(row[k], str) for k in ('source', 'status', 'updated_at', 'detail')):
            raise ValueError('Invalid text fields for ' + mac)


def load_baseline(db, key):
    """Return (baseline, saved). `saved` is False before the first sync with that remote."""
    saved = db.conn.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
    return (json.loads(saved[0]) if saved else {}), bool(saved)


def save_baseline(db, key, records):
    with db.conn:
        db.conn.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', (key, json.dumps(records, sort_keys=True)))


def _identity(row):
    return tuple((row or {}).get(k) for k in IDENTITY)


def _time(row):
    try:
        moment = datetime.fromisoformat(row.get('updated_at') or '')
        return moment.timestamp() if moment.tzinfo else moment.replace(tzinfo=None).timestamp()
    except (TypeError, ValueError):
        return float('-inf')


def _newer(a, b):
    """The record with the later updated_at; ties break on content so every computer picks the same one."""
    key = lambda row: (_time(row), json.dumps(row, sort_keys=True))
    return a if key(a) >= key(b) else b


def auto_resolve(before, ours, theirs):
    """Winner when both sides changed a record but not its meaning differently, else None.

    Identity fields equal on both sides: the newest record wins (latest seen/acknowledged state).
    Only one side changed the identity fields: that side wins; its status describes the new number/tag.
    Records are taken whole, never spliced, so status always matches uid/pending_uid.
    """
    if ours is None or theirs is None:
        return None
    if _identity(ours) == _identity(theirs):
        return _newer(ours, theirs)
    if before is not None and _identity(theirs) == _identity(before):
        return ours
    if before is not None and _identity(ours) == _identity(before):
        return theirs
    return None


def merge(local, remote, baseline, saved, resolutions=None):
    """Pure three-way merge. Returns (merged, conflicting MACs).

    Bookkeeping-only differences resolve automatically (`auto_resolve`); a conflict means both sides
    changed a device's number, tag or role differently, and never gets a silent winner.
    `resolutions` maps a conflicting MAC to 'local' or 'remote', chosen explicitly by an operator.
    """
    resolutions = resolutions or {}
    merged, conflicts = {}, []
    for mac in sorted(local.keys() | remote.keys() | baseline.keys()):
        before, ours, theirs = baseline.get(mac), local.get(mac), remote.get(mac)
        if saved and (ours is None or theirs is None) and before is not None:
            raise ValueError('Record deletion is unsupported; clear its fields instead: ' + mac)
        # Fresh SQLite seeds originals. Shared records replace untouched seeds.
        seed = (not saved and ours and ours.get('source') == 'imported'
                and ours.get('detail') == 'Trusted original mapping'
                and ours.get('status') == 'not_transmitted' and ours.get('role') == 'auto')
        if ours == theirs:
            value = ours
        elif ours == before or (seed and theirs is not None):
            value = theirs
        elif theirs == before:
            value = ours
        elif resolutions.get(mac) == 'local':
            value = ours
        elif resolutions.get(mac) == 'remote':
            value = theirs
        elif (winner := auto_resolve(before, ours, theirs)) is not None:
            value = winner
        else:
            conflicts.append(mac)
            continue
        if value is not None:
            merged[mac] = value
    return merged, conflicts


def apply(db, merged):
    """Replace local device records with a validated merged set. Caller holds app_locks."""
    validate(merged)
    # All checks precede mutation. Clear unique columns first to allow renumbering/tag transfers.
    with db.conn:
        db.conn.execute('UPDATE devices SET cube_id=NULL, uid=NULL, pending_uid=NULL')
        for mac, row in merged.items():
            if 'cube_id' in row:
                fields = sorted(FIELDS)
                db.conn.execute('INSERT OR REPLACE INTO devices (' + ','.join(fields) + ') VALUES (' + ','.join('?' for _ in fields) + ')', [row[k] for k in fields])
            db.conn.execute('INSERT OR REPLACE INTO device_roles VALUES (?,?)', (mac, row['role']))
        # Independent computers cannot safely allocate MAX(number)+1.
        db.conn.execute("INSERT OR REPLACE INTO metadata VALUES ('auto_number','0')")
    db.export_default()


def sync(db, folder):
    """Caller must close desktop apps. Conflicts never pick a silent winner."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    remote = {}
    for path in sorted(folder.glob('*.json')):
        row = json.loads(path.read_text())  # also rejects unresolved Git markers
        mac = row.get('mac', '')
        if path.stem != mac.replace(':', '').lower() or mac in remote:
            raise ValueError('Invalid inventory filename: ' + path.name)
        remote[mac] = row
    validate(remote)
    baseline, saved = load_baseline(db, KEY)
    merged, conflicts = merge(snapshot(db), remote, baseline, saved)
    if conflicts:
        raise Conflict(conflicts[:1])
    validate(merged)
    apply(db, merged)
    for mac, row in merged.items():
        path = folder / (mac.replace(':', '').lower() + '.json')
        content = json.dumps(row, indent=2, sort_keys=True) + '\n'
        if not path.exists() or path.read_text() != content:
            temporary = path.with_suffix('.tmp')
            temporary.write_text(content)
            os.replace(temporary, path)
    # If file writing fails, the old baseline allows a safe retry.
    save_baseline(db, KEY, merged)
    return len(merged)
