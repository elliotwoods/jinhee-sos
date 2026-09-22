"""ESP-IDF NVS partition images (format version 2), read and rebuilt in pure Python.

Used to check and replace the cube's main show over USB: the flasher reads the 0x9000 NVS
partition with esptool, `with_show` rebuilds it with the `show` namespace replaced and every
other entry (registration, PHY calibration, Wi-Fi/BT driver state) kept, and the flasher writes
it back and reads it again. Anything this module does not understand raises NvsError, so a
partition it cannot parse completely is never rewritten.

Layout (esp-idf components/nvs_flash, nvs_page.hpp / nvs_types.hpp): 4096-byte pages. A page
header is state u32, sequence u32, version u8 (0xFE = format 2), 19 unused bytes and a CRC32
over bytes 4..28. Then a 32-byte bitmap of 2-bit entry states (3 empty, 2 written, 0 erased)
and 126 entries of 32 bytes: namespace index u8, type u8, span u8, chunk index u8, CRC32 u32,
key[16], data[8]. Strings and blob chunks keep size/CRC in data and their bytes in the
following span-1 entries. A format-2 blob is a BLOB_IDX entry plus BLOB_DATA chunks
(chunk index = chunk start + n; chunk start 0x00 or 0x80 for the two alternating versions).
All CRCs are zlib CRC-32 seeded with 0xFFFFFFFF (esp_rom_crc32_le(0xffffffff, ...)).
"""
import struct
import zlib
from collections import namedtuple

PAGE, ENTRY, ENTRIES, FIRST = 4096, 32, 126, 64
SIZE = 0x5000                      # the cube's NVS partition (flashing_station/backend.py)
FORMAT = 0xFE
ACTIVE, FULL, UNINIT = 0xFFFFFFFE, 0xFFFFFFFC, 0xFFFFFFFF
EMPTY, WRITTEN, ERASED = 3, 2, 0
U8, I8, U16, I16, U32, I32, U64, I64 = 0x01, 0x11, 0x02, 0x12, 0x04, 0x14, 0x08, 0x18
STR, BLOB_V1, BLOB_DATA, BLOB_IDX = 0x21, 0x41, 0x42, 0x48
PRIMITIVE = {U8: '<B', I8: '<b', U16: '<H', I16: '<h', U32: '<I', I32: '<i', U64: '<Q', I64: '<q'}
BLOB = 'blob'                       # Entry.type of a reassembled format-2 blob
NO_CHUNK = 0xFF
MAX_KEY = 15

Entry = namedtuple('Entry', 'namespace key type value')


class NvsError(ValueError):
    pass


def crc(data, seed=0xFFFFFFFF):
    return zlib.crc32(data, seed) & 0xFFFFFFFF


def entry_crc(raw):
    return crc(raw[0:4] + raw[8:32])


def header_crc(page):
    return crc(page[4:28])


def _state(page, index):
    return (page[32 + index // 4] >> ((index % 4) * 2)) & 3


# ---------------------------------------------------------------------------- reading
def _items(image):
    """Every written item in page-sequence order: (ns_index, type, chunk, key, data8, payload)."""
    if len(image) % PAGE:
        raise NvsError(f'NVS image is {len(image)} bytes, not a whole number of pages')
    pages = []
    for number in range(len(image) // PAGE):
        page = image[number * PAGE:(number + 1) * PAGE]
        state, seq, version = struct.unpack_from('<IIB', page, 0)
        if state == UNINIT:
            if page != b'\xff' * PAGE:
                raise NvsError(f'NVS page {number} is uninitialised but not blank')
            continue
        if state not in (ACTIVE, FULL):
            raise NvsError(f'NVS page {number} is in state {state:#010x} (being freed or corrupt); not rewriting it')
        if version != FORMAT:
            raise NvsError(f'NVS page {number} has format {version:#04x}, expected {FORMAT:#04x}')
        if struct.unpack_from('<I', page, 28)[0] != header_crc(page):
            raise NvsError(f'NVS page {number} header CRC mismatch')
        pages.append((seq, number, page))
    if len({seq for seq, _, _ in pages}) != len(pages):
        raise NvsError('Two NVS pages share a sequence number')
    for _, number, page in sorted(pages):
        index = 0
        while index < ENTRIES:
            state = _state(page, index)
            if state != WRITTEN:
                if state not in (EMPTY, ERASED):
                    raise NvsError(f'NVS page {number} entry {index} has invalid state {state}')
                index += 1
                continue
            raw = page[FIRST + index * ENTRY:FIRST + (index + 1) * ENTRY]
            ns, kind, span, chunk = raw[0], raw[1], raw[2], raw[3]
            if struct.unpack_from('<I', raw, 4)[0] != entry_crc(raw):
                raise NvsError(f'NVS page {number} entry {index} CRC mismatch')
            if span < 1 or index + span > ENTRIES:
                raise NvsError(f'NVS page {number} entry {index} has bad span {span}')
            if any(_state(page, i) != WRITTEN for i in range(index + 1, index + span)):
                raise NvsError(f'NVS page {number} entry {index} data is not fully written')
            key = raw[8:24].split(b'\0', 1)[0]
            try:
                key = key.decode('ascii')
            except UnicodeDecodeError:
                raise NvsError(f'NVS page {number} entry {index} key is not ASCII') from None
            payload = None
            if kind in (STR, BLOB_DATA, BLOB_V1):
                size, _, data_crc = struct.unpack_from('<HHI', raw, 24)
                if size > (span - 1) * ENTRY:
                    raise NvsError(f'NVS {key!r} size {size} exceeds its span')
                start = FIRST + (index + 1) * ENTRY
                payload = page[start:start + size]
                if crc(payload) != data_crc:
                    raise NvsError(f'NVS {key!r} data CRC mismatch')
            elif kind not in PRIMITIVE and kind != BLOB_IDX:
                raise NvsError(f'NVS {key!r} has unsupported type {kind:#04x}')
            elif span != 1:
                raise NvsError(f'NVS {key!r} of fixed size spans {span} entries')
            yield ns, kind, chunk, key, raw[24:32], payload
            index += span


def parse(image):
    """Every live value in the partition as Entry(namespace, key, type, value), in storage order.

    Namespace names come from the index entries (namespace 0); blobs are reassembled from the
    chunks their BLOB_IDX names. Orphan chunks (an older blob version) are dropped, as IDF does."""
    items = list(_items(bytes(image)))
    names = {}
    for ns, kind, chunk, key, data, _ in items:
        if ns == 0:
            if kind != U8:
                raise NvsError(f'NVS namespace entry {key!r} is not u8')
            if data[0] in names or key in names.values():
                raise NvsError(f'NVS namespace {key!r} is defined twice')
            names[data[0]] = key
    chunks, out, seen = {}, [], set()
    for ns, kind, chunk, key, data, payload in items:
        if ns == 0 or kind != BLOB_DATA:
            continue
        if (ns, key, chunk) in chunks:
            raise NvsError(f'NVS blob {key!r} chunk {chunk} is stored twice')
        chunks[(ns, key, chunk)] = payload
    for ns, kind, chunk, key, data, payload in items:
        if ns == 0 or kind == BLOB_DATA:
            continue
        if ns not in names:
            raise NvsError(f'NVS {key!r} uses undefined namespace {ns}')
        if (ns, key) in seen:
            raise NvsError(f'NVS {names[ns]}/{key} is stored twice')
        seen.add((ns, key))
        if kind in PRIMITIVE:
            value = struct.unpack_from(PRIMITIVE[kind], data)[0]
        elif kind == STR:
            if not payload or payload[-1:] != b'\0':
                raise NvsError(f'NVS string {key!r} is not NUL-terminated')
            value = payload
        elif kind == BLOB_V1:
            value = payload
        else:
            size, count, start = struct.unpack_from('<IBB', data)
            parts = [chunks.get((ns, key, start + n)) for n in range(count)]
            if any(p is None for p in parts):
                raise NvsError(f'NVS blob {names[ns]}/{key} is missing a chunk')
            value = b''.join(parts)
            if len(value) != size:
                raise NvsError(f'NVS blob {names[ns]}/{key} is {len(value)} bytes, index says {size}')
            kind = BLOB
        out.append(Entry(names[ns], key, kind, value))
    namespaces = [names[i] for i in sorted(names)]
    return namespaces, out


# ---------------------------------------------------------------------------- writing
class _Writer:
    def __init__(self, size):
        if size % PAGE or size < 2 * PAGE:
            raise NvsError(f'NVS size {size:#x} must be at least two whole pages')
        self.limit = size // PAGE - 1         # IDF needs one free page to garbage-collect
        self.pages, self.used = [], ENTRIES

    def room(self):
        return ENTRIES - self.used

    def new_page(self):
        if len(self.pages) == self.limit:
            raise NvsError('Values do not fit in the NVS partition')
        self.pages.append(bytearray(b'\xff' * PAGE))
        self.used = 0

    def put(self, ns, kind, key, data8, payload=b'', chunk=NO_CHUNK):
        span = 1 + (len(payload) + ENTRY - 1) // ENTRY
        if span > ENTRIES:
            raise NvsError(f'NVS {key!r} is too large for one page')
        if span > self.room():
            self.new_page()
        page, index = self.pages[-1], self.used
        raw = bytearray(struct.pack('<BBBB', ns, kind, span, chunk) + b'\xff' * 4 + _key(key) + data8)
        raw[4:8] = struct.pack('<I', entry_crc(raw))
        at = FIRST + index * ENTRY
        page[at:at + ENTRY] = raw
        page[at + ENTRY:at + ENTRY + len(payload)] = payload
        for i in range(index, index + span):
            page[32 + i // 4] &= ~(1 << ((i % 4) * 2)) & 0xFF   # EMPTY (3) -> WRITTEN (2)
        self.used += span

    def image(self, size):
        out = bytearray()
        for seq, page in enumerate(self.pages):
            state = ACTIVE if seq == len(self.pages) - 1 else FULL
            page[0:9] = struct.pack('<IIB', state, seq, FORMAT)
            page[28:32] = struct.pack('<I', header_crc(page))
            out += page
        return bytes(out + b'\xff' * (size - len(out)))


def _key(key):
    raw = key.encode('ascii')
    if not raw or len(raw) > MAX_KEY:
        raise NvsError(f'NVS key {key!r} must be 1..{MAX_KEY} ASCII characters')
    return raw + b'\0' * (16 - len(raw))


def build(namespaces, entries, size=SIZE):
    """A fresh, compact NVS image holding exactly these namespaces (index order 1..n) and entries.

    Laid out as esp-idf-nvs-partition-gen does: each namespace entry, then its values."""
    if len(namespaces) > 254:
        raise NvsError('Too many NVS namespaces')
    unknown = {e.namespace for e in entries} - set(namespaces)
    if unknown:
        raise NvsError(f'NVS values use undefined namespaces {sorted(unknown)}')
    writer = _Writer(size)
    for number, name in enumerate(namespaces, 1):
        writer.put(0, U8, name, bytes([number]) + b'\xff' * 7)
        for e in entries:
            if e.namespace == name:
                _put(writer, number, e)
    return writer.image(size)


def _put(writer, ns, e):
    if e.type in PRIMITIVE:
        packed = struct.pack(PRIMITIVE[e.type], e.value)
        writer.put(ns, e.type, e.key, packed + b'\xff' * (8 - len(packed)))
    elif e.type in (STR, BLOB_V1):
        value = bytes(e.value)
        writer.put(ns, e.type, e.key, struct.pack('<HHI', len(value), 0xFFFF, crc(value)), value)
    elif e.type == BLOB:
        value, count, offset = bytes(e.value), 0, 0
        while offset < len(value) or count == 0:
            if writer.room() < 2:
                writer.new_page()
            part = value[offset:offset + (writer.room() - 1) * ENTRY]
            writer.put(ns, BLOB_DATA, e.key, struct.pack('<HHI', len(part), 0xFFFF, crc(part)), part, chunk=count)
            offset, count = offset + len(part), count + 1
        if writer.room() < 1:
            writer.new_page()
        writer.put(ns, BLOB_IDX, e.key, struct.pack('<IBBH', len(value), count, 0, 0xFFFF))
    else:
        raise NvsError(f'NVS {e.key!r} has unsupported type {e.type!r}')


# ---------------------------------------------------------------------------- the cube's show
SHOW = 'show'


def show_of(image):
    """The show stored in NVS, as the cube's loadStoredShow() would judge it, or None if absent."""
    _, entries = parse(image)
    values = {e.key: e.value for e in entries if e.namespace == SHOW}
    if not values:
        return None
    img = values.get('img') or b''
    stored = dict(version=int(values.get('ver', 0)), crc=int(values.get('crc', 0)), length=len(img))
    stored['valid'] = bool(stored['version'] and img and crc(img, 0) == stored['crc'])
    return stored


def with_show(image, version, show_crc, img, size=SIZE):
    """The same partition with the `show` namespace holding exactly img/crc/ver; nothing else changes."""
    img = bytes(img)
    if crc(img, 0) != show_crc:
        raise NvsError('Show image does not match its CRC')
    if not version:
        raise NvsError('Show version 0 is the compiled-in show and is never stored')
    namespaces, entries = parse(image)
    kept = [e for e in entries if e.namespace != SHOW]
    if SHOW not in namespaces:
        namespaces = namespaces + [SHOW]
    show = [Entry(SHOW, 'img', BLOB, img), Entry(SHOW, 'crc', U32, show_crc), Entry(SHOW, 'ver', U32, version)]
    return build(namespaces, kept + show, size)


def same_except_show(before, after):
    """True when two images hold identical values outside the `show` namespace."""
    def rest(image):
        _, entries = parse(image)
        return sorted((e for e in entries if e.namespace != SHOW), key=lambda e: (e.namespace, e.key))
    return rest(before) == rest(after)
