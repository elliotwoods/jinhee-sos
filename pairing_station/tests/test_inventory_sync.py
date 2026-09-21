import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import Database
from inventory_sync import merge, sync

class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.a = Database(self.root/'a/db.sqlite')
        self.b = Database(self.root/'b/db.sqlite')
        self.folder = self.root/'inventory'
        sync(self.a, self.folder)
        sync(self.b, self.folder)
    def tearDown(self):
        self.a.close(); self.b.close(); self.tmp.cleanup()
    def test_independent_computers_and_idempotence(self):
        self.a.reserve('02:00:00:00:00:01')
        self.b.reserve('02:00:00:00:00:02')
        sync(self.a, self.folder)
        sync(self.b, self.folder)
        sync(self.a, self.folder)
        self.assertIsNone(self.a.get('02:00:00:00:00:02')['cube_id'])
        before = {p.name:p.read_bytes() for p in self.folder.glob('*.json')}
        sync(self.a, self.folder)
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.folder.glob('*.json')})
    def test_same_device_conflict_preserves_database(self):
        mac = self.a.rows()[0]['mac']
        self.a.rename(mac, 100)
        self.b.rename(mac, 101)
        sync(self.a, self.folder)
        with self.assertRaisesRegex(ValueError, 'Both SQLite and Git changed'):
            sync(self.b, self.folder)
        self.assertEqual(self.b.get(mac)['cube_id'], 101)
    def test_status_only_changes_take_newest(self):
        mac = self.a.rows()[0]['mac']
        for db, when, status in ((self.a, '2026-09-21T10:00:00+00:00', 'acknowledged'),
                                 (self.b, '2026-09-21T09:00:00+00:00', 'unconfirmed')):
            with db.conn:
                db.conn.execute('UPDATE devices SET status=?, updated_at=? WHERE mac=?', (status, when, mac))
        sync(self.a, self.folder)
        sync(self.b, self.folder)  # no conflict: same number and tag
        self.assertEqual(self.b.get(mac)['status'], 'acknowledged')
    def test_merge_is_symmetric_on_equal_timestamps(self):
        base = {'mac': '02:00:00:00:00:01', 'cube_id': 5, 'uid': None, 'pending_uid': None, 'role': 'auto',
                'source': 'x', 'status': 'awaiting_tag', 'updated_at': '2026-09-21T10:00:00+00:00', 'detail': ''}
        ours, theirs = dict(base, detail='one'), dict(base, detail='two')
        key = base['mac']
        first, _ = merge({key: ours}, {key: theirs}, {key: base}, True)
        second, _ = merge({key: theirs}, {key: ours}, {key: base}, True)
        self.assertEqual(first, second)
        _, conflicts = merge({key: dict(base, cube_id=6)}, {key: dict(base, cube_id=7)}, {key: base}, True)
        self.assertEqual(conflicts, [key])
    def test_duplicate_numbers_across_computers(self):
        self.a.reserve('02:00:00:00:00:01'); self.a.rename('02:00:00:00:00:01', 100)
        self.b.reserve('02:00:00:00:00:02'); self.b.rename('02:00:00:00:00:02', 100)
        sync(self.a, self.folder)
        with self.assertRaisesRegex(ValueError, 'Duplicate number'):
            sync(self.b, self.folder)
        self.assertIsNone(self.b.get('02:00:00:00:00:01'))
    def test_deleted_record_and_conflict_markers(self):
        path = next(self.folder.glob('*.json'))
        content = path.read_text(); path.unlink()
        with self.assertRaisesRegex(ValueError, 'deletion'):
            sync(self.b, self.folder)
        path.write_text('<<<<<<< HEAD\n'+content)
        with self.assertRaises(ValueError):
            sync(self.b, self.folder)
    def test_roles_and_cleared_numbers(self):
        self.a.clear_unseen_numbers()
        self.a.set_role('02:00:00:00:00:03', 'excluded')
        sync(self.a, self.folder); sync(self.b, self.folder)
        self.assertTrue(self.b.excluded('02:00:00:00:00:03'))
        self.assertTrue(all(row['cube_id'] is None for row in self.b.rows()))

if __name__ == '__main__': unittest.main()
