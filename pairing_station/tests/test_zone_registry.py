import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from database import Database  # noqa: E402
from zone_registry import ZoneRegistry, BROADCAST  # noqa: E402
import zonedb  # noqa: E402

ZONE = '14:63:93:C0:EC:14'
ZONE2 = '14:63:93:C0:EC:15'
STATION = dict(zones=1, channel=2)


def status_hex(version, crc, count=32, name='Preshow 1', staging=(0, 0, 0), error=0):
    frame = zonedb.STATUS.pack(b'NZ', 1, zonedb.ZONE_STATUS, 0, 1, 1, name.encode().ljust(16, b'\0'),
                               b'preshow-2.0.0'.ljust(16, b'\0'), version, count, crc, *staging, 60, 0, 0, 0, error, 2, 1, 1)
    return frame.hex().upper()


class ZoneRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / 'devices.sqlite3')
        self.sent, self.logs = [], []
        self.now, self.wall = 1000.0, 1_700_000_000.0
        self.zones = ZoneRegistry(self.db, self.sent.append, self.logs.append, lambda: self.now, lambda: self.wall)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def ack_all(self):
        for message in list(self.sent):
            self.zones.event(dict(event='zone_sent', id=message['id'], status='delivered'))

    def run_ticks(self, n, busy=False):
        for _ in range(n):
            self.zones.tick(True, STATION, busy)
            self.ack_all()

    def frames(self):
        return [(m['mac'], bytes.fromhex(m['hex'])) for m in self.sent]

    def test_version_bumps_only_on_content_change(self):
        p1 = self.zones.store.publish()
        self.assertEqual((p1.version, p1.count), (1, 32))
        self.assertEqual(self.zones.store.publish().version, 1)
        self.db.reserve('02:00:00:00:00:99')
        self.assertEqual(self.zones.store.publish().version, 1)  # no UID yet: not a zone mapping
        row = self.db.get('02:00:00:00:00:99')
        self.db.prepare(row['mac'], '04:0A:0B:0C')
        self.db.result(row['mac'], True, 'ack')
        p2 = self.zones.store.publish()
        self.assertEqual((p2.version, p2.count), (2, 33))
        self.assertEqual(self.zones.store.published()['crc'], p2.crc)
        self.db.set_role(row['mac'], 'excluded')
        self.assertEqual(self.zones.store.publish().count, 32)

    def test_requires_zone_capable_station(self):
        with self.assertRaises(ValueError):
            self.zones.require(dict(channel=2), True)
        with self.assertRaises(ValueError):
            self.zones.require(STATION, False)
        self.zones.require(STATION, True)

    def test_carousel_until_known_zones_confirm(self):
        self.zones.event(dict(event='zone_frame', mac=ZONE, hex=status_hex(0, 0, count=0)))
        self.zones.tick(True, STATION)  # periodic broadcast status query
        self.assertEqual(self.frames()[-1][0], BROADCAST)
        self.assertEqual(zonedb.frame_kind(self.frames()[-1][1]), zonedb.ZONE_QUERY)
        self.sent.clear()
        p = self.zones.publish()
        self.assertEqual(self.zones.expected, {ZONE})
        self.zones.tick(True, STATION)
        self.zones.tick(True, STATION)
        self.assertEqual(len(self.sent), 1)  # waits for the station to confirm each relay
        self.ack_all()
        self.run_ticks(3)
        kinds = [zonedb.frame_kind(f) for _, f in self.frames()]
        self.assertEqual(kinds, [zonedb.DB_ANNOUNCE, zonedb.DB_CHUNK, zonedb.DB_CHUNK, zonedb.DB_CHUNK])
        self.assertTrue(all(mac == BROADCAST for mac, _ in self.frames()))
        self.assertEqual(self.zones.cycles, 1)
        # Pause between cycles, then repeat.
        self.sent.clear()
        self.run_ticks(1)
        self.assertFalse(self.sent)
        self.now += 1.1
        self.run_ticks(1)
        self.assertEqual(zonedb.frame_kind(self.frames()[0][1]), zonedb.DB_ANNOUNCE)
        # Staging progress is recorded; confirmation stops publishing.
        self.zones.event(dict(event='zone_frame', mac=ZONE, hex=status_hex(0, 0, count=0, staging=(1, 2, 3))))
        self.assertEqual(self.zones.zone_rows()[0]['staging_chunks'], 2)
        self.zones.event(dict(event='zone_frame', mac=ZONE, hex=status_hex(p.version, p.crc)))
        self.zones.tick(True, STATION)
        self.assertIsNone(self.zones.publication)
        self.assertIn('confirmed on 1 zone', self.zones.message)
        self.assertTrue(self.zones.zone_rows()[0]['current'])

    def test_new_zone_joins_and_timeout_reports_missing(self):
        self.zones.event(dict(event='zone_frame', mac=ZONE, hex=status_hex(0, 0)))
        self.wall += 16 * 60  # ZONE is no longer recent
        p = self.zones.publish()
        self.assertEqual(self.zones.expected, set())
        self.zones.event(dict(event='zone_frame', mac=ZONE2, hex=status_hex(0, 0)))
        self.assertEqual(self.zones.expected, {ZONE2})
        self.run_ticks(1, busy=True)
        self.run_ticks(1, busy=True)
        publish_frames = [f for _, f in self.frames() if zonedb.frame_kind(f) in (zonedb.DB_ANNOUNCE, zonedb.DB_CHUNK)]
        self.assertEqual(len(publish_frames), 1)  # throttled while pairing is active
        self.now += ZoneRegistry.PUBLISH_TIMEOUT + 1
        self.zones.tick(True, STATION)
        self.assertIsNone(self.zones.publication)
        self.assertIn(ZONE2, self.zones.message)
        self.assertNotEqual(self.zones.zone_rows()[1]['db_version'], p.version)

    def test_forced_rollback_targets_one_zone(self):
        with self.assertRaises(ValueError):
            self.zones.publish(force=True)
        self.zones.publish(target=ZONE, force=True)
        self.run_ticks(5)
        announce_mac, announce = self.frames()[0]
        self.assertEqual(announce_mac, ZONE)
        self.assertEqual(zonedb.ANNOUNCE.unpack(announce)[7], zonedb.ANNOUNCE_FORCE)
        self.assertTrue(all(mac == BROADCAST for mac, _ in self.frames()[1:]))

    def test_unacknowledged_relay_times_out_and_continues(self):
        self.zones.publish()
        self.zones.tick(True, STATION)
        self.zones.tick(True, STATION)
        self.assertEqual(len(self.sent), 1)
        self.now += ZoneRegistry.ACK_TIMEOUT
        self.zones.tick(True, STATION)
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.zones.send_failures, 1)
        request = self.sent[-1]['id']
        self.zones.event(dict(event='error', id=request, detail='Invalid JSON'))
        self.zones.tick(True, STATION)
        self.assertEqual(len(self.sent), 3)

    def test_disconnect_stops_publishing_and_commands(self):
        self.zones.publish()
        self.zones.tick(False, STATION)
        self.assertIsNone(self.zones.publication)
        self.sent.clear()
        self.zones.identify(ZONE, 5)
        self.zones.reboot(ZONE)
        self.zones.request_log(ZONE)
        kinds = [(mac, zonedb.frame_kind(f)) for mac, f in self.frames()]
        self.assertEqual(kinds, [(ZONE, zonedb.ZONE_IDENTIFY), (ZONE, zonedb.ZONE_REBOOT), (ZONE, zonedb.ZONE_QUERY)])

    def test_log_and_errors(self):
        entry = zonedb.LOG_ENTRY.pack(7, bytes.fromhex('0460354AB62191'), 1, 1, 3)
        log = zonedb.LOG_HEADER.pack(b'NZ', 1, zonedb.ZONE_LOG, 1, 1) + entry + b'\0' * (17 * 7)
        self.assertTrue(self.zones.event(dict(event='zone_frame', mac=ZONE, hex=log.hex())))
        self.assertTrue(self.zones.event(dict(event='zone_frame', mac=ZONE, hex=status_hex(1, 2, error=3))))
        row = self.zones.zone_rows()[0]
        self.assertEqual(row['error_text'], 'NFC reader not found')
        self.assertEqual(row['log']['entries'][0]['cube_id'], 1)
        self.assertTrue(any('NFC reader' in line for line in self.logs))
        self.assertTrue(self.zones.event(dict(event='zone_frame', mac=ZONE, hex='4E5A')))  # malformed, ignored
        request = self.zones.identify(ZONE)
        self.assertTrue(self.zones.event(dict(event='error', id=request, detail='nope')))
        self.assertFalse(self.zones.event(dict(event='error', id='other')))
        self.assertFalse(self.zones.event(dict(event='registered')))


if __name__ == '__main__':
    unittest.main()
