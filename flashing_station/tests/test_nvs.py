"""NVS image reader/writer (flashing_station/nvs.py) used to check and replace the cube's show over USB."""
import hashlib
import struct
import sys
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import nvs  # noqa: E402
from nvs import Entry, NvsError  # noqa: E402


def pattern(n, a, b):
    return bytes((i * a + b) % 256 for i in range(n))


UID = bytes.fromhex('04776655443324')
IMG = pattern(3084, 13, 5)          # the largest show image (NctShowEngine.h MAX_IMAGE)


def registered(show=None):
    """A partition like a registered cube's: PHY calibration, registration, optionally a show."""
    namespaces = ['phy', 'cube'] + (['show'] if show else [])
    entries = [Entry('phy', 'cal_data', nvs.BLOB, pattern(1904, 7, 1)), Entry('phy', 'cal_version', nvs.U32, 1235),
               Entry('cube', 'cubeID', nvs.U32, 34), Entry('cube', 'uidLen', nvs.U8, 7), Entry('cube', 'uid', nvs.BLOB, UID)]
    if show:
        version, img = show
        entries += [Entry('show', 'img', nvs.BLOB, img), Entry('show', 'crc', nvs.U32, zlib.crc32(img)),
                    Entry('show', 'ver', nvs.U32, version)]
    return nvs.build(namespaces, entries)


class OfficialGeneratorVectors(unittest.TestCase):
    """build() must match esp-idf-nvs-partition-gen 0.3.0 byte for byte (sha256 of its output for these CSVs)."""

    def test_registration_and_show(self):
        # key,type,encoding,value: cube namespace; cubeID u32 34; uidLen u8 7; uid binary UID;
        # show namespace; img binary pattern(3084, 7, 3); crc u32 crc32(img); ver u32 7
        img = pattern(3084, 7, 3)
        image = nvs.build(['cube', 'show'], [
            Entry('cube', 'cubeID', nvs.U32, 34), Entry('cube', 'uidLen', nvs.U8, 7), Entry('cube', 'uid', nvs.BLOB, UID),
            Entry('show', 'img', nvs.BLOB, img), Entry('show', 'crc', nvs.U32, zlib.crc32(img)), Entry('show', 'ver', nvs.U32, 7)])
        self.assertEqual(hashlib.sha256(image).hexdigest(), '80ce8b1ba9f5102f7e5885c82d8c2c9c777ab76e6951ef84e3ac309695169948')

    def test_blobs_split_across_pages_and_every_type(self):
        image = nvs.build(['phy', 'cube', 'misc', 'show'], [
            Entry('phy', 'cal_data', nvs.BLOB, pattern(1904, 7, 1)), Entry('phy', 'cal_version', nvs.U32, 1235),
            Entry('cube', 'cubeID', nvs.U32, 34), Entry('cube', 'uidLen', nvs.U8, 7), Entry('cube', 'uid', nvs.BLOB, UID),
            Entry('misc', 'big', nvs.BLOB, pattern(3500, 3, 9)), Entry('misc', 'name', nvs.STR, b'hello\0'),
            Entry('misc', 'n16', nvs.I16, -5), Entry('misc', 'n64', nvs.U64, 1234567890123),
            Entry('show', 'img', nvs.BLOB, IMG), Entry('show', 'crc', nvs.U32, zlib.crc32(IMG)), Entry('show', 'ver', nvs.U32, 7)])
        self.assertEqual(hashlib.sha256(image).hexdigest(), 'c373655b54f0ca9fbffd2448909889d3e0c946bd8b7651e83574235912ccea14')
        states = [struct.unpack_from('<I', image, p * nvs.PAGE)[0] for p in range(5)]
        self.assertEqual(states, [nvs.FULL, nvs.FULL, nvs.ACTIVE, nvs.UNINIT, nvs.UNINIT])


class ParseTests(unittest.TestCase):
    def test_round_trip_every_type(self):
        entries = [Entry('a', f'k{kind}', kind, value) for kind, value in (
            (nvs.U8, 255), (nvs.I8, -128), (nvs.U16, 65535), (nvs.I16, -1), (nvs.U32, 2 ** 32 - 1),
            (nvs.I32, -(2 ** 31)), (nvs.U64, 2 ** 64 - 1), (nvs.I64, -(2 ** 63)))]
        entries += [Entry('a', 'str', nvs.STR, b'text\0'), Entry('b', 'empty', nvs.BLOB, b''), Entry('b', 'img', nvs.BLOB, IMG)]
        self.assertEqual(nvs.parse(nvs.build(['a', 'b'], entries)), (['a', 'b'], entries))

    def test_runtime_layout_erased_entries_and_second_blob_version(self):
        """What a running cube leaves: an erased older value and a blob rewritten at chunk start 0x80."""
        image = bytearray(registered())
        page = image[:nvs.PAGE]
        used = [i for i in range(nvs.ENTRIES) if nvs._state(page, i) == nvs.WRITTEN]
        index = max(used) + 1
        old = nvs._Writer(0x2000)
        old.new_page()
        # An erased u32 and a live blob version 0x80 (chunk 0x80) whose version-0 chunks were orphaned.
        old.put(2, nvs.U32, 'stale', struct.pack('<I', 1) + b'\xff' * 4)
        old.put(2, nvs.BLOB_DATA, 'uid', struct.pack('<HHI', 7, 0xFFFF, nvs.crc(b'NEWUID!')), b'NEWUID!', chunk=0x80)
        at = nvs.FIRST + index * nvs.ENTRY
        image[at:at + 3 * nvs.ENTRY] = old.pages[0][nvs.FIRST:nvs.FIRST + 3 * nvs.ENTRY]
        for i in range(index, index + 3):
            image[32 + i // 4] &= ~(1 << ((i % 4) * 2)) & 0xFF
        image[32 + index // 4] &= ~(3 << ((index % 4) * 2)) & 0xFF     # erase 'stale'
        # Point the uid index at the 0x80 chunk.
        for i in used:
            raw = image[nvs.FIRST + i * nvs.ENTRY:nvs.FIRST + (i + 1) * nvs.ENTRY]
            if raw[1] == nvs.BLOB_IDX and raw[8:11] == b'uid':
                raw[24:32] = struct.pack('<IBBH', 7, 1, 0x80, 0xFFFF)
                raw[4:8] = struct.pack('<I', nvs.entry_crc(raw))
                image[nvs.FIRST + i * nvs.ENTRY:nvs.FIRST + (i + 1) * nvs.ENTRY] = raw
        image[28:32] = struct.pack('<I', nvs.header_crc(image))
        values = {(e.namespace, e.key): e.value for e in nvs.parse(bytes(image))[1]}
        self.assertEqual(values[('cube', 'uid')], b'NEWUID!')
        self.assertNotIn(('cube', 'stale'), values)

    def test_corruption_is_refused(self):
        image = registered((3, IMG))
        for offset, what in ((nvs.FIRST + 5, 'entry CRC'), (4, 'header CRC'), (nvs.FIRST + 3 * nvs.ENTRY + 40, 'data CRC')):
            bad = bytearray(image)
            bad[offset] ^= 0x01
            with self.assertRaises(NvsError, msg=what):
                nvs.parse(bytes(bad))
        freeing = bytearray(image)
        freeing[0:4] = struct.pack('<I', 0xFFFFFFF8)
        with self.assertRaises(NvsError):
            nvs.parse(bytes(freeing))
        with self.assertRaises(NvsError):
            nvs.parse(image[:-1])

    def test_too_large_is_refused(self):
        with self.assertRaises(NvsError):
            nvs.build(['a'], [Entry('a', f'b{i}', nvs.BLOB, IMG) for i in range(6)])


class ShowTests(unittest.TestCase):
    def test_no_show(self):
        self.assertIsNone(nvs.show_of(registered()))

    def test_with_show_keeps_everything_else(self):
        before = registered()
        after = nvs.with_show(before, 7, zlib.crc32(IMG), IMG)
        self.assertEqual(nvs.show_of(after), dict(version=7, crc=zlib.crc32(IMG), length=len(IMG), valid=True))
        self.assertTrue(nvs.same_except_show(before, after))
        values = {(e.namespace, e.key): e.value for e in nvs.parse(after)[1]}
        self.assertEqual((values[('cube', 'cubeID')], values[('cube', 'uid')]), (34, UID))
        self.assertEqual(values[('phy', 'cal_data')], pattern(1904, 7, 1))

    def test_replacing_a_show(self):
        older = registered((3, pattern(516, 5, 2)))
        newer = nvs.with_show(older, 8, zlib.crc32(IMG), IMG)
        self.assertEqual(nvs.show_of(newer)['version'], 8)
        self.assertEqual(nvs.parse(newer)[0], ['phy', 'cube', 'show'], 'namespace indices are kept')
        self.assertTrue(nvs.same_except_show(older, newer))

    def test_torn_show_is_invalid(self):
        image = registered((3, IMG))
        namespaces, entries = nvs.parse(image)
        entries = [e._replace(value=e.value + 1) if e.key == 'crc' else e for e in entries]
        self.assertFalse(nvs.show_of(nvs.build(namespaces, entries))['valid'])

    def test_bad_arguments(self):
        with self.assertRaises(NvsError):
            nvs.with_show(registered(), 7, 1234, IMG)
        with self.assertRaises(NvsError):
            nvs.with_show(registered(), 0, zlib.crc32(IMG), IMG)

    def test_registration_change_is_detected(self):
        before = registered()
        namespaces, entries = nvs.parse(before)
        changed = nvs.build(namespaces, [e._replace(value=35) if e.key == 'cubeID' else e for e in entries])
        self.assertFalse(nvs.same_except_show(before, changed))


class LocalBackups(unittest.TestCase):
    """Every NVS backup this computer's flasher kept (private, never committed) parses and survives a rebuild."""

    def test_local_backups(self):
        backups = sorted((Path(__file__).resolve().parents[1] / 'data' / 'runs').glob('*/nvs*.bin'))
        if not backups:
            self.skipTest('no local NVS backups')
        for path in backups:
            with self.subTest(path=path.parent.name + '/' + path.name):
                image = path.read_bytes()
                parsed = nvs.parse(image)
                self.assertEqual(nvs.parse(nvs.build(*parsed)), parsed)
                if 'cube' in parsed[0]:
                    after = nvs.with_show(image, 99, zlib.crc32(IMG), IMG)
                    self.assertTrue(nvs.same_except_show(image, after))
                    self.assertEqual(nvs.show_of(after)['version'], 99)


if __name__ == '__main__':
    unittest.main()
