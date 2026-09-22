#!/usr/bin/env python3
"""Flash a zone board: firmware + zone identity (zcfg) + the current published cube database (zdb_a).
`--update-database` writes only the published database to a board that already runs zone firmware.

Reuses flashing_station's pinned esptool runner and USB port detection. Usable from the GUI (app.py)
or headless:  ../../pairing_station/.venv/bin/python zone_flash.py --point 1 [--build] [--port ...]
"""
import argparse
import hashlib
import json
import re
import sys
import time
import uuid
from pathlib import Path

import serial

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parents[1]
sys.path.insert(0, str(WORKSPACE / 'flashing_station'))
sys.path.insert(0, str(WORKSPACE / 'pairing_station'))
sys.path.insert(0, str(WORKSPACE / 'zones/tools'))
from backend import Runner, ports, tool_command  # noqa: E402  (flashing_station)
from database import Database, timestamp  # noqa: E402
from port_lock import PortLock  # noqa: E402
from zone_registry import ZoneStore  # noqa: E402
import zonedb  # noqa: E402
import zone_build  # noqa: E402
import zone_detect  # noqa: E402

DEFAULT_DATABASE = WORKSPACE / 'pairing_station/data/devices.sqlite3'
DATA = ROOT / 'data'
MAC_RE = re.compile(r'(?i)MAC:\s*([0-9a-f]{2}(?::[0-9a-f]{2}){5})')


def atomic_json(path, data):
    temp = Path(path).with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temp.replace(path)


def parse_report(text):
    """Parse the NctZone '?' report. Returns a dict once READY follows a complete report, else None."""
    end = text.rfind('READY')
    if end < 0:
        return None
    start = text.rfind('FW:', 0, end)
    if start < 0:
        return None
    block = text[start:end]
    patterns = dict(firmware=r'FW:\s*(\S+)', mac=r'MAC:\s*([0-9A-Fa-f:]{17})', channel=r'CHANNEL:\s*(\d+)',
                    zone=r'ZONE:\s*type=(\d+) point=(\d+) name=([^\r\n]*)', db=r'DB:\s*version=(\d+) count=(\d+) crc=([0-9A-Fa-f]{8}) slot=(\w+)',
                    stats=r'STATS:.*error=(\d+)', rx_gain=r'RXGAIN:\s*stored=(\d+)dB applied=(?:(\d+)dB|\?)', pool=r'POOL: radio=\d+ cal1=([\d.]+) cal23=([\d.]+)')
    found = {k: re.search(p, block) for k, p in patterns.items()}
    if not all(found[k] for k in ('firmware', 'mac', 'channel', 'db')):
        return None
    report = dict(firmware=found['firmware'][1], mac=found['mac'][1].upper(), channel=int(found['channel'][1]),
                  db_version=int(found['db'][1]), db_count=int(found['db'][2]), db_crc=int(found['db'][3], 16),
                  active_slot={'A': 1, 'B': 2}.get(found['db'][4], 0), config_valid=bool(found['zone']),
                  last_error=int(found['stats'][1]) if found['stats'] else 0)
    if found['zone']:
        report.update(zone_type=int(found['zone'][1]), point_id=int(found['zone'][2]), name=found['zone'][3].strip())
    if found['rx_gain']:  # absent before desert-2.4.0 / tagplate-2.4.0 / pool-3.2.0 / preshow-3.3.0
        report['rx_gain'] = int(found['rx_gain'][1])
        report['rx_gain_applied'] = int(found['rx_gain'][2]) if found['rx_gain'][2] else None
    if found['pool']:
        report['params'] = [round(float(found['pool'][1]) * 10), round(float(found['pool'][2]) * 10)]
    return report


class ZoneFlasher:
    def __init__(self, database, emit):
        self.database, self.emit = Path(database), emit

    def execute(self, port, profile_name, point_id, name, params=(), force=False, rx_gain=zonedb.RX_GAIN_DEFAULT):
        """`force` overwrites a board the database lists as a neocube or excluded device; a neocube is unregistered
        (number and tags released) once the zone firmware is written. The known pairing station MAC and non-ESP32
        USB devices are refused regardless."""
        profile = zone_build.PROFILES[profile_name]
        sketch = profile['sketch']
        params = [int(v) for v in params]
        if point_id not in profile['points']:
            raise ValueError(f'Point must be one of {profile["points"]}')
        if len(params) != len(profile['params']):
            raise ValueError(f'{profile["label"]} needs {len(profile["params"])} parameter(s): ' +
                             ', '.join(p[0] for p in profile['params']))
        rx_gain = zonedb.check_rx_gain(rx_gain)
        config = zonedb.zcfg_image(profile['zone_type'], point_id, name, params, rx_gain)
        manifest = zone_build.load_manifest(sketch)
        ident = uuid.uuid4().hex
        folder = DATA / 'runs' / ident
        folder.mkdir(parents=True)
        runner = Runner(self.emit, folder / 'upload.log')
        record = dict(id=ident, kind='flash', started_at=timestamp(), port=port['port'], profile=profile_name, sketch=sketch, point_id=point_id,
                      name=name, params=params, rx_gain=rx_gain,
                      firmware=manifest['version'], build_hash=manifest['build_hash'], result='failed', forced=bool(force))
        db = Database(self.database, recover_pending=False)
        written = unregister_cube = False
        try:
            if not port.get('candidate'):
                raise RuntimeError('This USB device is not a flashable ESP32 (or is the protected pairing station)')
            store = ZoneStore(db)
            publication = store.current()  # the web-published database; versions are never allocated here
            slot = zonedb.slot_image(publication.records, publication.version)
            record.update(db_version=publication.version, db_count=publication.count, db_crc=publication.crc)
            (folder / 'zcfg.bin').write_bytes(config)
            (folder / 'zdb_a.bin').write_bytes(slot)
            for segment in manifest['segments']:  # freeze this build for the attempt
                data = (zone_build.build_dir(sketch) / segment['file']).read_bytes()
                (folder / segment['file']).write_bytes(data)
                if hashlib.sha256(data).hexdigest() != segment['sha256']:
                    raise RuntimeError('Firmware changed during preparation; rebuild and retry')
            with PortLock(port['port']):
                self.emit('stage', 'Check flashing tool')
                if '5.3.1' not in runner(tool_command() + ['version'], timeout=10):
                    raise RuntimeError('Flashing tool did not start correctly; expected esptool 5.3.1')
                connected = False

                def tool(*args, after='no-reset-stub', timeout=180):
                    nonlocal connected
                    current = next((p for p in ports() if p['port'] == port['port']), None)
                    if current is None or current['key'] != port['key']:
                        raise RuntimeError('USB device disconnected or changed; reconnect and retry')
                    output = runner(tool_command() + ['--chip', 'esp32c3', '--port', port['port'], '--baud', '460800',
                                                      '--before', 'no-reset' if connected else 'default-reset', '--after', after, *args], timeout)
                    connected = True
                    return output

                self.emit('stage', 'Identify')
                identity = tool('flash-id')
                match = MAC_RE.search(identity)
                if not match:
                    raise RuntimeError('ESP32 bootloader did not report a MAC; nothing was written')
                mac = match[1].upper()
                record['mac'] = mac
                self.emit('identity', dict(mac=mac, port=port['port']))
                if not re.search(r'Detected flash size:\s*4\s*MB', identity, re.I):
                    raise RuntimeError('Zone boards need 4 MB flash')
                role = zone_detect.database_role(db, mac)
                if mac in zone_detect.PROTECTED:
                    raise RuntimeError(f'{mac} is the pairing station; refusing to overwrite it with zone firmware')
                if role and force:
                    unregister_cube = role == 'cube'
                    runner.line(f'FORCED: {mac} is listed as {"a neocube" if role == "cube" else "an excluded device"} in the '
                                'database; overwriting it with zone firmware anyway')
                elif role == 'cube':
                    raise RuntimeError(f'{mac} is registered as neocube #{db.get(mac)["cube_id"]}; refusing to overwrite it with zone firmware')
                elif role == 'station':
                    raise RuntimeError(f'{mac} is an excluded device; refusing to overwrite it with zone firmware')
                reset = 'watchdog-reset' if 'USB-Serial/JTAG' in identity else 'hard-reset'

                self.emit('stage', 'Write firmware, identity and database')
                data = manifest['data']
                for part in ('zcfg', 'zdb_a', 'zdb_b'):
                    tool('erase-region', hex(data[part]['offset']), hex(data[part]['size']))
                args = ['write-flash', '--flash-mode', 'keep', '--flash-freq', 'keep', '--flash-size', 'keep']
                for segment in manifest['segments']:
                    args += [hex(segment['offset']), folder / segment['file']]
                args += [hex(data['zcfg']['offset']), folder / 'zcfg.bin', hex(data['zdb_a']['offset']), folder / 'zdb_a.bin']
                tool(*args, timeout=240)
                written = True
                if unregister_cube:  # the cube firmware is gone now, whatever the boot check says
                    previous = db.unregister(mac, f'Force-flashed with zone firmware {manifest["version"]} as "{name}"')
                    if previous:
                        record['unregistered'] = dict(cube_id=previous['cube_id'], uid=previous['uid'],
                                                      pending_uid=previous['pending_uid'])
                        runner.line(f'UNREGISTERED neocube #{previous["cube_id"]} ({mac}): number and NFC tag released')

                self.emit('stage', 'Verify data partitions')
                for part, expected in (('zcfg', config), ('zdb_a', slot)):
                    readback = folder / f'{part}-readback.bin'
                    tool('read-flash', hex(data[part]['offset']), hex(len(expected)), readback,
                         after=reset if part == 'zdb_a' else 'no-reset-stub')
                    if readback.read_bytes() != expected:
                        raise RuntimeError(f'{part} read-back mismatch')

            self.emit('stage', 'Confirm boot')
            report = self.boot_report(port, runner)
            expected = dict(firmware=manifest['version'], mac=mac, channel=2, zone_type=profile['zone_type'],
                            point_id=point_id, name=name, db_version=publication.version, db_count=publication.count,
                            db_crc=publication.crc, rx_gain=rx_gain)
            if params:
                expected['params'] = params
            mismatches = {k: (report or {}).get(k) for k, v in expected.items() if (report or {}).get(k) != v}
            if mismatches:
                record.update(result='boot_unconfirmed', detail=f'Written and verified; boot report mismatch {mismatches}')
            else:
                store.seen(mac, dict(report, staging_version=0, staging_chunks=0, staging_total=0, uptime=0, tags=0,
                                     unknown_tags=0, send_fail=0), source='flash')
                store.flashed(mac, profile_name, params)
                store.settings(mac, dict(rx_gain=rx_gain, rx_gain_applied=report.get('rx_gain_applied'), set_result=None))
                record.update(result='success', detail=f'{name} ({mac}) running {manifest["version"]} with database '
                                                       f'v{publication.version} ({publication.count} records)' +
                                                       (f' · was neocube #{record["unregistered"]["cube_id"]} (unregistered)'
                                                        if 'unregistered' in record else ''))
        except Exception as exc:
            record.update(result='attention' if written else 'failed', detail=str(exc))
            runner.line(str(exc))
        finally:
            record['finished_at'] = timestamp()
            atomic_json(folder / 'receipt.json', record)
            db.close()
        self.emit('result', record)
        return record

    def update_database(self, port, expected_mac):
        """Write only the published cube database (zdb_a, zdb_b erased) to an already-flashed NctZone board.
        Firmware and zone identity (zcfg) are never touched. `expected_mac` is the MAC the board was identified
        with; a different board on the port is refused. Like a full flash, the board is rebooted by esptool."""
        ident = uuid.uuid4().hex
        folder = DATA / 'runs' / ident
        folder.mkdir(parents=True)
        runner = Runner(self.emit, folder / 'upload.log')
        expected_mac = (expected_mac or '').upper()
        record = dict(id=ident, kind='database', started_at=timestamp(), port=port['port'], mac=expected_mac, result='failed')
        db = Database(self.database, recover_pending=False)
        written = False
        try:
            if not port.get('candidate'):
                raise RuntimeError('This USB device is not a flashable ESP32 (or is the protected pairing station)')
            if not expected_mac:
                raise RuntimeError('The board was not identified by MAC; identify it again before updating its database')
            store = ZoneStore(db)
            publication = store.current()  # the web-published database; versions are never allocated here
            slot = zonedb.slot_image(publication.records, publication.version)
            record.update(db_version=publication.version, db_count=publication.count, db_crc=publication.crc)
            (folder / 'zdb_a.bin').write_bytes(slot)
            with PortLock(port['port']):
                self.emit('stage', 'Check flashing tool')
                if '5.3.1' not in runner(tool_command() + ['version'], timeout=10):
                    raise RuntimeError('Flashing tool did not start correctly; expected esptool 5.3.1')
                connected = False

                def tool(*args, after='no-reset-stub', timeout=120):
                    nonlocal connected
                    current = next((p for p in ports() if p['port'] == port['port']), None)
                    if current is None or current['key'] != port['key']:
                        raise RuntimeError('USB device disconnected or changed; reconnect and retry')
                    output = runner(tool_command() + ['--chip', 'esp32c3', '--port', port['port'], '--baud', '460800',
                                                      '--before', 'no-reset' if connected else 'default-reset', '--after', after, *args], timeout)
                    connected = True
                    return output

                self.emit('stage', 'Identify')
                identity = tool('flash-id')
                match = MAC_RE.search(identity)
                if not match:
                    raise RuntimeError('ESP32 bootloader did not report a MAC; nothing was written')
                mac = match[1].upper()
                self.emit('identity', dict(mac=mac, port=port['port']))
                if mac != expected_mac:
                    raise RuntimeError(f'{mac} is not the board that was identified ({expected_mac}); nothing was written')
                if mac in zone_detect.PROTECTED:
                    raise RuntimeError(f'{mac} is the pairing station; refusing to write a zone database to it')
                role = zone_detect.database_role(db, mac)
                if role == 'cube':
                    raise RuntimeError(f'{mac} is registered as neocube #{db.get(mac)["cube_id"]}; refusing to write a zone database to it')
                if role == 'station':
                    raise RuntimeError(f'{mac} is an excluded device; refusing to write a zone database to it')
                reset = 'watchdog-reset' if 'USB-Serial/JTAG' in identity else 'hard-reset'

                self.emit('stage', 'Read partition table')
                table_file = folder / 'partitions-readback.bin'
                tool('read-flash', hex(0x8000), hex(0xC00), table_file)
                table = zone_detect.parse_partition_table(table_file.read_bytes())
                data = {p: table.get(p) for p in ('zcfg', 'zdb_a', 'zdb_b')}
                if not all(data.values()):
                    raise RuntimeError('No zone database partitions on this board; flash it with zone firmware first')
                if len(slot) > data['zdb_a']['size']:
                    raise RuntimeError(f'Database v{publication.version} ({len(slot)} bytes) does not fit the board\'s database slot')

                self.emit('stage', 'Write database')
                for part in ('zdb_a', 'zdb_b'):  # both slots: the board must boot the new version, not a stale slot B
                    tool('erase-region', hex(data[part]['offset']), hex(data[part]['size']))
                tool('write-flash', '--flash-mode', 'keep', '--flash-freq', 'keep', '--flash-size', 'keep',
                     hex(data['zdb_a']['offset']), folder / 'zdb_a.bin', timeout=240)
                written = True

                self.emit('stage', 'Verify database')
                readback = folder / 'zdb_a-readback.bin'
                tool('read-flash', hex(data['zdb_a']['offset']), hex(len(slot)), readback)
                if readback.read_bytes() != slot:
                    raise RuntimeError('zdb_a read-back mismatch')
                readback = folder / 'zdb_b-readback.bin'
                tool('read-flash', hex(data['zdb_b']['offset']), hex(zonedb.SLOT_HEADER.size), readback, after=reset)
                if readback.read_bytes().strip(b'\xff'):
                    raise RuntimeError('zdb_b was not erased')

            self.emit('stage', 'Confirm boot')
            report = self.boot_report(port, runner)
            expected = dict(mac=mac, db_version=publication.version, db_count=publication.count, db_crc=publication.crc)
            mismatches = {k: (report or {}).get(k) for k, v in expected.items() if (report or {}).get(k) != v}
            if mismatches:
                record.update(result='boot_unconfirmed', detail=f'Written and verified; boot report mismatch {mismatches}')
            else:
                store.seen(mac, dict(report, staging_version=0, staging_chunks=0, staging_total=0, uptime=0, tags=0,
                                     unknown_tags=0, send_fail=0), source='flash')
                record.update(name=report.get('name'), firmware=report['firmware'], result='success',
                              detail=f'{report.get("name") or "unconfigured zone"} ({mac}) database v{publication.version} '
                                     f'({publication.count} records)')
        except Exception as exc:
            record.update(result='attention' if written else 'failed', detail=str(exc))
            runner.line(str(exc))
        finally:
            record['finished_at'] = timestamp()
            atomic_json(folder / 'receipt.json', record)
            db.close()
        self.emit('result', record)
        return record

    def detect(self, port, quick=2.5):
        """Identify the board on `port`. Tries the serial report first; otherwise reads flash (reboots the board)."""
        runner = Runner(self.emit)
        if not port.get('candidate'):
            serial_mac = (port.get('serial') or '').upper()
            label = 'Pairing station (protected)' if serial_mac in zone_detect.PROTECTED else 'Not a flashable ESP32'
            return dict(kind='station' if serial_mac in zone_detect.PROTECTED else 'other', label=label, mac=serial_mac or None,
                        profile=None, source='USB identity')
        with PortLock(port['port']):
            report = self.boot_report(port, runner, timeout=quick)
            if report:
                return zone_detect.from_report(report)
            connected = False

            def tool(*args, after='no-reset-stub', timeout=120):
                nonlocal connected
                output = runner(tool_command() + ['--chip', 'esp32c3', '--port', port['port'], '--baud', '460800',
                                                  '--before', 'no-reset' if connected else 'default-reset', '--after', after, *args], timeout)
                connected = True
                return output

            identity = tool('flash-id')
            match = MAC_RE.search(identity)
            if not match:
                raise RuntimeError('ESP32 bootloader did not report a MAC')
            mac = match[1].upper()
            scratch = DATA / 'detect'
            scratch.mkdir(parents=True, exist_ok=True)

            def read(offset, size):
                out = scratch / f'{uuid.uuid4().hex}.bin'
                try:
                    tool('read-flash', hex(offset), hex(size), out)
                    return out.read_bytes()
                finally:
                    out.unlink(missing_ok=True)

            db = Database(self.database, recover_pending=False)
            try:
                detection = zone_detect.from_flash(mac, db, read)
                known = next((z for z in ZoneStore(db).zones() if z['mac'] == mac), None)
            finally:
                db.close()
                try:
                    tool('read-mac', after='watchdog-reset' if 'USB-Serial/JTAG' in identity else 'hard-reset')
                except Exception as exc:  # the board is identified; a failed reboot is only a nuisance
                    runner.line(f'Reboot after detection failed: {exc}')
            if known and known.get('profile') and detection['kind'] in ('nctzone', 'unknown', 'blank') and not detection.get('profile'):
                detection.update(profile=known['profile'], ambiguous=False)
            if known and known.get('profile') and detection.get('ambiguous') and \
                    zone_build.PROFILES.get(known['profile'], {}).get('zone_type') == detection.get('zone_type'):
                detection.update(profile=known['profile'], ambiguous=False)
            return detection

    def boot_report(self, original, runner, timeout=15):
        deadline = time.monotonic() + timeout
        text, last_error = '', None
        while time.monotonic() < deadline:
            candidate = next((p for p in ports() if p['key'] == original['key']), None)
            if not candidate:
                time.sleep(.3)
                continue
            try:
                # esp-idf-monitor ordering: plain dtr/rts=False before open resets a native-USB ESP32-C3.
                conn = serial.Serial(port=None, baudrate=115200, timeout=.2, exclusive=True)
                conn.dtr = True
                conn.rts = True
                conn.port = candidate['port']
                conn.open()
                conn.rts = False
                conn.dtr = False
                with conn:
                    next_query = 0
                    while time.monotonic() < deadline:
                        if time.monotonic() >= next_query:
                            conn.write(b'?\n')
                            next_query = time.monotonic() + 1
                        chunk = conn.read(4096).decode(errors='replace')
                        if chunk:
                            runner.line(chunk.rstrip())
                            text += chunk
                            report = parse_report(text)
                            if report:
                                return report
            except (OSError, serial.SerialException) as exc:
                if str(exc) != last_error:
                    runner.line('Waiting for USB boot: ' + str(exc))
                    last_error = str(exc)
                time.sleep(.3)
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--profile', default='preshow', choices=sorted(zone_build.PROFILES))
    parser.add_argument('--point', type=int, help='Zone point / radio ID')
    parser.add_argument('--name', help='Zone name (default from profile, max 15 bytes)')
    parser.add_argument('--param', type=float, action='append', default=[], help='Zone parameter in display units (pool: mm), in order')
    parser.add_argument('--rx-gain', type=int, default=zonedb.RX_GAIN_DEFAULT, choices=zonedb.RX_GAINS,
                        help='PN532 receiver gain in dB (default %(default)s)')
    parser.add_argument('--port', help='Serial port (default: the only flashable ESP32 connected)')
    parser.add_argument('--database', type=Path, default=DEFAULT_DATABASE)
    parser.add_argument('--build', action='store_true', help='Build the firmware before flashing')
    parser.add_argument('--check', action='store_true', help='Only read the report of a running zone (no reset)')
    parser.add_argument('--detect', action='store_true', help='Only identify the connected board (may reboot it)')
    parser.add_argument('--update-database', action='store_true',
                        help='Write only the published cube database to a board already running zone firmware (identity kept)')
    parser.add_argument('--force', action='store_true',
                        help='Overwrite a board the database lists as a neocube (unregistering it) or excluded device (never the pairing station)')
    args = parser.parse_args()

    def emit(kind, value):
        if kind == 'log':
            print('   ', value)
        elif kind == 'stage':
            print(f'== {value}')
        elif kind != 'progress':
            print(f'[{kind}] {value}')

    runner = Runner(emit)
    candidates = [p for p in ports() if (p['candidate'] or args.detect) and (not args.port or p['port'] == args.port)]
    if len(candidates) != 1:
        raise SystemExit(f'Expected one ESP32; found {[p["port"] for p in candidates]}. Use --port.')
    port = candidates[0]
    flasher = ZoneFlasher(args.database, emit)
    if args.check:
        report = flasher.boot_report(port, runner)
        print(json.dumps(report, indent=2))
        raise SystemExit(0 if report else 1)
    if args.detect:
        print(json.dumps(flasher.detect(port), indent=2))
        raise SystemExit(0)
    if args.update_database:
        detection = flasher.detect(port)
        db = Database(args.database, recover_pending=False)
        try:
            plan = zone_detect.database_plan(detection, ZoneStore(db).published())
        finally:
            db.close()
        print(f'{detection["label"]} ({detection.get("mac")}): {plan["reason"]}')
        if plan['action'] == 'refuse':
            raise SystemExit(1)
        record = flasher.update_database(port, detection['mac'])
        raise SystemExit(0 if record['result'] == 'success' else 1)
    if args.point is None:
        raise SystemExit('--point is required')
    profile = zone_build.PROFILES[args.profile]
    if args.build:
        zone_build.build(profile['sketch'], runner)
    name = args.name or profile['name'].format(point=args.point)
    params = [round(v * spec[2]) for v, spec in zip(args.param, profile['params'])]
    record = flasher.execute(port, args.profile, args.point, name, params, force=args.force, rx_gain=args.rx_gain)
    raise SystemExit(0 if record['result'] == 'success' else 1)


if __name__ == '__main__':
    main()
