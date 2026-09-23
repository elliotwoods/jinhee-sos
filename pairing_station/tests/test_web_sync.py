from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from database import Database
import hostos
from fake_web_inventory import FakeWebInventory
from unittest.mock import patch
from web_client import Transient, Unauthorized, Unreachable, WebClient, WebError
import web_status
import web_sync

MAC = '02:00:00:00:00:01'
MAC2 = '02:00:00:00:00:02'
EARLY, LATE = '2026-09-21T09:00:00+00:00', '2026-09-21T10:00:00+00:00'


class WebSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.web = FakeWebInventory()
        self.paths = {name: self.root / name / 'devices.sqlite3' for name in 'ab'}
        for path in self.paths.values():
            Database(path).close()

    def tearDown(self):
        self.web.close()
        self.tmp.cleanup()

    def client(self, password='test-password'):
        return WebClient(self.web.url, password, 'jinhee-sos', timeout=2)

    def sync(self, name, **kw):
        return web_sync.run(self.paths[name], self.client(), 'test ' + name, **kw)

    def db(self, name):
        return Database(self.paths[name], recover_pending=False)

    def number(self, name, mac, number, when=None):
        def action(db):
            db.reserve(mac)
            db.rename(mac, number)
            if when:
                db.conn.execute('UPDATE devices SET updated_at=? WHERE mac=?', (when, mac))
                db.conn.commit()
        self.edit(name, action)

    def events(self, name, action):
        return self.edit(name, lambda db: [r['detail'] for r in db.conn.execute(
            'SELECT detail FROM events WHERE action=? ORDER BY id', (action,))])

    def edit(self, name, action):
        db = self.db(name)
        try:
            return action(db)
        finally:
            db.close()

    def test_two_computers_converge_and_idempotent(self):
        first = self.sync('a')
        self.assertEqual(len(first['upload']), 32)  # originals seed an empty web inventory
        second = self.sync('b')
        self.assertEqual(second['upload'], [])  # (its own seeds may take the web's timestamps)
        self.edit('a', lambda db: (db.reserve(MAC), db.rename(MAC, 100)))
        self.assertEqual(self.sync('a')['upload'], [MAC])
        result = self.sync('b')
        self.assertTrue(result['applied'])
        self.assertEqual(self.edit('b', lambda db: db.get(MAC)['cube_id']), 100)
        revision = self.web.revision
        again = self.sync('b')
        self.assertEqual((again['upload'], again['download'], self.web.revision), ([], [], revision))

    def test_same_device_changed_on_two_computers_keeps_the_newest(self):
        self.sync('a'); self.sync('b')
        mac = self.edit('a', lambda db: db.rows()[0]['mac'])
        self.number('a', mac, 100, LATE); self.sync('a')
        self.number('b', mac, 101, EARLY)
        result = self.sync('b')  # b's older renumber gives way, and b is told
        self.assertEqual((result['conflicts'], result['upload'], result['download']), ([], [], [mac]))
        self.assertEqual([n['kind'] for n in result['notes']], ['both_changed'])
        self.assertEqual(self.edit('b', lambda db: db.get(mac)['cube_id']), 100)
        self.assertEqual(len(self.events('b', 'sync_resolved')), 1)
        self.assertEqual(self.sync('b')['notes'], [])
        self.assertEqual(len(self.events('b', 'sync_resolved')), 1)  # audited once
        # An operator can still force a side.
        self.number('a', mac, 102, LATE); self.sync('a')
        self.number('b', mac, 103, EARLY)
        self.sync('b', resolutions={mac: 'local'})
        self.assertEqual(self.web.records[mac]['record']['cube_id'], 103)

    def test_bookkeeping_only_differences_resolve_to_newest(self):
        self.sync('a'); self.sync('b')
        mac = self.edit('a', lambda db: db.rows()[0]['mac'])
        stamp = lambda name, when, status, detail: self.edit(name, lambda db: (db.conn.execute(
            'UPDATE devices SET status=?, detail=?, updated_at=? WHERE mac=?', (status, detail, when, mac)), db.conn.commit()))
        # Same cube, same number and tag: acknowledged on one computer, unconfirmed later on the other.
        stamp('a', '2026-09-21T10:00:00+00:00', 'acknowledged', 'ACK on a')
        stamp('b', '2026-09-21T11:00:00+00:00', 'unconfirmed', 'No ACK on b')
        self.sync('a')
        result = self.sync('b')
        self.assertEqual((result['conflicts'], result['auto_resolved']), ([], [mac]))
        self.assertEqual(self.web.records[mac]['record']['detail'], 'No ACK on b')  # newest wins
        self.sync('a')
        self.assertEqual(self.edit('a', lambda db: db.get(mac)['detail']), 'No ACK on b')
        # A renumber beats a newer bookkeeping-only change: its status describes the new number.
        stamp('b', '2099-01-01T00:00:00+00:00', 'acknowledged', 'seen again on b')
        self.edit('a', lambda db: db.rename(mac, 100))
        self.sync('a')
        result = self.sync('b')
        self.assertEqual((result['conflicts'], result['auto_resolved']), ([], [mac]))
        self.assertEqual(self.edit('b', lambda db: db.get(mac)['cube_id']), 100)

    def test_concurrent_push_is_retried_against_new_records(self):
        self.sync('a'); self.sync('b')
        mac = self.edit('a', lambda db: db.rows()[0]['mac'])
        other = self.edit('a', lambda db: db.rows()[1]['mac'])
        self.number('a', mac, 100, LATE)
        self.web.before_push = lambda: self.web.edit(mac, cube_id=102, detail='renumbered elsewhere', updated_at=EARLY)
        result = self.sync('a')  # re-planned against the other computer's record, not blindly overwritten
        self.assertEqual(([n['kind'] for n in result['notes']], result['uploaded']), (['both_changed'], [mac]))
        self.assertEqual(self.web.records[mac]['record']['cube_id'], 100)
        self.number('a', mac, 101, LATE)
        self.web.before_push = lambda: self.web.edit(other, detail='unrelated')
        self.sync('a')
        self.assertEqual(web_status.summarize(self.paths['a'], self.client())[0], 'warn')  # unseen web edit
        self.assertEqual(self.sync('a')['download'], [other])
        self.assertEqual(self.edit('a', lambda db: db.get(other)['detail']), 'unrelated')
        self.assertEqual(web_status.summarize(self.paths['a'], self.client()), ('ok', 'Web inventory: up to date'))

    def test_open_apps_upload_but_defer_applying(self):
        self.sync('a'); self.sync('b')
        self.edit('a', lambda db: (db.reserve(MAC), db.rename(MAC, 100))); self.sync('a')
        self.edit('b', lambda db: (db.reserve('02:00:00:00:00:02'), db.rename('02:00:00:00:00:02', 101)))
        with self.paths['b'].with_suffix('.lock').open('a') as lock:
            hostos.lock_file(lock, blocking=True)
            result = self.sync('b')
            self.assertFalse(result['applied'])
            self.assertEqual(result['unapplied'], 1)
            self.assertIsNone(self.edit('b', lambda db: db.get(MAC)))
            self.assertEqual(web_status.summarize(self.paths['b'], self.client())[0], 'warn')
        self.assertEqual(self.web.records['02:00:00:00:00:02']['record']['cube_id'], 101)
        self.assertEqual(self.sync('b')['download'], [MAC])
        self.assertEqual(self.edit('b', lambda db: db.get(MAC)['cube_id']), 100)
        self.assertEqual(web_status.summarize(self.paths['b'], self.client()), ('ok', 'Web inventory: up to date'))

    def test_number_used_on_two_computers_is_settled_without_anyone_deciding(self):
        self.sync('a'); self.sync('b')
        self.number('a', MAC, 100, LATE); self.sync('a')
        self.number('b', MAC2, 100, EARLY)
        result = self.sync('b')
        self.assertEqual([(n['kind'], n['mac'], n['local_lost']) for n in result['notes']], [('number_lost', MAC2, True)])
        self.assertEqual([entry['mac'] for entry in result['lost']], [MAC2])
        self.assertIn('loses number 100', result['lost'][0]['text'])
        self.assertEqual(self.edit('b', lambda db: (db.get(MAC)['cube_id'], db.get(MAC2)['cube_id'], db.get(MAC2)['status'])),
                         (100, None, 'needs_number'))
        self.assertEqual(self.web.records[MAC2]['record']['cube_id'], None)
        self.assertEqual(len(self.events('b', 'sync_resolved')), 1)
        self.sync('a')
        self.assertEqual(self.edit('a', lambda db: db.get(MAC2)['cube_id']), None)
        again = self.sync('b')
        self.assertEqual((again['upload'], again['download'], again['notes'], again['lost']), ([], [], [], []))

    def test_the_other_computer_hears_what_its_device_lost(self):
        self.sync('a'); self.sync('b')
        self.number('b', MAC2, 100, EARLY); self.sync('b')  # b uploads first, a settles it later
        self.number('a', MAC, 100, LATE); self.sync('a')
        result = self.sync('b')  # an ordinary download for the merge, but b's operator must know
        self.assertEqual((result['notes'], [entry['mac'] for entry in result['lost']]), ([], [MAC2]))

    def test_a_push_made_invalid_by_another_computer_is_replanned(self):
        self.sync('a'); self.sync('b')
        self.number('b', MAC2, 100, EARLY)
        self.number('a', MAC, 100, LATE)
        self.web.before_push = lambda: self.sync('b')  # b takes number 100 on the web between a's pull and push
        result = self.sync('a')
        self.assertEqual((self.web.records[MAC]['record']['cube_id'], self.web.records[MAC2]['record']['cube_id']), (100, None))
        self.assertEqual(sorted(result['uploaded']), [MAC, MAC2])

    def test_lost_push_response_and_busy_web_recover_by_themselves(self):
        self.sync('a')
        self.number('a', MAC, 100)
        self.web.after_push = lambda: True  # stored, but the answer never arrives
        result = self.sync('a')
        self.assertEqual((self.web.pushes, result['upload'], self.web.records[MAC]['record']['cube_id']), (2, [], 100))
        self.number('a', MAC, 101)
        self.web.failures = [(503, '<html>busy</html>'), (500, {'error': 'Document changed during write'})]
        self.assertEqual(self.sync('a')['uploaded'], [MAC])  # the pull is retried
        self.web.failures = [(503, 'busy')] * 3
        with self.assertRaises(Transient) as caught:
            self.sync('a')
        self.assertFalse(caught.exception.after_push)
        self.assertIn('temporarily unavailable', str(caught.exception))

    def test_crash_between_upload_and_baseline_is_harmless(self):
        self.sync('a'); self.sync('b')
        self.number('a', MAC, 100)
        with patch.object(web_sync, 'save_baseline', side_effect=OSError('power cut')):
            with self.assertRaises(OSError) as caught:
                self.sync('a')
        self.assertTrue(caught.exception.after_push)
        revision = self.web.revision
        result = self.sync('a')
        self.assertEqual((result['upload'], result['download'], self.web.revision), ([], [], revision))
        self.assertEqual(self.sync('b')['download'], [MAC])

    def test_local_change_during_sync_is_merged_not_overwritten(self):
        self.sync('a'); self.sync('b')
        self.number('b', MAC2, 100); self.sync('b')
        self.number('a', MAC, 101)
        # While a's upload is in flight, an app on a registers another device.
        self.web.before_push = lambda: self.number('a', '02:00:00:00:00:03', 102)
        result = self.sync('a')
        self.assertTrue(result['applied'])
        self.assertEqual(self.edit('a', lambda db: [db.get(m)['cube_id'] for m in (MAC, MAC2, '02:00:00:00:00:03')]), [101, 100, 102])
        self.assertEqual(self.web.records['02:00:00:00:00:03']['record']['cube_id'], 102)

    def test_one_sync_at_a_time_per_computer(self):
        with web_sync.sync_lock(self.paths['a']):
            with self.assertRaises(web_sync.SyncBusy):
                self.sync('a')
        self.sync('a')

    def test_sign_in_page_is_not_a_wrong_password(self):
        self.web.failures = [(401, '<html>Vercel Authentication</html>')]
        with self.assertRaises(WebError) as caught:
            self.client().head()
        self.assertNotIsInstance(caught.exception, Unauthorized)
        self.assertEqual(caught.exception.code, 401)

    def test_status_never_raises(self):
        self.assertIn('never synced', web_status.summarize(self.paths['a'], self.client())[1])
        self.sync('a')
        self.assertEqual(web_status.summarize(self.paths['a'], self.client()), ('ok', 'Web inventory: up to date'))
        self.web.offline = True
        self.edit('a', lambda db: db.reserve(MAC))
        level, text = web_status.summarize(self.paths['a'], self.client())
        self.assertIn('offline', text); self.assertIn('1 local change', text)
        self.web.offline = False
        self.assertIn('rejected the password', web_status.summarize(self.paths['a'], self.client('wrong'))[1])
        no_password = WebClient(self.web.url, None, 'jinhee-sos')  # host apps: local comparison only
        self.web.offline = True  # proves no request is made
        self.assertEqual(web_status.summarize(self.paths['a'], no_password),
                         ('warn', 'Web inventory: 1 local change not uploaded — run Web Sync'))
        self.web.offline = False
        self.sync('a')
        self.assertEqual(web_status.summarize(self.paths['a'], no_password)[0], 'muted')
        status = web_status.WebStatus(self.paths['a'], start=False)
        self.assertIn('never synced', status.check()[1])  # default server differs from the fake
        self.paths['a'].unlink()
        self.assertEqual(status.check()[0], 'muted')

    def test_password_and_unreachable(self):
        self.client().head()
        with self.assertRaises(Unauthorized):
            self.client('wrong').head()
        with self.assertRaises(Unreachable):
            WebClient('http://127.0.0.1:9', 'x', timeout=1).head()
        with self.assertRaises(Unauthorized):  # no password: refused before any network I/O
            WebClient('http://127.0.0.1:9', timeout=1).head()


if __name__ == '__main__':
    unittest.main()
