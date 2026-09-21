import base64
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


def web_doc(records, version):
    """A web zone-database document as web/src/lib/zonedb.ts returns it."""
    p = zonedb.Publication(version, records)
    return dict(version=version, hash=zonedb.content_hash(records), count=p.count, crc=p.crc,
                records_b64=base64.b64encode(p.body).decode(), published_at='2026-09-21T00:00:00Z', published_by='test')


class ZoneRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / 'devices.sqlite3')
        self.sent, self.logs = [], []
        self.now, self.wall = 1000.0, 1_700_000_000.0
        self.zones = ZoneRegistry(self.db, self.sent.append, self.logs.append, lambda: self.now, lambda: self.wall)
        self.zones.store.cache(web_doc(self.zones.store.records(), 1))

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

    def test_cached_web_publication(self):
        store = self.zones.store
        p1 = store.current()
        self.assertEqual((p1.version, p1.count), (1, 32))
        self.assertFalse(store.local_differs())
        self.assertTrue(store.published()['universal'])
        self.db.reserve('02:00:00:00:00:99')
        self.assertFalse(store.local_differs())  # no UID yet: not a zone mapping
        self.db.prepare('02:00:00:00:00:99', '04:0A:0B:0C')
        self.db.result('02:00:00:00:00:99', True, 'ack')
        self.assertTrue(store.local_differs())
        self.assertEqual(store.current().version, 1)  # nothing is allocated locally
        self.assertTrue(store.cache(web_doc(store.records(), 2)))
        self.assertEqual((store.current().version, store.current().count), (2, 33))
        self.assertFalse(store.cache(web_doc(store.records()[:5], 1)))  # never goes back
        self.assertFalse(store.cache(web_doc(store.records(), 2)))  # already cached
        bad = dict(web_doc(store.records(), 3), crc=1)
        with self.assertRaises(ValueError):
            store.cache(bad)
        self.assertEqual(store.current().version, 2)

    def test_legacy_local_publication_until_first_web_publish(self):
        with self.db.conn:
            self.db.conn.execute("DELETE FROM metadata WHERE key LIKE 'zone_db_%'")
        store = self.zones.store
        with self.assertRaises(ValueError):
            store.current()
        records = store.records()
        p = zonedb.Publication(7, records)
        with self.db.conn:
            for key, value in [('zone_db_version', 7), ('zone_db_hash', zonedb.content_hash(records)),
                               ('zone_db_count', p.count), ('zone_db_crc', p.crc)]:
                self.db.conn.execute('INSERT INTO metadata VALUES (?,?)', (key, str(value)))
        self.assertEqual(store.current().version, 7)
        self.assertFalse(store.cache(web_doc(records, 3)))  # web must be lifted above v7 by publishing
        self.db.set_role(self.db.rows()[0]['mac'], 'excluded')
        with self.assertRaises(ValueError):
            store.current()

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
        self.zones.event(dict(event='zone_frame', mac=ZONE, hex=status_hex(5, 0)))
        self.assertEqual(self.zones.expected, {ZONE2})  # a zone ahead of this version never joins
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

    def test_classification_and_in_range(self):
        p = self.zones.store.current()
        for mac, version, crc in [(ZONE, p.version, p.crc), (ZONE2, 0, 0), ('14:63:93:C0:EC:16', p.version, 123),
                                  ('14:63:93:C0:EC:17', p.version + 4, 9)]:
            self.zones.event(dict(event='zone_frame', mac=mac, hex=status_hex(version, crc)))
        self.zones.event(dict(event='zone_frame', mac='14:63:93:C0:EC:18', hex=status_hex(0, 0, staging=(p.version, 1, 3))))
        states = {z['mac']: z['state'] for z in self.zones.zone_rows()}
        self.assertEqual(states, {ZONE: 'current', ZONE2: 'behind', '14:63:93:C0:EC:16': 'ahead',
                                  '14:63:93:C0:EC:17': 'ahead', '14:63:93:C0:EC:18': 'updating'})
        self.assertTrue(all(z['in_range'] for z in self.zones.zone_rows()))
        self.wall += ZoneRegistry.IN_RANGE + 1
        self.assertFalse(any(z['in_range'] for z in self.zones.zone_rows()))
        self.assertEqual(self.zones.store.highest_seen(), p.version + 4)

    def test_signal_strength_is_smoothed_and_optional(self):
        self.zones.event(dict(event='zone_frame', mac=ZONE, hex=status_hex(1, 2)))  # firmware 1.6: no rssi
        self.assertIsNone(self.zones.zone_rows()[0]['rssi'])
        self.zones.event(dict(event='zone_frame', mac=ZONE, hex=status_hex(1, 2), rssi=-60))
        self.zones.event(dict(event='zone_frame', mac=ZONE, hex=status_hex(1, 2), rssi=-80))
        self.assertAlmostEqual(self.zones.zone_rows()[0]['rssi'], -66)
        self.zones.event(dict(event='zone_frame', mac=ZONE, hex=status_hex(1, 2), rssi=0))  # invalid: ignored
        self.assertAlmostEqual(self.zones.zone_rows()[0]['rssi'], -66)

    def test_auto_refresh_interval(self):
        self.zones.tick(True, STATION)
        self.ack_all()
        self.now += ZoneRegistry.AUTO_QUERY_INTERVAL
        self.zones.tick(True, STATION)
        self.assertEqual(len(self.sent), 1)  # manual mode: every 30 s
        self.zones.set_auto_refresh(True)
        self.zones.tick(True, STATION)
        self.ack_all()
        self.now += ZoneRegistry.AUTO_QUERY_INTERVAL
        self.zones.tick(True, STATION)
        self.assertEqual([zonedb.frame_kind(f) for _, f in self.frames()], [zonedb.ZONE_QUERY] * 3)

    def test_update_selected_zone_is_unicast_and_never_forced(self):
        p = self.zones.update(ZONE)
        self.run_ticks(5)
        mac, announce = self.frames()[0]
        self.assertEqual((mac, zonedb.ANNOUNCE.unpack(announce)[7]), (ZONE, 0))
        self.zones.event(dict(event='zone_frame', mac=ZONE, hex=status_hex(p.version, p.crc)))
        self.zones.tick(True, STATION)
        self.assertIsNone(self.zones.publication)

    def test_walkaround_updates_behind_zones_in_range_only(self):
        p = self.zones.store.current()
        far, ahead = '14:63:93:C0:EC:16', '14:63:93:C0:EC:17'
        self.zones.event(dict(event='zone_frame', mac=far, hex=status_hex(0, 0)))
        self.wall += ZoneRegistry.IN_RANGE + 1  # `far` walked out of range
        self.zones.event(dict(event='zone_frame', mac=ZONE, hex=status_hex(0, 0)))
        self.zones.event(dict(event='zone_frame', mac=ZONE2, hex=status_hex(p.version, p.crc)))
        self.zones.event(dict(event='zone_frame', mac=ahead, hex=status_hex(p.version + 3, 1)))
        self.zones.set_walkaround(True)
        self.zones.tick(True, STATION)
        self.assertEqual(self.zones.expected, {ZONE})
        self.assertTrue(self.zones.walk_run)
        self.run_ticks(6)
        self.assertEqual(self.frames()[0][0], BROADCAST)
        self.zones.event(dict(event='zone_frame', mac=ZONE, hex=status_hex(p.version, p.crc)))
        self.run_ticks(1)
        self.assertIsNone(self.zones.publication)
        self.assertIn('confirmed on 1 zone', self.zones.message)
        # A zone that does not confirm is backed off rather than hammered.
        self.zones.event(dict(event='zone_frame', mac=far, hex=status_hex(0, 0)))
        self.run_ticks(1)
        self.assertEqual(self.zones.expected, {far})
        self.now += ZoneRegistry.WALK_TIMEOUT + 1
        self.zones.event(dict(event='zone_frame', mac=far, hex=status_hex(0, 0)))
        self.run_ticks(1)
        self.assertIn('timed out', self.zones.message)
        self.run_ticks(1)
        self.assertIsNone(self.zones.publication)
        self.now += ZoneRegistry.WALK_BACKOFF + 1
        self.zones.event(dict(event='zone_frame', mac=far, hex=status_hex(0, 0)))
        self.run_ticks(1)
        self.assertEqual(self.zones.expected, {far})
        self.zones.set_walkaround(False)
        self.assertIsNone(self.zones.publication)

    def settings(self, mac, gain, applied, result, nonce=0):
        frame = zonedb.SETTINGS.pack(b'NZ', 1, zonedb.ZONE_SETTINGS, nonce, gain, applied, result)
        return self.zones.event(dict(event='zone_frame', mac=mac, hex=frame.hex().upper()))

    def zone(self, mac):
        return next(z for z in self.zones.zone_rows() if z['mac'] == mac)

    def test_rx_gain_settings_and_set_request(self):
        # Settings arriving before any status have no row to annotate.
        self.assertTrue(self.settings(ZONE, 48, 48, 0))
        self.assertEqual(self.zones.zone_rows(), [])
        self.zones.event(dict(event='zone_frame', mac=ZONE, hex=status_hex(1, 0)))
        self.assertIsNone(self.zone(ZONE)['rx_gain'])  # older firmware/dongle: never reported
        self.settings(ZONE, 48, 48, 0, nonce=5)
        self.assertEqual((self.zone(ZONE)['rx_gain'], self.zone(ZONE)['rx_gain_applied']), (48, 48))
        # The request is a unicast set-config frame; only the zone's own report settles it.
        self.sent.clear()
        self.zones.set_rx_gain(ZONE, 38)
        self.assertEqual(self.frames(), [(ZONE, zonedb.set_config_frame(38))])
        self.assertEqual(self.zone(ZONE)['rx_gain_pending'], 38)
        self.settings(ZONE, 48, 48, zonedb.SET_NONE, nonce=77)  # a routine query answered meanwhile
        self.assertEqual(self.zone(ZONE)['rx_gain_pending'], 38)
        self.settings(ZONE, 38, 38, zonedb.SET_OK)
        self.assertIsNone(self.zone(ZONE)['rx_gain_pending'])
        self.assertEqual((self.zone(ZONE)['rx_gain'], self.zone(ZONE)['set_result']), (38, zonedb.SET_OK))
        self.assertTrue(any('RX gain 38 dB — ok' in line for line in self.logs))
        # A failure reply (nonce 0) settles it too, and says the old gain still applies.
        self.zones.set_rx_gain(ZONE, 23)
        self.settings(ZONE, 38, 38, zonedb.SET_FLASH_FAILED)
        self.assertIsNone(self.zone(ZONE)['rx_gain_pending'])
        self.assertTrue(any('flash write failed (still 38 dB)' in line for line in self.logs))
        # No answer at all (old zone firmware ignores the frame): the request times out with a message.
        self.zones.set_rx_gain(ZONE, 43)
        self.now += self.zones.SET_TIMEOUT + 1
        self.zones.tick(True, STATION)
        self.assertIsNone(self.zone(ZONE)['rx_gain_pending'])
        self.assertTrue(any('RX gain 43 dB not confirmed' in line for line in self.logs))
        with self.assertRaises(ValueError):
            self.zones.set_rx_gain(ZONE, 40)
        # Reflashed with other firmware: the old settings are forgotten until reported again.
        frame = bytearray(bytes.fromhex(status_hex(1, 0)))
        frame[26:42] = b'preshow-3.3.0'.ljust(16, b'\0')
        self.zones.event(dict(event='zone_frame', mac=ZONE, hex=frame.hex()))
        self.assertIsNone(self.zone(ZONE)['rx_gain'])

    def test_settings_columns_migrate_an_existing_table(self):
        path = Path(self.temp.name) / 'old.sqlite3'
        old = Database(path)
        with old.conn:
            old.conn.execute('CREATE TABLE zones (mac TEXT PRIMARY KEY, name TEXT, last_seen TEXT)')
            old.conn.execute("INSERT INTO zones (mac, name) VALUES ('AA', 'x')")
        from zone_registry import ZoneStore, ZONE_COLUMNS
        with old.conn:
            for column in ZONE_COLUMNS[1:]:
                old.conn.execute(f'ALTER TABLE zones ADD COLUMN {column} INTEGER')
            for column in ('last_seen_epoch', 'source', 'detail'):
                old.conn.execute(f'ALTER TABLE zones ADD COLUMN {column} TEXT')
        store = ZoneStore(old)
        store.settings('AA', dict(rx_gain=33, rx_gain_applied=None, set_result=5))
        row = store.zones()[0]
        self.assertEqual((row['rx_gain'], row['rx_gain_applied'], row['set_result']), (33, None, 5))
        old.close()

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
