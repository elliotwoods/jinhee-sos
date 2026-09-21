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
        if 'flash-id' in args:
            return f'Chip type: ESP32-C3\nMAC: {self.mac}\n'
        return 'ok'

    def flash(self, state='current'):
        with patch.object(dongle, 'BUILD', self.build), patch.object(dongle, 'build_state', return_value=state), \
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
        self.assertEqual(write[write.index('--after') + 1], 'hard-reset')
        self.assertNotIn('erase-flash', sum(self.calls, []))

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
            self.assertFalse(any('write-flash' in c for c in self.calls))

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
