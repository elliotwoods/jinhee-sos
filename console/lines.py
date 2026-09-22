"""Notable console lines per device role, classified into tags the advisor and timeline use.

Pure. `classify(role, line)` -> dict(tag, level, fields) or None. The strings are the firmware's
own (see the plan's Appendix A3 for where each one is printed).
"""
import re

RULES = {
    'cube': [
        (re.compile(r'^UNREGISTERED\b'), 'cube.unregistered', 'warn', None),
        (re.compile(r'^REGISTERED Cube #(\d+)'), 'cube.registered', 'ok', ('number',)),
        (re.compile(r'^ESP-NOW INIT ERROR'), 'cube.espnow_init_error', 'bad', None),
        (re.compile(r'^ZONE = (\d+)'), 'cube.zone', 'info', ('zone',)),
        (re.compile(r'^SHOW_START IGNORED / ZONE=(\d+)'), 'cube.show_start_ignored', 'warn', ('zone',)),
        (re.compile(r'^SHOW_START DUPLICATE'), 'cube.show_start_duplicate', 'info', None),
        (re.compile(r'^MAIN SHOW START / ID = (\d+)'), 'cube.show_start', 'ok', ('show_id',)),
        (re.compile(r'^MAIN SHOW TIMELINE END'), 'cube.show_end', 'info', None),
        (re.compile(r'^UNKNOWN ZONE: (\d+)'), 'cube.unknown_zone', 'warn', ('zone',)),
    ],
    'zone': [
        (re.compile(r'^PARTITIONS MISSING'), 'zone.partitions_missing', 'bad', None),
        (re.compile(r'^CONFIG: INVALID'), 'zone.config_invalid', 'bad', None),
        (re.compile(r'^ZONE TYPE NOT CONFIGURED'), 'zone.config_invalid', 'bad', None),
        (re.compile(r'^PN532 I2C LINE HELD LOW'), 'zone.pn532_line_low', 'bad', None),
        (re.compile(r'^PN532 NOT FOUND'), 'zone.pn532_not_found', 'bad', None),
        (re.compile(r'^PN532 LOST'), 'zone.pn532_lost', 'warn', None),
        (re.compile(r'^PN532 FOUND'), 'zone.pn532_found', 'ok', None),
        (re.compile(r'^ESP-NOW INIT ERROR'), 'zone.espnow_init_error', 'bad', None),
        (re.compile(r'^UNKNOWN CUBE'), 'zone.unknown_cube', 'warn', None),
        (re.compile(r'^FOUND Cube #(\d+)'), 'zone.found_cube', 'ok', ('number',)),
        (re.compile(r'^Cube #(\d+) DELIVERED'), 'zone.delivered', 'ok', ('number',)),
        (re.compile(r'^Cube #(\d+) NOT ACKNOWLEDGED'), 'zone.not_acknowledged', 'warn', ('number',)),
        (re.compile(r'^ERR cube (\d+) is not in this zone\'s database'), 'zone.not_in_db', 'warn', ('number',)),
        (re.compile(r'^DB UPDATE: staging version (\d+)'), 'zone.db_staging', 'info', ('version',)),
        (re.compile(r'^DB UPDATE: committed version (\d+)'), 'zone.db_committed', 'ok', ('version',)),
        (re.compile(r'^DB UPDATE: CRC mismatch'), 'zone.db_crc_mismatch', 'bad', None),
        (re.compile(r'^DB UPDATE: invalid records'), 'zone.db_invalid', 'bad', None),
        (re.compile(r'^DB UPDATE: flash commit failed'), 'zone.db_commit_failed', 'bad', None),
        (re.compile(r'^RXGAIN SET (\d+)dB: (.*)$'), 'zone.rxgain_set', 'info', ('gain', 'result')),
        (re.compile(r'^MEDIA FAIL'), 'preshow.media_fail', 'warn', None),
        (re.compile(r'^MEDIA LEGACY'), 'preshow.media_legacy', 'info', None),
        (re.compile(r'^MEDIA ACK'), 'preshow.media_ack', 'ok', None),
        (re.compile(r'^MEDIA: bridge found'), 'preshow.bridge_found', 'ok', None),
        (re.compile(r'^\[ERROR\] VL53L4CD'), 'pool.vl53_error', 'bad', None),
        (re.compile(r'^\[OK\] VL53L4CD'), 'pool.vl53_ok', 'ok', None),
        (re.compile(r'^EVENT override (\w+)'), 'zone.override', 'info', ('what',)),
        (re.compile(r'^ERR '), 'zone.err', 'warn', None),
        (re.compile(r'^PEER ADD FAILED'), 'zone.peer_failed', 'warn', None),
        (re.compile(r'^ESP-NOW SEND FAILED'), 'zone.send_failed', 'warn', None),
        (re.compile(r'^RESET -> idle: Cube #(\d+)'), 'zone.reset_cube', 'ok', ('number',)),
    ],
    'poolcentral': [
        (re.compile(r'^RADIO TIMEOUT: (.*)$'), 'central.radio_timeout', 'warn', ('label',)),
        (re.compile(r'^NOTE (\d+) live boards share a radio id'), 'central.id_clash', 'bad', ('count',)),
        (re.compile(r'^I2C ERROR'), 'central.i2c_error', 'bad', None),
        (re.compile(r'^I2C MODE MISMATCH'), 'central.i2c_mode', 'bad', None),
        (re.compile(r'^I2C READBACK MISMATCH'), 'central.readback', 'bad', None),
        (re.compile(r'^I2C READY'), 'central.i2c_ready', 'ok', None),
        (re.compile(r'^RADIO (.+) -> MEMBER (\d+)(.*)$'), 'central.member', 'info', ('label', 'member', 'legacy')),
        (re.compile(r'^RADIO (.+) RELEASE'), 'central.release', 'info', ('label',)),
        (re.compile(r'^ERR '), 'central.err', 'warn', None),
    ],
    'preshowbridge': [
        (re.compile(r'^NOTE (\d+) live plates share a point id'), 'bridge.point_clash', 'bad', ('count',)),
        (re.compile(r'^PRESHOW,(\d+),(ON|OFF)'), 'bridge.cue', 'info', ('point', 'state')),
        (re.compile(r'^ERR '), 'bridge.err', 'warn', None),
    ],
    'pooltest': [
        (re.compile(r'^EVENT USB watchdog'), 'pooltest.watchdog', 'warn', None),
        (re.compile(r'^ERR '), 'pooltest.err', 'warn', None),
    ],
    'station': [],
    'mainshow': [],
    'rangetest': [
        (re.compile(r'^WARNING'), 'rangetest.warning', 'warn', None),
        (re.compile(r'^ESP-NOW INIT'), 'rangetest.init', 'info', None),
    ],
}
# PoolZone and PreshowZone plates answer as 'zone'; their sketch lines are in the zone table.


def classify(role, line):
    for pattern, tag, level, names in RULES.get(role, ()):
        match = pattern.search(line)
        if match:
            fields = dict(zip(names, match.groups())) if names else {}
            return dict(tag=tag, level=level, fields=fields, text=line)
    return None
