"""Durable mappings. All access is on the GUI/controller thread."""
import fcntl
import csv
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def hex_bytes(value, lengths):
    value = value.upper()
    if not re.fullmatch(r'[0-9A-F]{2}(?::[0-9A-F]{2})*', value):
        raise ValueError('Use colon-separated hexadecimal bytes')
    if len(value.split(':')) not in lengths:
        raise ValueError('Unsupported byte length')
    return value

class Database:
    def __init__(self, path, recover_pending=True):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=5)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript('''
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=FULL;
        CREATE TABLE IF NOT EXISTS devices (
          mac TEXT PRIMARY KEY, cube_id INTEGER UNIQUE,
          uid TEXT UNIQUE, pending_uid TEXT UNIQUE, source TEXT NOT NULL,
          status TEXT NOT NULL, updated_at TEXT NOT NULL, detail TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS device_roles (mac TEXT PRIMARY KEY, role TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY, time TEXT NOT NULL, mac TEXT, action TEXT NOT NULL, detail TEXT NOT NULL
        );
        ''')
        # Existing installations required a number even before a tag was scanned.
        if next(r for r in self.conn.execute('PRAGMA table_info(devices)') if r['name']=='cube_id')['notnull']:
            with self.conn:
                self.conn.execute('ALTER TABLE devices RENAME TO devices_numbered')
                self.conn.execute("""CREATE TABLE devices (
                  mac TEXT PRIMARY KEY, cube_id INTEGER UNIQUE, uid TEXT UNIQUE,
                  pending_uid TEXT UNIQUE, source TEXT NOT NULL, status TEXT NOT NULL,
                  updated_at TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '')""")
                self.conn.execute('INSERT INTO devices SELECT * FROM devices_numbered')
                self.conn.execute('DROP TABLE devices_numbered')
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            if not self.conn.execute("SELECT 1 FROM metadata WHERE key='original_imported'").fetchone():
                for row in self.originals():
                    self.conn.execute('INSERT INTO devices VALUES (?,?,?,NULL,?,?,?,?)',
                        (row['mac'], row['cube_id'], row['uid'], 'imported', 'not_transmitted', timestamp(), 'Trusted original mapping'))
                self.conn.execute("INSERT INTO metadata VALUES ('original_imported','1')")
            if recover_pending:
                self.conn.execute("UPDATE devices SET status='unconfirmed', detail='Interrupted; retry the saved transaction' WHERE status='pending'")
        self.ensure_reserved_numbers()
        self.export_default()

    @staticmethod
    def originals():
        return json.loads((ROOT / 'original_32.json').read_text())

    def rows(self):
        return [dict(r) for r in self.conn.execute('SELECT * FROM devices ORDER BY cube_id')]

    def get(self, mac):
        row = self.conn.execute('SELECT * FROM devices WHERE mac=?', (mac,)).fetchone()
        return dict(row) if row else None

    def event(self, mac, action, detail):
        self.conn.execute('INSERT INTO events(time,mac,action,detail) VALUES (?,?,?,?)',
                          (timestamp(), mac, action, detail))

    def roles(self):
        return dict(self.conn.execute('SELECT mac, role FROM device_roles'))

    def set_role(self, mac, role):
        mac = hex_bytes(mac, {6})
        if role not in ('auto', 'led', 'excluded'):
            raise ValueError('Unknown device role')
        with self.conn:
            self.conn.execute('INSERT OR REPLACE INTO device_roles VALUES (?,?)', (mac, role))
            self.event(mac, 'role', role)

    def excluded(self, mac):
        return self.roles().get(mac) == 'excluded'

    def reserve(self, mac, source="paired"):
        mac = hex_bytes(mac, {6})
        if int(mac[:2], 16) & 1:
            raise ValueError('A cube needs a unicast MAC')
        row = self.get(mac)
        if row:
            return row
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            row = self.get(mac)
            if row:
                return row
            automatic = self.conn.execute("SELECT value FROM metadata WHERE key='auto_number'").fetchone()
            cube_id = self.suggested_number() if automatic is None or automatic[0]=='1' else None
            self.conn.execute('INSERT INTO devices VALUES (?,?,NULL,NULL,?,?,?,?)',
                              (mac, cube_id, source, 'awaiting_tag' if cube_id else 'needs_number', timestamp(), 'ID reserved' if cube_id else 'Choose Rename device to assign its label number'))
        self.export_default()
        return self.get(mac)

    def mark_nfc_seen(self, mac, uid):
        with self.conn:
            self.event(mac, 'nfc_seen', uid)

    def clear_unseen_numbers(self, also_clear=()):
        with self.conn:
            seen = {r[0] for r in self.conn.execute("SELECT DISTINCT mac FROM events WHERE action='nfc_seen'")}
            rows = [r for r in self.conn.execute("SELECT mac,cube_id FROM devices WHERE cube_id IS NOT NULL") if r["mac"] not in seen or r["mac"] in also_clear]
            for row in rows:
                self.conn.execute("UPDATE devices SET cube_id=NULL,status='needs_number',updated_at=?,detail=? WHERE mac=?",
                                  (timestamp(), f"Previous number {row['cube_id']} cleared; assign physical label number", row['mac']))
                self.event(row['mac'], 'number_cleared', str(row['cube_id']))
            self.conn.execute("INSERT OR REPLACE INTO metadata VALUES ('auto_number','0')")
        self.export_default()
        return len(rows)

    def ensure_reserved_numbers(self):
        with self.conn:
            self.conn.execute("CREATE TABLE IF NOT EXISTS reserved_numbers (cube_id INTEGER PRIMARY KEY, detail TEXT NOT NULL)")
            self.conn.executemany('INSERT OR IGNORE INTO reserved_numbers VALUES (?,?)',
                [(number, 'Known existing physical module; exclude from automatic numbering') for number in (2,22,39,43)])

    def suggested_number(self):
        number = 33
        for row in self.conn.execute('SELECT cube_id FROM devices WHERE cube_id>=33 UNION SELECT cube_id FROM reserved_numbers WHERE cube_id>=33 ORDER BY cube_id'):
            if row[0] > number:
                break
            number = row[0] + 1
        if number > 0xFFFFFFFF:
            raise ValueError('No free device numbers remain above 32')
        return number

    def validate_number(self, mac, number):
        if type(number) is not int or not 1 <= number <= 0xFFFFFFFF:
            raise ValueError('Enter a whole number from 1 to 4294967295')
        row = self.get(mac)
        if not row:
            raise ValueError('Wait for this device to be discovered first')
        if self.excluded(mac):
            raise ValueError('Readers and base stations cannot have cube numbers')
        if row['pending_uid'] and row['cube_id'] is not None:
            raise ValueError('Finish or retry the pending registration before renaming')
        conflict = self.conn.execute('SELECT mac FROM devices WHERE cube_id=? AND mac<>?', (number, mac)).fetchone()
        if conflict:
            raise ValueError(f'Number {number} already belongs to {conflict[0]}. Rename that device to an unused number first.')
        return row

    def rename(self, mac, number, fresh_scan=False):
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            row = self.validate_number(mac, number)
            if row['cube_id'] == number:
                return row
            status = 'not_transmitted' if row['uid'] else 'awaiting_tag'
            detail = f"Renumbered from {row['cube_id']} to {number}. " + ('New number needs transmission.' if row['uid'] else 'Awaiting NFC registration.')
            self.conn.execute('UPDATE devices SET cube_id=?,status=?,updated_at=?,detail=?,pending_uid=CASE WHEN ? THEN NULL ELSE pending_uid END WHERE mac=?',
                              (number, status, timestamp(), detail, fresh_scan, mac))
            self.event(mac, 'renamed', detail)
        self.export_default()
        return self.get(mac)

    def prepare(self, mac, uid, take_over=False):
        uid = hex_bytes(uid, {4, 7})
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            row = self.get(mac)
            if not row or row['cube_id'] is None:
                raise ValueError('Use Rename device to assign a number before registering')
            conflicts = [dict(r) for r in self.conn.execute(
                'SELECT * FROM devices WHERE mac<>? AND (uid=? OR pending_uid=?)', (mac, uid, uid))]
            if conflicts and not take_over:
                raise ValueError('Tag belongs to another device; scan it with REGISTER DEVICE to transfer it')
            for previous in conflicts:
                kept_uid = None if previous['uid'] == uid else previous['uid']
                kept_pending = None if previous['pending_uid'] == uid else previous['pending_uid']
                status = ('needs_number' if previous['cube_id'] is None else
                          'unconfirmed' if kept_pending else 'not_transmitted' if kept_uid else 'awaiting_tag')
                detail = f"Tag {uid} transferred to #{row['cube_id']} ({mac}); previous device firmware not cleared"
                self.conn.execute('UPDATE devices SET uid=?,pending_uid=?,status=?,updated_at=?,detail=? WHERE mac=?',
                                  (kept_uid, kept_pending, status, timestamp(), detail, previous['mac']))
                self.event(previous['mac'], 'tag_transferred_out', detail)
                self.event(mac, 'tag_transferred_in', f"{uid} from {previous['mac']}")
            self.conn.execute("UPDATE devices SET pending_uid=?,status='pending',updated_at=?,detail='Awaiting cube acknowledgment' WHERE mac=?",
                              (uid, timestamp(), mac))
            self.event(mac, 'register_requested', uid)
        self.export_default()
        result = self.get(mac)
        result['transferred_from'] = [f"#{r['cube_id']}" if r['cube_id'] is not None else r['mac'] for r in conflicts]
        return result

    def result(self, mac, acknowledged, detail):
        row = self.get(mac)
        if not row or not row['pending_uid']:
            raise ValueError('No pending registration for this MAC')
        with self.conn:
            if acknowledged:
                self.conn.execute("UPDATE devices SET uid=pending_uid,pending_uid=NULL,status='acknowledged',updated_at=?,detail=? WHERE mac=?",
                                  (timestamp(), detail, mac))
            else:
                self.conn.execute("UPDATE devices SET status='unconfirmed',updated_at=?,detail=? WHERE mac=?", (timestamp(), detail, mac))
            self.event(mac, 'acknowledged' if acknowledged else 'unconfirmed', detail)
        self.export_default()

    def original_batch(self):
        result = []
        for original in self.originals():
            row = self.get(original['mac'])
            if row['cube_id'] != original['cube_id'] or row['uid'] != original['uid'] or row['pending_uid'] not in (None, original['uid']):
                raise ValueError('An original mapping has changed or is pending. Use Transmit selected or Retry unconfirmed to preserve that change.')
            result.append(row)
        return result

    def export_csv(self, path):
        path = Path(path)
        with path.with_suffix(path.suffix + '.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            temp = path.with_name(path.name + f'.{os.getpid()}.tmp')
            fields = ['cube_id', 'mac', 'uid', 'pending_uid', 'source', 'status', 'updated_at', 'detail']
            try:
                with temp.open('w', newline='', encoding='utf-8-sig') as out:
                    writer = csv.DictWriter(out, fieldnames=fields)
                    writer.writeheader()
                    writer.writerows(self.rows())
                os.replace(temp, path)
            finally:
                temp.unlink(missing_ok=True)

    def export_default(self):
        # Database commits remain authoritative even if an open spreadsheet locks CSV.
        self.export_error = ''
        try:
            self.export_csv(self.path.parent / 'devices.csv')
        except OSError as exc:
            self.export_error = str(exc)

    def export_header(self, path):
        rows = [r for r in self.rows() if r['uid'] and r['cube_id'] is not None]
        data = ['#pragma once', '#include <stdint.h>',
                '// Replace the entrance reader CubeRecord/table definitions with this header.',
                '// Pending replacement UIDs are excluded; inspect CSV status before use.',
                'struct CubeRecord { uint32_t cubeID; uint8_t uidLength; uint8_t uid[7]; uint8_t mac[6]; };',
                'const CubeRecord cubeTable[] = {']
        for r in rows:
            uid = ','.join('0x' + b for b in r['uid'].split(':'))
            mac = ','.join('0x' + b for b in r['mac'].split(':'))
            data.append(f'  {{{r["cube_id"]},{len(r["uid"].split(":"))},{{{uid}}},{{{mac}}}}},')
        data += ['};', 'const int CUBE_COUNT = sizeof(cubeTable) / sizeof(cubeTable[0]);', '']
        Path(path).write_text('\n'.join(data))

    def close(self):
        self.conn.close()
