import json
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import zonedb  # noqa: E402

ORIGINALS = json.loads((ROOT.parent / 'pairing_station/original_32.json').read_text(encoding='utf-8'))


class ZoneDbTests(unittest.TestCase):
    def test_records_sorted_filtered_and_validated(self):
        rows = ORIGINALS + [dict(cube_id=40, mac='02:00:00:00:00:40', uid=None),
                            dict(cube_id=None, mac='02:00:00:00:00:41', uid='04:01:02:03'),
                            dict(cube_id=41, mac='02:00:00:00:00:42', uid='04:09:09:09')]
        records = zonedb.records_from_rows(rows)
        self.assertEqual(len(records), 33)
        self.assertEqual(records[0][1], bytes.fromhex('04090909'))  # 4-byte UIDs sort first
        keys = [(len(uid), uid) for _, uid, _ in records]
        self.assertEqual(keys, sorted(keys))
        with self.assertRaises(ValueError):
            zonedb.records_from_rows(ORIGINALS + [dict(cube_id=50, mac='02:00:00:00:00:50', uid=ORIGINALS[0]['uid'])])
        with self.assertRaises(ValueError):
            zonedb.records_from_rows([dict(cube_id=1, mac='FF:FF:FF:FF:FF:FF', uid='04:01:02:03')])

    def test_slot_and_config_round_trip(self):
        records = zonedb.records_from_rows(ORIGINALS)
        image = zonedb.slot_image(records, 7, generation=3)
        self.assertEqual(len(image), 24 + 18 * 32)
        parsed = zonedb.parse_slot(image + b'\xff' * 100)
        self.assertEqual((parsed['version'], parsed['generation'], parsed['count']), (7, 3, 32))
        self.assertEqual(parsed['records'], records)
        corrupt = bytearray(image)
        corrupt[30] ^= 1
        self.assertIsNone(zonedb.parse_slot(bytes(corrupt)))
        self.assertIsNone(zonedb.parse_slot(b'\xff' * 0x8000))
        config = zonedb.config_image(1, 3, 'Preshow 3')
        self.assertEqual(len(config), 28)
        self.assertEqual(zonedb.parse_config(config), dict(zone_type=1, point_id=3, name='Preshow 3', rx_gain=48))
        self.assertEqual(zonedb.parse_config(zonedb.config_image(1, 3, 'Preshow 3', rx_gain=23))['rx_gain'], 23)
        with self.assertRaises(ValueError):
            zonedb.config_image(1, 3, 'Preshow 3', rx_gain=40)
        # A config written before the setting existed stores 0 there, which means the default.
        legacy = bytearray(config)
        legacy[7] = 0
        legacy[24:28] = zonedb.crc32(bytes(legacy[:24])).to_bytes(4, 'little')
        self.assertEqual(zonedb.parse_config(bytes(legacy))['rx_gain'], 48)
        with self.assertRaises(ValueError):
            zonedb.config_image(1, 3, 'x' * 16)
        with self.assertRaises(ValueError):
            zonedb.config_image(9, 3, 'bad type')
        # The reset plate kind (5) is a plate kind only; it round-trips like the cube-valued kinds.
        self.assertEqual(zonedb.parse_config(zonedb.config_image(5, 1, 'Reset 1')), dict(zone_type=5, point_id=1, name='Reset 1', rx_gain=48))
        self.assertEqual(zonedb.ZONE_TYPES[5], 'reset')
        with self.assertRaises(ValueError):
            zonedb.config_image(6, 1, 'above the last kind')

    def test_publication_frames(self):
        records = zonedb.records_from_rows(ORIGINALS)
        p = zonedb.Publication(5, records)
        self.assertEqual(p.chunk_count, 3)
        announce = p.announce_frame()
        self.assertEqual(len(announce), 18)
        self.assertEqual(zonedb.frame_kind(announce), zonedb.DB_ANNOUNCE)
        _, _, _, version, count, chunks, per_chunk, flags, crc = zonedb.ANNOUNCE.unpack(announce)
        self.assertEqual((version, count, chunks, per_chunk, flags, crc), (5, 32, 3, 12, 0, p.crc))
        self.assertEqual(zonedb.ANNOUNCE.unpack(p.announce_frame(force=True))[7], zonedb.ANNOUNCE_FORCE)
        lengths = [len(p.chunk_frame(i)) for i in range(p.chunk_count)]
        self.assertEqual(lengths, [11 + 18 * 12, 11 + 18 * 12, 11 + 18 * 8])
        self.assertEqual(b''.join(p.chunk_frame(i)[11:] for i in range(3)), p.body)
        for n in range(1, 13):  # never collides with cube (24) or media (2) frame lengths
            self.assertNotIn(11 + 18 * n, (2, 24))
        self.assertTrue(all(len(p.chunk_frame(i)) <= 250 for i in range(p.chunk_count)))
        self.assertEqual(zonedb.Publication(1, []).chunk_count, 0)

    def test_status_and_log_parsing(self):
        name = b'Preshow 1'.ljust(16, b'\0')
        fw = b'preshow-2.0.0'.ljust(16, b'\0')
        status = zonedb.STATUS.pack(b'NZ', 1, zonedb.ZONE_STATUS, 9, 1, 1, name, fw, 4, 33, 0xDEADBEEF, 5, 2, 3, 100,
                                    12, 2, 1, 6, 2, 1, 2)
        parsed = zonedb.parse_status(status)
        self.assertEqual((parsed['name'], parsed['firmware'], parsed['db_version'], parsed['db_crc'], parsed['staging_chunks']),
                         ('Preshow 1', 'preshow-2.0.0', 4, 0xDEADBEEF, 2))
        self.assertTrue(parsed['config_valid'])
        entry = zonedb.LOG_ENTRY.pack(4, bytes.fromhex('04AABBCC').ljust(7, b'\0'), 99, 1, 12)
        log = zonedb.LOG_HEADER.pack(b'NZ', 1, zonedb.ZONE_LOG, 3, 1) + entry + b'\0' * (17 * 7)
        self.assertEqual(zonedb.parse_log(log)['entries'], [dict(uid='04:AA:BB:CC', cube_id=99, result='delivered', age_s=12)])
        with self.assertRaises(ValueError):
            zonedb.parse_status(b'XX' + status[2:])

    def test_small_frames(self):
        self.assertEqual(zonedb.query_frame(zonedb.QUERY_LOG, 7), b'NZ\x01\x20\x07\x00\x00\x00\x02')
        self.assertEqual(len(zonedb.identify_frame(99)), 5)
        self.assertEqual(zonedb.identify_frame(99)[4], 60)
        self.assertEqual(struct.unpack('<I', zonedb.reboot_frame()[4:])[0], zonedb.REBOOT_CONFIRM)

    def test_rx_gain_frames(self):
        frame = zonedb.set_config_frame(38)
        self.assertEqual(frame, b'NZ\x01\x25SCFG\x26')  # confirm word "SCFG" little-endian, then 38
        self.assertEqual(zonedb.frame_kind(frame), zonedb.ZONE_SET_CONFIG)
        with self.assertRaises(ValueError):
            zonedb.set_config_frame(40)
        settings = zonedb.SETTINGS.pack(b'NZ', 1, zonedb.ZONE_SETTINGS, 0, 43, 43, zonedb.SET_OK)
        self.assertEqual(zonedb.parse_settings(settings), dict(nonce=0, rx_gain=43, rx_gain_applied=43, set_result=1))
        unapplied = zonedb.SETTINGS.pack(b'NZ', 1, zonedb.ZONE_SETTINGS, 5, 0, 0, zonedb.SET_NONE)
        self.assertEqual(zonedb.parse_settings(unapplied), dict(nonce=5, rx_gain=48, rx_gain_applied=None, set_result=0))
        for bad in (settings[:-1], b'XX' + settings[2:]):
            with self.assertRaises(ValueError):
                zonedb.parse_settings(bad)
        self.assertNotIn(len(frame), (2, 24))
        self.assertNotIn(len(settings), (2, 24))


if __name__ == '__main__':
    unittest.main()
