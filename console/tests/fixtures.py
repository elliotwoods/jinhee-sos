"""Builders for advisor tests: state sections shaped exactly as console/state.py produces them."""
import copy

NOW = 1_790_000_000.0
PLATE_MAC, POOL_MAC = '14:63:93:C0:EC:14', '14:63:93:C0:EC:33'
CUBE_MAC, CUBE_UID, CUBE_NUMBER = 'A4:CF:12:34:56:78', '53:21:D4:CF:33:00:01', 44
STATION_MAC = '30:ED:A0:5B:6D:D8'
PUBLISHED = dict(version=32, hash='abc', count=33, crc=0x5A17C0DE, published_at='2026-09-21T10:14:00+0900',
                 published_by='studio-mac', universal=True)


def inventory_row(mac=CUBE_MAC, cube_id=CUBE_NUMBER, uid=CUBE_UID, pending_uid=None, status='acknowledged', role='auto',
                  detail='Cube acknowledged; flash persistence not verified', updated_at='2026-09-21T09:00:00+0900', source='paired'):
    return dict(mac=mac, cube_id=cube_id, uid=uid, pending_uid=pending_uid, status=status, role=role, detail=detail,
                updated_at=updated_at, source=source, original_number=None, nfc_seen=True, age_s=None, recent=False,
                telemetry={}, usb_firmware=None, pinned=False, on_usb=False)


def zone_row(mac=PLATE_MAC, name='Preshow 1', zone_type=1, point_id=1, firmware='preshow-3.4.0', db_version=31,
             db_crc=0x11E2A0F3, last_error=0, last_seen_epoch=NOW - 6, source='radio', state=None, in_range=None, rx_gain=48,
             rx_gain_applied=48, rx_gain_pending=None, staging_version=0, staging_total=0):
    row = dict(mac=mac, name=name, zone_type=zone_type, point_id=point_id, firmware=firmware, db_version=db_version,
               db_count=32, db_crc=db_crc, staging_version=staging_version, staging_chunks=0, staging_total=staging_total,
               uptime=100, tags=3, unknown_tags=1, send_fail=0, last_error=last_error, channel=2, config_valid=1,
               active_slot=1, last_seen='', last_seen_epoch=last_seen_epoch, source=source, detail='', profile=None,
               params=None, rx_gain=rx_gain, rx_gain_applied=rx_gain_applied, set_result=0)
    if state is not None:
        row.update(state=state, in_range=in_range if in_range is not None else True,
                   age_s=max(0, NOW - (last_seen_epoch or NOW)), error_text='', rssi=-61, rx_gain_pending=rx_gain_pending,
                   current=state == 'current', zone_label='preshow', log=None)
    return row


def usb_device(port='/dev/cu.usbmodem1101', role='zone', mac=PLATE_MAC, state='session', details=None, firmware='preshow-3.4.0',
               candidate=True, presumed=None, detection=None, fw_status=None, error=None, session_kind=None, attempts=1):
    return dict(id=mac or f'usb:{port}', port=port, key=mac or port, serial=mac, description='ESP32-C3', native_usb=True,
                candidate=candidate, usb_mac=mac, mac=mac, role=role, role_label=role, presumed=presumed or {}, firmware=firmware,
                details=details or {}, state=state, attempts=attempts, error=error, session=None, job=None, pinned=False,
                fw_status=fw_status, detection=detection, first_seen=0, last_seen=0, probed_at=0,
                session_kind=session_kind or (role if role != 'zone' else 'zone'), manual_off=False)


def zone_report(mac=PLATE_MAC, name='Preshow 1', zone_type=1, point_id=1, firmware='preshow-3.4.0', db_version=31,
                db_crc=0x11E2A0F3, config_valid=True, last_error=0, rx_gain=48, rx_gain_applied=48):
    report = dict(firmware=firmware, mac=mac, channel=2, db_version=db_version, db_count=32, db_crc=db_crc, active_slot=1,
                  config_valid=config_valid, last_error=last_error, rx_gain=rx_gain, rx_gain_applied=rx_gain_applied)
    if config_valid:
        report.update(zone_type=zone_type, point_id=point_id, name=name)
    return report


def zone_session(mac=PLATE_MAC, kind='preshow', report=None, history=(), nfc=None, tags=(), stats=None, port='/dev/cu.usbmodem1101',
                 host=None, interaction=None, calibration=None, tune_supported=True):
    report = zone_report(mac=mac) if report is None else report
    nfc = dict(ok=True, polls=400, found=3, last_ms=38, fast_fail=0, recoveries=0, sda='1', scl='1', pins='4/3') if nfc is None else nfc
    s = dict(kind=kind, id='s1', opened_at=NOW - 60, last_rx=NOW - 1, age_s=1.0, device=mac, port=port, report=report, nfc=nfc,
             reader=dict(text='ok', level='ok'), current=None, history=list(history), cubes={}, notes=[],
             stats=stats or dict(tags=3, unknown=1, send_fail=0, error=0, at=NOW), rfcfg=None, db_lines=[], log_lines=[],
             zone_type=(report or {}).get('zone_type'), tags=list(tags))
    if kind == 'preshow':
        s.update(host=host or {}, armed=False, want_armed=False)
    if kind == 'pool':
        s.update(interaction=interaction or {}, calibration=calibration, tuning=None, tune_supported=tune_supported, ready=True)
    return s


def tap(uid, cube_id=None, mac=None, state='unknown tag', at=NOW - 20, zone=1):
    return dict(time=at, uid=uid, cube_id=cube_id, mac=mac, zone=zone, state=state, held_ms=None)


def station_section(connected=True, reader_ok=True, nfc_ok=True, nfc_i2c_status=0, mode='', phase='', feedback=None, zones=1,
                    channel=2, firmware='nct-pairing-1.8-zones', discovered=None, dongle=False, active=None, last_disconnect=None,
                    device=STATION_MAC):
    return dict(present=True, kind='workstation', id='st', device=device, port='/dev/cu.usbmodem2101', connected=connected,
                reader_ok=reader_ok, mode=mode, phase=phase, active=active, message='', feedback=feedback or {},
                hello=dict(firmware=firmware, zones=zones, mac=device, channel=channel, radio_ok=True, nfc_ok=nfc_ok,
                           nfc_polling=nfc_ok, nfc_i2c_status=nfc_i2c_status),
                telemetry={}, discovered=discovered or {}, tag_present=False, progress=0, total=0, dongle=dongle,
                last_disconnect=last_disconnect, zone_support=zones == 1, events=10)


def sections(**overrides):
    base = dict(
        meta=dict(database='x', simulate=True),
        ports=[], devices=[], sessions={},
        inventory=dict(rows=[inventory_row()], roles={}, reserved=[2, 22, 39, 43], suggested_number=45, auto_number=False,
                       zones=[zone_row()], published=dict(PUBLISHED), local_differs=False, published_error=None, flash_runs=[],
                       events=[], counts=dict(total=1, registered=1, unconfirmed=0, needs_number=0, needs_tag=0), controllers=[],
                       published_records=[[CUBE_NUMBER, CUBE_UID, CUBE_MAC]]),
        station=dict(present=False),
        registry=dict(present=False, published=dict(PUBLISHED)),
        jobs=[],
        sync=dict(status=dict(state='ok', up=0, down=0, conflicts=0, lost=0, inventory_up=0, inventory_down=0, zone_publish=False,
                              zone_pull=False, waiting=0, web_version=32, local_version=32),
                  text='✓ Synced', tone='ok', detail='', busy=False, checked_at=NOW, last_result=None, last_error=None, summary='',
                  password_known=True),
        locks={'.lock': False, '.flasher.lock': False, '.zonedb.lock': False, '.mainshow.lock': False},
        builds=dict(cube=dict(version='v1.4.1-USB.2', build_hash='h', error=None), zones={},
                    workstation=dict(state='current', version='workstation-1.0.0'), mainshow=dict(state='current', version='mainshow-1.2.0'),
                    tools=dict(esptool_ok=True, esptool_text='esptool 5.3.1', arduino_cli='/usr/bin/arduino-cli', core_ok=True)),
        show=dict(present=False), settings={})
    base = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict) and key != 'sessions':
            base[key].update(value)
        else:
            base[key] = value
    return base


def with_registry(base, zones):
    base['registry'] = dict(present=True, published=dict(PUBLISHED), publishing=None, zones=zones, message='', auto_refresh=True,
                            walkaround=False, logs={}, device=STATION_MAC, connected=True)
    return base


def f1_sections(**kw):
    """The user's example: plate on USB holds v31, an unknown tap for cube #44's tag, which is in published v32."""
    base = sections(devices=[usb_device(session_kind='preshow')],
                    sessions={PLATE_MAC: zone_session(history=[tap(CUBE_UID)])},
                    station=station_section())
    with_registry(base, [zone_row(state='behind', in_range=True)])
    for k, v in kw.items():
        base[k] = v
    return base
