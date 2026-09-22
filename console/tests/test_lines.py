import unittest

import support  # noqa: F401
from lines import classify


class LineTests(unittest.TestCase):
    CASES = [
        ('cube', 'UNREGISTERED', 'cube.unregistered', 'warn'),
        ('cube', 'REGISTERED Cube #44', 'cube.registered', 'ok'),
        ('cube', 'ESP-NOW INIT ERROR', 'cube.espnow_init_error', 'bad'),
        ('cube', 'SHOW_START IGNORED / ZONE=1', 'cube.show_start_ignored', 'warn'),
        ('cube', 'ZONE = 4', 'cube.zone', 'info'),
        ('zone', 'PARTITIONS MISSING: flash with the zone flasher (custom partitions.csv)', 'zone.partitions_missing', 'bad'),
        ('zone', 'CONFIG: INVALID', 'zone.config_invalid', 'bad'),
        ('zone', 'PN532 I2C LINE HELD LOW (check wiring / power-cycle the reader; retrying)', 'zone.pn532_line_low', 'bad'),
        ('zone', 'PN532 NOT FOUND (radio continues; retrying)', 'zone.pn532_not_found', 'bad'),
        ('zone', 'UNKNOWN CUBE', 'zone.unknown_cube', 'warn'),
        ('zone', 'Cube #12 NOT ACKNOWLEDGED', 'zone.not_acknowledged', 'warn'),
        ('zone', "ERR cube 44 is not in this zone's database", 'zone.not_in_db', 'warn'),
        ('zone', 'DB UPDATE: committed version 32 (33 records, slot B)', 'zone.db_committed', 'ok'),
        ('zone', 'DB UPDATE: flash commit failed; previous database kept', 'zone.db_commit_failed', 'bad'),
        ('zone', 'MEDIA FAIL: point 1 ON seq=3 unacknowledged after 3000ms', 'preshow.media_fail', 'warn'),
        ('zone', 'MEDIA LEGACY: point 1 ON seq=3 (2-byte fallback, unacknowledged)', 'preshow.media_legacy', 'info'),
        ('zone', '[ERROR] VL53L4CD', 'pool.vl53_error', 'bad'),
        ('poolcentral', 'RADIO TIMEOUT: 3@EE:33', 'central.radio_timeout', 'warn'),
        ('poolcentral', 'NOTE 2 live boards share a radio id with another; the central keeps one slot per sender', 'central.id_clash', 'bad'),
        ('preshowbridge', 'PRESHOW,2,ON', 'bridge.cue', 'info'),
        ('pooltest', 'EVENT USB watchdog: all off', 'pooltest.watchdog', 'warn'),
    ]

    def test_table(self):
        for role, line, tag, level in self.CASES:
            with self.subTest(line=line):
                result = classify(role, line)
                self.assertIsNotNone(result, line)
                self.assertEqual((result['tag'], result['level']), (tag, level))

    def test_fields(self):
        self.assertEqual(classify('cube', 'REGISTERED Cube #44')['fields'], {'number': '44'})
        self.assertEqual(classify('zone', "ERR cube 44 is not in this zone's database")['fields'], {'number': '44'})
        self.assertEqual(classify('preshowbridge', 'PRESHOW,2,ON')['fields'], {'point': '2', 'state': 'ON'})

    def test_quiet_lines(self):
        self.assertIsNone(classify('zone', 'READY'))
        self.assertIsNone(classify('cube', 'Cube READY'))
        self.assertIsNone(classify('station', 'anything'))


if __name__ == '__main__':
    unittest.main()
