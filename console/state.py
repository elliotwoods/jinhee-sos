"""Snapshot sections: plain JSON-able dicts the UI polls and the advisor evaluates.

Section shapes (a version counter accompanies each; the UI re-renders what changed):
  meta       {database, api_url, simulate, started, console_version}
  ports      [ {port, key, serial, description, candidate, native_usb} ]          raw USB enumeration
  devices    [ Device.to_dict() + {session_kind, session_state} ]                  everything on USB
  inventory  {rows:[device rows + role/original_number/nfc_seen/pinned], roles, reserved, suggested_number,
              auto_number, zones:[registry rows], published, local_differs, published_error, flash_runs,
              events:[recent audit events], counts:{...}}
  station    {present, device, port, connected, reader_ok, mode, phase, active, message, feedback, hello,
              telemetry, discovered:{mac: age_s}, tag_present, progress, total, dongle, zone_support}
  registry   ZoneRegistry.snapshot() + {logs, device, connected}   or {present: False}
  sessions   {device_id: session.snapshot()}
  jobs       [Job.to_dict()] newest first
  sync       {status, text, tone, detail, busy, checked_at, last_result, last_error, summary, password_known}
  advisor    {suggestions:[...], by_scope:{scope:[ids]}, counts:{bad,warn,info}}   (advisor.section)
  locks      {'.lock': held, ...}   the old apps' instance locks held by other processes
  builds     {cube:{version,error}, zones:{sketch:{version,error}}, dongle:{state,version}, mainshow:{state,version},
              tools:{esptool_ok, esptool_text, arduino_cli, core_ok}, checked_at}
  show       MainshowSession.snapshot() or {present: False}
  showedit   ShowEditor.snapshot(): draft show, published show, cube show versions, update progress
  settings   hub.settings
  register   RegistrationFlow.snapshot(): the guided registration workflow (regflow.py)
"""
import paths  # noqa: F401
import time

from dashboard import ORIGINAL_NUMBERS
from sync_widget import describe as describe_sync
import core
import dongle
import hostos
import zone_build
import zonedb

CONSOLE_VERSION = '0.1.0'


def build(hub, dirty):
    out = {}
    if 'meta' in dirty:
        out['meta'] = dict(database='simulated (temporary copy, discarded on exit)' if hub.simulate else str(hub.database), api_url=hub.api.url if hub.api else None, simulate=hub.simulate,
                           started=hub.started_at, console_version=CONSOLE_VERSION, root=str(paths.ROOT))
    if 'ports' in dirty:
        out['ports'] = hub.sections.get('ports', [])
    if 'devices' in dirty:
        out['devices'] = devices(hub)
    if 'inventory' in dirty:
        out['inventory'] = inventory(hub)
    if 'station' in dirty:
        out['station'] = station(hub)
    if 'registry' in dirty:
        out['registry'] = registry(hub)
    if 'sessions' in dirty:
        out['sessions'] = {device_id: s.snapshot() for device_id, s in hub.sessions.items()}
    if 'jobs' in dirty:
        out['jobs'] = hub.jobs.snapshot()
    if 'sync' in dirty:
        out['sync'] = sync(hub)
    if 'locks' in dirty:
        out['locks'] = dict(hub.locks_held)
    if 'builds' in dirty:
        out['builds'] = hub.builds
    if 'show' in dirty:
        out['show'] = show(hub)
    if 'showedit' in dirty and getattr(hub, 'showedit', None):
        out['showedit'] = hub.showedit.snapshot()
    if 'settings' in dirty:
        out['settings'] = dict(hub.settings)
    if 'register' in dirty and getattr(hub, 'regflow', None):
        out['register'] = hub.regflow.snapshot()
    return out


def devices(hub):
    rows = []
    for device in hub.devices.values():
        d = device.to_dict()
        session = hub.sessions.get(device.id)
        d['session_kind'] = session.kind if session else None
        d['manual_off'] = device.id in hub.manual_off
        d['pinned'] = bool(device.mac and device.mac == hub.pinned_mac)
        rows.append(d)
    rows.sort(key=lambda d: (d['role'] or 'zzz', d['port']))
    return rows


def inventory(hub):
    db, store = hub.db, hub.store
    cache = hub.inventory_cache
    roles = cache['roles']
    nfc_seen = db.nfc_seen_macs()
    station_session = hub.station_session()
    discovered = station_session.controller.discovered if station_session else {}
    telemetry = station_session.controller.telemetry if station_session else {}
    now = hub.clock()
    rows = []
    for row in cache['rows']:
        row = dict(row)
        mac = row['mac']
        age = now - discovered[mac] if mac in discovered else None
        row.update(role=roles.get(mac, 'auto'), original_number=ORIGINAL_NUMBERS.get(mac), nfc_seen=mac in nfc_seen,
                   age_s=None if age is None else round(age, 1), recent=age is not None and age < 10,
                   telemetry=telemetry.get(mac, {}), usb_firmware=hub.usb_firmware.get(mac),
                   pinned=mac == hub.pinned_mac, on_usb=any(d.mac == mac for d in hub.devices.values()))
        rows.append(row)
    known = {r['mac'] for r in rows}
    for mac in set(discovered) | set(roles):
        if mac not in known:
            age = now - discovered[mac] if mac in discovered else None
            rows.append(dict(mac=mac, cube_id=None, uid=None, pending_uid=None, status='discovered', source='radio',
                             detail='', updated_at='—', role=roles.get(mac, 'auto'), original_number=ORIGINAL_NUMBERS.get(mac),
                             nfc_seen=False, age_s=None if age is None else round(age, 1),
                             recent=age is not None and age < 10, telemetry=telemetry.get(mac, {}),
                             usb_firmware=None, pinned=mac == hub.pinned_mac, on_usb=False))
    c = station_session.controller if station_session else None
    for row in rows:
        row['capabilities'] = capabilities(row, c)
    rows.sort(key=lambda r: (r['cube_id'] is None, r['cube_id'] or 0, r['mac']))
    try:
        published = store.published()
    except Exception:
        published = dict(version=0, hash='', count=0, crc=0)
    published_error, published_records = None, None
    try:
        publication = store.current()
        published_records = [[cid, zonedb.bytes_to_hex(uid), zonedb.bytes_to_hex(mac)] for cid, uid, mac in publication.records]
    except ValueError as exc:
        published_error = str(exc)
    try:
        local_differs = store.local_differs()
    except Exception:
        local_differs = True
    try:
        suggested = db.suggested_number()
    except ValueError:
        suggested = None
    auto = db.metadata('auto_number')
    counts = dict(total=len([r for r in rows if r['role'] != 'excluded']),
                  registered=len([r for r in rows if r['status'] == 'acknowledged']),
                  unconfirmed=len([r for r in rows if r['status'] in ('unconfirmed', 'pending', 'not_transmitted')]),
                  needs_number=len([r for r in rows if r['status'] == 'needs_number']),
                  needs_tag=len([r for r in rows if r['status'] == 'awaiting_tag']))
    return dict(rows=rows, roles=roles, reserved=db.reserved_numbers(), suggested_number=suggested,
                auto_number=auto is None or auto == '1', zones=cache['zones'], published=published,
                local_differs=local_differs, published_error=published_error, published_records=published_records,
                flash_runs=db.history(), intake=hub.intake.snapshot() if getattr(hub, 'intake', None) else None,
                events=db.recent_events(200), counts=counts, controllers=sorted(cache['controllers']),
                export_error=getattr(db, 'export_error', None))


def capabilities(row, c):
    """What the cube card may offer right now, with the reason when it may not (the pairing app's button rules)."""
    excluded = row.get('role') == 'excluded'
    connected, reader, mode, phase = (c.connected, c.reader_ok, c.mode, c.phase) if c else (False, False, '', '')
    idle = connected and not mode
    previewing = mode == 'preview' and phase == 'flashing'
    register_reason = ('Connect the NFC station to register; cube USB identification alone is not enough' if not connected else
                       'NFC reader is unavailable; check the station and reader connection' if not reader else
                       'This device is excluded as a reader or base station' if excluded else
                       'An operation is active; use Stop before registering' if mode and not previewing else '')
    saved = row.get('cube_id') is not None and bool(row.get('uid') or row.get('pending_uid'))
    return dict(
        register=dict(enabled=not register_reason, reason=register_reason),
        transmit=dict(enabled=idle and not excluded and saved,
                      reason='' if idle and not excluded and saved else 'Needs a connected idle station and a saved number + tag' if not saved else
                      'Station busy or not connected' if not idle else 'Excluded device'),
        flash=dict(enabled=idle and not excluded, reason='' if idle and not excluded else 'Station busy or not connected'),
        rename=dict(enabled=not excluded and (not row.get('pending_uid') or row.get('cube_id') is None) and (not mode or previewing),
                    reason='' if not excluded and (not row.get('pending_uid') or row.get('cube_id') is None) and (not mode or previewing) else
                    'Finish or retry the pending registration before renaming' if row.get('pending_uid') and row.get('cube_id') is not None else
                    'Stop the active operation first' if mode else 'Excluded device'),
        role=dict(enabled=not mode, reason='' if not mode else 'Stop the active operation first'),
    )


def station(hub):
    session = hub.station_session()
    if not session:
        return dict(present=False)
    return dict(present=True, **session.snapshot())


def registry(hub):
    session = hub.station_session()
    if not session:
        return dict(present=False, published=hub.store.published() if hub.store else None)
    return dict(present=True, **session.registry_snapshot())


def sync(hub):
    s = hub.sync
    status = s['status'] or dict(state='checking')
    text, tone, detail = describe_sync(status)
    return dict(status=status, text=text, tone=tone, detail=detail, busy=s['busy'], checked_at=s['checked_at'],
                last_result=s['last_result'], last_error=s['last_error'], summary=s['summary'],
                password_known=s['password_known'], plan=s.get('plan'))


def show(hub):
    session = hub.show_session()
    if session:
        snap = session.snapshot()
        return dict(present=True, via=session.kind, device=session.device.id, usable=snap.get('usable'), connected=snap.get('connected'),
                    info=snap.get('info'), problem=snap.get('problem'), pending=snap.get('pending'), show=snap.get('show'),
                    timeline=snap.get('timeline'))
    return dict(present=False)


def builds(previous=None):
    """Manifest and tool state. File hashing only; the esptool version probe is a job (tools.check)."""
    out = dict(cube={}, zones={}, dongle={}, mainshow={}, tools=(previous or {}).get('tools', {}), checked_at=time.time())
    try:
        manifest = core.load_manifest()
        out['cube'] = dict(version=manifest['version'], build_hash=manifest['build_hash'], error=None)
    except Exception as exc:
        out['cube'] = dict(version=core.VERSION, build_hash=None, error=str(exc))
    for sketch in zone_build.SKETCHES:
        try:
            manifest = zone_build.load_manifest(sketch)
            out['zones'][sketch] = dict(version=manifest['version'], build_hash=manifest['build_hash'], error=None)
        except Exception as exc:
            out['zones'][sketch] = dict(version=None, build_hash=None, error=str(exc))
    from jobs.dongle import FIRMWARES
    for name, firmware in (('dongle', dongle.PAIRING), ('mainshow', dongle.MAINSHOW), ('general', FIRMWARES['general'])):
        try:
            out[name] = dict(state=dongle.build_state(firmware), version=firmware.version, label=firmware.label)
        except Exception as exc:
            out[name] = dict(state='missing', version=firmware.version, label=firmware.label, error=str(exc))
    out['tools'].setdefault('arduino_cli', hostos.arduino_cli())
    out['tools'].setdefault('core_ok', hostos.esp32_core().is_dir())
    return out
