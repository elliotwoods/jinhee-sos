"""Every operation the UI (and the advisor's actions) can ask for, by name, run on the owner thread.

kind: safe (runs on click) | hardware (runs on click; has a physical effect, so the UI marks it and its
tooltip carries the warning) | destructive (needs a confirmation token: the UI's press-and-hold). The token
is checked here, so the hold is enforced, not cosmetic. Every function raises ValueError with operator text.
"""
import paths  # noqa: F401
import json
from pathlib import Path

from database import hex_bytes
import dongle
import zone_build
import zonedb

from jobs import build as build_jobs, cube as cube_jobs, dongle as dongle_jobs, pool as pool_jobs, sync as sync_jobs, zone as zone_jobs

COMMANDS = {}
mainshow_app = paths.load_app_module('mainshow_app', 'zones/mainshow/app.py')


def command(name, kind='safe'):
    def register(fn):
        COMMANDS[name] = dict(name=name, kind=kind, fn=fn, doc=(fn.__doc__ or '').strip())
        return fn
    return register


def run(hub, name, args=None, token=None):
    spec = COMMANDS.get(name)
    if not spec:
        raise ValueError(f'Unknown command {name}')
    args = dict(args or {})
    if spec['kind'] == 'destructive':
        hub.check_confirmation(token or args.pop('token', None), name, args)
    else:
        args.pop('token', None)
    return spec['fn'](hub, **args)


def _job(job):
    return dict(job=job.id, title=job.title)


# ---------------------------------------------------------------- console / devices
@command('console.settings')
def settings(hub, key, value):
    if key not in hub.settings:
        raise ValueError(f'Unknown setting {key}')
    hub.settings[key] = value
    hub.mark_dirty('settings')
    return hub.settings


@command('usb.rescan')
def usb_rescan(hub):
    hub.scanner.rescan()
    return True


@command('device.probe')
def device_probe(hub, device):
    """Ask the board what it is again (no reset)."""
    d = hub.device_by_id(device)
    if d.id in hub.sessions:
        hub.close_session(hub.sessions[d.id], 'probe again')
    d.state, d.attempts, d.next_probe, d.error = 'present', 0, 0, None
    hub.mark_dirty('devices')
    return d.to_dict()


@command('device.connect')
def device_connect(hub, device):
    d = hub.device_by_id(device)
    hub.manual_off.discard(d.id)
    if d.state in ('present', 'probing'):
        raise ValueError('The board has not been identified yet')
    session = hub.open_session(d)
    if not session:
        raise ValueError(d.error or 'Could not open the port')
    return session.snapshot()


@command('device.disconnect')
def device_disconnect(hub, device):
    d = hub.device_by_id(device)
    session = hub.sessions.get(d.id)
    if session:
        hub.close_session(session, 'disconnected by operator', manual=True)
    else:
        hub.manual_off.add(d.id)
    return True


@command('device.console')
def device_console(hub, device, line):
    """Send one console line to a device session (each role validates its own commands)."""
    session = hub.session_for(device)
    if not hasattr(session, 'console'):
        raise ValueError('That device has no text console')
    session.console(str(line))
    return True


@command('device.unpin')
def device_unpin(hub):
    hub.pinned_mac = None
    for d in hub.devices.values():
        d.pinned = False
    hub.mark_dirty('devices', 'inventory')
    return True


@command('device.stop')
def device_stop(hub, device=None):
    """Esc: stop whatever this device (or every device) is doing."""
    targets = [hub.session_for(device)] if device else list(hub.sessions.values())
    for session in targets:
        session.stop_active()
    return len(targets)


@command('jobs.cancel')
def jobs_cancel(hub, job):
    return hub.jobs.cancel(job).to_dict()


# ---------------------------------------------------------------- cube monitor (zone console)
@command('monitor.flash')
def monitor_flash(hub, device, cube_id, seconds=5):
    hub.session_for(device, ('zone', 'pool', 'preshow')).cube_command('flash', cube_id, seconds)
    return True


@command('monitor.stop')
def monitor_stop(hub, device):
    hub.session_for(device, ('zone', 'pool', 'preshow')).cube_command('stop', None)
    return True


@command('monitor.zone', 'hardware')
def monitor_zone(hub, device, cube_id, zone):
    """Send SET_ZONE <zone> to a cube through this plate (0 idle, 1 preshow, 2 desert, 3 pool, 4 mainshow)."""
    if int(zone) not in range(0, 5):
        raise ValueError('Zone must be 0-4 (5, the reset plate kind, is never sent to a cube)')
    hub.session_for(device, ('zone', 'pool', 'preshow')).cube_command('zone', cube_id, int(zone))
    return True


@command('monitor.clear', 'hardware')
def monitor_clear(hub, device, cube_id):
    hub.session_for(device, ('zone', 'pool', 'preshow')).cube_command('clear', cube_id)
    return True


@command('zone.nfc_recover', 'hardware')
def zone_nfc_recover(hub, device):
    hub.session_for(device, ('zone', 'pool', 'preshow')).console('nfc recover')
    return True


@command('zone.rxgain_usb', 'hardware')
def zone_rxgain_usb(hub, device, db):
    hub.session_for(device, ('zone', 'pool', 'preshow')).console(f'rxgain {zonedb.check_rx_gain(db)}')
    return True


# ---------------------------------------------------------------- pairing station
def _station(hub, device=None):
    """The pairing link: `device` names a board (station or General Radio), else the primary link."""
    session = hub.station_session(device)
    if not session:
        raise ValueError('Connect a pairing station first')
    return session


@command('pairing.discover')
def pairing_discover(hub, device=None):
    _station(hub, device).controller.discover()
    return True


@command('pairing.stop')
def pairing_stop(hub, device=None):
    _station(hub, device).controller.stop()
    return True


@command('pairing.skip')
def pairing_skip(hub, device=None):
    _station(hub, device).controller.skip()
    return True


@command('pairing.retry', 'hardware')
def pairing_retry(hub, device=None):
    _station(hub, device).controller.retry()
    return True


@command('pairing.start_pair', 'hardware')
def pairing_start_pair(hub, device=None):
    """Pair new cubes one after another (discover, flash the target, wait for its tag)."""
    _station(hub, device).controller.start_pair()
    return True


@command('pairing.register', 'hardware')
def pairing_register(hub, mac, number=None, device=None):
    """REGISTER DEVICE: flash this cube and wait for a fresh NFC scan (takes over a tag if it is scanned)."""
    c = _station(hub, device).controller
    c.repair(mac, int(number) if number not in (None, '') else None)
    hub.mark_dirty('inventory')
    return True


@command('pairing.transmit', 'hardware')
def pairing_transmit(hub, macs, device=None):
    """Send the saved mapping(s) without a new scan."""
    rows = [hub.db.get(m) for m in macs]
    if not all(rows):
        raise ValueError('Unknown device')
    _station(hub, device).controller.transmit(rows)
    return True


@command('pairing.transmit_originals', 'hardware')
def pairing_transmit_originals(hub, device=None):
    _station(hub, device).controller.transmit(hub.db.original_batch())
    return True


@command('pairing.retry_unconfirmed', 'hardware')
def pairing_retry_unconfirmed(hub, device=None):
    rows = [r for r in hub.db.rows() if r['status'] == 'unconfirmed' and (r['uid'] or r['pending_uid'])
            and not hub.db.excluded(r['mac'])]
    if not rows:
        raise ValueError('No unconfirmed registrations')
    _station(hub, device).controller.transmit(rows)
    return len(rows)


@command('pairing.flash')
def pairing_flash(hub, macs, sequential=False, device=None):
    """Identify-flash cubes (red/blue) until Stop, or two seconds each in sequence."""
    rows = [hub.db.get(m) for m in macs]
    if not all(rows):
        raise ValueError('Unknown device')
    _station(hub, device).controller.flash(rows, sequential=bool(sequential))
    return True


@command('pairing.preview')
def pairing_preview(hub, mac, device=None):
    if hub.settings.get('preview_flash'):
        _station(hub, device).controller.preview(mac)
    return True


@command('station.nfc_recover', 'hardware')
def station_nfc_recover(hub, device=None):
    _station(hub, device).controller.emit('nfc_recover')
    return True


@command('station.nfc_status')
def station_nfc_status(hub, device=None):
    _station(hub, device).controller.emit('nfc_status')
    return True


# ---------------------------------------------------------------- inventory
@command('inventory.rename')
def inventory_rename(hub, mac, number):
    """Assign the physical label number (validated for uniqueness); transmitted when a station is connected."""
    number = int(number)
    session = hub.station_session()
    if session and session.controller.connected:
        session.controller.rename(mac, number)
    else:
        hub.db.rename(mac, number)
    hub.mark_dirty('inventory')
    return hub.db.get(mac)


@command('inventory.clear_number')
def inventory_clear_number(hub, mac):
    hub.db.clear_unseen_numbers(also_clear=(mac,)) if hasattr(hub.db, 'clear_unseen_numbers') else None
    hub.mark_dirty('inventory')
    return hub.db.get(mac)


@command('inventory.set_role')
def inventory_set_role(hub, mac, role):
    session = hub.station_session()
    if session and session.controller.mode:
        raise ValueError('Finish or stop the current station operation before changing a role')
    hub.db.set_role(mac, role)
    hub.mark_dirty('inventory')
    return role


@command('inventory.unregister', 'destructive')
def inventory_unregister(hub, mac):
    """Release this device's number and tags (its firmware is not changed)."""
    hub.db.unregister(mac, 'Unregistered in the NCT Console')
    hub.mark_dirty('inventory')
    return hub.db.get(mac)


@command('inventory.export_csv')
def inventory_export_csv(hub, path):
    hub.db.export_csv(Path(path))
    return str(path)


@command('inventory.export_header')
def inventory_export_header(hub, path):
    hub.db.export_header(Path(path))
    return str(path)


@command('inventory.events')
def inventory_events(hub, mac=None, limit=200):
    return dict(events=hub.db.recent_events(int(limit), mac), sightings=hub.db.sightings(mac) if mac else [])


# ---------------------------------------------------------------- zone registry (over the air)
@command('zones.query')
def zones_query(hub, device=None):
    hub.zone_relay(device).zones.query()
    return True


@command('zones.request_log')
def zones_request_log(hub, mac, device=None):
    hub.zone_relay(device).zones.request_log(mac)
    return True


@command('zones.identify')
def zones_identify(hub, mac, seconds=10, device=None):
    hub.zone_relay(device).zones.identify(mac, int(seconds))
    return True


@command('zones.update', 'hardware')
def zones_update(hub, mac, device=None):
    """Send the published database to one zone over the air (unicast announce, never forced)."""
    session = hub.zone_relay(device)
    if session.controller.mode:
        raise ValueError('Stop the pairing operation first; the station is busy')
    p = session.zones.update(mac)
    return dict(version=p.version, count=p.count)


@command('zones.update_all', 'hardware')
def zones_update_all(hub, device=None):
    """One broadcast run for every in-range zone that is out of date."""
    session = hub.zone_relay(device)
    if session.controller.mode:
        raise ValueError('Stop the pairing operation first; the station is busy')
    candidates = [z['mac'] for z in session.zones.zone_rows() if z['in_range'] and z['state'] == 'behind']
    if not candidates:
        raise ValueError(f'No out-of-date zones in range (published v{hub.store.published()["version"]})')
    p = session.zones.publish(expected=candidates, timeout=session.zones.WALK_TIMEOUT)
    return dict(version=p.version, zones=candidates)


@command('zones.stop')
def zones_stop(hub, device=None):
    session = hub.station_session(device)
    if session:
        session.zones.stop('Publishing stopped')
    return True


@command('zones.walkaround')
def zones_walkaround(hub, enabled, device=None):
    session = hub.zone_relay(device)
    session.zones.set_walkaround(bool(enabled))
    if enabled:
        session.zones.set_auto_refresh(True)
    return bool(enabled)


@command('zones.auto_refresh')
def zones_auto_refresh(hub, enabled, device=None):
    hub.zone_relay(device).zones.set_auto_refresh(bool(enabled))
    return bool(enabled)


@command('zones.reboot', 'hardware')
def zones_reboot(hub, mac, device=None):
    hub.zone_relay(device).zones.reboot(mac)
    return True


@command('zones.set_rx_gain', 'hardware')
def zones_set_rx_gain(hub, mac, db, device=None):
    session = hub.zone_relay(device)
    firmware = str(session.controller.station.get('firmware', ''))
    if firmware not in dongle.RELAY_VERSIONS:  # the 1.8 relay or a General Radio
        raise ValueError(f'The dongle runs {firmware or "unknown firmware"}; setting the RX gain needs '
                         f'{" or ".join(sorted(dongle.RELAY_VERSIONS))}')
    session.zones.set_rx_gain(mac, zonedb.check_rx_gain(db))
    return True


# ---------------------------------------------------------------- sync
@command('sync.run')
def sync_run(hub):
    return _job(sync_jobs.sync_job(hub))


@command('sync.upload')
def sync_upload(hub):
    return _job(sync_jobs.sync_job(hub, upload=True, download=False))


@command('sync.download')
def sync_download(hub):
    return _job(sync_jobs.sync_job(hub, upload=False, download=True))


@command('sync.status')
def sync_status(hub):
    return _job(sync_jobs.status_job(hub))


@command('sync.signin')
def sync_signin(hub, password):
    return _job(sync_jobs.signin_job(hub, password))


@command('sync.forget')
def sync_forget(hub):
    import web_client
    web_client.forget_password()
    hub.sync['password_known'] = False
    hub.mark_dirty('sync')
    return True


@command('zone.pull')
def zone_pull(hub):
    return _job(sync_jobs.zone_pull_job(hub))


@command('zone.publish')
def zone_publish(hub):
    return _job(sync_jobs.zone_publish_job(hub))


# ---------------------------------------------------------------- flashing and builds
@command('cube.flash_firmware', 'hardware')
def cube_flash_firmware(hub, device, manual=True):
    """Write the bundled cube firmware (NVS preserved, verified, boot checked)."""
    d = hub.device_by_id(device)
    if d.role not in ('cube', 'unknown', None):
        raise ValueError(f'That board is a {d.role_label()}; the cube flasher refuses it')
    return _job(cube_jobs.flash_job(hub, d, manual=bool(manual)))


@command('usb.auto_cubes', 'hardware')
def usb_auto_cubes(hub, enabled):
    """Turn on automatic cube flashing for boards plugged in from now on (off at every launch)."""
    hub.intake.arm_cubes(bool(enabled))
    return hub.intake.snapshot()


@command('usb.auto_zones', 'hardware')
def usb_auto_zones(hub, enabled, form=None, options=None):
    """Turn on automatic zone flashing (identified boards are updated in place; legacy sketches take the form's zone)."""
    hub.intake.arm_zones(bool(enabled), form, options)
    return hub.intake.snapshot()


@command('usb.intake_form')
def usb_intake_form(hub, form=None, options=None):
    if form:
        hub.intake.zone_form.update(form)
    if options:
        hub.intake.zone_options.update(options)
    hub.mark_dirty('inventory')
    return hub.intake.snapshot()


@command('cube.check_boot')
def cube_check_boot(hub, device):
    return _job(cube_jobs.boot_check_job(hub, hub.device_by_id(device)))


@command('zone.flash', 'hardware')
def zone_flash(hub, device, profile, point, name, params=(), rx_gain=zonedb.RX_GAIN_DEFAULT):
    """Write firmware + identity + the published database to a zone board."""
    return _job(zone_jobs.flash_job(hub, hub.device_by_id(device), profile, point, name, params, rx_gain))


@command('zone.flash_force', 'destructive')
def zone_flash_force(hub, device, profile, point, name, params=(), rx_gain=zonedb.RX_GAIN_DEFAULT):
    """Overwrite a board the inventory lists as a cube or excluded device (a cube is unregistered)."""
    return _job(zone_jobs.flash_job(hub, hub.device_by_id(device), profile, point, name, params, rx_gain, force=True))


@command('zone.update_db_usb', 'hardware')
def zone_update_db_usb(hub, device):
    """Write only the published cube database to a zone board on USB (firmware and identity untouched)."""
    return _job(zone_jobs.update_db_job(hub, hub.device_by_id(device)))


@command('zone.detect', 'hardware')
def zone_detect_cmd(hub, device):
    """Identify a silent board through its bootloader (reboots it)."""
    return _job(zone_jobs.detect_job(hub, hub.device_by_id(device)))


@command('zone.check_report')
def zone_check_report(hub, device):
    return _job(zone_jobs.report_job(hub, hub.device_by_id(device)))


@command('zone.profiles')
def zone_profiles(hub):
    return dict(profiles={k: dict(v, params=[list(p) for p in v['params']]) for k, v in zone_build.PROFILES.items()},
                rx_gains=list(zonedb.RX_GAINS), rx_gain_default=zonedb.RX_GAIN_DEFAULT, sketches=list(zone_build.SKETCHES))


@command('dongle.flash', 'hardware')
def dongle_flash(hub, device, firmware='dongle'):
    """Make a spare ESP32-C3 an ESP-NOW dongle (pairing-station relay) or the Mainshow controller."""
    if firmware not in ('dongle', 'mainshow', 'general'):
        raise ValueError('firmware must be dongle, mainshow or general')
    return _job(dongle_jobs.flash_job(hub, hub.device_by_id(device), firmware))


@command('pool.flash_firmware', 'hardware')
def pool_flash_firmware(hub, device, database_only=False):
    return _job(pool_jobs.flash_job(hub, hub.device_by_id(device), database_only=bool(database_only)))


@command('pool.assign_radio_id', 'hardware')
def pool_assign_radio_id(hub, device, new_id, force=False):
    return _job(pool_jobs.assign_radio_id_job(hub, hub.device_by_id(device), int(new_id), bool(force)))


@command('build.cube')
def build_cube(hub):
    return _job(build_jobs.cube_build_job(hub))


@command('build.zone')
def build_zone(hub, sketch):
    return _job(build_jobs.zone_build_job(hub, sketch))


@command('build.dongle')
def build_dongle(hub, firmware='dongle'):
    return _job(build_jobs.dongle_build_job(hub, firmware))


@command('tools.check')
def tools_check(hub):
    return _job(build_jobs.tools_job(hub))


@command('builds.refresh')
def builds_refresh(hub):
    hub.refresh_builds()
    return hub.builds


# ---------------------------------------------------------------- mainshow
def _mainshow(hub):
    session = hub.show_session()
    if not session:
        raise ValueError('Connect the Mainshow controller or a General Radio first')
    return session


def _cube_target(hub, cube):
    if isinstance(cube, str) and ':' in cube:
        row = hub.db.get(cube.upper())
        if not row:
            raise ValueError(f'No cube {cube} in the inventory')
        return row['mac'], f'#{row["cube_id"]}' if row['cube_id'] else row['mac']
    mac, row = mainshow_app.find_cube(hub.db, int(cube))
    return mac, f'#{row["cube_id"]}'


@command('mainshow.ready', 'hardware')
def mainshow_ready(hub, cube):
    """① Mainshow ready: SET_ZONE 4 (neon) to one cube."""
    mac, name = _cube_target(hub, cube)
    return dict(request=_mainshow(hub).set_zone(mac, 4, name), mac=mac)


@command('mainshow.idle', 'hardware')
def mainshow_idle(hub, cube):
    """Stop → idle: SET_ZONE 0 to one cube (ends its show)."""
    mac, name = _cube_target(hub, cube)
    session = _mainshow(hub)
    request = session.set_zone(mac, 0, name)
    (getattr(session, 'session', None) or session).forget_show(mac)
    return dict(request=request, mac=mac)


@command('mainshow.trigger', 'hardware')
def mainshow_trigger(hub, cube):
    """② Trigger the main show on one cube (fresh showId ×5; only a mainshow-ready cube starts)."""
    mac, name = _cube_target(hub, cube)
    return dict(request=_mainshow(hub).trigger(mac, name), mac=mac)


@command('mainshow.trigger_all', 'destructive')
def mainshow_trigger_all(hub):
    """② Trigger the main show on every mainshow-ready cube (broadcast, no ACK)."""
    return dict(request=_mainshow(hub).trigger('broadcast', 'all cubes'))


@command('mainshow.led_test', 'hardware')
def mainshow_led_test(hub, on):
    return _mainshow(hub).led_test(bool(on))


# ---------------------------------------------------------------- General Radio
def _radio(hub, device):
    return hub.session_for(device, ('generalradio',))


@command('radio.set_zone', 'hardware')
def radio_set_zone(hub, device, mac, zone):
    """SET_ZONE to one cube through the General Radio (0 idle, 1 preshow, 2 desert, 3 pool, 4 mainshow-ready)."""
    if mac == 'broadcast':
        raise ValueError('Use radio.set_zone_all for every cube in range')
    row = hub.db.get(str(mac).upper())
    name = f'#{row["cube_id"]}' if row and row.get('cube_id') else str(mac).upper()
    return dict(request=_radio(hub, device).set_zone(str(mac).upper(), zone, name))


@command('radio.set_zone_all', 'destructive')
def radio_set_zone_all(hub, device, zone):
    """SET_ZONE to EVERY cube in range (broadcast, never acknowledged): recolours the whole installation."""
    return dict(request=_radio(hub, device).set_zone('broadcast', zone, 'every cube in range'))


@command('radio.show_start', 'hardware')
def radio_show_start(hub, device, cube):
    mac, name = _cube_target(hub, cube)
    return dict(request=_radio(hub, device).trigger(mac, name), mac=mac)


@command('radio.show_start_all', 'destructive')
def radio_show_start_all(hub, device):
    """Start the main show on every mainshow-ready cube (broadcast, no ACK)."""
    return dict(request=_radio(hub, device).trigger('broadcast', 'all cubes'))


@command('radio.pool', 'hardware')
def radio_pool(hub, device, member, radio_id=None):
    """Hold one pool lamp (1-23) through the pool central as an emulated slider radio; 0 releases. Leased: keep touching."""
    return dict(request=_radio(hub, device).pool_set(member, radio_id))


@command('radio.pool_touch')
def radio_pool_touch(hub, device):
    return _radio(hub, device).pool_touch()


@command('radio.pool_release')
def radio_pool_release(hub, device):
    session = _radio(hub, device)
    session.pool_held = 0
    return dict(request=session._request('pool', member=0, radio_id=session.pool_radio_id))


@command('radio.preshow', 'hardware')
def radio_preshow(hub, device, point, on):
    """Raise (on) or drop a TouchDesigner cue for point 1-4 through the media bridge. Leased: keep touching."""
    return dict(request=_radio(hub, device).preshow_set(point, bool(on)))


@command('radio.preshow_touch')
def radio_preshow_touch(hub, device):
    return _radio(hub, device).preshow_touch()


@command('radio.release')
def radio_release(hub, device):
    """Release everything this radio holds (pool lamp, preshow cue, identify target)."""
    _radio(hub, device).stop_active()
    return True


@command('radio.led_test', 'hardware')
def radio_led_test(hub, device, on):
    return dict(request=_radio(hub, device).led_test(bool(on)))


@command('radio.status')
def radio_status(hub, device):
    return dict(request=_radio(hub, device).request_status())


@command('radio.preshow_release')
def radio_preshow_release(hub, device):
    """Turn off the preshow cue this radio holds (nothing to do when none is held)."""
    return dict(request=_radio(hub, device).preshow_release())


# The pairing-station verbs on this board's own link, so a General Radio keeps discovering, identify-
# flashing and sending saved mappings while a real pairing station is also plugged in (the pairing.*
# commands go to the primary link unless given a device). No reader: a fresh tag scan is not possible.
@command('radio.discover')
def radio_discover(hub, device):
    _radio(hub, device).controller.discover()
    return True


@command('radio.stop')
def radio_stop(hub, device):
    """Stop the cube operation on this radio (identify flash, registration, saved-mapping run)."""
    _radio(hub, device).controller.stop()
    return True


@command('radio.identify', 'hardware')
def radio_identify(hub, device, macs, sequential=False):
    """Identify-flash cubes (red/blue) until Stop, or two seconds each in sequence, through this radio."""
    rows = [hub.db.get(m) for m in macs]
    if not all(rows):
        raise ValueError('Unknown device')
    _radio(hub, device).controller.flash(rows, sequential=bool(sequential))
    return True


@command('radio.transmit', 'hardware')
def radio_transmit(hub, device, macs):
    """Send the saved mapping(s) to cubes through this radio (no scan needed)."""
    rows = [hub.db.get(m) for m in macs]
    if not all(rows):
        raise ValueError('Unknown device')
    _radio(hub, device).controller.transmit(rows)
    return True


# ---------------------------------------------------------------- pool radio (calibration)
@command('pool.arm', 'hardware')
def pool_arm(hub, device):
    """Start the pool radio's host output override (HOST ARM; leased: the UI must keep touching it)."""
    hub.session_for(device, ('pool',)).arm()
    return True


@command('pool.touch')
def pool_touch(hub, device):
    return hub.session_for(device, ('pool',)).touch()


@command('pool.disarm')
def pool_disarm(hub, device):
    hub.session_for(device, ('pool',)).disarm()
    return True


@command('pool.cal_set')
def pool_cal_set(hub, device, index, mm):
    hub.session_for(device, ('pool',)).cal_set(index, mm)
    return True


@command('pool.cal_save', 'hardware')
def pool_cal_save(hub, device):
    """Write the control points to the radio's flash."""
    hub.session_for(device, ('pool',)).cal_save()
    return True


@command('pool.cal_load')
def pool_cal_load(hub, device):
    hub.session_for(device, ('pool',)).cal_load()
    return True


@command('pool.cal_anchors')
def pool_cal_anchors(hub, device, mask):
    hub.session_for(device, ('pool',)).cal_anchors(mask)
    return True


@command('pool.tune_apply')
def pool_tune_apply(hub, device, values, save=False):
    hub.session_for(device, ('pool',)).tune_apply(dict(values), bool(save))
    return True


@command('pool.tune_load')
def pool_tune_load(hub, device):
    hub.session_for(device, ('pool',)).tune_load()
    return True


@command('pool.tune_defaults')
def pool_tune_defaults(hub, device):
    hub.session_for(device, ('pool',)).tune_defaults()
    return True


@command('pool.raw')
def pool_raw(hub, device, on):
    hub.session_for(device, ('pool',)).raw_mode(bool(on))
    return True


# ---------------------------------------------------------------- preshow plate cue test
@command('preshow.arm', 'hardware')
def preshow_arm(hub, device):
    hub.session_for(device, ('preshow',)).arm()
    return True


@command('preshow.disarm')
def preshow_disarm(hub, device):
    hub.session_for(device, ('preshow',)).disarm()
    return True


@command('preshow.cue', 'hardware')
def preshow_cue(hub, device, point, on):
    """Raise or drop a TouchDesigner cue through this plate's override."""
    hub.session_for(device, ('preshow',)).cue(int(point), bool(on))
    return True


# ---------------------------------------------------------------- pool light test bridge, central, media bridge
@command('pooltest.toggle', 'hardware')
def pooltest_toggle(hub, device, member):
    hub.session_for(device, ('pooltest',)).toggle(int(member))
    return True


@command('pooltest.all_off')
def pooltest_all_off(hub, device):
    hub.session_for(device, ('pooltest',)).all_off()
    return True


@command('pooltest.channel', 'hardware')
def pooltest_channel(hub, device, channel):
    hub.session_for(device, ('pooltest',)).set_channel(int(channel))
    return True


@command('pooltest.sequential', 'hardware')
def pooltest_sequential(hub, device, on, interval=None):
    hub.session_for(device, ('pooltest',)).sequential(bool(on), interval)
    return True


@command('central.recover', 'hardware')
def central_recover(hub, device):
    hub.session_for(device, ('poolcentral',)).send('RECOVER')
    return True


@command('bridge.test', 'hardware')
def bridge_test(hub, device, point, on):
    hub.session_for(device, ('preshowbridge',)).test(int(point), bool(on))
    return True


# ---------------------------------------------------------------- advisor
@command('advisor.dismiss')
def advisor_dismiss(hub, id, scope='once'):
    """scope: once (this occurrence) | scope (this rule on this device) | rule (everywhere)."""
    entry = next((s for s in hub.suggestions if s['id'] == id), None)
    if scope == 'once' or not entry:
        hub.dismissed.add(id)
    elif scope == 'scope':
        hub.dismissed.add(f'{entry["rule"]}@{entry["scope"]}')
    else:
        hub.dismissed.add(f'{entry["rule"]}@*')
    hub.evaluate_advisor()
    return sorted(hub.dismissed)


@command('advisor.undismiss')
def advisor_undismiss(hub):
    hub.dismissed.clear()
    hub.evaluate_advisor()
    return True


@command('advisor.act', 'safe')
def advisor_act(hub, action_id, token=None):
    """Run a suggestion's action after re-checking that it still applies. Destructive actions
    need `token` from confirm('advisor.act', {action_id})."""
    hub.evaluate_advisor()
    entry = hub.actions.get(action_id)
    if not entry:
        scope = action_id.split('#')[0].split(':', 1)[-1]
        return dict(ok=False, reason='stale', explanation='That suggestion no longer applies; the situation changed',
                    now=[s['id'] for s in hub.suggestions if scope in s['id']])
    suggestion, action = entry
    spec = COMMANDS.get(action['command'])
    if not spec:
        raise ValueError(f'Action command {action["command"]} is not available')
    if action.get('kind', 'safe') == 'destructive' or spec['kind'] == 'destructive':
        hub.check_confirmation(token, 'advisor.act', dict(action_id=action_id))
    result = spec['fn'](hub, **dict(action.get('args') or {}))
    hub.log(f'Suggestion action: {action.get("label")} ({suggestion["title"]})', 'info', suggestion.get('device'), source='advisor')
    return dict(ok=True, result=result)


@command('docs.open')
def docs_open(hub, path):
    """Read a repository document for the built-in viewer (paths inside the checkout only)."""
    target = (paths.ROOT / path).resolve()
    if paths.ROOT not in target.parents or not target.is_file():
        raise ValueError('Only files inside the repository can be shown')
    return dict(path=str(path), text=target.read_text(encoding='utf-8', errors='replace')[:200000])


def catalogue():
    return {name: dict(kind=spec['kind'], doc=spec['doc']) for name, spec in COMMANDS.items()}
