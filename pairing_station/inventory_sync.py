"""Explicit, three-way synchronization between local SQLite and shared device records.

The Git folder (`sync`) and the web database (`web_sync.py`) exchange identical records and
keep separate baselines, so either can run in any order without seeing the other's changes
as conflicts.

The merge always resolves by itself and every computer reaches the same answer (`merge_records`):
the newest change to a device wins, and a number or NFC tag claimed by two devices stays with the
newest claim, exactly as a local interactive take-over would (`reconcile`). Nothing is silent: each
decision is returned as a note, audited as an event and shown to the operator.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
from database import Database, hex_bytes, released_status

KEY = 'git_inventory_baseline_v1'
FIELDS = {'mac', 'cube_id', 'uid', 'pending_uid', 'source', 'status', 'updated_at', 'detail'}
# A record means its number, tags (`_identity`) and role. The other fields (status, updated_at, detail,
# source) are bookkeeping that describes these and the latest event (seen, acknowledged, unconfirmed).


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


def validate_record(mac, row):
    """One record's structure. Uniqueness across records is `validate`'s job."""
    if not isinstance(row, dict) or hex_bytes(mac, {6}) != mac or row.get('mac') != mac:
        raise ValueError('Invalid MAC record: ' + mac)
    if set(row) not in (FIELDS | {'role'}, {'mac', 'role'}):
        raise ValueError('Unexpected fields for ' + mac)
    if row['role'] not in ('auto', 'led', 'excluded'):
        raise ValueError('Invalid role for ' + mac)
    if 'cube_id' not in row:
        return
    number = row['cube_id']
    if number is not None and (type(number) is not int or not 1 <= number <= 0xFFFFFFFF):
        raise ValueError('Invalid number for ' + mac)
    for field in ('uid', 'pending_uid'):
        if row[field] is not None and (not isinstance(row[field], str) or hex_bytes(row[field], {4, 7}) != row[field]):
            raise ValueError('Invalid tag for ' + mac)
    if not all(isinstance(row[k], str) for k in ('source', 'status', 'updated_at', 'detail')):
        raise ValueError('Invalid text fields for ' + mac)


def validate(records):
    numbers, tags = {}, {}
    for mac, row in records.items():
        validate_record(mac, row)
        if 'cube_id' not in row:
            continue
        number = row['cube_id']
        if number is not None:
            if number in numbers:
                raise ValueError(f'Duplicate number {number}: {numbers[number]} and {mac}; resolve inventory records first')
            numbers[number] = mac
        for field in ('uid', 'pending_uid'):
            uid = row[field]
            if uid is not None:
                if uid in tags and tags[uid] != mac:
                    raise ValueError(f'Duplicate NFC {uid}: {tags[uid]} and {mac}; resolve inventory records first')
                tags[uid] = mac


def load_baseline(db, key):
    """Return (baseline, saved). `saved` is False before the first sync with that remote.

    An unreadable baseline counts as none: the merge then decides without shared history.
    """
    saved = db.conn.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
    try:
        baseline = json.loads(saved[0]) if saved else {}
    except ValueError:
        return {}, False
    return (baseline, True) if saved and isinstance(baseline, dict) else ({}, False)


def save_baseline(db, key, records):
    with db.conn:
        db.conn.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', (key, json.dumps(records, sort_keys=True)))


def _device(row):
    """The device part of a record (taken whole, never spliced), or None for absent/role-only."""
    return {k: row[k] for k in FIELDS} if row and 'cube_id' in row else None


def _identity(row):
    """What a device record means. Retransmitting a committed tag (pending_uid == uid) is bookkeeping."""
    if not row:
        return None
    return row['cube_id'], row['uid'], row['pending_uid'] if row['pending_uid'] != row['uid'] else None


def _time(row):
    try:
        moment = datetime.fromisoformat(row.get('updated_at') or '')
        return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).timestamp()
    except (TypeError, ValueError):
        return float('-inf')


def _newer(a, b):
    """The record with the later updated_at; ties break on content so every computer picks the same one."""
    key = lambda row: (_time(row), json.dumps(row, sort_keys=True))
    return a if key(a) >= key(b) else b


def _label(row):
    if not row:
        return 'no device record'
    tag = row['uid'] or (f"{row['pending_uid']} (pending)" if row['pending_uid'] else 'no tag')
    return (f"#{row['cube_id']}" if row['cube_id'] is not None else 'no number') + ', ' + tag


_ORIGINALS = None


def _untouched_original(row):
    """A seeded original mapping nobody changed here (retransmitting it is not a change)."""
    global _ORIGINALS
    if _ORIGINALS is None:
        _ORIGINALS = {o['mac']: (o['cube_id'], o['uid'], None) for o in Database.originals()}
    return row['source'] == 'imported' and _identity(row) == _ORIGINALS.get(row['mac'])


def _merge_device(mac, before, ours, theirs, saved):
    """Returns (device part, note or None)."""
    if ours == theirs or theirs is None:
        return ours, None
    if ours is None or ours == before:
        return theirs, None
    if theirs == before:
        return ours, None
    # Both sides changed. Fresh SQLite seeds originals: without shared history they yield to shared records.
    if not saved and _untouched_original(ours):
        return theirs, None
    if _identity(ours) == _identity(theirs):
        return _newer(ours, theirs), None  # bookkeeping only: latest seen/acknowledged state
    if before is not None and _identity(theirs) == _identity(before):
        return ours, None  # only we changed the number/tag; our status describes it
    if before is not None and _identity(ours) == _identity(before):
        return theirs, None
    winner = _newer(ours, theirs)
    loser = theirs if winner is ours else ours
    return winner, dict(mac=mac, kind='both_changed', local_lost=winner is theirs,
                        text=f'{mac} was changed on two computers; the newer change was kept '
                             f'({_label(winner)}) and the older one dropped ({_label(loser)})')


ROLE_RANK = {'auto': 0, 'led': 1, 'excluded': 2}


def _merge_role(mac, before, ours, theirs):
    """Roles live in their own table and change on their own. Returns (role, note or None)."""
    if ours == theirs or theirs is None:
        return ours, None
    if ours is None or ours == before:
        return theirs, None
    if theirs == before:
        return ours, None
    role = max(ours, theirs, key=ROLE_RANK.get)  # the cautious one: an excluded board is never flashed as a cube
    note = None
    if before is not None or 'auto' not in (ours, theirs):
        note = dict(mac=mac, kind='role', local_lost=role != ours,
                    text=f'{mac} got two different roles ({ours} here, {theirs} on the web); kept {role}')
    return role, note


def reconcile(records):
    """Give every number and NFC tag exactly one owner. Pure, idempotent, identical on every computer.

    A tag stays with its newest holder, as a local interactive take-over would decide; a number stays
    with a registered device before an unregistered one, then with the newest. Losers keep their own
    updated_at (a repair never outranks a later human edit) and get a detail naming the winner.
    Returns (records, notes).
    """
    full = {mac: row for mac, row in records.items() if 'cube_id' in row}
    tags, numbers = {}, {}
    for mac in sorted(full):
        row = full[mac]
        for tag in sorted({row['uid'], row['pending_uid']} - {None}):
            tags.setdefault(tag, []).append(mac)
        if row['cube_id'] is not None:
            numbers.setdefault(row['cube_id'], []).append(mac)
    # Priorities come from the records as given, so the two passes cannot influence each other.
    base = lambda mac: (full[mac]['role'] != 'excluded',)
    tail = lambda mac: (_time(full[mac]), json.dumps(full[mac], sort_keys=True))
    repaired, reasons, notes = {}, {}, []

    def loser(mac, kind, text):
        repaired.setdefault(mac, dict(full[mac]))
        reasons.setdefault(mac, []).append(text)
        notes.append(dict(mac=mac, kind=kind, text=text, local_lost=False))

    for tag in sorted(tags):
        holders = tags[tag]
        if len(holders) > 1:
            winner = max(holders, key=lambda mac: base(mac) + (_time(full[mac]), full[mac]['uid'] == tag) + tail(mac))
            for mac in holders:
                if mac != winner:
                    loser(mac, 'tag_lost', f'Sync: tag {tag} now belongs to {winner} (newer registration); '
                                           'this device\'s firmware was not cleared')
                    for field in ('uid', 'pending_uid'):
                        if repaired[mac][field] == tag:
                            repaired[mac][field] = None
    for number in sorted(numbers):
        holders = numbers[number]
        if len(holders) > 1:
            winner = max(holders, key=lambda mac: base(mac) + (full[mac]['uid'] is not None,
                                                               full[mac]['pending_uid'] is not None) + tail(mac))
            for mac in holders:
                if mac != winner:
                    loser(mac, 'number_lost', f'Sync: number {number} is also used by {winner}, which keeps it; '
                                              'assign this device\'s physical label number')
                    repaired[mac]['cube_id'] = None
    for mac, row in repaired.items():
        row['status'] = released_status(row['cube_id'], row['uid'], row['pending_uid'])
        row['detail'] = ' '.join(reasons[mac])
    return {**records, **repaired}, notes


def _invalid(mac, row):
    try:
        validate_record(mac, row)
    except (ValueError, TypeError, AttributeError) as exc:
        return str(exc)
    return None


def merge_records(local, remote, baseline, saved, resolutions=None):
    """Pure three-way merge that always resolves. Returns (merged, notes).

    The device part (number, tags and their bookkeeping) and the role merge separately; absence never
    deletes: a side that lacks a record, or has only its role, takes the other side's. When both sides
    changed a device's number or tag differently the newest change wins whole, then `reconcile` settles
    numbers and tags claimed twice. A structurally invalid record leaves its MAC untouched on both sides.
    `resolutions` maps a MAC to 'local' or 'remote' to force that side.
    Notes: dict(mac, kind, text, local_lost); kinds both_changed, number_lost, tag_lost, role, invalid, restored.
    """
    resolutions = resolutions or {}
    merged, notes = {}, []
    for mac in sorted(local.keys() | remote.keys() | baseline.keys()):
        ours, theirs = local.get(mac), remote.get(mac)
        before = baseline.get(mac) if saved else None
        if ours is None and theirs is None:
            continue
        problems = [f'{side}: {problem}' for side, row in (('here', ours), ('web', theirs))
                    if row is not None and (problem := _invalid(mac, row))]
        if problems:
            notes.append(dict(mac=mac, kind='invalid', local_lost=False,
                              text=f'{mac} was left alone: its record is not understood ({"; ".join(problems)})'))
            continue
        if before is not None and _invalid(mac, before):
            before = None
        forced = resolutions.get(mac) if ours is not None and theirs is not None else None
        if forced in ('local', 'remote'):
            merged[mac] = ours if forced == 'local' else theirs
            continue
        if before is not None and (ours is None or theirs is None):
            notes.append(dict(mac=mac, kind='restored', local_lost=False,
                              text=f'{mac} was missing {"here" if ours is None else "on the web"} and was restored'))
        device, note = _merge_device(mac, _device(before), _device(ours), _device(theirs), saved)
        role, role_note = _merge_role(mac, (before or {}).get('role'), (ours or {}).get('role'), (theirs or {}).get('role'))
        notes += [n for n in (note, role_note) if n]
        merged[mac] = dict(device, role=role) if device else {'mac': mac, 'role': role}
    merged, repairs = reconcile(merged)
    for note in repairs:
        ours = _device(local.get(note['mac']))
        note['local_lost'] = ours is not None and _identity(ours) != _identity(merged[note['mac']])
    return merged, notes + repairs


def merge(local, remote, baseline, saved, resolutions=None):
    """`merge_records` for callers that expect (merged, conflicting MACs): nothing conflicts any more."""
    return merge_records(local, remote, baseline, saved, resolutions)[0], []


class LocalChanged(RuntimeError):
    """SQLite changed after the merge was planned: plan again rather than overwrite that change."""


def apply(db, merged, only=None, expected=None):
    """Write merged records into SQLite. Caller holds app_locks.

    `only`: the MACs to write (default: all of `merged`). `expected`: the local snapshot the merge was
    planned from; if SQLite differs by now, raises LocalChanged without writing.
    """
    validate(merged)
    macs = sorted(merged if only is None else only)
    fields = sorted(FIELDS)
    upsert = ('INSERT INTO devices (' + ','.join(fields) + ') VALUES (' + ','.join('?' for _ in fields) + ') '
              'ON CONFLICT(mac) DO UPDATE SET ' + ','.join(f'{f}=excluded.{f}' for f in fields if f != 'mac'))
    with db.conn:
        db.conn.execute('BEGIN IMMEDIATE')
        current = snapshot(db)
        if expected is not None and current != expected:
            raise LocalChanged('Local records changed during sync')
        # All checks precede mutation. Clear unique columns first to allow renumbering/tag transfers.
        db.conn.executemany('UPDATE devices SET cube_id=NULL, uid=NULL, pending_uid=NULL WHERE mac=?', [(m,) for m in macs])
        for mac in macs:
            row, old = merged[mac], current.get(mac)
            if 'cube_id' in row:
                db.conn.execute(upsert, [row[k] for k in fields])
            db.conn.execute('INSERT OR REPLACE INTO device_roles VALUES (?,?)', (mac, row['role']))
            before = (_identity(_device(old)), (old or {}).get('role', 'auto'))
            if before != (_identity(_device(row)), row['role']):
                db.event(mac, 'sync_applied', f"{_label(_device(old))}, {before[1]} -> {_label(_device(row))}, {row['role']}")
        # Independent computers cannot safely allocate MAX(number)+1.
        db.conn.execute("INSERT OR REPLACE INTO metadata VALUES ('auto_number','0')")
    db.export_default()


def record_decisions(db, notes):
    """Audit the merge's automatic decisions (caller commits)."""
    for note in notes:
        db.event(note['mac'], 'sync_resolved', note['text'])


def sync(db, folder):
    """Caller must close desktop apps. The merge resolves by itself; its decisions are audited as events."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    remote = {}
    for path in sorted(folder.glob('*.json')):
        row = json.loads(path.read_text())  # also rejects unresolved Git markers
        mac = row.get('mac', '') if isinstance(row, dict) else ''
        if path.stem != mac.replace(':', '').lower() or mac in remote:
            raise ValueError('Invalid inventory filename: ' + path.name)
        validate_record(mac, row)  # Git can merge two people's files into a shared number/tag: repaired below
        remote[mac] = row
    baseline, saved = load_baseline(db, KEY)
    local = snapshot(db)
    merged, notes = merge_records(local, remote, baseline, saved)
    apply(db, merged, expected=local)
    with db.conn:
        record_decisions(db, notes)
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
