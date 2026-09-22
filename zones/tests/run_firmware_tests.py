#!/usr/bin/env python3
"""Compile the real NctZone library and zone sketches for the host against stubs, with fixtures from zonedb.py."""
import json
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(WORKSPACE / 'scripts'))
import host_cxx  # noqa: E402
import zonedb  # noqa: E402

LIBRARY = ROOT / 'firmware/libraries/NctZone/src'
SKETCHES = ['PreshowZone', 'TagPlateZone', 'DesertZone', 'PoolZone', 'ResetZone']
# Sketches that are not zone boards (no zcfg/zdb partitions, not a zone-flasher target)
# but are still compiled for the host against the same stubs.
EXTRA_SKETCHES = ['PoolCentral', 'PreshowBridge', 'MainshowController']
# Packet definitions a sketch may never re-declare: the pool packet used to be copied into
# five sketches with nothing cross-checking them, and the preshow media packet was copied
# into the plate and the bridge with the same result.
PRIVATE_STRUCTS = ['Packet', 'PoolState', 'PoolBeacon', 'RadioPacket',
                   'PreshowMediaPacket', 'PreshowEvent', 'PreshowAck', 'PreshowBeacon', 'PreshowLegacy']
SHIMS = ['Arduino.h', 'WiFi.h', 'esp_now.h', 'esp_wifi.h', 'Wire.h', 'Adafruit_PN532.h', 'esp_partition.h', 'VL53L4CD.h', 'Preferences.h',
         'freertos/FreeRTOS.h', 'freertos/queue.h', 'Adafruit_NeoPixel.h']


def packet_text(source):
    return re.sub(r'\s+', '', re.search(r'struct Packet\s*\{(.*?)\};', source, re.S)[1])


def array(name, data):
    return f'const std::vector<uint8_t> {name} = {{{",".join(str(b) for b in data)}}};\n'


def frames(name, publication):
    items = ','.join('{' + ','.join(str(b) for b in publication.chunk_frame(i)) + '}' for i in range(publication.chunk_count))
    return (array(name + '_ANNOUNCE', publication.announce_frame()) +
            array(name + '_ANNOUNCE_FORCE', publication.announce_frame(force=True)) +
            f'const std::vector<std::vector<uint8_t>> {name}_CHUNKS = {{{items}}};\n'
            f'constexpr uint32_t {name}_CRC = {publication.crc}u; constexpr uint16_t {name}_COUNT = {publication.count};\n')


def fixtures():
    rows = json.loads((WORKSPACE / 'pairing_station/original_32.json').read_text(encoding='utf-8'))
    v1 = zonedb.records_from_rows(rows)
    extra = dict(cube_id=99, mac='02:11:22:33:44:55', uid='04:AA:BB:CC')
    v2 = zonedb.records_from_rows(rows + [extra])
    rollback = zonedb.records_from_rows(rows[:-1])
    first = rows[0]
    text = '#pragma once\n#include <vector>\n#include <cstdint>\n'
    text += array('SLOT_V1', zonedb.slot_image(v1, 1))
    text += f'constexpr uint32_t SLOT_V1_CRC = {zonedb.crc32(zonedb.pack_records(v1))}u;\n'
    text += array('CONFIG_POINT2', zonedb.config_image(1, 2, 'Preshow 2'))
    text += array('CONFIG_MAINSHOW', zonedb.config_image(4, 0, 'Mainshow Entry'))
    text += array('CONFIG_DESERT', zonedb.config_image(2, 1, 'Desert 1'))
    text += array('CONFIG_RESET', zonedb.config_image(5, 1, 'Reset 1'))
    text += array('CONFIG_POOL4', zonedb.zcfg_image(3, 4, 'Pool Radio 4', [3830, 430]))
    text += array('CONFIG_POOL_NOCAL', zonedb.config_image(3, 4, 'Pool Radio 4'))
    text += array('FIRST_UID', zonedb.hex_to_bytes(first['uid'], range(1, 8)))
    text += array('FIRST_MAC', zonedb.hex_to_bytes(first['mac'], {6}))
    text += f'constexpr uint32_t FIRST_ID = {first["cube_id"]}u;\n'
    text += array('EXTRA_UID', zonedb.hex_to_bytes(extra['uid'], {4}))
    text += array('EXTRA_MAC', zonedb.hex_to_bytes(extra['mac'], {6}))
    text += frames('V2', zonedb.Publication(2, v2))
    text += frames('V3SMALL', zonedb.Publication(3, v2, per_chunk=5))
    text += frames('ROLLBACK', zonedb.Publication(1, rollback))
    # Zone DB Manager: a web-allocated universal version far above a legacy local counter.
    text += frames('UNIVERSAL', zonedb.Publication(100000, v2))
    text += array('FRAME_QUERY_STATUS', zonedb.query_frame(zonedb.QUERY_STATUS, 0xABCDEF01))
    text += array('FRAME_QUERY_LOG', zonedb.query_frame(zonedb.QUERY_LOG, 7))
    text += array('IDENTIFY_5', zonedb.identify_frame(5))
    text += array('REBOOT', zonedb.reboot_frame())
    text += array('SET_GAIN_38', zonedb.set_config_frame(38))
    text += array('SET_GAIN_BAD', zonedb.SET_CONFIG.pack(zonedb.MAGIC, zonedb.PROTO, zonedb.ZONE_SET_CONFIG,
                                                         zonedb.SET_CONFIG_CONFIRM, 40))
    text += array('SET_GAIN_NOCONFIRM', zonedb.SET_CONFIG.pack(zonedb.MAGIC, zonedb.PROTO, zonedb.ZONE_SET_CONFIG, 0, 38))
    # A zcfg written by a flasher before the RX gain existed: byte 7 is 0, which means the 48 dB default.
    legacy = bytearray(zonedb.config_image(1, 2, 'Preshow 2'))
    legacy[7] = 0
    legacy[24:28] = zonedb.crc32(bytes(legacy[:24])).to_bytes(4, 'little')
    text += array('CONFIG_LEGACY_GAIN', bytes(legacy))
    text += array('CONFIG_POOL4_GAIN23', zonedb.zcfg_image(3, 4, 'Pool Radio 4', [3830, 430], rx_gain=23))
    return text


def main():
    cube = packet_text((WORKSPACE / 'ForKimchi.ino').read_text(encoding='utf-8'))
    assert packet_text((LIBRARY / 'NctCubeProtocol.h').read_text(encoding='utf-8')) == cube, 'NctCubeProtocol.h Packet differs from ForKimchi.ino'
    # Sketches must use the shared definitions, never a private copy. The pool packet was
    # duplicated across five sketches with nothing cross-checking them; that is what let the
    # live central and the radios drift apart. Match through any attribute, so that a
    # `struct __attribute__((packed)) RadioPacket` cannot slip past a plain substring test.
    for name in SKETCHES + EXTRA_SKETCHES:
        source = (ROOT / 'firmware' / name / f'{name}.ino').read_text(encoding='utf-8')
        for private in PRIVATE_STRUCTS:
            assert not re.search(rf'struct\s+(?:__attribute__\s*\(\(.*?\)\)\s+)?{private}\b', source), \
                f'{name} declares its own {private}; include the shared header instead'
    sources = [str(p) for p in sorted(LIBRARY.glob('*.cpp'))]
    with tempfile.TemporaryDirectory(prefix='zone-fw-tests-') as directory:
        directory = pathlib.Path(directory)
        for shim in SHIMS:
            path = directory / shim
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('#include "zone_stubs.h"\n', encoding='utf-8')
        (directory / 'fixtures.h').write_text(fixtures(), encoding='utf-8')
        flags = [host_cxx.compiler(), '-std=c++17', '-Wall', '-Wno-unused-function', '-g'] + host_cxx.SANITIZE + [
                 '-I' + str(directory), '-I' + str(ROOT / 'tests/stubs'), '-I' + str(LIBRARY)]
        tests = (['test_library.cpp', 'test_PoolProtocol.cpp', 'test_PreshowProtocol.cpp',
                  'test_OneEuroFilter.cpp', 'test_SliderTuning.cpp'] +
                 [f'test_{name}.cpp' for name in SKETCHES + EXTRA_SKETCHES])
        for test in tests:
            binary = host_cxx.executable(directory / test.replace('.cpp', ''))
            subprocess.run(flags + [str(ROOT / 'tests' / test)] + sources + ['-o', binary], check=True)
            subprocess.run([binary], check=True)


if __name__ == '__main__':
    main()
