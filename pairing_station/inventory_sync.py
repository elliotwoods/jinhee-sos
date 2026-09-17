"""Explicit, three-way synchronization between local SQLite and Git device records."""
import json
import os
from pathlib import Path
from database import hex_bytes

KEY = 'git_inventory_baseline_v1'
FIELDS = {'mac', 'cube_id', 'uid', 'pending_uid', 'source', 'status', 'updated_at', 'detail'}


def snapshot(db):
    roles = db.roles()
    rows = {r['mac']: dict(r, role=roles.get(r['mac'], 'auto')) for r in db.rows()}
    for mac, role in roles.items():
        if mac not in rows:
            rows[mac] = {'mac': mac, 'role': role}
    return rows


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
    saved = db.conn.execute('SELECT value FROM metadata WHERE key=?', (KEY,)).fetchone()
    baseline = json.loads(saved[0]) if saved else {}
    local = snapshot(db)
    merged = {}
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
        else:
            raise ValueError('Both SQLite and Git changed ' + mac + '; resolve before syncing')
        if value is not None:
            merged[mac] = value
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
    for mac, row in merged.items():
        path = folder / (mac.replace(':', '').lower() + '.json')
        content = json.dumps(row, indent=2, sort_keys=True) + '\n'
        if not path.exists() or path.read_text() != content:
            temporary = path.with_suffix('.tmp')
            temporary.write_text(content)
            os.replace(temporary, path)
    # If file writing fails, the old baseline allows a safe retry.
    with db.conn:
        db.conn.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', (KEY, json.dumps(merged, sort_keys=True)))
    db.export_default()
    return len(merged)
