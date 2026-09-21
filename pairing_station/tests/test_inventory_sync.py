import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import Database
from inventory_sync import (KEY, LocalChanged, apply, merge, merge_records, reconcile, snapshot, sync,
                            validate)

M1, M2 = '02:00:00:00:00:01', '02:00:00:00:00:02'
EARLY, LATE = '2026-09-21T09:00:00+00:00', '2026-09-21T10:00:00+00:00'


def stamp(db, mac, when):
    with db.conn:
        db.conn.execute('UPDATE devices SET updated_at=? WHERE mac=?', (when, mac))


def record(mac, **fields):
    return dict(dict(mac=mac, cube_id=None, uid=None, pending_uid=None, role='auto', source='x', status='s',
                     updated_at=EARLY, detail=''), **fields)


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
    def test_same_device_changed_twice_keeps_the_newest(self):
        mac = self.a.rows()[0]['mac']
        self.a.rename(mac, 100); stamp(self.a, mac, EARLY)
        self.b.rename(mac, 101); stamp(self.b, mac, LATE)
        sync(self.a, self.folder)
        sync(self.b, self.folder)  # no decision needed: b's change is newer
        self.assertEqual(self.b.get(mac)['cube_id'], 101)
        events = [r['detail'] for r in self.b.conn.execute("SELECT detail FROM events WHERE action='sync_resolved'")]
        self.assertEqual(len(events), 1); self.assertIn('#101', events[0]); self.assertIn('#100', events[0])
        sync(self.a, self.folder)
        self.assertEqual(self.a.get(mac)['cube_id'], 101)
        applied = [r['detail'] for r in self.a.conn.execute("SELECT detail FROM events WHERE action='sync_applied' AND mac=?", (mac,))]
        self.assertRegex(applied[-1], r'^#100, .* -> #101, ')
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
        six, seven = {key: dict(base, cube_id=6)}, {key: dict(base, cube_id=7)}
        first, notes = merge_records(six, seven, {key: base}, True)
        second, _ = merge_records(seven, six, {key: base}, True)
        self.assertEqual(first, second)  # equal timestamps: every computer still picks the same one
        self.assertEqual([n['kind'] for n in notes], ['both_changed'])
        self.assertEqual(merge(six, seven, {key: base}, True)[1], [])
    def test_duplicate_numbers_across_computers(self):
        self.a.reserve(M1); self.a.rename(M1, 100); stamp(self.a, M1, EARLY)
        self.b.reserve(M2); self.b.rename(M2, 100); stamp(self.b, M2, LATE)
        sync(self.a, self.folder)
        sync(self.b, self.folder)  # the newest assignment keeps the number
        self.assertEqual((self.b.get(M2)['cube_id'], self.b.get(M1)['cube_id'], self.b.get(M1)['status']),
                         (100, None, 'needs_number'))
        self.assertIn(M2, self.b.get(M1)['detail'])
        self.assertEqual(self.b.get(M1)['updated_at'], EARLY)  # a repair never outranks a later human edit
        sync(self.a, self.folder)
        self.assertEqual(snapshot(self.a), snapshot(self.b))
        self.a.rename(M1, 102)  # the operator reads the label again
        sync(self.a, self.folder); sync(self.b, self.folder)
        self.assertEqual(self.b.get(M1)['cube_id'], 102)

    def test_git_merged_duplicate_in_the_folder_is_repaired(self):
        self.a.reserve(M1); self.a.rename(M1, 100); stamp(self.a, M1, LATE)
        sync(self.a, self.folder)
        path = self.folder / '020000000002.json'
        path.write_text(json.dumps(record(M2, cube_id=100)))
        sync(self.b, self.folder)
        self.assertEqual((self.b.get(M1)['cube_id'], self.b.get(M2)['cube_id']), (100, None))
        self.assertIsNone(json.loads(path.read_text())['cube_id'])

    def test_deleted_record_and_conflict_markers(self):
        path = next(self.folder.glob('*.json'))
        content = path.read_text(); path.unlink()
        sync(self.b, self.folder)  # nothing is ever deleted: the record is restored
        self.assertEqual(path.read_text(), content)
        path.write_text('<<<<<<< HEAD\n'+content)
        with self.assertRaises(ValueError):
            sync(self.b, self.folder)

    def test_roles_and_cleared_numbers(self):
        self.a.clear_unseen_numbers()
        self.a.set_role('02:00:00:00:00:03', 'excluded')
        sync(self.a, self.folder); sync(self.b, self.folder)
        self.assertTrue(self.b.excluded('02:00:00:00:00:03'))
        self.assertTrue(all(row['cube_id'] is None for row in self.b.rows()))

    def test_corrupt_baseline_counts_as_none(self):
        self.a.set_metadata(KEY, '{"truncated": ')
        sync(self.a, self.folder)
        self.assertEqual(snapshot(self.a), snapshot(self.b))

    def test_apply_refuses_to_overwrite_a_change_made_since_the_plan(self):
        planned = snapshot(self.a)
        mac = self.a.rows()[0]['mac']
        self.a.rename(mac, 100)
        with self.assertRaises(LocalChanged):
            apply(self.a, planned, expected=planned)
        self.assertEqual(self.a.get(mac)['cube_id'], 100)


class MergeTests(unittest.TestCase):
    def merged(self, local, remote, baseline=None, saved=True):
        merged, notes = merge_records(local, remote, baseline or {}, saved)
        validate(merged)
        mirrored, _ = merge_records(remote, local, baseline or {}, saved)
        if saved:
            self.assertEqual(merged, mirrored)
        return merged, notes

    def test_tag_claimed_twice_stays_with_the_newest_holder(self):
        tag = '04:0A:0B:0C'
        old = record(M1, cube_id=5, uid=tag, status='acknowledged')
        new = record(M2, cube_id=6, pending_uid=tag, status='pending', updated_at=LATE)
        merged, notes = self.merged({M1: old}, {M2: new})
        self.assertEqual((merged[M1]['uid'], merged[M1]['status'], merged[M2]['pending_uid']), (None, 'awaiting_tag', tag))
        self.assertEqual([(n['kind'], n['mac'], n['local_lost']) for n in notes], [('tag_lost', M1, True)])
        self.assertEqual(reconcile(merged), (merged, []))  # idempotent

    def test_bulk_retransmit_never_steals_a_tag(self):
        tag = '04:0A:0B:0C'
        before = {M1: record(M1, cube_id=5, uid=tag, status='acknowledged'), M2: record(M2, cube_id=6)}
        # Here: #5 retransmits its committed tag (no ACK yet). Elsewhere, earlier: the tag moved to #6.
        local = dict(before, **{M1: record(M1, cube_id=5, uid=tag, pending_uid=tag, status='pending', updated_at=LATE)})
        remote = {M1: record(M1, cube_id=5, status='awaiting_tag', updated_at='2026-09-21T09:30:00+00:00'),
                  M2: record(M2, cube_id=6, uid=tag, status='acknowledged', updated_at='2026-09-21T09:30:00+00:00')}
        merged, _ = self.merged(local, remote, before)
        self.assertEqual((merged[M1]['uid'], merged[M1]['pending_uid'], merged[M2]['uid']), (None, None, tag))

    def test_registered_device_keeps_a_number_claimed_twice_and_excluded_boards_lose(self):
        registered = record(M1, cube_id=7, uid='04:0A:0B:0C')
        newer = record(M2, cube_id=7, updated_at=LATE)
        merged, _ = self.merged({M1: registered}, {M2: newer})
        self.assertEqual((merged[M1]['cube_id'], merged[M2]['cube_id'], merged[M2]['status']), (7, None, 'needs_number'))
        merged, _ = self.merged({M1: dict(registered, role='excluded', updated_at=LATE)}, {M2: record(M2, cube_id=7)})
        self.assertEqual((merged[M1]['cube_id'], merged[M1]['uid'], merged[M2]['cube_id']), (None, '04:0A:0B:0C', 7))

    def test_role_only_record_never_removes_a_number_and_roles_merge_on_their_own(self):
        full = record(M1, cube_id=7, uid='04:0A:0B:0C')
        merged, notes = self.merged({M1: full}, {M1: {'mac': M1, 'role': 'excluded'}}, {M1: full})
        self.assertEqual((merged[M1], notes), (dict(full, role='excluded'), []))
        # A renumber here and a role change elsewhere both survive.
        merged, _ = self.merged({M1: dict(full, cube_id=8, updated_at=LATE)}, {M1: dict(full, role='led')}, {M1: full})
        self.assertEqual((merged[M1]['cube_id'], merged[M1]['role']), (8, 'led'))
        merged, notes = self.merged({M1: dict(full, role='led')}, {M1: dict(full, role='excluded')}, {M1: full})
        self.assertEqual((merged[M1]['role'], [n['kind'] for n in notes]), ('excluded', ['role']))

    def test_unknown_record_shape_is_left_alone(self):
        future = dict(record(M1, cube_id=7), firmware='9.9')
        merged, notes = merge_records({M1: record(M1, cube_id=8), M2: record(M2)}, {M1: future}, {}, True)
        self.assertEqual((sorted(merged), [n['kind'] for n in notes]), ([M2], ['invalid']))

    def test_without_shared_history_newest_wins_but_untouched_originals_yield(self):
        from database import Database
        original = Database.originals()[0]
        seed = record(original['mac'], cube_id=original['cube_id'], uid=original['uid'], pending_uid=original['uid'],
                      source='imported', status='unconfirmed', updated_at=LATE)  # retransmitted here, never edited
        web = record(original['mac'], cube_id=200, uid=original['uid'])
        self.assertEqual(merge_records({seed['mac']: seed}, {seed['mac']: web}, {}, False)[0][seed['mac']], web)
        edited = dict(seed, cube_id=201)
        self.assertEqual(merge_records({seed['mac']: edited}, {seed['mac']: web}, {}, False)[0][seed['mac']], edited)


if __name__ == '__main__': unittest.main()
