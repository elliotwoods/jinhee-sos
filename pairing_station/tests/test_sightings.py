from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from controller import Controller
from database import Database
from fake_web_inventory import FakeWebInventory
import sightings
from web_client import WebClient
import web_sync
from zone_registry import ZoneStore

MAC = '02:00:00:00:00:01'


class SightingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'devices.sqlite3'
        self.db = Database(self.path)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_record_keeps_latest_per_kind(self):
        sightings.record(self.db.conn, MAC, 'radio', 'a', '2026-09-21T10:00:00+00:00')
        sightings.record(self.db.conn, MAC, 'radio', 'old', '2026-09-20T10:00:00+00:00')  # older: ignored
        sightings.record(self.db.conn, MAC, 'usb', 'v1', '2026-09-21T09:00:00+00:00')
        cubes = sightings.collect(self.db.conn)['cubes']
        self.assertEqual(cubes[MAC]['radio'], {'at': '2026-09-21T10:00:00+00:00', 'detail': 'a'})
        self.assertEqual(cubes[MAC]['usb']['detail'], 'v1')

    def test_collect_uses_events_flash_runs_and_zones(self):
        self.db.reserve(MAC); self.db.rename(MAC, 50)
        self.db.mark_nfc_seen(MAC, '04:11:22:33')
        with self.db.conn:
            self.db.conn.execute('CREATE TABLE flash_runs (id TEXT PRIMARY KEY, mac TEXT, port TEXT, version TEXT, build_hash TEXT, '
                                 'started_at TEXT, finished_at TEXT, stage TEXT, result TEXT, detail TEXT, log_path TEXT)')
            self.db.conn.execute("INSERT INTO flash_runs VALUES ('1',?,'p','v1.4.1',NULL,'2026-09-21T08:00:00+00:00',NULL,'Complete','skipped','',NULL)", (MAC,))
            self.db.conn.execute("INSERT INTO flash_runs VALUES ('2',?,'p','v1.4.1',NULL,'2026-09-21T09:00:00+00:00',NULL,'Identify','failed','',NULL)", (MAC,))
        store = ZoneStore(self.db, wall=lambda: 1790000000.0)
        store.seen('14:63:93:C0:EC:14', {'name': 'Preshow 4', 'firmware': 'preshow-2.2.0', 'tags': 5})
        report = sightings.collect(self.db.conn)
        self.assertEqual(report['cubes'][MAC]['nfc']['detail'], '04:11:22:33')
        self.assertEqual(report['cubes'][MAC]['usb_flash'], {'at': '2026-09-21T08:00:00+00:00', 'detail': 'v1.4.1 · skipped'})
        zone = report['zones'][0]
        self.assertEqual((zone['name'], zone['tags']), ('Preshow 4', 5))
        self.assertTrue(zone['last_seen'].endswith('+00:00'))  # normalized from the local-time column

    def test_utc_normalizes_local_offsets(self):
        self.assertEqual(sightings.utc('2026-09-21T17:16:54+0900'), '2026-09-21T08:16:54+00:00')
        self.assertIsNone(sightings.utc('garbage'))

    def test_radio_discovery_is_throttled(self):
        clock = [1000.0]
        controller = Controller(self.db, lambda *a, **k: None, clock=lambda: clock[0])
        for _ in range(5):
            controller.event({'event': 'device', 'mac': MAC})
        first = sightings.collect(self.db.conn)['cubes'][MAC]['radio']['at']
        writes = []
        original = sightings.record
        sightings.record = lambda *a, **k: writes.append(a) or original(*a, **k)
        try:
            controller.event({'event': 'device', 'mac': MAC})
            clock[0] += 61
            controller.event({'event': 'device', 'mac': MAC})
        finally:
            sightings.record = original
        self.assertEqual(len(writes), 1)
        self.assertTrue(first)

    def test_zone_taps_map_uid_and_number_to_mac(self):
        self.db.reserve(MAC); self.db.rename(MAC, 50)
        with self.db.conn:
            self.db.conn.execute("UPDATE devices SET uid='04:11:22:33' WHERE mac=?", (MAC,))
        ZoneStore(self.db).seen('14:63:93:C0:EC:14', {'name': 'Preshow 4'})
        sightings.zone_taps(self.db.conn, '14:63:93:C0:EC:14', [
            {'uid': '04:11:22:33', 'cube_id': None, 'result': 'ok', 'age_s': 30},
            {'uid': '04:99:99:99', 'cube_id': 777, 'result': 'unknown', 'age_s': 1}], 1790000030.0)
        tap = sightings.collect(self.db.conn)['cubes'][MAC]['zone_tap']
        self.assertEqual(tap['detail'], 'Preshow 4 · ok')
        self.assertEqual(tap['at'], '2026-09-21T14:13:20+00:00')

    def test_sync_reports_sightings_and_failures_are_quiet(self):
        web = FakeWebInventory()
        try:
            self.db.mark_nfc_seen(self.db.rows()[0]['mac'], '04:11:22:33')
            self.db.close()
            client = WebClient(web.url, 'test-password', 'jinhee-sos', timeout=2, client='bench · Web Sync')
            result = web_sync.run(self.path, client, 'bench')
            self.assertEqual(result['sightings'], 1)
            self.assertIn('bench', web.sightings)
            self.assertEqual(len(web.sightings['bench']['cubes']), 1)
            bad = WebClient(web.url, 'wrong', 'jinhee-sos', timeout=2)
            self.assertIsNone(web_sync.report_sightings(self.path, bad))
        finally:
            web.close()
            self.db = Database(self.path)


if __name__ == '__main__':
    unittest.main()
