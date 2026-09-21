import fcntl
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from database import Database
from fake_web_inventory import FakeWebInventory
from inventory_sync import sync as git_sync
from web_client import Unauthorized, Unreachable, WebClient
import web_status
import web_sync

MAC = '02:00:00:00:00:01'


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
        self.assertEqual((second['upload'], second['download']), ([], []))
        self.edit('a', lambda db: (db.reserve(MAC), db.rename(MAC, 100)))
        self.assertEqual(self.sync('a')['upload'], [MAC])
        result = self.sync('b')
        self.assertTrue(result['applied'])
        self.assertEqual(self.edit('b', lambda db: db.get(MAC)['cube_id']), 100)
        revision = self.web.revision
        again = self.sync('b')
        self.assertEqual((again['upload'], again['download'], self.web.revision), ([], [], revision))

    def test_conflict_needs_explicit_resolution(self):
        self.sync('a'); self.sync('b')
        mac = self.edit('a', lambda db: db.rows()[0]['mac'])
        self.edit('a', lambda db: db.rename(mac, 100)); self.sync('a')
        self.edit('b', lambda db: db.rename(mac, 101))
        result = self.sync('b')
        self.assertEqual(result['conflicts'], [mac])
        self.assertEqual(self.edit('b', lambda db: db.get(mac)['cube_id']), 101)
        self.assertEqual(self.web.records[mac]['record']['cube_id'], 100)
        self.sync('b', resolutions={mac: 'local'})
        self.assertEqual(self.web.records[mac]['record']['cube_id'], 101)
        self.assertEqual(self.sync('a')['download'], [mac])
        self.assertEqual(self.edit('a', lambda db: db.get(mac)['cube_id']), 101)

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
        self.edit('a', lambda db: db.rename(mac, 100))
        self.web.before_push = lambda: self.web.edit(mac, cube_id=102, detail='renumbered elsewhere')
        result = self.sync('a')
        self.assertEqual(result['conflicts'], [mac])  # re-planned, not overwritten
        self.web.before_push = lambda: self.web.edit(other, detail='unrelated')
        self.edit('a', lambda db: db.rename(mac, 100))
        self.sync('a', resolutions={mac: 'local'})
        self.assertEqual(web_status.summarize(self.paths['a'], self.client())[0], 'warn')  # unseen web edit
        self.assertEqual(self.sync('a')['download'], [other])
        self.assertEqual(self.edit('a', lambda db: db.get(other)['detail']), 'unrelated')
        self.assertEqual(web_status.summarize(self.paths['a'], self.client()), ('ok', 'Web inventory: up to date'))

    def test_open_apps_upload_but_defer_applying(self):
        self.sync('a'); self.sync('b')
        self.edit('a', lambda db: (db.reserve(MAC), db.rename(MAC, 100))); self.sync('a')
        self.edit('b', lambda db: (db.reserve('02:00:00:00:00:02'), db.rename('02:00:00:00:00:02', 101)))
        with self.paths['b'].with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            result = self.sync('b')
            self.assertFalse(result['applied'])
            self.assertEqual(result['unapplied'], 1)
            self.assertIsNone(self.edit('b', lambda db: db.get(MAC)))
            self.assertEqual(web_status.summarize(self.paths['b'], self.client())[0], 'warn')
        self.assertEqual(self.web.records['02:00:00:00:00:02']['record']['cube_id'], 101)
        self.assertEqual(self.sync('b')['download'], [MAC])
        self.assertEqual(self.edit('b', lambda db: db.get(MAC)['cube_id']), 100)
        self.assertEqual(web_status.summarize(self.paths['b'], self.client()), ('ok', 'Web inventory: up to date'))

    def test_duplicate_number_is_rejected_before_any_write(self):
        self.sync('a'); self.sync('b')
        self.edit('a', lambda db: (db.reserve(MAC), db.rename(MAC, 100))); self.sync('a')
        self.edit('b', lambda db: (db.reserve('02:00:00:00:00:02'), db.rename('02:00:00:00:00:02', 100)))
        revision = self.web.revision
        with self.assertRaisesRegex(ValueError, 'Duplicate number'):
            self.sync('b')
        self.assertEqual(self.web.revision, revision)
        self.assertIsNone(self.edit('b', lambda db: db.get(MAC)))

    def test_git_and_web_interoperate(self):
        folder = self.root / 'inventory'
        for name in 'ab':
            self.edit(name, lambda db: git_sync(db, folder))
        self.sync('a'); self.sync('b')
        self.edit('a', lambda db: (db.reserve(MAC), db.rename(MAC, 100)))
        self.sync('a')                                   # a -> web
        self.sync('b')                                   # web -> b
        self.edit('b', lambda db: git_sync(db, folder))  # b -> git
        self.edit('a', lambda db: git_sync(db, folder))  # git -> a: identical, no conflict
        self.edit('b', lambda db: db.rename(MAC, 105))
        self.edit('b', lambda db: git_sync(db, folder))  # b -> git only
        self.edit('a', lambda db: git_sync(db, folder))  # git -> a
        self.assertEqual(self.sync('a')['upload'], [MAC])  # a forwards the Git change to web
        result = self.sync('b')                          # b already has it: no conflict
        self.assertEqual((result['conflicts'], result['download']), ([], []))

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
