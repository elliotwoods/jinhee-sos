"""Dongle flashing with a fake esptool: refusals, NVS-preserving segments, no SQLite on the worker."""
import contextlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'dbmanager'))
import dongle  # noqa: E402

PORT = dict(port='/dev/cu.fake', key='k', candidate=True)
MAC = 'AA:BB:CC:00:11:22'
KNOWN = dict(cubes={'02:00:00:00:00:01': 5, '02:00:00:00:00:02': None}, zones={'14:63:93:C0:EC:14'}, excluded={MAC})


class DongleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.build = Path(self.tmp.name) / 'build'
        self.build.mkdir()
        for name, data in [('bootloader', b'B'), ('partitions', b'P'), ('app', b'A' * 10)]:
            (self.build / f'pairing_station.ino{"" if name == "app" else "." + name}.bin').write_bytes(data)
        merged = bytearray(b'\xff' * 0x20000)
        merged[0xE000:0x10000] = b'\x01' * 0x2000
        (self.build / 'pairing_station.ino.merged.bin').write_bytes(bytes(merged))
        self.calls, self.mac = [], MAC

    def tearDown(self):
        self.tmp.cleanup()

    def fake_tool(self, args, timeout=90):
        args = [str(a) for a in args]
        self.calls.append(args)
        if args[-1] == 'version':
            return 'esptool v5.3.1'
        if 'read-flash' in args:
            Path(args[-1]).write_bytes(b'\xff' * 0x400000)
        if 'flash-id' in args:
            return f'Chip type: ESP32-C3\nUSB mode: USB-Serial/JTAG\nMAC: {self.mac}\n'
        return 'ok'

    def flash(self, state='current'):
        with patch.object(dongle.PAIRING, 'build', self.build), patch.object(dongle, 'BACKUPS', self.build / 'backups'), patch.object(dongle, 'build_state', return_value=state), \
                patch.object(dongle, 'build') as build, patch('backend.Runner.__call__', side_effect=self.fake_tool), \
                patch.object(dongle, 'ports', return_value=[PORT]), \
                patch.object(dongle, 'PortLock', lambda _: contextlib.nullcontext()):
            try:
                return dongle.flash(PORT, KNOWN, Path(self.tmp.name) / 'run', lambda *e: None), build
            except RuntimeError as exc:
                return exc, build

    def test_writes_segments_without_touching_nvs(self):
        mac, build = self.flash()
        self.assertEqual(mac, MAC)
        build.assert_not_called()
        write = next(c for c in self.calls if 'write-flash' in c)
        offsets = [a for a in write if a.startswith('0x')]
        self.assertEqual(offsets, ['0x0', '0x8000', '0xe000', '0x10000'])  # NVS 0x9000-0xDFFF untouched
        boot_app0 = Path(write[write.index('0xe000') + 1]).read_bytes()
        self.assertEqual(boot_app0, b'\x01' * 0x2000)
        self.assertEqual(write[write.index('--after') + 1], 'watchdog-reset')
        self.assertNotIn('erase-flash', sum(self.calls, []))
        self.assertTrue((self.build / 'backups' / 'AABBCC001122.bin').is_file())
        self.assertLess([i for i, c in enumerate(self.calls) if 'read-flash' in c][0],
                        [i for i, c in enumerate(self.calls) if 'write-flash' in c][0])
        self.calls.clear()
        self.flash()
        self.assertFalse(any('read-flash' in c for c in self.calls))  # backup kept, not repeated

    def test_builds_when_stale(self):
        _, build = self.flash('stale')
        build.assert_called_once()

    def test_refuses_cubes_zones_and_the_station(self):
        for mac, text in [('02:00:00:00:00:01', 'cube #5'), ('02:00:00:00:00:02', 'is a cube in'),
                          ('14:63:93:C0:EC:14', 'zone board'), ('3C:0F:02:AD:83:24', 'installed pairing station')]:
            self.calls.clear()
            self.mac = mac
            error, _ = self.flash()
            self.assertIsInstance(error, RuntimeError)
            self.assertIn(text, str(error))
            self.assertIn('nothing was written', str(error))
            self.assertFalse(any('write-flash' in c or 'read-flash' in c for c in self.calls))

    def test_mainshow_firmware_and_controller_protection(self):
        stem = 'MainshowController.ino'
        self.assertEqual(dongle.artifacts(dongle.MAINSHOW)['app'].name, stem + '.bin')
        self.assertEqual(dongle.MAINSHOW.sketch.name, 'MainshowController')
        for name, data in [('bootloader', b'B'), ('partitions', b'P'), ('app', b'M' * 10)]:
            (self.build / f'{stem}{"" if name == "app" else "." + name}.bin').write_bytes(data)
        (self.build / f'{stem}.merged.bin').write_bytes((self.build / 'pairing_station.ino.merged.bin').read_bytes())
        known = dict(KNOWN, controllers={MAC})
        # Both firmwares build into the fixture: the refused write below is the (default) pairing one.
        with patch.object(dongle.MAINSHOW, 'build', self.build), patch.object(dongle.PAIRING, 'build', self.build), \
                patch.object(dongle, 'BACKUPS', self.build / 'backups'), \
                patch.object(dongle, 'build_state', return_value='current'), patch('backend.Runner.__call__', side_effect=self.fake_tool), \
                patch.object(dongle, 'ports', return_value=[PORT]), patch.object(dongle, 'PortLock', lambda _: contextlib.nullcontext()):
            # The controller cannot be turned back into a relay dongle by the dongle flasher...
            with self.assertRaisesRegex(RuntimeError, 'Mainshow controller'):
                dongle.flash(PORT, known, Path(self.tmp.name) / 'run', lambda *e: None)
            self.assertFalse(any('write-flash' in c for c in self.calls))
            # ...but the Mainshow app may (re)write the controller firmware to it.
            self.assertEqual(dongle.flash(PORT, known, Path(self.tmp.name) / 'run2', lambda *e: None,
                                          firmware=dongle.MAINSHOW), MAC)
        write = next(c for c in self.calls if 'write-flash' in c)
        self.assertEqual(Path(write[write.index('0x10000') + 1]).read_bytes(), b'M' * 10)
        self.assertEqual(dongle.refusal('02:00:00:00:00:01', known, dongle.MAINSHOW)[:22], '02:00:00:00:00:01 is a')

    def test_general_radio_firmware_and_backups(self):
        stem = 'GeneralRadio.ino'
        self.assertEqual(dongle.artifacts(dongle.GENERAL)['app'].name, stem + '.bin')
        self.assertEqual((dongle.GENERAL.sketch.name, dongle.GENERAL.version), ('GeneralRadio', 'general-radio-1.2.0'))
        self.assertTrue(dongle.is_general('general-radio-1.0.0') and not dongle.is_general('nct-pairing-1.8-zones') and not dongle.is_general(None))
        self.assertTrue(dongle.show_capable('general-radio-1.0.0') and dongle.show_capable('mainshow-1.2.0') and not dongle.show_capable('nct-pairing-1.8-zones'))
        self.assertEqual(dongle.RELAY_VERSIONS, {'nct-pairing-1.8-zones', 'general-radio-1.2.0', 'general-radio-1.1.0', 'general-radio-1.0.0'})
        for name, data in [('bootloader', b'B'), ('partitions', b'P'), ('app', b'G' * 10)]:
            (self.build / f'{stem}{"" if name == "app" else "." + name}.bin').write_bytes(data)
        (self.build / f'{stem}.merged.bin').write_bytes((self.build / 'pairing_station.ino.merged.bin').read_bytes())
        # A recorded Mainshow controller is refused the general radio as it is refused the relay.
        self.assertIn('Mainshow controller', dongle.refusal(MAC, dict(KNOWN, controllers={MAC}), dongle.GENERAL))
        self.assertIsNone(dongle.refusal(MAC, KNOWN, dongle.GENERAL))  # an excluded ex-cube may be given it
        with patch.object(dongle.GENERAL, 'build', self.build), patch.object(dongle, 'BACKUPS', self.build / 'backups'), \
                patch.object(dongle, 'build_state', return_value='current'), patch('backend.Runner.__call__', side_effect=self.fake_tool), \
                patch.object(dongle, 'ports', return_value=[PORT]), patch.object(dongle, 'PortLock', lambda _: contextlib.nullcontext()), \
                patch.object(dongle.time, 'strftime', side_effect=['20260923-010000', '20260923-010001']):
            for _ in range(2):
                self.assertEqual(dongle.flash(PORT, KNOWN, Path(self.tmp.name) / 'run', lambda *e: None,
                                              firmware=dongle.GENERAL, backup='always'), MAC)
        writes = [c for c in self.calls if 'write-flash' in c]
        self.assertEqual(Path(writes[0][writes[0].index('0x10000') + 1]).read_bytes(), b'G' * 10)
        reads = [c for c in self.calls if 'read-flash' in c]
        self.assertEqual(len(reads), 2, 'backup="always" reads the flash before every write')
        backups = sorted(p.name for p in (self.build / 'backups').iterdir())
        self.assertEqual(len(backups), 2)
        self.assertTrue(all(b.startswith('AABBCC001122-') and b.endswith('.bin') for b in backups), backups)
        self.assertLess(self.calls.index(reads[0]), self.calls.index(writes[0]))

    def test_controller_record(self):
        sys.path.insert(0, str(ROOT.parent / 'pairing_station'))
        from database import Database
        db = Database(Path(self.tmp.name) / 'devices.sqlite3')
        try:
            self.assertEqual(dongle.controllers(db), set())
            dongle.set_controller(db, MAC, True)
            self.assertEqual(dongle.known_boards(db, [])['controllers'], {MAC})
            dongle.set_controller(db, MAC, False)
            self.assertEqual(dongle.controllers(db), set())
        finally:
            db.close()

    def test_known_boards_snapshot(self):
        sys.path.insert(0, str(ROOT.parent / 'pairing_station'))
        from database import Database
        db = Database(Path(self.tmp.name) / 'devices.sqlite3')
        try:
            station = db.rows()[0]['mac']
            db.set_role(station, 'excluded')
            known = dongle.known_boards(db, [dict(mac='14:63:93:C0:EC:14')])
            self.assertNotIn(station, known['cubes'])
            self.assertIn(station, known['excluded'])
            self.assertEqual(len(known['cubes']), 31)
            self.assertIsNone(dongle.refusal(station, known))  # an existing dongle/station may be reflashed
        finally:
            db.close()


if __name__ == '__main__':
    unittest.main()
