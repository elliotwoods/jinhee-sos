"""Ordinary work on several computers, in any order, must always sync without anyone deciding anything.

Seeded random runs drive the real Database operations on three computers (numbering, registration with
take-over, bulk retransmit, unregister, roles, clearing numbers) and sync them in random order, with apps
open or idle and other computers pushing mid-sync. Every sync must succeed, leave the web and every
computer valid, and all of them must end up identical. NCT_SYNC_SEEDS=200 runs more seeds.
"""
import os
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import database  # noqa: E402
from database import Database  # noqa: E402
from fake_web_inventory import FakeWebInventory  # noqa: E402
from inventory_sync import merge_records, snapshot, validate  # noqa: E402
from web_client import WebClient  # noqa: E402
import web_sync  # noqa: E402

MACS = [f'02:00:00:00:00:{n:02X}' for n in range(1, 9)]
TAGS = [f'04:0A:0B:{n:02X}' for n in range(1, 6)]
NUMBERS = range(33, 40)  # few numbers and tags, so computers collide all the time
COMPUTERS = 'abc'


class ConvergenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.web = FakeWebInventory()
        self.now = 1_790_000_000
        self.clock = patch.object(database, 'timestamp', side_effect=self.timestamp)
        self.clock.start()

    def tearDown(self):
        self.clock.stop()
        self.web.close()
        self.tmp.cleanup()

    def timestamp(self):
        from datetime import datetime, timezone
        self.now += self.random.choice((0, 0, 1, 1, 5, 60))  # equal timestamps happen: seconds are coarse
        return datetime.fromtimestamp(self.now, timezone.utc).isoformat(timespec='seconds')

    def work(self, db):
        """One thing an operator or an app does. Refusals (number taken, nothing pending…) are part of normal work."""
        r, mac = self.random, self.random.choice(MACS)
        try:
            action = r.choice(('reserve', 'rename', 'rename', 'register', 'register', 'result', 'retransmit',
                               'unregister', 'role', 'clear'))
            if action == 'reserve':
                db.reserve(mac, r.choice(('discovered', 'usb', 'usb_flash')))
            elif action == 'rename':
                db.reserve(mac)
                db.rename(mac, r.choice(NUMBERS), fresh_scan=r.random() < 0.3)
            elif action == 'register':
                db.reserve(mac)
                if db.get(mac)['cube_id'] is None:
                    db.rename(mac, r.choice(NUMBERS))
                db.prepare(mac, r.choice(TAGS), take_over=r.random() < 0.7)
                if r.random() < 0.7:
                    db.result(mac, r.random() < 0.8, 'radio result')
            elif action == 'result':
                db.result(mac, r.random() < 0.5, 'late result')
            elif action == 'retransmit':
                row = db.get(mac)
                if row and row['uid']:
                    db.prepare(mac, row['uid'])  # bulk transmission of the saved mapping
            elif action == 'unregister':
                db.unregister(mac, 'board reflashed as something else')
            elif action == 'role':
                db.set_role(mac, r.choice(('auto', 'auto', 'led', 'excluded')))
            elif r.random() < 0.2:
                db.clear_unseen_numbers()
        except ValueError:
            pass

    def sync(self, name, apply_ok=True, concurrent=None):
        if concurrent:
            self.web.before_push = lambda: self.sync(concurrent)
        result = web_sync.run(self.paths[name], WebClient(self.web.url, self.web.password, 'jinhee-sos', timeout=5),
                              name, apply_ok=apply_ok)
        self.web.before_push = None
        self.assertEqual(result['conflicts'], [])
        validate({mac: entry['record'] for mac, entry in self.web.records.items()})
        validate(self.local(name))
        return result

    def local(self, name):
        db = Database(self.paths[name], recover_pending=False)
        try:
            return snapshot(db)
        finally:
            db.close()

    def scenario(self, seed):
        self.random = random.Random(seed)
        root = Path(self.tmp.name) / str(seed)
        self.paths = {name: root / name / 'devices.sqlite3' for name in COMPUTERS}
        self.web.records, self.web.revision = {}, 0
        for name in COMPUTERS:
            Database(self.paths[name]).close()
            if self.random.random() < 0.7:
                self.sync(name)  # some computers work before their first sync, without shared history
        for _ in range(40):
            name = self.random.choice(COMPUTERS)
            if self.random.random() < 0.65:
                db = Database(self.paths[name], recover_pending=self.random.random() < 0.2)  # apps restart too
                try:
                    self.work(db)
                finally:
                    db.close()
            else:
                other = self.random.choice([c for c in COMPUTERS if c != name])
                self.sync(name, apply_ok=self.random.random() < 0.7,
                          concurrent=other if self.random.random() < 0.25 else None)
        # Everybody idle: two rounds must settle everything, and a third must find nothing to do.
        for _ in range(2):
            for name in COMPUTERS:
                self.sync(name)
        revision = self.web.revision
        for name in COMPUTERS:
            result = self.sync(name)
            self.assertEqual((result['upload'], result['download'], result['notes'], result['lost']), ([], [], [], []))
        self.assertEqual(self.web.revision, revision)
        web = {mac: entry['record'] for mac, entry in self.web.records.items()}
        for name in COMPUTERS:
            self.assertEqual(self.local(name), web)

    def test_random_work_on_three_computers_always_converges(self):
        for seed in range(int(os.environ.get('NCT_SYNC_SEEDS', 12))):
            with self.subTest(seed=seed):
                self.scenario(seed)

    def test_merge_gives_the_same_answer_on_both_sides(self):
        self.random = random.Random(7)
        base = {}
        for mac in MACS:
            base[mac] = dict(mac=mac, cube_id=None, uid=None, pending_uid=None, role='auto', source='x',
                             status='s', updated_at=self.timestamp(), detail='')

        def changed():
            records = {mac: dict(row) for mac, row in base.items()}
            for mac in self.random.sample(MACS, 5):
                records[mac].update(cube_id=self.random.choice(NUMBERS), uid=self.random.choice(TAGS + [None]),
                                    role=self.random.choice(('auto', 'led', 'excluded')), updated_at=self.timestamp())
            return records
        for _ in range(300):
            one, two = changed(), changed()
            merged, _ = merge_records(one, two, base, True)
            validate(merged)
            self.assertEqual(merged, merge_records(two, one, base, True)[0])
            self.assertEqual(merged, merge_records(merged, merged, base, True)[0])


if __name__ == '__main__':
    unittest.main()
