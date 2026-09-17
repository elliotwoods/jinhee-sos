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
import zonedb  # noqa: E402

LIBRARY = ROOT / 'firmware/libraries/NctZone/src'
SKETCHES = ['PreshowZone', 'TagPlateZone', 'DesertZone', 'PoolZone']
SHIMS = ['Arduino.h', 'WiFi.h', 'esp_now.h', 'esp_wifi.h', 'Wire.h', 'Adafruit_PN532.h', 'esp_partition.h', 'VL53L4CD.h',
         'freertos/FreeRTOS.h', 'freertos/queue.h']


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
    rows = json.loads((WORKSPACE / 'pairing_station/original_32.json').read_text())
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
    text += array('FRAME_QUERY_STATUS', zonedb.query_frame(zonedb.QUERY_STATUS, 0xABCDEF01))
    text += array('FRAME_QUERY_LOG', zonedb.query_frame(zonedb.QUERY_LOG, 7))
    text += array('IDENTIFY_5', zonedb.identify_frame(5))
    text += array('REBOOT', zonedb.reboot_frame())
    return text


def main():
    cube = packet_text((WORKSPACE / 'ForKimchi.ino').read_text())
    assert packet_text((LIBRARY / 'NctCubeProtocol.h').read_text()) == cube, 'NctCubeProtocol.h Packet differs from ForKimchi.ino'
    for name in SKETCHES:  # sketches must use the shared definition, not a private copy
        assert 'struct Packet' not in (ROOT / 'firmware' / name / f'{name}.ino').read_text(), name
    sources = [str(p) for p in sorted(LIBRARY.glob('*.cpp'))]
    with tempfile.TemporaryDirectory(prefix='zone-fw-tests-') as directory:
        directory = pathlib.Path(directory)
        for shim in SHIMS:
            path = directory / shim
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('#include "zone_stubs.h"\n')
        (directory / 'fixtures.h').write_text(fixtures())
        flags = ['c++', '-std=c++17', '-Wall', '-Wno-unused-function', '-g', '-fsanitize=address,undefined',
                 '-I' + str(directory), '-I' + str(ROOT / 'tests/stubs'), '-I' + str(LIBRARY)]
        for test in ['test_library.cpp'] + [f'test_{name}.cpp' for name in SKETCHES]:
            binary = directory / test.replace('.cpp', '')
            subprocess.run(flags + [str(ROOT / 'tests' / test)] + sources + ['-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
