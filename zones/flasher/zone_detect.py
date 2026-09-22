"""Work out what is plugged in: a running NctZone board, a legacy zone sketch, a neocube, the pairing station…

Order of evidence: (1) the running firmware's own "?" report over serial (no reset); (2) the USB/bootloader MAC
looked up in the shared database; (3) the zone identity partition (zcfg) read with esptool; (4) text signatures in
the application image of legacy sketches. Steps 2-4 put the board in its bootloader and reboot it afterwards.
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import zonedb
import zone_build

# First match wins. (needle, kind, label, profile)
SIGNATURES = [
    # Before the station: the Workstation (and the legacy General Radio it replaces) speak the relay
    # protocol and could carry that text.
    (b'NCT WORKSTATION', 'other', 'Workstation (Workstation)', None),
    (b'NCT GENERAL RADIO', 'other', 'General radio (GeneralRadio)', None),  # legacy radio, pre-Workstation
    (b'nct-pairing', 'station', 'Pairing / registry station', None),
    (b'registration console READY', 'station', 'Registration console', None),
    (b'Cube READY', 'cube', 'Neocube firmware', None),
    (b'NCT NEOCORE CUBE', 'cube', 'Neocube firmware', None),
    (b'POOL CENTRAL', 'other', 'Pool central controller', None),
    (b'NCT RANGE TEST', 'other', 'ESP-NOW range/link test board', None),
    (b'NCT PRESHOW MEDIA BRIDGE', 'other', 'Preshow media bridge (PreshowBridge)', None),
    (b'NCT MAINSHOW CONTROLLER', 'other', 'Mainshow controller (MainshowController)', None),
    (b'MEDIA BRIDGE PEER', 'legacy_zone', 'Legacy PreshowZone plate', 'preshow'),
    (b'PRESHOW EXIT TAG', 'legacy_zone', 'Legacy preshow exit plate', 'preshow_exit'),
    (b'MAINSHOW ENTRANCE', 'legacy_zone', 'Legacy mainshow entrance plate', 'mainshow'),
    (b'NCT MAIN SHOW ENTRANCE', 'legacy_zone', 'Legacy mainshow entrance plate', 'mainshow'),
    (b'DESERT TAG PLATE', 'legacy_zone', 'Legacy desert plate', 'desert'),
    (b'POOL RADIO', 'legacy_zone', 'Legacy pool radio', 'pool'),
    (b'NCT PRESHOW TAG PLATE', 'legacy_zone', 'Legacy preshow tag plate (no media)', 'preshow_exit'),
]
NOT_FLASHABLE = {'cube': 'Registered/recognised neocube: use the cube flashing station',
                 'station': 'This is the pairing station', 'other': 'Not a tag zone; flash it from its own sketch'}


def classify_image(image):
    """Classify a raw application image (or whole-flash dump) by the text it contains."""
    if not image.strip(b'\xff'):
        return dict(kind='blank', label='Blank flash', profile=None)
    for needle, kind, label, profile in SIGNATURES:
        if needle in image:
            return dict(kind=kind, label=label, profile=profile)
    return dict(kind='unknown', label='Unrecognised firmware', profile=None)


def parse_partition_table(data):
    table = {}
    for i in range(0, len(data) - 31, 32):
        entry = data[i:i + 32]
        if entry[:2] != b'\xaa\x50':
            break
        kind, subtype, offset, size = entry[2], entry[3], *struct.unpack('<II', entry[4:12])
        table[entry[12:28].rstrip(b'\0').decode(errors='replace')] = dict(type=kind, subtype=subtype, offset=offset, size=size)
    return table


def from_report(report):
    """Detection from a parsed NctZone serial report."""
    profile = zone_build.profile_for(report['firmware'], report.get('zone_type'))
    detection = dict(kind='nctzone', label='NctZone firmware', mac=report['mac'], firmware=report['firmware'], profile=profile,
                     configured=report['config_valid'], db_version=report['db_version'], db_count=report['db_count'],
                     db_crc=report['db_crc'], source='serial report', last_error=report.get('last_error', 0))
    if report['config_valid']:
        detection.update(point=report['point_id'], name=report['name'], zone_type=report['zone_type'])
    if report.get('params'):
        detection['params'] = report['params']
    if report.get('rx_gain'):
        detection.update(rx_gain=report['rx_gain'], rx_gain_applied=report.get('rx_gain_applied'))
    return detection


def database_role(db, mac):
    """'cube', 'station' or None from the shared device database."""
    if mac in PROTECTED or db.excluded(mac):
        return 'station'
    row = db.get(mac)
    if row and (row['uid'] or row['cube_id'] is not None):
        return 'cube'
    return None


PROTECTED = {'3C:0F:02:AD:83:24'}


def from_flash(mac, db, read):
    """Detection using esptool reads. `read(offset, size) -> bytes`."""
    role = database_role(db, mac)
    if role == 'cube':
        row = db.get(mac)
        return dict(kind='cube', label=f'Neocube #{row["cube_id"]} (database)', mac=mac, profile=None, source='database')
    if mac in PROTECTED:
        return dict(kind='station', mac=mac, profile=None, source='database', label='Pairing station (protected)')
    if role == 'station':
        # Refused like the station, but not the same thing: an excluded device is a board deliberately
        # taken out of cube service (the registry dongle, a retired cube now carrying zone firmware), so
        # it is named by what it actually runs rather than sent the wrong way as "the pairing station".
        firmware = from_image(mac, read)
        running = f'zone "{firmware["name"]}"' if firmware['kind'] == 'nctzone' and firmware.get('name') else firmware['label']
        return dict(kind='station', mac=mac, profile=None, source='database', label=f'Excluded from the cube registry · {running}')
    return from_image(mac, read)


def from_image(mac, read):
    """Detection from the flash contents alone: zone identity partition first, then firmware text signatures."""
    table = parse_partition_table(read(0x8000, 0xC00))
    if 'zcfg' in table and 'zdb_a' in table:
        zcfg = read(table['zcfg']['offset'], 0x80)
        config, params = zonedb.parse_config(zcfg), zonedb.parse_params(zcfg)
        slots = [zonedb.parse_slot_header(read(table[s]['offset'], 24)) for s in ('zdb_a', 'zdb_b') if s in table]
        slot = max((s for s in slots if s), key=lambda s: (s['version'], s['generation']), default=None)
        detection = dict(kind='nctzone', label='NctZone board (not answering on serial)', mac=mac, firmware=None,
                         configured=bool(config), profile=None, source='flash identity', db_version=slot['version'] if slot else 0,
                         db_count=slot['count'] if slot else 0, db_crc=slot['crc'] if slot else 0)
        if config:
            candidates = [k for k, p in zone_build.PROFILES.items() if p['zone_type'] == config['zone_type']]
            if params:
                candidates = [k for k in candidates if zone_build.PROFILES[k]['params']] or candidates
            detection.update(point=config['point_id'], name=config['name'], zone_type=config['zone_type'],
                             profile=candidates[0] if candidates else None, ambiguous=len(candidates) > 1,
                             rx_gain=config['rx_gain'])
            if params:
                detection['params'] = params
        return detection
    app = next((p for p in table.values() if p['type'] == 0), None)
    if not app:
        result = classify_image(read(0x10000, 0x1000))
        if result['kind'] != 'blank':
            result = dict(kind='unknown', label='No partition table', profile=None)
    else:
        result = classify_image(read(app['offset'], min(app['size'], 0x140000)))
    return dict(result, mac=mac, source='firmware image')


def forceable(detection):
    """A refused board the operator may still overwrite by hand. The known pairing station never is."""
    return detection['kind'] in NOT_FLASHABLE and (detection.get('mac') or '').upper() not in PROTECTED


def database_state(detection, published):
    """How an NctZone board's database compares with the published one: 'current', 'behind', 'ahead', or
    None when there is no evidence (no NctZone board, no database read, nothing published). Same rule as
    the Zone Database Manager's ZoneRegistry.classify: `ahead` is a higher version, or the same version
    with different content (a legacy per-computer counter)."""
    if detection.get('kind') != 'nctzone' or 'db_version' not in detection or not (published or {}).get('version'):
        return None
    if detection['db_version'] == published['version'] and detection.get('db_crc') == published['crc']:
        return 'current'
    if (detection['db_version'] or 0) < published['version']:
        return 'behind'
    return 'ahead'


def database_plan(detection, published):
    """What a database-only update (no firmware, no identity) would do. Returns dict(action=database|skip|ask|refuse, reason)."""
    if detection.get('kind') != 'nctzone':
        return dict(action='refuse', reason=NOT_FLASHABLE.get(detection.get('kind'), 'Not an NctZone board: flash it first'))
    if not detection.get('mac'):
        return dict(action='refuse', reason='The board\'s MAC is unknown; identify it again')
    state = database_state(detection, published)
    if state is None:
        return dict(action='ask', reason='No database published yet' if not (published or {}).get('version') else
                    'The board\'s database could not be read; identify it again')
    return _database_action(state, detection['db_version'], published['version'])


def _database_action(state, old, new):
    if state == 'current':
        return dict(action='skip', reason=f'Database v{new} is current')
    if state == 'behind':
        return dict(action='database', reason=f'Update database v{old} → v{new}')
    return dict(action='ask', reason=f'Database v{old} is ahead of published v{new}; "Update database" overwrites it')


def plan(detection, form, manifests, published, auto=False, allow_unidentified=False, force=False):
    """Decide what flashing this board would do.
    Returns dict(action=flash|database|skip|refuse|ask, reason, profile, point, name, params, rx_gain).
    `database` (auto only): the firmware is current and only the database is behind.

    `force` (manual flashing only, never auto) overrides a refusal for anything `forceable`."""
    kind = detection['kind']
    chosen = dict(profile=form['profile'], point=form['point'], name=form['name'], params=list(form.get('params') or []),
                  rx_gain=form.get('rx_gain', zonedb.RX_GAIN_DEFAULT))
    if kind in NOT_FLASHABLE:
        if force and not auto and forceable(detection):
            return dict(chosen, action='flash', force=True, reason=f'FORCED over refusal: {NOT_FLASHABLE[kind]}')
        return dict(action='refuse', reason=NOT_FLASHABLE[kind])
    if not auto:
        return dict(chosen, action='flash', reason='Flash with the selected zone settings')
    if kind == 'nctzone' and detection.get('configured') and detection.get('profile') and not detection.get('ambiguous'):
        profile = zone_build.PROFILES[detection['profile']]
        params = detection.get('params') or []
        if len(params) != len(profile['params']):
            return dict(action='ask', reason='Zone parameters are missing on the board; flash it manually once')
        # A board reporting no gain runs firmware older than the setting, which always used the default.
        keep = dict(profile=detection['profile'], point=detection['point'], name=detection['name'], params=list(params),
                    rx_gain=detection.get('rx_gain') or zonedb.RX_GAIN_DEFAULT)
        manifest = manifests.get(profile['sketch'])
        firmware_current = bool(manifest and detection.get('firmware') == manifest['version'])
        state = database_state(detection, published)
        if firmware_current and state == 'current':
            return dict(keep, action='skip', reason=f'Already {manifest["version"]} with database v{published["version"]}')
        if firmware_current and state in ('behind', 'ahead'):
            return dict(keep, **_database_action(state, detection['db_version'], published['version']))
        return dict(keep, action='flash', reason=f'Update "{detection["name"]}" keeping its identity')
    if kind == 'nctzone':
        return dict(action='ask', reason='Zone identity on the board is missing or ambiguous; flash it manually once')
    if kind == 'legacy_zone':
        if detection['profile'] != form['profile']:
            wanted = zone_build.PROFILES[detection['profile']]['label']
            return dict(action='ask', reason=f'Looks like "{wanted}"; select that zone (and its point) to auto-flash it')
        return dict(chosen, action='flash', reason=f'{detection["label"]} → {form["name"]}')
    if allow_unidentified:
        return dict(chosen, action='flash', reason=f'{detection["label"]} → {form["name"]}')
    return dict(action='ask', reason=f'{detection["label"]}: tick "flash unidentified boards" or flash manually')
