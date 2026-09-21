import fcntl
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from database import Database  # noqa: E402
from fake_web_inventory import FakeWebInventory  # noqa: E402
import sync_all  # noqa: E402
import web_client  # noqa: E402
from web_client import WebClient  # noqa: E402
import web_sync  # noqa: E402

MAC = '02:00:00:00:00:01'


class PasswordStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch.object(web_client, 'PASSWORD_FILE', Path(self.tmp.name) / 'data' / 'web_password')
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_store_is_owner_only_and_used_by_default(self):
        self.assertIsNone(web_client.load_password())
        self.assertIsNone(WebClient('http://x').password)
        web_client.save_password('s3cret')
        self.assertEqual(stat.S_IMODE(os.stat(web_client.PASSWORD_FILE).st_mode), 0o600)
        self.assertEqual(WebClient('http://x').password, 's3cret')
        self.assertIsNone(WebClient('http://x', None).password)  # explicit None: no password
        web_client.forget_password()
        self.assertIsNone(web_client.load_password())
        web_client.forget_password()  # idempotent


class SyncAllTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.web = FakeWebInventory()
        self.paths = {n: Path(self.tmp.name) / n / 'devices.sqlite3' for n in 'ab'}
        for path in self.paths.values():
            Database(path).close()

    def tearDown(self):
        self.web.close()
        self.tmp.cleanup()

    def client(self, password=None):
        return WebClient(self.web.url, password or self.web.password, 'jinhee-sos', timeout=2)

    def register(self, name, number, uid='04:0A:0B:0C'):
        db = Database(self.paths[name], recover_pending=False)
        db.reserve(MAC)
        db.rename(MAC, number)
        db.prepare(MAC, uid)
        db.result(MAC, True, 'ack')
        db.close()

    def status(self, name, **kw):
        return sync_all.status(self.paths[name], self.client(**kw))

    def test_states(self):
        self.assertEqual(sync_all.status(self.paths['a'], WebClient(self.web.url, None, 'jinhee-sos'))['state'], 'signin')
        self.assertEqual(self.status('a', password='wrong')['state'], 'unauthorized')
        self.web.close()
        self.assertEqual(self.status('a')['state'], 'offline')
        self.web = FakeWebInventory()

    def test_counts_and_one_click_sync_across_two_computers(self):
        first = self.status('a')
        self.assertEqual((first['inventory_up'], first['zone_publish'], first['up'], first['down']), (32, True, 33, 0))
        result = sync_all.sync(self.paths['a'], self.client(), 'a')
        self.assertEqual(result['zone']['published']['version'], 1)
        self.assertEqual(self.status('a')['up'] + self.status('a')['down'], 0)
        # Computer b: nothing local to upload; the web has the published zone DB to pull.
        b = self.status('b')
        self.assertEqual((b['up'], b['zone_pull'], b['down']), (0, True, 1))
        again = sync_all.sync(self.paths['b'], self.client(), 'b')
        self.assertFalse(again['zone']['changed'])  # same mappings: no new version
        self.assertEqual(self.web.zonedb['version'], 1)
        self.assertEqual((self.status('b')['up'], self.status('b')['down']), (0, 0))
        # A new mapping on b: ↑1 inventory + ↑1 zone DB; after Sync, a sees ↓1 + ↓1.
        self.register('b', 100)
        b = self.status('b')
        self.assertEqual((b['inventory_up'], b['zone_publish'], b['up']), (1, True, 2))
        self.assertEqual(sync_all.sync(self.paths['b'], self.client(), 'b')['zone']['published']['version'], 2)
        a = self.status('a')
        self.assertEqual((a['inventory_down'], a['zone_pull'], a['down']), (1, True, 2))  # inventory + zone DB
        sync_all.sync(self.paths['a'], self.client(), 'a')
        self.assertEqual(self.web.zonedb['version'], 2)
        db = Database(self.paths['a'], recover_pending=False)
        self.assertEqual(db.get(MAC)['cube_id'], 100)
        db.close()

    def test_same_cube_registered_on_two_computers_still_publishes(self):
        sync_all.sync(self.paths['a'], self.client(), 'a')
        sync_all.sync(self.paths['b'], self.client(), 'b')
        self.register('a', 101)
        sync_all.sync(self.paths['a'], self.client(), 'a')
        self.register('b', 102, uid='04:0A:0B:0D')  # later: the newest registration wins
        self.assertEqual(self.status('b')['conflicts'], 0)
        result = sync_all.sync(self.paths['b'], self.client(), 'b')
        self.assertEqual((result['blocked'], result['zone_error'], self.web.zonedb['version']), (None, None, 3))
        self.assertIn(self.web.records[MAC]['record']['cube_id'], (101, 102))

    def test_zone_publish_failure_is_not_a_failed_sync(self):
        self.register('a', 100)
        self.web.zonedb_missing = True  # a server from before the zone database
        result = sync_all.sync(self.paths['a'], self.client(), 'a')
        self.assertEqual((len(result['sync']['uploaded']), result['zone']), (33, None))
        self.assertIn('404', result['zone_error'])
        self.web.zonedb_missing = False
        self.assertEqual(sync_all.sync(self.paths['a'], self.client(), 'a')['zone']['published']['version'], 1)

    def test_status_says_what_is_wrong_instead_of_offline(self):
        self.web.failures = [(500, '<html>oops</html>')]
        status = self.status('a')
        self.assertEqual(status['state'], 'error')
        self.assertIn('temporary problem', status['message'])

    def test_host_app_lock_and_idle_flag(self):
        sync_all.sync(self.paths['a'], self.client(), 'a')
        self.register('b', 100)
        sync_all.sync(self.paths['b'], self.client(), 'b')
        lock = self.paths['a'].with_suffix('.lock').open('a')  # the pairing app itself is open
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            busy = sync_all.sync(self.paths['a'], self.client(), 'a', held=('.lock',), apply_ok=False)
            self.assertEqual((busy['sync']['applied'], busy['sync']['unapplied']), (False, 1))
            idle = sync_all.sync(self.paths['a'], self.client(), 'a', held=('.lock',), apply_ok=True)
            self.assertTrue(idle['sync']['applied'])
        finally:
            lock.close()

    def test_upload_only_and_download_only(self):
        web_sync.run(self.paths['a'], self.client(), 'a')
        web_sync.run(self.paths['b'], self.client(), 'b')
        self.register('a', 100)
        down = web_sync.run(self.paths['a'], self.client(), 'a', upload=False)
        self.assertEqual((down['uploaded'], down['waiting_upload']), ([], [MAC]))
        self.assertEqual(self.status('a')['inventory_up'], 1)  # still waiting to upload
        up = web_sync.run(self.paths['a'], self.client(), 'a', download=False)
        self.assertEqual(up['uploaded'], [MAC])
        b = web_sync.run(self.paths['b'], self.client(), 'b', download=False)
        self.assertEqual((b['applied'], b['unapplied']), (False, 1))
        self.assertEqual(self.status('b')['inventory_down'], 1)
        web_sync.run(self.paths['b'], self.client(), 'b', upload=False)
        self.assertEqual(self.status('b')['inventory_down'], 0)


if __name__ == '__main__':
    unittest.main()
