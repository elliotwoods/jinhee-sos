"""Zone flasher pipeline with a fake esptool (mirrors flashing_station/tests/test_flasher.py)."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'flasher'))
import zone_flash  # noqa: E402
import zone_build  # noqa: E402
import zonedb  # noqa: E402
from zone_flash import ZoneFlasher, parse_report  # noqa: E402
from database import Database  # noqa: E402
from zone_registry import ZoneStore  # noqa: E402

MAC = '14:63:93:C0:EC:14'
DATA = {'zcfg': dict(offset=0x210000, size=0x1000), 'zdb_a': dict(offset=0x211000, size=0x8000),
        'zdb_b': dict(offset=0x219000, size=0x8000)}


class ZoneFlasherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / 'devices.sqlite3'
        Database(self.db_path).close()
        self.build = self.root / 'build'
        self.build.mkdir()
        (self.build / 'app.bin').write_bytes(b'firmware')
        self.manifest = dict(version='preshow-2.0.0', build_hash='h', data=DATA,
                             segments=[dict(offset=0x10000, file='app.bin', sha256=zone_build.digest(self.build / 'app.bin'))])
        self.port = dict(port='/dev/fake', key='fake', candidate=True)
        self.calls, self.events = [], []
        self.mac, self.corrupt_readback, self.report = MAC, False, 'match'
        self.zone_line = 'ZONE: type=1 point=2 name=Preshow 2'

    def tearDown(self):
        self.tmp.cleanup()

    def fake_tool(self, args, timeout=90):
        args = [str(a) for a in args]
        self.calls.append(args)
        if args[-1] == 'version':
            return 'esptool v5.3.1'
        if 'flash-id' in args:
            return f'USB mode: USB-Serial/JTAG\nMAC: {self.mac}\nDetected flash size: 4MB'
        if 'read-flash' in args:
            offset, size, out = int(args[-3], 0), int(args[-2], 0), Path(args[-1])
            run = out.parent
            if offset == DATA['zcfg']['offset']:
                out.write_bytes((run / 'zcfg.bin').read_bytes()[:size])
            elif offset == DATA['zdb_a']['offset']:
                data = (run / 'zdb_a.bin').read_bytes()[:size]
                out.write_bytes(bytes([data[0] ^ 1]) + data[1:] if self.corrupt_readback else data)
            else:
                out.write_bytes(b'\xff' * 16)  # backup
        return 'ok'

    def boot(self, port, runner):
        db = Database(self.db_path)
        publication = ZoneStore(db).publish()
        db.close()
        if self.report is None:
            return None
        text = (f'FW: preshow-2.0.0\nMAC: {self.mac}\nCHANNEL: 2\n{self.zone_line}\n'
                f'DB: version={publication.version} count={publication.count} crc={publication.crc:08X} slot=A capacity=1819\n'
                'STATS: tags=0 unknown=0 send_fail=0 error=0\nREADY\n')
        return parse_report(text)

    def execute(self, point=2, name='Preshow 2', profile='preshow', params=()):
        with patch.object(zone_flash, 'DATA', self.root / 'data'), \
                patch('zone_flash.Runner.__call__', side_effect=self.fake_tool), \
                patch('zone_flash.ports', return_value=[self.port]), \
                patch('zone_build.load_manifest', return_value=self.manifest), \
                patch('zone_build.build_dir', return_value=self.build), \
                patch.object(ZoneFlasher, 'boot_report', side_effect=self.boot):
            return ZoneFlasher(self.db_path, lambda *e: self.events.append(e)).execute(self.port, profile, point, name, params)

    def test_success_writes_identity_database_and_records_zone(self):
        record = self.execute()
        self.assertEqual(record['result'], 'success', record.get('detail'))
        self.assertEqual((record['db_version'], record['db_count']), (1, 32))
        erased = [c[c.index('erase-region') + 1] for c in self.calls if 'erase-region' in c]
        self.assertEqual(erased, ['0x210000', '0x211000', '0x219000'])
        write = next(c for c in self.calls if 'write-flash' in c)
        self.assertIn('0x10000', write)
        self.assertEqual(Path(write[write.index('0x210000') + 1]).name, 'zcfg.bin')
        self.assertEqual(Path(write[write.index('0x211000') + 1]).name, 'zdb_a.bin')
        run = Path(write[write.index('0x211000') + 1]).parent
        slot = zonedb.parse_slot((run / 'zdb_a.bin').read_bytes())
        self.assertEqual((slot['version'], slot['count']), (1, 32))
        self.assertEqual(zonedb.parse_config((run / 'zcfg.bin').read_bytes()), dict(zone_type=1, point_id=2, name='Preshow 2'))
        self.assertEqual(sum('0x400000' in c for c in self.calls), 1)  # first flash backs up
        self.assertEqual(self.calls[-1][self.calls[-1].index('--after') + 1], 'watchdog-reset')
        self.assertTrue(all(c[c.index('--before') + 1] == 'no-reset' for c in self.calls[2:] if '--before' in c))
        db = Database(self.db_path)
        zones = ZoneStore(db).zones()
        db.close()
        self.assertEqual([(z['mac'], z['name'], z['source'], z['db_version']) for z in zones], [(MAC, 'Preshow 2', 'flash', 1)])
        self.calls.clear()
        self.assertEqual(self.execute()['result'], 'success')
        self.assertFalse(any('0x400000' in c for c in self.calls))  # backup kept, not repeated

    def test_refuses_registered_cube_and_bad_input(self):
        db = Database(self.db_path)
        cube = db.rows()[0]
        db.close()
        self.mac = cube['mac']
        record = self.execute()
        self.assertEqual(record['result'], 'failed')
        self.assertIn('neocube', record['detail'])
        self.assertFalse(any('write-flash' in c for c in self.calls))
        with self.assertRaises(ValueError):
            self.execute(point=9)
        with self.assertRaises(ValueError):
            self.execute(name='a name that is far too long')

    def test_readback_mismatch_and_boot_mismatch_are_not_success(self):
        self.corrupt_readback = True
        record = self.execute()
        self.assertEqual(record['result'], 'attention')
        self.assertIn('read-back', record['detail'])
        self.corrupt_readback, self.report = False, None
        self.assertEqual(self.execute()['result'], 'boot_unconfirmed')

    def test_pool_profile_writes_calibration_params(self):
        self.zone_line = 'ZONE: type=3 point=4 name=Pool Radio 4\nPOOL: radio=4 cal1=383.0 cal23=43.5 laser=ok member=-1'
        with self.assertRaises(ValueError):
            self.execute(point=4, name='Pool Radio 4', profile='pool')  # calibration is mandatory
        record = self.execute(point=4, name='Pool Radio 4', profile='pool', params=[3830, 435])
        self.assertEqual(record['result'], 'success', record.get('detail'))
        write = next(c for c in self.calls if 'write-flash' in c)
        zcfg = Path(write[write.index('0x210000') + 1]).read_bytes()
        self.assertEqual(zonedb.parse_config(zcfg), dict(zone_type=3, point_id=4, name='Pool Radio 4'))
        self.assertEqual(zonedb.parse_params(zcfg), [3830, 435])
        db = Database(self.db_path)
        zone = ZoneStore(db).zones()[0]
        db.close()
        self.assertEqual((zone['profile'], zone['params']), ('pool', '3830,435'))

    def test_pairing_station_is_refused_by_mac(self):
        self.mac = '3C:0F:02:AD:83:24'
        record = self.execute()
        self.assertEqual(record['result'], 'failed')
        self.assertIn('pairing station', record['detail'])
        self.assertFalse(any('write-flash' in c or 'erase-region' in c for c in self.calls))

    def test_non_candidate_port_is_never_opened(self):
        self.port = dict(self.port, candidate=False)
        record = self.execute()
        self.assertEqual(record['result'], 'failed')
        self.assertEqual(self.calls, [])

    def test_boot_report_opens_without_resetting(self):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.read.return_value = b'FW: preshow-2.0.0\nMAC: 14:63:93:C0:EC:14\nCHANNEL: 2\nDB: version=1 count=29 crc=11684781 slot=A\nREADY\n'
        opened = []
        conn.open.side_effect = lambda: opened.append((conn.dtr, conn.rts))
        with patch('zone_flash.ports', return_value=[self.port]), patch('zone_flash.serial.Serial', return_value=conn):
            report = ZoneFlasher(self.db_path, lambda *_: None).boot_report(self.port, MagicMock(), timeout=2)
        self.assertEqual(report['db_count'], 29)
        self.assertFalse(report['config_valid'])
        self.assertEqual(opened, [(True, True)])
        self.assertEqual((conn.dtr, conn.rts), (False, False))


class PartitionTests(unittest.TestCase):
    def test_sketch_partitions_have_data_slots_sized_for_firmware(self):
        for sketch in zone_build.SKETCHES:
            self.check(zone_build.parse_partitions(ROOT / 'firmware' / sketch / 'partitions.csv'))

    def check(self, table):
        self.assertEqual(table['nvs']['offset'], 0x9000)
        self.assertEqual(table['zdb_a']['size'], zonedb.SLOT_SIZE)
        self.assertEqual(table['zdb_b']['size'], zonedb.SLOT_SIZE)
        spans = sorted((p['offset'], p['offset'] + p['size']) for p in table.values())
        self.assertTrue(all(a[1] <= b[0] for a, b in zip(spans, spans[1:])))
        self.assertLessEqual(spans[-1][1], 0x400000)


if __name__ == '__main__':
    unittest.main()
