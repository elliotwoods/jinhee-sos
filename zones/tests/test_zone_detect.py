"""Board identification, auto-flash planning and the cube monitor's parsing."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'flasher'))
import zone_flash  # noqa: E402  (sets up import paths)
import zone_build  # noqa: E402
import zone_detect  # noqa: E402
import zonedb  # noqa: E402
from zone_monitor import MonitorState  # noqa: E402
from database import Database  # noqa: E402

MAC = '14:63:93:C0:EC:14'
TABLE_ENTRY = lambda kind, sub, off, size, label: b'\xaa\x50' + bytes([kind, sub]) + off.to_bytes(4, 'little') + size.to_bytes(4, 'little') + label.ljust(16, b'\0') + bytes(4)
LEGACY_TABLE = TABLE_ENTRY(1, 2, 0x9000, 0x5000, b'nvs') + TABLE_ENTRY(0, 0x10, 0x10000, 0x140000, b'app0')
ZONE_TABLE = (TABLE_ENTRY(1, 2, 0x9000, 0x5000, b'nvs') + TABLE_ENTRY(0, 0x10, 0x10000, 0x200000, b'app0') +
              TABLE_ENTRY(1, 0x40, 0x210000, 0x1000, b'zcfg') + TABLE_ENTRY(1, 0x41, 0x211000, 0x8000, b'zdb_a') +
              TABLE_ENTRY(1, 0x41, 0x219000, 0x8000, b'zdb_b'))


def flash(regions):
    def read(offset, size):
        for start, data in regions.items():
            if start <= offset < start + max(len(data), 1):
                return data[offset - start:offset - start + size].ljust(size, b'\xff')
        return b'\xff' * size
    return read


class DetectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / 'devices.sqlite3')

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_signatures(self):
        cases = {b'..MEDIA BRIDGE PEER FAILED..NCT PRESHOW TAG PLATE..': ('legacy_zone', 'preshow'),
                 b'PRESHOW EXIT TAG NCT IMMERSIVE DEEP': ('legacy_zone', 'preshow_exit'),
                 b'..NCT MAIN SHOW ENTRANCE..': ('legacy_zone', 'mainshow'), b'MAINSHOW ENTRANCE TAG': ('legacy_zone', 'mainshow'),
                 b'NCT DESERT TAG PLATE v1.4.1-CH2-FIX': ('legacy_zone', 'desert'), b'=== POOL RADIO v1.2.0 ===': ('legacy_zone', 'pool'),
                 b'NCT PRESHOW TAG PLATE': ('legacy_zone', 'preshow_exit'), b'Cube READY': ('cube', None),
                 b'nct-pairing-1.6-zones': ('station', None), b'=== POOL CENTRAL READY ===': ('other', None),
                 b'NCT PRESHOW MEDIA BRIDGE': ('other', None), b'..NCT MAINSHOW CONTROLLER..': ('other', None), b'hello world': ('unknown', None), b'\xff' * 64: ('blank', None)}
        for image, (kind, profile) in cases.items():
            result = zone_detect.classify_image(image if kind == 'blank' else b'\x00' * 40 + image)
            self.assertEqual((result['kind'], result['profile']), (kind, profile), image)

    def test_real_firmware_dumps_when_available(self):
        workspace = ROOT.parent
        expected = [(workspace / 'zones/flasher/data/backups', '*original*.bin', 'legacy_zone', 'preshow'),
                    (workspace / 'pairing_station/data', 'station-before-zones-*.bin', 'station', None),
                    (workspace / 'flashing_station/build', 'neocore_usb.ino.bin', 'cube', None)]
        for folder, pattern, kind, profile in expected:
            for path in folder.glob(pattern):
                result = zone_detect.classify_image(path.read_bytes())
                self.assertEqual((result['kind'], result['profile']), (kind, profile), path.name)

    def test_from_flash(self):
        legacy = zone_detect.from_flash(MAC, self.db, flash({0x8000: LEGACY_TABLE, 0x10000: b'x' * 64 + b'NCT DESERT TAG PLATE'}))
        self.assertEqual((legacy['kind'], legacy['profile'], legacy['mac']), ('legacy_zone', 'desert', MAC))
        blank = zone_detect.from_flash(MAC, self.db, flash({}))
        self.assertEqual(blank['kind'], 'blank')
        records = zonedb.records_from_rows(self.db.rows())
        regions = {0x8000: ZONE_TABLE, 0x210000: zonedb.zcfg_image(3, 4, 'Pool Radio 4', [3830, 430], rx_gain=38),
                   0x211000: zonedb.slot_image(records, 5), 0x219000: zonedb.slot_image(records, 7, generation=3)}
        zone = zone_detect.from_flash(MAC, self.db, flash(regions))
        self.assertEqual((zone['kind'], zone['profile'], zone['point'], zone['name'], zone['params'], zone['db_version'], zone['db_count']),
                         ('nctzone', 'pool', 4, 'Pool Radio 4', [3830, 430], 7, 32))
        self.assertEqual(zone['rx_gain'], 38)
        regions[0x210000] = zonedb.zcfg_image(1, 2, 'Preshow 2')  # type 1 is shared by two profiles
        zone = zone_detect.from_flash(MAC, self.db, flash(regions))
        self.assertTrue(zone['ambiguous'] and zone['configured'])
        regions[0x210000] = zonedb.zcfg_image(5, 3, 'Reset 3')  # the reset plate kind has exactly one profile
        zone = zone_detect.from_flash(MAC, self.db, flash(regions))
        self.assertEqual((zone['kind'], zone['profile'], zone['point'], zone['name'], zone['zone_type'], zone['ambiguous']),
                         ('nctzone', 'reset', 3, 'Reset 3', 5, False))
        regions[0x210000] = b''
        self.assertFalse(zone_detect.from_flash(MAC, self.db, flash(regions))['configured'])
        cube = self.db.rows()[0]
        self.assertEqual(zone_detect.from_flash(cube['mac'], self.db, flash(regions))['kind'], 'cube')
        self.assertEqual(zone_detect.from_flash('3C:0F:02:AD:83:24', self.db, flash(regions))['kind'], 'station')

    def test_from_report_maps_firmware_to_profile(self):
        report = zone_flash.parse_report('FW: tagplate-2.1.0\nMAC: 14:63:93:C0:EC:14\nCHANNEL: 2\nZONE: type=4 point=2 name=Mainshow 2\n'
                                         'DB: version=3 count=30 crc=0000ABCD slot=B capacity=1819\nSTATS: tags=1 unknown=0 send_fail=0 error=0\nREADY\n')
        d = zone_detect.from_report(report)
        self.assertEqual((d['profile'], d['point'], d['name'], d['db_version']), ('mainshow', 2, 'Mainshow 2', 3))
        self.assertNotIn('rx_gain', d)  # tagplate-2.1.0 predates the setting
        self.assertEqual(zone_build.profile_for('tagplate-2.1.0', 1), 'preshow_exit')
        self.assertEqual(zone_build.profile_for('pool-2.1.0', 3), 'pool')
        self.assertEqual(zone_build.profile_for('reset-1.0.0', 5), 'reset')
        self.assertEqual(zone_build.PROFILES['reset']['sketch'], 'ResetZone')
        self.assertIsNone(zone_build.profile_for('mystery-1', 1))

    def test_plan(self):
        form = dict(profile='desert', point=3, name='Desert 3', params=[], rx_gain=33)
        manifests = {'DesertZone': dict(version='desert-2.1.0'), 'PoolZone': dict(version='pool-2.1.0')}
        published = dict(version=4, crc=0xAA)
        plan = lambda d, **kw: zone_detect.plan(d, form, manifests, published, **kw)
        for kind in ('cube', 'station', 'other'):
            self.assertEqual(plan(dict(kind=kind, label='x'), auto=True)['action'], 'refuse')
            self.assertEqual(plan(dict(kind=kind, label='x'))['action'], 'refuse')
            forced = plan(dict(kind=kind, label='x', mac='14:63:93:C0:EC:14'), force=True)
            self.assertEqual((forced['action'], forced['force'], forced['name']), ('flash', True, 'Desert 3'))
            self.assertEqual(plan(dict(kind=kind, label='x'), auto=True, force=True)['action'], 'refuse')  # never in auto
        station = dict(kind='station', label='Pairing station (protected)', mac='3C:0F:02:AD:83:24')
        self.assertEqual(plan(station, force=True)['action'], 'refuse')
        self.assertFalse(zone_detect.forceable(station))
        manual = plan(dict(kind='unknown', label='Unrecognised firmware'))
        self.assertEqual((manual['action'], manual['profile'], manual['point'], manual['name']), ('flash', 'desert', 3, 'Desert 3'))
        zone = dict(kind='nctzone', label='z', configured=True, profile='pool', point=2, name='Pool Radio 2', params=[3800, 400],
                    firmware='pool-2.0.0', db_version=4, db_crc=0xAA)
        keep = plan(zone, auto=True)  # identity is kept even though the form says desert 3
        self.assertEqual((keep['action'], keep['profile'], keep['point'], keep['name'], keep['params']), ('flash', 'pool', 2, 'Pool Radio 2', [3800, 400]))
        # The board's RX gain is kept too; a board too old to report one ran at the 48 dB default.
        self.assertEqual(keep['rx_gain'], 48)
        self.assertEqual(plan(dict(zone, rx_gain=23), auto=True)['rx_gain'], 23)
        self.assertEqual(plan(dict(zone, rx_gain=23))['rx_gain'], 33)  # manual flashing uses the form
        self.assertEqual(plan(dict(zone, firmware='pool-2.1.0'), auto=True)['action'], 'skip')
        self.assertEqual(plan(dict(zone, firmware='pool-2.1.0', db_version=3), auto=True)['action'], 'flash')
        self.assertEqual(plan(dict(zone, params=[]), auto=True)['action'], 'ask')
        self.assertEqual(plan(dict(zone, ambiguous=True), auto=True)['action'], 'ask')
        self.assertEqual(plan(dict(zone, configured=False), auto=True)['action'], 'ask')
        legacy = dict(kind='legacy_zone', label='Legacy desert plate', profile='desert')
        self.assertEqual(plan(legacy, auto=True)['action'], 'flash')
        self.assertEqual(plan(dict(legacy, profile='pool'), auto=True)['action'], 'ask')
        blank = dict(kind='blank', label='Blank flash', profile=None)
        self.assertEqual(plan(blank, auto=True)['action'], 'ask')
        self.assertEqual(plan(blank, auto=True, allow_unidentified=True)['action'], 'flash')


class MonitorTests(unittest.TestCase):
    def test_tag_lifecycle_and_commands(self):
        now = [1000.0]
        m = MonitorState(clock=lambda: now[0])
        for line in ['FW: preshow-2.1.0', 'MAC: 14:63:93:C0:EC:14', 'CHANNEL: 2', 'ZONE: type=1 point=1 name=Preshow 1',
                     'DB: version=1 count=29 crc=11684781 slot=A capacity=1819', 'STATS: tags=0 unknown=0 send_fail=0 error=0']:
            self.assertFalse(m.feed(line))
        self.assertTrue(m.feed('READY'))
        self.assertEqual((m.zone['name'], m.zone['db_count']), ('Preshow 1', 29))
        self.assertFalse(m.feed('TAG ENTER: 04:60'))
        self.assertTrue(m.feed('EVT TAG uid=04:60:35:4A:B6:21:91 cube=1 mac=AC:27:6E:80:37:BC zone=1'))
        self.assertEqual((m.current['cube_id'], m.current['state']), (1, 'pending'))
        self.assertEqual(m.display_zone(1)[0], 'unknown')
        m.feed('EVT SENT cube=1 type=6 value=1 ok=1')
        self.assertEqual(m.current['state'], 'delivered')
        self.assertEqual(m.display_zone(1), ('preshow', zonedb.ZONE_COLORS[1][1], 'cube acknowledged'))
        now[0] += 3
        m.feed('EVT LEAVE uid=04:60:35:4A:B6:21:91 cube=1 held_ms=2950')
        self.assertIsNone(m.current)
        self.assertEqual((m.history[0]['held_ms'], m.cubes[1]['taps']), (2950, 1))
        # Unknown tag, then an unacknowledged cube.
        m.feed('EVT TAG uid=04:AA:BB:CC cube=0 mac=- zone=1')
        self.assertEqual((m.current['cube_id'], m.current['mac'], m.current['state']), (None, None, 'unknown tag'))
        m.feed('EVT LEAVE uid=04:AA:BB:CC cube=0 held_ms=400')
        m.feed('EVT TAG uid=53:21:D4:CF:33:00:01 cube=2 mac=AC:27:6E:82:60:4C zone=1')
        m.feed('EVT SENT cube=2 type=6 value=1 ok=0')
        self.assertEqual(m.history[0]['state'], 'not acknowledged')
        self.assertEqual(m.display_zone(2)[2], 'NOT acknowledged by cube')
        # Commands from the UI: flash then clear.
        m.command_sent('flash', 1)
        m.feed('EVT SENT cube=1 type=6 value=3 ok=1')
        self.assertEqual(m.display_zone(1)[0], 'flashing')
        self.assertEqual(m.history[2]['state'], 'delivered')  # old taps are not rewritten by later commands
        m.feed('EVT SENT cube=1 type=6 value=0 ok=1')
        m.feed('EVT FLASH cube=1 done')
        self.assertEqual(m.display_zone(1)[0], 'idle')
        m.command_sent('flash', 1)
        m.command_sent('stop', None)
        self.assertFalse(m.cubes[1]['flashing'])
        m.feed('EVT SENT cube=1 type=7 value=1 ok=1')  # tag-state messages do not change the zone colour
        self.assertEqual(m.display_zone(1)[0], 'idle')
        # A tap whose send never completed is closed as not acknowledged, not left pending or credited to a later command.
        m.feed('EVT TAG uid=53:21:D4:CF:33:00:01 cube=2 mac=AC:27:6E:82:60:4C zone=1')
        m.feed('EVT SENT cube=2 type=6 value=0 ok=1')
        self.assertEqual(m.history[0]['state'], 'pending')
        m.feed('EVT LEAVE uid=53:21:D4:CF:33:00:01 cube=2 held_ms=500')
        self.assertEqual(m.history[0]['state'], 'not acknowledged')
        self.assertTrue(m.feed('DB UPDATE: committed version 2 (30 records, slot B)'))
        self.assertFalse(m.feed('EVT garbage'))
        self.assertEqual(m.reader_text()[1], 'warn')
        self.assertTrue(m.feed('NFC: ok=1 fw=32010607 polls=188 found=0 last_ms=84 max_ms=94 fast_fail=0 recoveries=0 sda=1 scl=1'))
        self.assertEqual(m.reader_text(), ('NFC reader scanning normally · 188 scans, 0 with a tag in the field · last scan 84 ms', 'ok'))
        m.feed('NFC: ok=0 fw=00000000 polls=190 found=0 last_ms=0 max_ms=94 fast_fail=10 recoveries=2 sda=0 scl=1')
        self.assertEqual(m.reader_text()[1], 'bad')
        self.assertIn('SDA=0', m.reader_text()[0])
        # The NFC line inside a "?" report does not break report parsing.
        for line in ['FW: preshow-2.2.0', 'MAC: 14:63:93:C0:EC:14', 'CHANNEL: 2', 'DB: version=1 count=29 crc=11684781 slot=A capacity=1819',
                     'NFC: ok=1 fw=32010607 polls=1 found=0 last_ms=84 max_ms=84 fast_fail=0 recoveries=0 sda=1 scl=1', 'READY']:
            m.feed(line)
        self.assertEqual(m.zone['firmware'], 'preshow-2.2.0')


if __name__ == '__main__':
    unittest.main()
