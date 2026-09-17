"""Zone database images and ESP-NOW chunks. Byte layout matches NctZone (firmware/libraries/NctZone)."""
import hashlib
import struct
import zlib

RECORD = struct.Struct('<IB7s6s')          # cubeID, uidLength, uid[7], mac[6]
SLOT_HEADER = struct.Struct('<4sBBHIII')   # magic, format, recordSize, count, dbVersion, generation, recordsCrc (+headerCrc)
CONFIG = struct.Struct('<4sBBBB16s')       # magic, format, zoneType, pointId, reserved, name (+crc)
ANNOUNCE = struct.Struct('<2sBBIHHBBI')
CHUNK_HEADER = struct.Struct('<2sBBIHB')
QUERY = struct.Struct('<2sBBIB')
STATUS = struct.Struct('<2sBBIBB16s16sIHIIHHIIIIBBBB')
LOG_HEADER = struct.Struct('<2sBBIB')
LOG_ENTRY = struct.Struct('<B7sIBI')

RECORD_SIZE = RECORD.size
MAX_PER_CHUNK = 12
SLOT_SIZE = 0x8000
SLOT_CAPACITY = (SLOT_SIZE - SLOT_HEADER.size - 4) // RECORD_SIZE
MAGIC, PROTO = b'NZ', 1
DB_ANNOUNCE, DB_CHUNK, ZONE_QUERY, ZONE_STATUS, ZONE_LOG, ZONE_IDENTIFY, ZONE_REBOOT = 0x10, 0x11, 0x20, 0x21, 0x22, 0x23, 0x24
ANNOUNCE_FORCE = 0x01
QUERY_STATUS, QUERY_LOG = 1, 2
REBOOT_CONFIRM = 0x544F4F42
ZONE_TYPES = {1: 'preshow', 2: 'desert', 3: 'pool', 4: 'mainshow'}
ZONE_COLORS = {0: ('idle', '#d8d8d8'), 1: ('preshow', '#ff2a1a'), 2: ('desert', '#ffb000'), 3: ('pool', '#1f4dff'), 4: ('mainshow', '#d4ff2a')}
TAG_RESULTS = {0: 'unknown', 1: 'delivered', 2: 'unconfirmed', 3: 'pending'}
ERRORS = {0: '', 1: 'zone config invalid', 2: 'database empty', 3: 'NFC reader not found', 4: 'radio init failed',
          5: 'update: out of memory', 6: 'update: CRC mismatch', 7: 'update: invalid data', 8: 'update: flash commit failed',
          9: 'update: timed out', 10: 'zone parameters missing/invalid', 11: 'sensor not found'}

assert SLOT_HEADER.size + 4 == 24 and CONFIG.size + 4 == 28 and RECORD_SIZE == 18
assert ANNOUNCE.size == 18 and CHUNK_HEADER.size == 11 and QUERY.size == 9 and STATUS.size == 80
assert LOG_ENTRY.size == 17


def crc32(data, value=0):
    return zlib.crc32(data, value) & 0xFFFFFFFF


def hex_to_bytes(text, lengths):
    parts = text.split(':')
    if len(parts) not in lengths or any(len(p) != 2 for p in parts):
        raise ValueError(f'Invalid hex bytes: {text!r}')
    return bytes(int(p, 16) for p in parts)


def bytes_to_hex(data):
    return ':'.join(f'{b:02X}' for b in data)


def records_from_rows(rows):
    """Committed mappings only (same rule as the CubeTable.h export), ordered as the firmware requires."""
    records = []
    for row in rows:
        if not row.get('uid') or row.get('cube_id') is None:
            continue
        uid = hex_to_bytes(row['uid'], range(1, 8))
        mac = hex_to_bytes(row['mac'], {6})
        cube_id = int(row['cube_id'])
        if not 0 < cube_id <= 0xFFFFFFFF:
            raise ValueError(f'Invalid cube ID {cube_id}')
        if mac[0] & 1 or mac == bytes(6):
            raise ValueError(f'Invalid cube MAC {row["mac"]}')
        records.append((cube_id, uid, mac))
    records.sort(key=lambda r: (len(r[1]), r[1]))
    for a, b in zip(records, records[1:]):
        if a[1] == b[1]:
            raise ValueError(f'Duplicate UID {bytes_to_hex(a[1])} (cubes {a[0]} and {b[0]})')
    if len(records) > SLOT_CAPACITY:
        raise ValueError(f'{len(records)} records exceed zone capacity {SLOT_CAPACITY}')
    return records


def pack_records(records):
    return b''.join(RECORD.pack(cube_id, len(uid), uid, mac) for cube_id, uid, mac in records)


def unpack_records(data):
    out = []
    for offset in range(0, len(data), RECORD_SIZE):
        cube_id, length, uid, mac = RECORD.unpack_from(data, offset)
        out.append((cube_id, uid[:length], mac))
    return out


def content_hash(records):
    return hashlib.sha256(pack_records(records)).hexdigest()


def slot_image(records, db_version, generation=1):
    body = pack_records(records)
    header = SLOT_HEADER.pack(b'NZDB', 1, RECORD_SIZE, len(records), db_version, generation, crc32(body))
    return header + struct.pack('<I', crc32(header)) + body


def parse_slot(image):
    """Returns dict(version, generation, count, crc, records) or None if the slot is not valid."""
    if len(image) < 24:
        return None
    magic, fmt, size, count, version, generation, records_crc = SLOT_HEADER.unpack_from(image)
    (header_crc,) = struct.unpack_from('<I', image, 20)
    if magic != b'NZDB' or fmt != 1 or size != RECORD_SIZE or header_crc != crc32(image[:20]):
        return None
    body = image[24:24 + count * RECORD_SIZE]
    if len(body) != count * RECORD_SIZE or crc32(body) != records_crc:
        return None
    return dict(version=version, generation=generation, count=count, crc=records_crc, records=unpack_records(body))


def parse_slot_header(header):
    """Version/count of a slot from its first 24 bytes only (records not verified)."""
    if len(header) < 24:
        return None
    magic, fmt, size, count, version, generation, records_crc = SLOT_HEADER.unpack_from(header)
    if magic != b'NZDB' or fmt != 1 or size != RECORD_SIZE or struct.unpack_from('<I', header, 20)[0] != crc32(header[:20]):
        return None
    return dict(version=version, generation=generation, count=count, crc=records_crc)


def config_image(zone_type, point_id, name):
    encoded = name.encode()
    if zone_type not in ZONE_TYPES:
        raise ValueError('Unknown zone type')
    if not 0 <= point_id <= 255:
        raise ValueError('Point ID must be 0–255')
    if len(encoded) > 15:
        raise ValueError('Zone name must be at most 15 bytes')
    body = CONFIG.pack(b'NZCF', 1, zone_type, point_id, 0, encoded)
    return body + struct.pack('<I', crc32(body))


PARAMS_OFFSET = 0x40
PARAMS = struct.Struct('<4sBBH8i')


def params_image(values):
    values = [int(v) for v in values]
    if len(values) > 8:
        raise ValueError('At most 8 zone parameters')
    body = PARAMS.pack(b'NZPR', 1, len(values), 0, *(values + [0] * (8 - len(values))))
    return body + struct.pack('<I', crc32(body))


def zcfg_image(zone_type, point_id, name, params=None):
    """Full zcfg partition content: identity, then optional parameters at PARAMS_OFFSET."""
    image = config_image(zone_type, point_id, name)
    if params:
        image = image.ljust(PARAMS_OFFSET, b'\xff') + params_image(params)
    return image


def parse_params(image):
    block = image[PARAMS_OFFSET:PARAMS_OFFSET + PARAMS.size + 4]
    if len(block) < PARAMS.size + 4:
        return None
    magic, fmt, count, _, *values = PARAMS.unpack_from(block)
    if magic != b'NZPR' or fmt != 1 or count > 8 or struct.unpack_from('<I', block, PARAMS.size)[0] != crc32(block[:PARAMS.size]):
        return None
    return values[:count]


def parse_config(image):
    if len(image) < 28:
        return None
    magic, fmt, zone_type, point_id, _, name = CONFIG.unpack_from(image)
    (crc,) = struct.unpack_from('<I', image, 24)
    if magic != b'NZCF' or fmt != 1 or crc != crc32(image[:24]) or 0 not in name:
        return None
    return dict(zone_type=zone_type, point_id=point_id, name=name.split(b'\0')[0].decode(errors='replace'))


class Publication:
    """One database version prepared for ESP-NOW distribution."""

    def __init__(self, version, records, per_chunk=MAX_PER_CHUNK):
        if not 1 <= per_chunk <= MAX_PER_CHUNK:
            raise ValueError('records per chunk must be 1–12')
        self.version, self.records, self.per_chunk = version, list(records), per_chunk
        self.body = pack_records(self.records)
        self.count = len(self.records)
        self.crc = crc32(self.body)
        self.chunk_count = (self.count + per_chunk - 1) // per_chunk

    def chunk_records(self, index):
        start = index * self.per_chunk * RECORD_SIZE
        return self.body[start:start + self.per_chunk * RECORD_SIZE]

    def announce_frame(self, force=False):
        return ANNOUNCE.pack(MAGIC, PROTO, DB_ANNOUNCE, self.version, self.count, self.chunk_count, self.per_chunk,
                             ANNOUNCE_FORCE if force else 0, self.crc)

    def chunk_frame(self, index):
        data = self.chunk_records(index)
        return CHUNK_HEADER.pack(MAGIC, PROTO, DB_CHUNK, self.version, index, len(data) // RECORD_SIZE) + data


def parse_status(data):
    fields = STATUS.unpack(data)
    (magic, proto, kind, nonce, zone_type, point_id, name, firmware, db_version, db_count, db_crc, staging_version,
     staging_chunks, staging_total, uptime, tags, unknown_tags, send_fail, last_error, channel, config_valid,
     active_slot) = fields
    if magic != MAGIC or proto != PROTO or kind != ZONE_STATUS:
        raise ValueError('Not a zone status frame')
    text = lambda b: b.split(b'\0')[0].decode(errors='replace')
    return dict(nonce=nonce, zone_type=zone_type, point_id=point_id, name=text(name), firmware=text(firmware),
                db_version=db_version, db_count=db_count, db_crc=db_crc, staging_version=staging_version,
                staging_chunks=staging_chunks, staging_total=staging_total, uptime=uptime, tags=tags,
                unknown_tags=unknown_tags, send_fail=send_fail, last_error=last_error, channel=channel,
                config_valid=bool(config_valid), active_slot=active_slot)


def parse_log(data):
    magic, proto, kind, nonce, n = LOG_HEADER.unpack_from(data)
    if magic != MAGIC or proto != PROTO or kind != ZONE_LOG or len(data) != LOG_HEADER.size + 8 * LOG_ENTRY.size or n > 8:
        raise ValueError('Not a zone log frame')
    entries = []
    for i in range(n):
        length, uid, cube_id, result, age = LOG_ENTRY.unpack_from(data, LOG_HEADER.size + i * LOG_ENTRY.size)
        entries.append(dict(uid=bytes_to_hex(uid[:length]), cube_id=cube_id or None,
                            result=TAG_RESULTS.get(result, str(result)), age_s=age))
    return dict(nonce=nonce, entries=entries)


def frame_kind(data):
    return data[3] if len(data) >= 4 and data[:2] == MAGIC and data[2] == PROTO else None


def query_frame(what, nonce=0):
    return QUERY.pack(MAGIC, PROTO, ZONE_QUERY, nonce, what)


def identify_frame(seconds):
    return struct.pack('<2sBBB', MAGIC, PROTO, ZONE_IDENTIFY, max(0, min(60, seconds)))


def reboot_frame():
    return struct.pack('<2sBBI', MAGIC, PROTO, ZONE_REBOOT, REBOOT_CONFIRM)
