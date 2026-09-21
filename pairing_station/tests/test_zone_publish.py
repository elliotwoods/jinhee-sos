from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from database import Database  # noqa: E402
from fake_web_inventory import FakeWebInventory  # noqa: E402
from web_client import WebClient, WebError  # noqa: E402
from zone_registry import ZoneStore  # noqa: E402
import web_status  # noqa: E402
import zone_publish  # noqa: E402
import zonedb  # noqa: E402

MAC = '02:00:00:00:00:01'


class ZonePublishTests(unittest.TestCase):
    """Two laptops sharing one web inventory must produce one increasing version sequence."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.web = FakeWebInventory()
        self.paths = {n: Path(self.tmp.name) / n / 'devices.sqlite3' for n in 'ab'}
        for path in self.paths.values():
            Database(path).close()

    def tearDown(self):
        self.web.close()
        self.tmp.cleanup()

    def client(self):
        return WebClient(self.web.url, 'test-password', 'jinhee-sos', timeout=2)

    def publish(self, name, **kw):
        return zone_publish.publish(self.paths[name], self.client(), 'test ' + name, **kw)

    def store(self, name, action):
        db = Database(self.paths[name], recover_pending=False)
        try:
            return action(ZoneStore(db))
        finally:
            db.close()

    def test_universal_versions_across_laptops(self):
        first = self.publish('a')
        self.assertEqual((first['published']['version'], first['published']['count'], first['changed']), (1, 32, True))
        # Laptop b has the same mappings: same version, nothing allocated.
        again = self.publish('b')
        self.assertEqual((again['published']['version'], again['changed']), (1, False))
        # b adds a cube mapping; a's next publish includes it (via the web inventory) and goes higher.
        db = Database(self.paths['b'], recover_pending=False)
        db.reserve(MAC)
        db.rename(MAC, 100)
        db.prepare(MAC, '04:0A:0B:0C')
        db.result(MAC, True, 'ack')
        db.close()
        self.assertEqual(self.publish('b')['published']['version'], 2)
        result = self.publish('a')
        self.assertEqual((result['published']['version'], result['published']['count'], result['changed']), (2, 33, False))
        self.assertEqual(self.store('a', lambda s: s.current().count), 33)
        self.assertEqual(self.web.zonedb['version'], 2)

    def test_min_version_lifts_legacy_counters_and_versions_on_air(self):
        def legacy(store):
            with store.conn:
                store.conn.execute("INSERT OR REPLACE INTO metadata VALUES ('zone_db_version','9')")
        self.store('a', legacy)
        self.assertEqual(self.publish('a')['published']['version'], 10)
        self.assertEqual(self.publish('b', seen_versions=[14])['published']['version'], 15)

    def test_pull_caches_web_publication(self):
        self.publish('a')
        published, status = zone_publish.pull(self.paths['b'], self.client())
        self.assertEqual((published['version'], status), (1, 'updated'))
        self.assertEqual(self.store('b', lambda s: s.current().crc), self.web.zonedb['crc'])
        self.assertEqual(zone_publish.pull(self.paths['b'], self.client())[1], 'current')

    def test_pull_reports_legacy_local_version_above_web(self):
        self.publish('a')

        def legacy(store):
            with store.conn:
                store.conn.execute("INSERT OR REPLACE INTO metadata VALUES ('zone_db_version','20')")
        self.store('b', legacy)
        published, status = zone_publish.pull(self.paths['b'], self.client())
        self.assertEqual((published['version'], status), (20, 'legacy_ahead'))
        self.assertEqual(self.publish('b')['published']['version'], 21)  # publishing lifts the web above it

    def test_pull_when_nothing_published_or_server_too_old(self):
        self.assertEqual(zone_publish.pull(self.paths['a'], self.client()), (self.store('a', lambda s: s.published()), 'none'))
        self.web.zonedb_missing = True
        with self.assertRaises(WebError):
            zone_publish.pull(self.paths['a'], self.client())

    def test_device_changed_on_two_computers_does_not_block_publishing(self):
        zone_publish.web_sync.run(self.paths['a'], self.client(), 'a')
        zone_publish.web_sync.run(self.paths['b'], self.client(), 'b')
        for name, number in (('a', 101), ('b', 102)):
            db = Database(self.paths[name], recover_pending=False)
            db.reserve(MAC)
            db.rename(MAC, number)
            db.close()
            if name == 'a':
                zone_publish.web_sync.run(self.paths['a'], self.client(), 'a')
        self.assertEqual(self.publish('b')['published']['version'], 1)  # the merge settled it; nobody had to decide

    def test_status_line_warns_about_unpublished_and_newer_web_versions(self):
        anonymous = WebClient(self.web.url, None, 'jinhee-sos', timeout=2)  # status lines have no password
        summary = lambda name: web_status.zone_summary(self.paths[name], anonymous)
        self.assertIn('never published', summary('a')[1])
        self.publish('a')
        self.assertIsNone(summary('a'))
        self.assertIn('v1 on the web, this computer has v0 — Pull', summary('b')[1])
        zone_publish.pull(self.paths['b'], self.client())
        self.assertIsNone(summary('b'))
        db = Database(self.paths['a'], recover_pending=False)
        db.reserve(MAC)
        db.rename(MAC, 100)
        db.prepare(MAC, '04:0A:0B:0C')
        db.result(MAC, True, 'ack')
        db.close()
        self.assertIn('1 mapping change not published', summary('a')[1])
        self.publish('a')
        self.assertIsNone(summary('a'))
        self.assertIn('v2 on the web, this computer has v1', summary('b')[1])
        # Offline (or a server without the route): local comparison only, never an exception.
        self.web.zonedb_missing = True
        self.assertIsNone(summary('a'))
        self.web.close()
        self.assertIsNone(summary('b'))
        self.web = FakeWebInventory()  # tearDown closes it

    def test_records_from_inventory_matches_local_rule(self):
        db = Database(self.paths['a'], recover_pending=False)
        from inventory_sync import snapshot
        snap = snapshot(db)
        db.set_role(db.rows()[0]['mac'], 'excluded')
        excluded = snapshot(db)
        self.assertEqual(zone_publish.records_from_inventory(snap), zonedb.records_from_rows(db.rows()))
        self.assertEqual(len(zone_publish.records_from_inventory(excluded)), 31)
        self.assertEqual(zone_publish.records_from_inventory(excluded), ZoneStore(db).records())
        db.close()


if __name__ == '__main__':
    unittest.main()
