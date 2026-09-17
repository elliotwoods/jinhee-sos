"""Firmware artifacts, durable history, and hardware-independent scheduling."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
sys.path.insert(0, str(WORKSPACE / 'pairing_station'))
from database import Database, timestamp
from port_lock import PortLock

VERSION = 'v1.4.1-USB.2'
FQBN = 'esp32:esp32:XIAO_ESP32C3:CDCOnBoot=default,PartitionScheme=no_ota,FlashSize=4M'
# This replacement console is documented in registration_console/README.md.
PROTECTED = {'3C:0F:02:AD:83:24'}

def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def atomic_json(path, data):
    path = Path(path)
    temp = path.with_suffix('.tmp')
    with temp.open('w') as f:
        json.dump(data, f, indent=2)
        f.flush(); os.fsync(f.fileno())
    temp.replace(path)

class Store(Database):
    def __init__(self, path):
        super().__init__(path, recover_pending=False)
        self.conn.execute('''CREATE TABLE IF NOT EXISTS flash_runs (
          id TEXT PRIMARY KEY, mac TEXT, port TEXT, version TEXT, build_hash TEXT,
          started_at TEXT, finished_at TEXT, stage TEXT, result TEXT, detail TEXT,
          log_path TEXT)''')
        self.conn.commit()
    def recover(self):
        with self.conn:
            self.conn.execute("UPDATE flash_runs SET result='interrupted', detail='Application stopped; inspect device before retrying' WHERE result='running'")
    def protected(self, mac): return mac in PROTECTED or self.excluded(mac)
    def seen(self, mac, build):
        return bool(self.conn.execute("SELECT 1 FROM flash_runs WHERE mac=? AND build_hash=? AND result='success'", (mac,build)).fetchone())
    def start(self, ident, port, manifest, log):
        with self.conn:
            self.conn.execute('INSERT INTO flash_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (ident,None,port,manifest['version'],manifest['build_hash'],timestamp(),None,'identify','running','',str(log)))
    def update_run(self, ident, **values):
        assert set(values) <= {'mac','stage','result','detail','finished_at'}
        with self.conn:
            self.conn.execute('UPDATE flash_runs SET '+','.join(k+'=?' for k in values)+' WHERE id=?',(*values.values(),ident))
    def history(self):
        return [dict(r) for r in self.conn.execute('SELECT * FROM flash_runs ORDER BY started_at DESC LIMIT 200')]

class Scheduler:
    def __init__(self):
        self.armed = False
        self.attempted = set()
        self.present = {}
        self.missing_since = {}
    def scan(self, ports, busy=False):
        self.present = {p['port']:p for p in ports}
        keys = {p['key'] for p in ports}
        now = time.monotonic()
        for key in list(self.attempted):
            if key in keys or busy:
                self.missing_since.pop(key, None)
            elif now - self.missing_since.setdefault(key, now) > 2:
                self.attempted.discard(key)
                self.missing_since.pop(key, None)
    def next(self):
        if not self.armed: return None
        return next((p for p in self.present.values() if p['key'] not in self.attempted and p['candidate']), None)
    def mark(self, port): self.attempted.add(port['key'])

def load_manifest():
    path = ROOT / 'build' / 'manifest.json'
    m = json.loads(path.read_text())
    if m['version'] != VERSION or m['fqbn'] != FQBN: raise ValueError('Firmware target/version mismatch; rebuild')
    if m['source_hash'] != digest(ROOT/'firmware/neocore_usb/neocore_usb.ino'):
        raise ValueError('Firmware source changed; rebuild before flashing')
    for segment in m['segments']:
        if digest(path.parent / segment['file']) != segment['sha256']:
            raise ValueError('Firmware checksum mismatch; rebuild')
    expected = hashlib.sha256(json.dumps(m['segments'],sort_keys=True).encode()).hexdigest()
    if m['build_hash'] != expected: raise ValueError('Build manifest checksum mismatch')
    return m
