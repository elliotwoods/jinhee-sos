"""Contextual suggestions: pure rules over the state sections.

evaluate(sections, now, dismissed) -> [suggestion]      section(suggestions) -> the 'advisor' section

A suggestion is a plain dict: id (stable '<rule>:<scope>[:<key>]'), rule, severity (bad|warn|info), scope
('global' | 'mac:<MAC>' | 'zone:<MAC>' | 'port:<port>' | 'station' | 'sync'), device (id for the badge),
title, know / why / check (honest texts quoting versions, dates and sources), evidence [{source, text, at}],
actions [{id, label, command, args, kind, needs_confirm, long}], fired_at.

Rules run in tiers (environment -> links -> database -> device events -> outcomes); later tiers see what
fired earlier. Every action names a command in commands.COMMANDS; nothing here ever runs one. No I/O and
no clock: `now` is injected, so evaluation is deterministic and testable from fixtures.
"""
import re

import paths  # noqa: F401  (puts zones/dbmanager on the path)
import dongle

SEVERITY_RANK = {'bad': 0, 'warn': 1, 'info': 2}
WINDOW = dict(tag=15 * 60, nack=10 * 60, show_start=5 * 60, port=2 * 60, job=30 * 60, flag=30 * 60, resolved=60)
ZONE_TYPES = {1: 'preshow', 2: 'desert', 3: 'pool', 4: 'mainshow', 5: 'reset'}
ZONE_ERRORS = {0: '', 1: 'zone config invalid', 2: 'database empty', 3: 'NFC reader not found', 4: 'radio init failed',
               5: 'update: out of memory', 6: 'update: CRC mismatch', 7: 'update: invalid data',
               8: 'update: flash commit failed', 9: 'update: timed out', 10: 'zone parameters missing/invalid',
               11: 'sensor not found'}
DONGLE_FIRMWARE = dongle.PAIRING.version          # the last relay-dongle build; the installed station runs it
WORKSTATION_FIRMWARE = dongle.WORKSTATION.version  # what "Write the Workstation firmware" puts on a spare board
RX_GAIN_FLOOR = 'desert-2.4.0 / tagplate-2.4.0 / pool-3.2.0 / preshow-3.3.0'
LOCK_APPS = {'.lock': 'the Pairing station app', '.flasher.lock': 'the Cube USB flasher',
             '.zonedb.lock': 'the Zone Database Manager', '.mainshow.lock': 'the Mainshow controller app'}
FLASH_COMMANDS = ('cube.flash_firmware', 'zone.flash', 'zone.flash_force', 'zone.update_db_usb', 'dongle.flash', 'dongle.flash_force',
                  'pool.flash_firmware', 'pool.assign_radio_id', 'zone.detect')
AIR_COMMANDS = ('zones.update', 'zones.update_all', 'zones.reboot', 'zones.set_rx_gain', 'zones.identify', 'zones.query',
                'zones.request_log', 'zones.walkaround')
# A rule that fires silences these rules for the same scope (the surviving card carries the actions).
SUPERSEDES = {
    'tag.known_zone_behind': {'zone.db_behind'},
    'tag.known_unpublished': {'zone.local_differs'},
    'zone.partitions_missing': {'zone.config_invalid', 'zone.error', 'zone.db_behind', 'zone.db_ahead'},
    'zone.nfc_down': {'zone.error', 'zone.nfc_fast_fail'},
    'station.disconnected': {'station.nfc_down', 'station.wrong_channel', 'station.no_zone_support'},
    'station.wrong_channel': {'station.no_zone_support'},
    'zone.unpublished': {'zone.local_differs', 'zone.db_behind', 'zone.db_ahead', 'sync.publish_pending'},
    'zone.cache_inconsistent': {'zone.local_differs', 'sync.publish_pending'},
    'tools.esptool': {'build.stale'},
}


# ---------------------------------------------------------------------- helpers
def action(id, label, command, args=None, kind='safe', long=False):
    return dict(id=id, label=label, command=command, args=dict(args or {}), kind=kind, needs_confirm=kind == 'destructive', long=long)


def evidence(source, text, at=None):
    return dict(source=source, text=text, at=at)


def make(rule, scope, severity, title, know, why='', check='', actions=(), evidence=(), key=None, device=None, fired_at=0):
    id = f'{rule}:{scope}' + (f':{key}' if key else '')
    if device is None and scope.startswith(('mac:', 'zone:')):
        device = scope.split(':', 1)[1]
    return dict(id=id, rule=rule, severity=severity, scope=scope, device=device, title=title, know=know, why=why,
                check=check, evidence=list(evidence), actions=list(actions), fired_at=fired_at)


def when(at):
    """Compact relative description used in texts; `at` is an epoch or None."""
    return 'unknown time' if not at else f'{int(at)}'


def ago(now, at):
    if at is None:
        return 'never'
    seconds = max(0, now - at)
    if seconds < 90:
        return f'{seconds:.0f} s ago'
    if seconds < 3600:
        return f'{seconds / 60:.0f} min ago'
    return f'{seconds / 3600:.1f} h ago'


def norm_uid(uid):
    return (uid or '').upper()


def classify_zone(zone, published):
    """ZoneRegistry.classify, for registry rows without a state (no station session)."""
    if not (published or {}).get('version'):
        return 'unpublished'
    if zone.get('db_version') == published['version'] and zone.get('db_crc') == published['crc']:
        return 'current'
    if zone.get('staging_version') == published['version'] and zone.get('staging_total'):
        return 'updating'
    if (zone.get('db_version') or 0) < published['version']:
        return 'behind'
    return 'ahead'


class Ctx:
    def __init__(self, sections, now, dismissed):
        self.s, self.now, self.dismissed = sections or {}, now, dismissed or set()
        self.devices = list(self.s.get('devices') or [])
        self.sessions = dict(self.s.get('sessions') or {})
        inv = self.s.get('inventory') or {}
        self.inv = inv
        self.rows = list(inv.get('rows') or [])
        self.by_mac = {r['mac']: r for r in self.rows}
        self.by_uid = {norm_uid(r.get('uid')): r for r in self.rows if r.get('uid')}
        self.by_pending = {norm_uid(r.get('pending_uid')): r for r in self.rows if r.get('pending_uid')}
        self.by_number = {r['cube_id']: r for r in self.rows if r.get('cube_id') is not None}
        self.published = inv.get('published') or dict(version=0, hash='', count=0, crc=0)
        records = inv.get('published_records')
        self.membership_known = records is not None
        self.published_uids = {norm_uid(r[1]): r for r in (records or [])}
        self.local_differs = bool(inv.get('local_differs'))
        self.published_error = inv.get('published_error')
        reg = self.s.get('registry') or {}
        self.registry = reg
        self.reg_zones = {z['mac']: z for z in (reg.get('zones') or [])} if reg.get('present') else {}
        if not self.reg_zones:
            for z in inv.get('zones') or []:
                z = dict(z)
                z.setdefault('state', classify_zone(z, self.published))
                age = None if z.get('last_seen_epoch') is None else max(0, now - z['last_seen_epoch'])
                z.setdefault('age_s', age)
                z.setdefault('in_range', False)
                z.setdefault('error_text', ZONE_ERRORS.get(z.get('last_error') or 0, ''))
                self.reg_zones[z['mac']] = z
        self.station = self.s.get('station') or {}
        self.sync = self.s.get('sync') or {}
        self.builds = self.s.get('builds') or {}
        self.locks = self.s.get('locks') or {}
        self.jobs = list(self.s.get('jobs') or [])
        self.show = self.s.get('show') or {}
        self.settings = self.s.get('settings') or {}
        self.autoupdate = self.s.get('autoupdate') or {}
        self.auto_firmware_usb = bool(self.settings.get('auto_firmware_usb'))
        self.fired = set()
        self.devices_by_mac = {d['mac']: d for d in self.devices if d.get('mac')}
        self.usb_zone_devices = [d for d in self.devices if d.get('role') == 'zone' and d.get('mac')]
        self.station_ok = bool(self.station.get('present') and self.station.get('connected'))
        self.relay_ok = self.station_ok and bool(self.station.get('zone_support'))
        self.esptool_ok = (self.builds.get('tools') or {}).get('esptool_ok', True) is not False

    def usb_device(self, mac):
        return self.devices_by_mac.get(mac)

    def session(self, mac):
        d = self.usb_device(mac)
        return self.sessions.get(d['id']) if d else None

    def zone_name(self, mac):
        z = self.reg_zones.get(mac) or {}
        s = self.session(mac) or {}
        report = s.get('report') or {}
        return report.get('name') or z.get('name') or mac

    def zone_db_version(self, mac):
        """(version, crc, source, at) from the freshest evidence: USB report first, then the registry row."""
        s = self.session(mac) or {}
        report = s.get('report') or {}
        if report.get('db_version') is not None:
            return report['db_version'], report.get('db_crc'), f'USB "?" report on {(self.usb_device(mac) or {}).get("port")}', s.get('last_rx')
        z = self.reg_zones.get(mac)
        if z and z.get('db_version') is not None:
            source = 'radio status' if z.get('source') == 'radio' else f'{z.get("source") or "registry"} record'
            return z['db_version'], z.get('db_crc'), f'{source} {ago(self.now, z.get("last_seen_epoch"))}', z.get('last_seen_epoch')
        return None, None, 'no report', None

    def zone_update_actions(self, mac):
        out = []
        d = self.usb_device(mac)
        if d and d.get('candidate') and d.get('state') not in ('job',):
            out.append(action('usb', 'Update database over USB', 'zone.update_db_usb', dict(device=d['id']), 'hardware'))
        z = self.reg_zones.get(mac) or {}
        if self.relay_ok and z.get('in_range'):
            out.append(action('air', 'Update database over the air', 'zones.update', dict(mac=mac), 'hardware'))
        elif self.relay_ok:
            out.append(action('query', 'Query zones over the air', 'zones.query'))
        return out

    def published_text(self):
        p = self.published
        who = f' by {p["published_by"]}' if p.get('published_by') else ''
        at = f' on {p["published_at"][:16].replace("T", " ")}' if p.get('published_at') else ''
        return f'v{p["version"]} ({p.get("count", 0)} records, published{at}{who})' if p.get('version') else 'nothing published'


# ---------------------------------------------------------------------- tier 0: environment
def rule_tools(ctx):
    tools = ctx.builds.get('tools') or {}
    if tools.get('esptool_ok') is False:
        yield make('tools.esptool', 'global', 'bad', 'Flashing tool is not working',
                   f'esptool did not answer as version 5.3.1: {tools.get("esptool_text") or "no output"}.',
                   'Every cube, zone and dongle flash will refuse until the tool runs.',
                   'Run Setup.command again (docs/SETUP.md §2) and re-check.',
                   [action('recheck', 'Check the flashing tool again', 'tools.check'),
                    action('docs', 'Open the setup guide', 'docs.open', dict(path='docs/SETUP.md'))],
                   [evidence('tools', tools.get('esptool_text') or 'esptool check failed')])
    if tools and not tools.get('packaged') and (not tools.get('arduino_cli') or tools.get('core_ok') is False):
        missing = 'arduino-cli was not found' if not tools.get('arduino_cli') else 'the ESP32 core 3.3.11 directory is missing'
        yield make('tools.arduino', 'global', 'warn', 'Firmware builds are unavailable',
                   f'{missing}. Flashing existing verified builds still works.',
                   'Rebuilding cube, zone or dongle firmware needs Arduino IDE 2 (bundled CLI) or arduino-cli with ESP32 core 3.3.11.',
                   'docs/SETUP.md §6 lists the install commands.',
                   [action('docs', 'Open the setup guide', 'docs.open', dict(path='docs/SETUP.md'))],
                   [evidence('tools', f'arduino_cli={tools.get("arduino_cli")} core_ok={tools.get("core_ok")}')])


def rule_builds(ctx):
    """Stale builds the automatic builder has queued or is building are its business; a failed (or tool-less)
    automatic build, or auto_build off, raises the card as before."""
    tools = ctx.builds.get('tools') or {}
    builder = bool(ctx.settings.get('auto_build') and tools.get('arduino_cli') and tools.get('core_ok') is not False)
    auto = {b['target']: (b.get('state'), b.get('reason')) for b in ctx.autoupdate.get('builds') or [] if b.get('target')}

    def handled(target):
        return builder and auto.get(target, (None,))[0] in ('queued', 'building')

    def failed(target, know):
        state, reason = auto.get(target, (None, None))
        return f'{know} Automatic build: {reason}' if state in ('failed', 'no_tools') and reason else know

    cube = ctx.builds.get('cube') or {}
    if cube.get('error') and not handled('cube'):
        yield make('build.stale', 'global', 'warn', f'Cube firmware build needs attention: {cube["error"]}',
                   failed('cube', f'flashing_station/build/manifest.json: {cube["error"]} (expected {cube.get("version")}).'),
                   'The cube flasher refuses to write until the manifest, binaries and source agree. Never hand-edit hashes.',
                   'Rebuild (needs Arduino tools) or restore the verified build files from git.',
                   [action('build', 'Rebuild the cube firmware', 'build.cube', long=True)],
                   [evidence('manifest', cube['error'])], key='cube')
    for sketch, info in (ctx.builds.get('zones') or {}).items():
        if info.get('error') and not handled(f'zone:{sketch}'):
            yield make('build.stale', 'global', 'info', f'{sketch} firmware: {info["error"]}',
                       failed(f'zone:{sketch}', f'zones/build/{sketch}/manifest.json: {info["error"]}.'),
                       'Flashing that zone type needs a verified build.',
                       'Rebuild it (needs Arduino tools).',
                       [action('build', f'Build {sketch}', 'build.zone', dict(sketch=sketch), long=True)],
                       [evidence('manifest', info['error'])], key=sketch)
    for name, label in (('workstation', 'Workstation'), ('mainshow', 'Mainshow controller')):
        info = ctx.builds.get(name) or {}
        if info.get('state') in ('missing', 'stale') and not handled(name):
            yield make('build.stale', 'global', 'info', f'{label} firmware build is {info["state"]}',
                       failed(name, f'The {label} build ({info.get("version")}) is {info["state"]}: a source is newer than the build, or nothing was built.'),
                       'Flashing a dongle or controller builds it first, which takes a few minutes.',
                       'Build it now to have it ready.',
                       [action('build', f'Build the {label} firmware', 'build.dongle', dict(firmware=name), long=True)],
                       [evidence('build', f'{name}: {info["state"]}')], key=name)


def rule_locks(ctx):
    held = [s for s, h in ctx.locks.items() if h and s in LOCK_APPS]
    if held:
        names = ', '.join(LOCK_APPS[s] for s in held)
        yield make('apps.legacy_open', 'global', 'info', f'Another app is open on this database: {names}',
                   f'Instance lock(s) {", ".join(held)} are held by another process.',
                   'Web downloads are not applied while the pairing or cube-flasher app runs, and that app may own the station port.',
                   'Close the other app when you want the console to do that work.',
                   [], [evidence('locks', ', '.join(held))])


def rule_ports(ctx):
    for d in ctx.devices:
        if d.get('state') == 'foreign':
            held = [LOCK_APPS[s] for s, h in ctx.locks.items() if h and s in LOCK_APPS]
            holder = ('probably ' + ' or '.join(held)) if held else 'a tool without an instance lock (zone flasher, calibration, a bench test, or a serial monitor)'
            yield make('port.owned', f'port:{d["port"]}', 'warn', f'{d["port"]} is owned by another application',
                       f'{d.get("error") or "The port refused to open"}. Likely holder: {holder}.',
                       'The console cannot identify or use the board until the port is free.',
                       'Close the other application, then probe again.',
                       [action('retry', 'Probe the port again', 'device.probe', dict(device=d['id']))],
                       [evidence('usb', d.get('error') or 'port busy')], device=d['id'])


# ---------------------------------------------------------------------- tier 1: links
def rule_station(ctx):
    st = ctx.station
    station_devices = [d for d in ctx.devices if d.get('role') == 'workstation']
    if station_devices and not st.get('present'):
        d = station_devices[0]
        reason = d.get('error') or 'no session is open'
        yield make('station.disconnected', 'station', 'bad', 'Pairing station is plugged in but not connected',
                   f'{d.get("port")} identified as {d.get("firmware") or "a station"}; {reason}.',
                   'Registration, discovery and zone updates over the air need the station link.',
                   'Reconnect; nothing is resent automatically.',
                   [action('connect', 'Connect the station', 'device.connect', dict(device=d['id']))],
                   [evidence('usb', reason)], device=d['id'])
        return
    if not st.get('present'):
        return
    device = st.get('device')
    if not st.get('connected'):
        reason = st.get('last_disconnect') or st.get('message') or 'no hello yet'
        yield make('station.disconnected', 'station', 'bad', 'Station link is not connected',
                   f'{reason}. The console re-handshakes every 3 s and never replays an interrupted operation.',
                   'Registration and zone updates over the air are unavailable until the station answers.',
                   'If it stays silent, unplug and replug the station; check for a reboot loop in the console.',
                   [action('reconnect', 'Reconnect the station', 'device.probe', dict(device=device))],
                   [evidence('station', reason)], device=device)
        return
    hello = st.get('hello') or {}
    if hello.get('channel') not in (None, 2):
        yield make('station.wrong_channel', 'station', 'bad', f'Station is on channel {hello.get("channel")}; cubes and zones use 2',
                   f'hello reported channel {hello.get("channel")} from firmware {hello.get("firmware")}.',
                   'On another channel it cannot reach any cube or zone.',
                   'This is compiled into the firmware: reflash the board with the maintained Workstation build.',
                   [action('flash', 'Write the Workstation firmware', 'dongle.flash', dict(device=device, firmware='workstation'), 'hardware')]
                   if hello.get('mac') != '3C:0F:02:AD:83:24' else [],
                   [evidence('hello', f'channel={hello.get("channel")}')], device=device)
    firmware = str(hello.get('firmware') or '')
    if not st.get('zone_support'):
        yield make('station.no_zone_support', 'station', 'warn', 'Station firmware has no zone support',
                   f'hello from {hello.get("firmware")} reports no zone relay (needs a zone relay: {WORKSTATION_FIRMWARE} or {DONGLE_FIRMWARE}).',
                   'Zone database updates, queries and RX gain changes over the air are unavailable.',
                   'Reflash the pairing station (or use a separate Workstation) with the Workstation firmware.',
                   [action('flash', 'Write the Workstation firmware', 'dongle.flash', dict(device=device, firmware='workstation'), 'hardware')]
                   if hello.get('mac') != '3C:0F:02:AD:83:24' else
                   [action('docs', 'Open the zones guide', 'docs.open', dict(path='zones/README.md'))],
                   [evidence('hello', f'firmware={hello.get("firmware")} zones={hello.get("zones")}')], device=device)
    elif dongle.family(hello) in ('pairing', 'workstation') and not dongle.current(hello):
        # A legacy General Radio is left alone: it is superseded, not out of date within its family.
        current = dongle.CURRENT[dongle.family(hello)]
        protected = hello.get('mac') == '3C:0F:02:AD:83:24'
        on_usb = any(d.get('id') == device and d.get('state') != 'protected' for d in ctx.devices)
        auto = ctx.auto_firmware_usb and on_usb and not protected
        yield make('dongle.old', 'station', 'warn', f'Relay firmware {firmware} is older than {current}',
                   f'hello reports {firmware}. ' + ('1.7 adds signal strength, 1.8 RX gain control.' if current == DONGLE_FIRMWARE
                                                    else 'The Workstation build on this computer is newer.'),
                   'Set RX gain over the air needs 1.8; the signal column needs 1.7.' if current == DONGLE_FIRMWARE
                   else 'Newer Workstation builds carry protocol fixes the console expects.',
                   f'It will be upgraded automatically to {WORKSTATION_FIRMWARE} over USB once the console is idle '
                   '(Settings › Automatic updates).' if auto else 'Reflash the board with the current Workstation firmware.',
                   [] if auto or protected else
                   [action('flash', 'Write the Workstation firmware', 'dongle.flash', dict(device=device, firmware='workstation'), 'hardware')],
                   [evidence('hello', firmware)], device=device)
    feedback = st.get('feedback') or {}
    nfc_ok = hello.get('nfc_ok', True) and st.get('reader_ok', True)
    if not st.get('dongle') and (not nfc_ok or feedback.get('title') == 'NFC READER NOT RESPONDING'):
        status = hello.get('nfc_i2c_status')
        if status == 2:
            meaning = 'I²C status 2 = address NACK: the reader is not answering at its address (wiring, I²C mode switch, power)'
        elif status == 5:
            meaning = 'I²C status 5 = bus timeout: a line is held low (power-cycle the reader and the station together)'
        else:
            meaning = f'I²C status {status}'
        busy = bool(st.get('mode'))
        actions = [action('status', 'Read the reader status', 'station.nfc_status'),
                   action('docs', 'Open the I²C notes', 'docs.open', dict(path='pairing_station/I2C_DEBUG.md'))]
        if not busy:
            actions.insert(0, action('recover', 'Try a bus clear and re-init', 'station.nfc_recover', kind='hardware'))
        yield make('station.nfc_down', 'station', 'bad', 'Station NFC reader is not responding',
                   f'{meaning}. {feedback.get("detail") or ""}'.strip(),
                   'Registration is disabled; discovery, saved-mapping transmission and LED tests still work.',
                   'Check SDA 4 / SCL 3, the reader in I²C mode, VCC from the station 5 V; the PN532 stays powered '
                   'across resets and can hold the bus, so power-cycle reader and station together.'
                   + (' Stop the current operation first to run a recovery.' if busy else ''),
                   actions, [evidence('hello', f'nfc_ok={hello.get("nfc_ok")} nfc_i2c_status={status}')], device=device)


def rule_radio(ctx):
    """A Workstation whose driver died, or holding a lamp/cue that nothing in range can be hearing.
    A legacy pairing station is the same kind but never reports `fatal` or holds anything, so nothing fires."""
    for device_id, s in ctx.sessions.items():
        if s.get('kind') != 'workstation':
            continue
        d = next((d for d in ctx.devices if d.get('id') == device_id), None) or {}
        scope = f'port:{d.get("port") or device_id}'
        if s.get('fatal'):
            yield make('radio.fatal', scope, 'bad', f'{s.get("label") or "Workstation"}: its radio driver stopped answering',
                       f'The board reported "{s["fatal"]}": three sends in a row got no result from the Wi-Fi driver, so it '
                       'refuses every radio operation until it is power-cycled. Its own leases release anything it held.',
                       'Cube colours, show start, zone relay, pool lamp and preshow cue through this board are all unavailable.',
                       'Unplug and replug the board (a watchdog reset is not enough), then probe it again.',
                       [action('probe', 'Probe again after replugging', 'device.probe', dict(device=device_id))],
                       [evidence('radio', s['fatal'], s.get('last_rx'))], device=device_id)
            continue
        pool = s.get('pool') or {}
        if s.get('pool_held') and not pool.get('central_mac'):
            yield make('radio.held_without_beacon', scope, 'warn', f'Pool lamp {s["pool_held"]} is held but no pool central is heard',
                       'The radio is broadcasting the member with no PoolCentral beacon latched: nothing has confirmed it lit.',
                       'Either the central is off or out of range, or it is on another channel.',
                       'Check the pool central; release the lamp if this was a test.',
                       [action('release', 'Release the lamp', 'radio.pool_release', dict(device=device_id))],
                       [evidence('radio', f'central_mac={pool.get("central_mac") or "none"} radio_mask={pool.get("radio_mask")}')],
                       key='pool', device=device_id)
        preshow = s.get('preshow') or {}
        if s.get('preshow_held') and preshow.get('mode') == 'legacy':
            yield make('radio.held_without_beacon', scope, 'warn', f'Preshow cue {s["preshow_held"]} is held but no media bridge is heard',
                       'No PreshowBridge beacon has ever been heard, so the cue also goes out as the pre-2026 2-byte packet, which '
                       'nothing can acknowledge.',
                       'TouchDesigner may never have received the cue, and nothing will report it.',
                       'Check the media bridge (powered, on channel 2, its beacon reaching this room); turn the cue off if this was a test.',
                       [action('release', 'Turn the cue off', 'radio.preshow_release', dict(device=device_id))],
                       [evidence('radio', f'mode={preshow.get("mode")} bridge_mac={preshow.get("bridge_mac") or "none"}')],
                       key='preshow', device=device_id)


def rule_mainshow(ctx):
    show = ctx.show
    if not show.get('present'):
        return
    problem = show.get('problem')
    if problem:
        device = show.get('device')
        rule = 'mainshow.wrong_firmware' if 'not the Mainshow controller' in problem or 'No reply' in problem else \
            'mainshow.channel' if 'channel' in problem else 'mainshow.radio'
        actions = [action('flash', 'Write the Mainshow controller firmware', 'dongle.flash', dict(device=device, firmware='mainshow'), 'hardware')]
        yield make(rule, f'mac:{show.get("device")}', 'bad', 'Mainshow controller problem', problem,
                   'Mainshow ready / trigger need the controller firmware answering on channel 2.',
                   'Flash the controller firmware onto this board (a spare dongle), then reconnect.', actions,
                   [evidence('mainshow', problem)], device=device)


def rule_sync(ctx):
    sync = ctx.sync
    status = sync.get('status') or {}
    state = status.get('state')
    err = sync.get('last_error') or {}
    # Automatic sync (Settings › Automatic updates): pending uploads, publishes and waiting downloads resolve by
    # themselves, so those cards only show while it is off or after it failed.
    auto = bool(sync.get('auto')) and not err
    retry = 'It retries by itself; Sync now to try at once.' if sync.get('auto') else 'Click Sync to try again.'
    if state == 'signin' or not sync.get('password_known', True):
        yield make('sync.signin', 'sync', 'info', 'Web sync needs the inventory password',
                   'No web inventory password is stored on this computer.',
                   'Without it the console cannot upload registrations or publish the zone database.',
                   'Enter the shared password once; it is stored owner-only outside git.',
                   [action('signin', 'Enter the password', 'sync.signin')], [evidence('sync', 'state=signin')])
    elif state == 'unauthorized' or err.get('kind') == 'unauthorized':
        yield make('sync.unauthorized', 'sync', 'warn', 'The web rejected the stored password',
                   err.get('text') or 'The web answered 401.', 'Nothing syncs until the password is right.',
                   'Enter it again (ask the team if it changed).',
                   [action('signin', 'Enter the password again', 'sync.signin')], [evidence('sync', err.get('text') or 'unauthorized')])
    elif state == 'offline':
        yield make('sync.offline', 'sync', 'info', 'Web inventory unreachable; working locally',
                   'The last status check could not reach the web.', 'Flashing and zone updates use the last pulled database.',
                   'Retry when the network is back.', [action('retry', 'Check again', 'sync.status')], [evidence('sync', 'offline')])
    elif state == 'error':
        yield make('sync.error', 'sync', 'warn', 'Web sync problem', status.get('message') or 'The web could not answer usefully.',
                   'Sync is not confirmed.', retry, [action('retry', 'Sync now', 'sync.run')],
                   [evidence('sync', status.get('message') or 'error')])
    if err.get('kind') == 'busy':
        yield make('sync.busy', 'sync', 'info', 'Another app is syncing right now', err.get('text') or '', '', 'Wait and retry.', [],
                   [evidence('sync', err.get('text') or 'busy')])
    if err.get('kind') == 'after_push':
        yield make('sync.interrupted', 'sync', 'warn', 'Sync was interrupted while uploading',
                   err.get('text') or '', 'Nothing is lost: the next Sync checks what the web received.',
                   'Sync again.', [action('retry', 'Sync now', 'sync.run')], [evidence('sync', err.get('text') or '')])
    if status.get('zone_publish') and state == 'ok' and not auto:
        n = status.get('inventory_up') or 0
        yield make('sync.publish_pending', 'sync', 'warn', 'Cube mappings changed but the zone database was not published',
                   f'{n} inventory change(s) to upload; the published database ({ctx.published_text()}) does not contain them.',
                   'Zones only ever receive the published image, so new registrations stay unknown at every plate.',
                   'Sync uploads the changes and publishes the next version (allocated by the web, never locally).',
                   [action('sync', 'Sync & publish', 'sync.run')], [evidence('sync', f'zone_publish=1 inventory_up={n}')])
    if status.get('zone_pull') and state == 'ok':
        yield make('sync.pull_pending', 'sync', 'warn', f'The web has a newer zone database v{status.get("web_version")}',
                   f'This computer holds v{status.get("local_version")}; the web publishes v{status.get("web_version")}.',
                   'Flashing from the older local copy would put an outdated database on a zone.',
                   'Pull it with Sync.', [action('sync', 'Sync (pulls the database)', 'sync.run')],
                   [evidence('sync', f'web v{status.get("web_version")} local v{status.get("local_version")}')])
    if status.get('waiting') and not status.get('inventory_down') and not auto:
        held = [LOCK_APPS[s] for s, h in ctx.locks.items() if h and s in LOCK_APPS] or ['another app']
        yield make('sync.waiting', 'sync', 'info', f'{status["waiting"]} downloaded change(s) are waiting to be applied',
                   f'They wait for {", ".join(held)} to be idle.', 'The local inventory is behind the web until then.',
                   'Close the other app or stop the operation, then Sync.',
                   [action('apply', 'Apply now', 'sync.download')], [evidence('sync', f'waiting={status["waiting"]}')])
    last = sync.get('last_result') or {}
    lost = ((last.get('sync') or {}).get('lost')) or []
    for entry in lost[:6]:
        mac = entry.get('mac') or ''
        row = ctx.by_mac.get(mac, {})
        actions = []
        if row.get('cube_id') is None:
            actions.append(action('rename', 'Assign a number', 'inventory.rename', dict(mac=mac, number=ctx.inv.get('suggested_number'))))
        if not row.get('uid') and ctx.station_ok:
            actions.append(action('register', 'Register a tag at the station', 'pairing.register', dict(mac=mac), 'hardware'))
        yield make('sync.lost', f'mac:{mac}', 'warn', 'A newer change elsewhere took this device\'s number or tag',
                   entry.get('text') or str(entry), 'A cube without a number or tag is left out of the zone database.',
                   'Assign the physical label number or register again, then Sync.', actions,
                   [evidence('sync', entry.get('text') or str(entry))], key='lost')
    if last.get('zone_error'):
        yield make('sync.zone_error', 'sync', 'warn', 'The inventory synced but the zone database was not published',
                   str(last['zone_error']), 'Zones cannot receive the new mappings yet.', retry,
                   [action('sync', 'Sync again', 'sync.run')], [evidence('sync', str(last['zone_error']))])


# ---------------------------------------------------------------------- tier 2: database
def rule_zone_db_global(ctx):
    p = ctx.published
    if not ctx.inv:
        return
    if not p.get('version'):
        if ctx.published_error and 'inconsistent' in ctx.published_error:
            yield make('zone.cache_inconsistent', 'global', 'bad', 'Cached zone database is inconsistent',
                       ctx.published_error, 'Nothing can be flashed or distributed from a broken cache.',
                       'Pull it again from the web.', [action('pull', 'Pull the zone database', 'zone.pull')],
                       [evidence('store', ctx.published_error)])
        else:
            yield make('zone.unpublished', 'global', 'bad', 'No zone database has been published yet',
                       ctx.published_error or 'metadata has no zone_db_version.',
                       'Zone boards cannot be flashed with a database, and no plate knows any cube.',
                       'Sync: it uploads the inventory and publishes the first version (allocated by the web).',
                       [action('sync', 'Sync & publish', 'sync.run')], [evidence('store', ctx.published_error or 'version 0')])
        return
    if ctx.published_error and 'inconsistent' in ctx.published_error:
        yield make('zone.cache_inconsistent', 'global', 'bad', 'Cached zone database is inconsistent', ctx.published_error,
                   'Nothing can be flashed or distributed from a broken cache.', 'Pull it again from the web.',
                   [action('pull', 'Pull the zone database', 'zone.pull')], [evidence('store', ctx.published_error)])
    elif ctx.local_differs:
        yield make('zone.local_differs', 'global', 'warn', 'Local cube mappings differ from the published zone database',
                   f'This computer\'s committed mappings no longer match {ctx.published_text()}.',
                   'Zones only ever receive the published image: a cube registered here stays unknown at every plate until a new version is published.',
                   'Sync uploads the mappings and publishes the next version.',
                   [action('sync', 'Sync & publish', 'sync.run')], [evidence('store', 'local_differs')])


def rule_zone_db_each(ctx):
    far_behind = []
    for mac, z in ctx.reg_zones.items():
        state = z.get('state')
        name = ctx.zone_name(mac)
        version, crc, source, at = ctx.zone_db_version(mac)
        if state == 'behind' and not (z.get('in_range') or ctx.usb_device(mac)):
            far_behind.append((name, version))
            continue
        if state == 'behind':
            yield make('zone.db_behind', f'zone:{mac}', 'warn', f'Zone "{name}" holds database v{version}; published is v{ctx.published["version"]}',
                       f'{source}: v{version}' + (f' (CRC {crc:08X})' if isinstance(crc, int) else '') +
                       f'. Published: {ctx.published_text()}.' + (' In range.' if z.get('in_range') else ' Not heard over the radio recently.'),
                       'Cubes registered after that version are unknown at this plate; it will not send them a zone colour.',
                       'Update over USB (plug it in) or over the air while it is in range; the zone confirms with the new version and CRC.',
                       ctx.zone_update_actions(mac), [evidence(source, f'db_version={version}', at)], fired_at=at or 0)
        elif state == 'ahead':
            yield make('zone.db_ahead', f'zone:{mac}', 'bad', f'Zone "{name}" holds v{version}, above this computer\'s v{ctx.published["version"]} (or the same version with different content)',
                       f'{source}: v{version}. Local publication: {ctx.published_text()}. Another computer published, or this is a legacy per-computer counter.',
                       'Never roll a zone back. The web allocates versions above anything seen, so publishing lifts every zone.',
                       'Sync (pulls the web version); if the zone still differs, the next Sync publishes above it.',
                       [action('sync', 'Sync', 'sync.run')], [evidence(source, f'db_version={version} crc={crc}', at)], fired_at=at or 0)
        elif state == 'updating':
            yield make('zone.db_updating', f'zone:{mac}', 'info', f'Zone "{name}" is receiving v{z.get("staging_version")}',
                       f'chunks {z.get("staging_chunks")}/{z.get("staging_total")} staged. A partial update is discarded after 60 s without chunks.',
                       '', 'Stay in range until the zone reports the new version.', [], [evidence(source, 'updating', at)], fired_at=at or 0)
    if far_behind:
        names = ', '.join(f'{n} (v{v})' for n, v in far_behind[:6]) + (' …' if len(far_behind) > 6 else '')
        yield make('zone.db_behind_many', 'global', 'info', f'{len(far_behind)} known zone(s) out of range hold an older database',
                   f'{names}. Published: {ctx.published_text()}. None of them has answered over the radio in the last 20 s.',
                   'They keep treating cubes registered since their version as unknown until updated.',
                   'Walk the dongle within range with Auto-update all on, or plug each plate in and update it over USB.',
                   [action('walk', 'Turn on Auto-update all', 'zones.walkaround', dict(enabled=True))] if ctx.relay_ok else [],
                   [evidence('registry', names)])
    message = ctx.registry.get('message') or ''
    m = re.match(r'Publishing v(\d+) timed out; not confirmed: (.*)', message)
    if m:
        for mac in [x.strip() for x in m[2].split(',') if ':' in x]:
            name = ctx.zone_name(mac)
            yield make('zone.publish_timeout', f'zone:{mac}', 'warn', f'Zone "{name}" did not confirm database v{m[1]}',
                       f'Announce and chunks were sent (radio "delivered" is the station\'s ACK only); the zone never reported v{m[1]} with the published CRC.',
                       'Delivered is not acknowledged: the zone may have lost chunks or left range.',
                       'Retry over the air closer to it, or update it over USB.',
                       ctx.zone_update_actions(mac), [evidence('registry', message)])


def rule_zone_firmware(ctx):
    """Zones heard over the air with firmware older than the build (autoupdate.air.firmware): only USB fixes that.
    Grouped like zone.db_behind_many; boards already on USB are the automatic-upgrade panel's."""
    air = (ctx.autoupdate.get('air') or {}).get('firmware') or []
    behind = [f for f in air if f.get('kind') == 'zone' and f.get('mac') and not ctx.usb_device(f['mac'])]
    pool = [f for f in behind if str(f.get('current') or '').startswith('pool-')]
    plates = [f for f in behind if f not in pool]

    def names(rows):
        return ', '.join(f'{f.get("label") or f["mac"]} ({f.get("current")} → {f.get("version")})' for f in rows[:6]) + \
            (' …' if len(rows) > 6 else '')
    if plates:
        auto = ' (automatically)' if ctx.auto_firmware_usb else ''
        yield make('zone.fw_behind', 'global', 'info', f'{len(plates)} zone(s) run firmware older than the build',
                   f'Zone firmware older than the build: {names(plates)}.',
                   'Firmware is only upgraded over USB; the zone database still updates over the air.',
                   f'Plug it in over USB to upgrade it{auto}; it keeps its identity.', [],
                   [evidence('radio', names(plates))], key='plates')
    if pool:
        yield make('zone.fw_behind', 'global', 'info', f'{len(pool)} pool radio(s) run firmware older than the build',
                   f'Zone firmware older than the build: {names(pool)}.',
                   'The pool radios and the pool central are a matched set: a partial upgrade can leave the lights unanswered.',
                   'Upgrade the pool radios and the pool central together by hand (they are never upgraded automatically).', [],
                   [evidence('radio', names(pool))], key='pool')


# ---------------------------------------------------------------------- tier 3: device events
def rule_tags(ctx):
    for d in ctx.usb_zone_devices:
        s = ctx.sessions.get(d['id']) or {}
        mac = d['mac']
        name = ctx.zone_name(mac)
        version, crc, source, at = ctx.zone_db_version(mac)
        seen = set()
        for entry in s.get('history') or []:
            if entry.get('state') != 'unknown tag' or ctx.now - (entry.get('time') or 0) > WINDOW['tag']:
                continue
            uid = norm_uid(entry.get('uid'))
            if uid in seen:
                continue
            seen.add(uid)
            ev = [evidence(f'plate {name} (USB)', f'EVT TAG uid={uid} cube=0 (UNKNOWN CUBE)', entry.get('time'))]
            fired = entry.get('time') or 0
            row = ctx.by_uid.get(uid)
            pending = ctx.by_pending.get(uid)
            if row and row.get('cube_id') is not None:
                number = row['cube_id']
                in_published = uid in ctx.published_uids if ctx.membership_known else None
                if in_published or (in_published is None and not ctx.local_differs and ctx.published.get('version')):
                    if version is not None and version >= ctx.published['version'] and crc == ctx.published.get('crc'):
                        yield make('tag.inconsistent', f'zone:{mac}', 'info', f'Plate "{name}" holds the published database yet did not match cube #{number}\'s tag',
                                   f'{source}: v{version} = published v{ctx.published["version"]} with the same CRC, but the plate reported tag {uid} unknown.',
                                   'Possible 4- vs 7-byte uid difference or a stale record read.',
                                   'Run `db` on the plate and compare its record for #%d.' % number,
                                   [action('db', 'List the plate\'s database', 'device.console', dict(device=d['id'], line='db'))], ev, key=uid, fired_at=fired)
                    else:
                        yield make('tag.known_zone_behind', f'zone:{mac}', 'warn', f'Unknown tag on "{name}" is cube #{number} — the plate\'s database is behind',
                                   f'Plate "{name}" ({source}) holds database v{version}; tag {uid} is cube #{number} ({row["mac"]}) in the published {ctx.published_text()}.',
                                   f'Until the plate holds v{ctx.published["version"]} it treats cube #{number} as unknown and sends no zone colour.',
                                   f'After the update a tap should print "FOUND Cube #{number}".',
                                   ctx.zone_update_actions(mac), ev, key=uid, fired_at=fired)
                else:
                    yield make('tag.known_unpublished', f'zone:{mac}', 'warn', f'Unknown tag on "{name}" is cube #{number} — not yet in the published database',
                               f'Tag {uid} is cube #{number} ({row["mac"]}, status {row.get("status")}, updated {row.get("updated_at")}) in this computer\'s inventory, '
                               f'but the published database is {ctx.published_text()} and local mappings differ.',
                               'Zones only ever receive the published image.',
                               'Sync uploads the mapping and publishes the next version (allocated by the web); then update the plate.',
                               [action('sync', 'Sync & publish', 'sync.run')], ev, key=uid, fired_at=fired)
            elif pending:
                number = pending.get('cube_id')
                actions = []
                if ctx.station_ok and not ctx.station.get('mode'):
                    if ctx.station.get('phase') == 'paused':
                        actions.append(action('retry', 'Retry the paused registration', 'pairing.retry', kind='hardware'))
                    actions.append(action('transmit', f'Send the saved mapping to cube #{number}', 'pairing.transmit', dict(macs=[pending['mac']]), 'hardware'))
                yield make('tag.pending_registration', f'zone:{mac}', 'warn', f'Unknown tag on "{name}" is a pending registration for cube #{number}',
                           f'Tag {uid} is the *pending* tag of cube #{number} ({pending["mac"]}): status {pending.get("status")} — "{pending.get("detail")}". '
                           'The cube has not acknowledged, so the mapping is not committed and in no zone database.',
                           'Radio delivery is not acknowledgment; only the cube\'s ACK commits the tag.',
                           'Power the cube, bring it in range of the station and retry the saved registration.', actions, ev, key=uid, fired_at=fired)
            elif row and row.get('cube_id') is None:
                yield make('tag.device_without_number', f'zone:{mac}', 'warn', f'Unknown tag on "{name}" belongs to a device without a number',
                           f'Tag {uid} is on {row["mac"]} whose number is cleared ("{row.get("detail")}").',
                           'Records without a number are left out of the zone database.',
                           'Assign its physical label number, then Sync to publish.',
                           [action('rename', 'Assign a number', 'inventory.rename', dict(mac=row['mac'], number=ctx.inv.get('suggested_number')))],
                           ev, key=uid, fired_at=fired)
            else:
                actions = [action('sync', 'Sync first (another computer may know it)', 'sync.run')]
                if ctx.station_ok:
                    actions.append(action('register', 'Start registration at the pairing station', 'pairing.start_pair', kind='hardware'))
                yield make('tag.unknown_everywhere', f'zone:{mac}', 'info', f'Unknown tag on "{name}" is not in this computer\'s inventory',
                           f'Tag {uid} matches no committed or pending tag here. It may be registered on another computer, or never registered.',
                           'A plate tap is not a station scan: registering needs the tag at the pairing station.',
                           'Sync; if still unknown, register the tag to its cube at the station.', actions, ev, key=uid, fired_at=fired)


def rule_nack(ctx):
    for d in ctx.usb_zone_devices:
        s = ctx.sessions.get(d['id']) or {}
        mac = d['mac']
        name = ctx.zone_name(mac)
        seen = set()
        for entry in s.get('history') or []:
            if entry.get('state') != 'not acknowledged' or ctx.now - (entry.get('time') or 0) > WINDOW['nack']:
                continue
            uid = norm_uid(entry.get('uid'))
            number = entry.get('cube_id')
            plate_mac = (entry.get('mac') or '').upper()
            if (uid, plate_mac) in seen:
                continue
            seen.add((uid, plate_mac))
            row = ctx.by_uid.get(uid) or ctx.by_number.get(number)
            ev = [evidence(f'plate {name} (USB)', f'EVT SENT cube={number} ok=0 / NOT ACKNOWLEDGED', entry.get('time'))]
            fired = entry.get('time') or 0
            if row and plate_mac and row['mac'] != plate_mac:
                yield make('cube.nack_mac_mismatch', f'zone:{mac}', 'warn', f'Plate "{name}" addresses cube #{number} at an old MAC',
                           f'The plate\'s record maps tag {uid} to {plate_mac}; the inventory now says {row["mac"]} (updated {row.get("updated_at")}). The plate is talking to the old board.',
                           'The tag was transferred, and the plate\'s database predates that.',
                           'Sync (publishes the current mapping), then update this plate\'s database.',
                           [action('sync', 'Sync & publish', 'sync.run')] + ctx.zone_update_actions(mac), ev, key=uid, fired_at=fired)
            elif row and row.get('status') in ('not_transmitted', 'unconfirmed', 'awaiting_tag') or \
                    (row and (ctx.session(row['mac']) or {}).get('flags', {}).get('unregistered')):
                actions = [action('transmit', f'Send the saved mapping to cube #{number}', 'pairing.transmit', dict(macs=[row['mac']]), 'hardware')] \
                    if ctx.station_ok and row.get('uid') else []
                yield make('cube.nack_unregistered', f'mac:{row["mac"]}', 'warn', f'Cube #{number} did not acknowledge the plate — it may not hold its ID',
                           f'Inventory status for {row["mac"]} is {row.get("status")} ("{row.get("detail")}"); a cube that has not stored ID #{number} ignores SET_ZONE addressed to it.',
                           'The plate\'s command reached the radio, but the cube did not answer.',
                           'Transmit the saved mapping from the station and watch for the cube\'s ACK.', actions, ev, key=uid, fired_at=fired)
            else:
                age = ctx.station.get('discovered', {}).get(plate_mac or (row or {}).get('mac', ''))
                heard = f'the station heard it {age:.0f} s ago' if isinstance(age, (int, float)) else 'the station has not heard it this session'
                actions = [action('discover', 'Discover cubes', 'pairing.discover')] if ctx.station_ok else []
                if ctx.station_ok and row:
                    actions.append(action('identify', f'Flash cube #{number} to locate it', 'pairing.flash', dict(macs=[row['mac']])))
                yield make('cube.nack_offline', f'zone:{mac}', 'warn', f'Cube #{number} did not acknowledge plate "{name}"',
                           f'The plate delivered SET_ZONE to {plate_mac or "the cube"} without an ESP-NOW ACK; {heard}.',
                           'Likely off, out of range, or not on channel 2. Delivered is not acknowledged.',
                           'Power the cube and tap again; discovery from the station shows whether it answers at all.', actions, ev, key=uid, fired_at=fired)


def rule_zone_health(ctx):
    for d in ctx.usb_zone_devices:
        s = ctx.sessions.get(d['id']) or {}
        mac = d['mac']
        name = ctx.zone_name(mac)
        report = s.get('report') or {}
        tags = {t.get('tag'): t for t in (s.get('tags') or [])}
        if 'zone.partitions_missing' in tags:
            yield make('zone.partitions_missing', f'zone:{mac}', 'bad', f'Board on {d["port"]} runs zone firmware without zone partitions',
                       'It printed "PARTITIONS MISSING: flash with the zone flasher (custom partitions.csv)": identity and database cannot be stored.',
                       'The plate will never know a cube.', 'Flash it fully (firmware + partitions + identity + database).',
                       [action('flash', 'Flash firmware + identity + database', 'zone.flash', dict(device=d['id']), 'hardware')],
                       [evidence('console', tags['zone.partitions_missing'].get('text', ''))])
        if report and not report.get('config_valid'):
            yield make('zone.config_invalid', f'zone:{mac}', 'bad', f'Zone board on {d["port"]} has no valid identity',
                       f'"?" reports ZONE: unconfigured ({report.get("firmware")}). It will not send SET_ZONE to any cube.',
                       'Without a zone type and point the plate does nothing useful.',
                       'Flash it with its zone profile, point and name.',
                       [action('flash', 'Flash identity (and database)', 'zone.flash', dict(device=d['id']), 'hardware')],
                       [evidence('report', 'ZONE: unconfigured')])
        nfc = s.get('nfc')
        if nfc and nfc.get('ok') is False:
            lines = '' if (nfc.get('sda'), nfc.get('scl')) == ('1', '1') else f' I²C lines SDA={nfc.get("sda")} SCL={nfc.get("scl")} (both should read 1).'
            yield make('zone.nfc_down', f'zone:{mac}', 'bad', f'NFC reader on "{name}" is not responding',
                       f'NFC: ok=0, {nfc.get("recoveries", 0)} automatic recovery attempt(s) so far.{lines} Pins {nfc.get("pins") or "4/3"}.',
                       'No taps will be read; the plate\'s radio still works.',
                       'Reader wired to SDA 4 / SCL 3 (XIAO replacement plates: D4/D5 = GPIO 6/7), powered from 5 V, in I²C mode. '
                       'The PN532 stays powered across resets and can hold the bus: power-cycle reader and board together. '
                       'SCL held low was traced to the reader/cable side (pairing_station/VALIDATION.md); history in I2C_DEBUG.md.',
                       [action('recover', 'Ask the plate to recover the reader', 'zone.nfc_recover', dict(device=d['id']), 'hardware'),
                        action('status', 'Read the reader status', 'device.console', dict(device=d['id'], line='nfc')),
                        action('docs', 'Open the I²C notes', 'docs.open', dict(path='pairing_station/I2C_DEBUG.md'))],
                       [evidence('NFC line', f'ok=0 sda={nfc.get("sda")} scl={nfc.get("scl")} recoveries={nfc.get("recoveries")}')])
        elif nfc and nfc.get('fast_fail'):
            yield make('zone.nfc_fast_fail', f'zone:{mac}', 'warn', f'NFC reader on "{name}" answers but scan commands fail',
                       f'{nfc.get("fast_fail")} scan command(s) failed on I²C · {nfc.get("polls")} polls, {nfc.get("found")} with a tag.',
                       'Tags may be missed.', 'Check the cable and power; a recovery re-initialises the reader.',
                       [action('recover', 'Recover the reader', 'zone.nfc_recover', dict(device=d['id']), 'hardware')],
                       [evidence('NFC line', f'fast_fail={nfc.get("fast_fail")}')])
        code = report.get('last_error') or 0
        if code and code not in (3,):
            yield from _zone_error(ctx, mac, name, code, d, f'USB "?" report on {d["port"]}')
        preshow = s.get('kind') == 'preshow'
        host = s.get('host') or {}
        media_mode = host.get('mode') or _media_mode(s)
        if preshow and media_mode == 'legacy':
            yield make('preshow.legacy_mode', f'zone:{mac}', 'info', f'Preshow plate "{name}" is in legacy media mode',
                       'No bridge beacon has been heard, so the plate also sends the 2-byte packet the original TouchDesigner bridge reads.',
                       'Expected while the bridge is not updated; cues cannot be acknowledged in this mode (MEDIA LEGACY, not MEDIA FAIL).',
                       'Update the bridge board when convenient; plates and bridge update in either order.',
                       [action('docs', 'Read about the preshow link', 'docs.open', dict(path='zones/README.md'))],
                       [evidence('MEDIA line', 'mode=legacy')])
        if preshow and any(t.get('tag') == 'preshow.media_fail' and ctx.now - (t.get('t') or 0) < WINDOW['nack'] for t in s.get('tags') or []):
            yield make('preshow.media_fail', f'zone:{mac}', 'warn', f'Preshow plate "{name}" reported MEDIA FAIL',
                       f'A bridge was heard (mode {media_mode}) but did not acknowledge a cue within 3 s; bridge_sees_me={host.get("bridge_sees_me")}.',
                       'The cue may not have reached TouchDesigner.', 'Check the bridge board and its range; query its STATUS.',
                       [], [evidence('console', 'MEDIA FAIL')])
        if s.get('kind') == 'pool':
            yield from _pool_rules(ctx, d, s, mac, name)
        if report.get('rx_gain') and report.get('rx_gain_applied') is None:
            yield make('zone.rx_gain_unconfirmed', f'zone:{mac}', 'warn', f'RX gain on "{name}" is stored but the reader did not accept it',
                       f'RXGAIN: stored={report["rx_gain"]}dB applied=? — the PN532 did not take the setting (absent, failing or disabled).',
                       'The reader runs at whatever gain it last accepted.', 'It is applied again when the reader recovers.',
                       [], [evidence('report', f'stored={report["rx_gain"]} applied=?')])


def _media_mode(session):
    return None


def _zone_error(ctx, mac, name, code, d, source):
    text = ZONE_ERRORS.get(code, f'error {code}')
    usb = d['id'] if d else None
    actions = []
    if code in (1, 10):
        actions = [action('flash', 'Flash identity/parameters', 'zone.flash', dict(device=usb), 'hardware')] if usb else []
    elif code in (2, 6, 7, 9):
        actions = ctx.zone_update_actions(mac)
    elif code in (4, 5):
        actions = ([action('reboot', 'Reboot over the air', 'zones.reboot', dict(mac=mac), 'hardware')] if ctx.relay_ok else []) + \
                  ([action('flash', 'Reflash firmware', 'zone.flash', dict(device=usb), 'hardware')] if usb and code == 4 else [])
    elif code == 8:
        actions = [action('usb', 'Write the database over USB', 'zone.update_db_usb', dict(device=usb), 'hardware')] if usb else []
    elif code == 11:
        actions = []
    why = {1: 'No valid identity: the plate sends nothing to cubes.', 2: 'No records: every tag is unknown.',
           4: 'The radio did not start; nothing is sent or received.', 5: 'The update could not be staged.',
           6: 'Chunks arrived corrupted or the publication is inconsistent.', 7: 'The staged records failed validation.',
           8: 'The zone kept its previous database; the slot may be worn.', 9: 'An announce was heard but chunks were lost (range).',
           10: 'A pool radio needs its slider parameters.', 11: 'The distance sensor was not found (SDA 4 / SCL 3, shared with the PN532).'}.get(code, '')
    severity = 'bad' if code in (1, 2, 4, 8, 11) else 'warn'
    yield make('zone.error', f'zone:{mac}', severity, f'Zone "{name}" reports: {text}', f'{source}: error {code} ({text}).', why,
               'Clear it by fixing the cause; the code persists until the next successful operation.', actions,
               [evidence(source, f'error={code}')], key=str(code))


def _pool_rules(ctx, d, s, mac, name):
    inter = s.get('interaction') or {}
    if inter and inter.get('radio') and inter.get('central_sees_me') is False:
        yield make('pool.central_not_seeing', f'zone:{mac}', 'warn', f'Pool radio "{name}" is not seen by the central controller',
                   f'The radio reports radio=true, central_sees_me=false (last central beacon {inter.get("central_seen_ms")} ms ago, central {inter.get("central_mac") or "unknown"}).',
                   'The radios and the central are a matched set: their protocol versions must agree, and the central must be on and in range.',
                   'Check the central is powered and on channel 2; reflash both together if their versions differ.',
                   [], [evidence('interaction', f'central_sees_me=false central_mac={inter.get("central_mac")}')])
    cal = s.get('calibration')
    if cal is not None and (not cal.get('saved') or cal.get('valid') is False):
        yield make('pool.calibration_missing', f'zone:{mac}', 'warn', f'Pool radio "{name}" has no saved calibration',
                   f'CAL GET: saved={cal.get("saved")} valid={cal.get("valid")} anchors={cal.get("anchors")}.',
                   'Without control points at ticks 1 and 23 the slider cannot map distance to a member.',
                   'Set the control points on the Calibration tab and apply & save.', [], [evidence('CAL GET', f'saved={cal.get("saved")}')])
    if s.get('tune_supported') is False:
        yield make('pool.fw_update', f'zone:{mac}', 'info', f'Pool radio "{name}" runs firmware without tuning support',
                   f'{(s.get("report") or {}).get("firmware")} answers CAL GET but has no TUNE command (before pool-2.8.0).',
                   'Guided recording and filter tuning need pool-2.8.0 or newer.', 'Update the firmware from the Firmware & database tab.',
                   [action('flash', 'Update pool radio firmware', 'pool.flash_firmware', dict(device=d['id']), 'hardware')],
                   [evidence('console', 'no TUNE reply')])
    if any(t.get('tag') == 'pool.vl53_error' for t in s.get('tags') or []):
        yield make('pool.vl53_error', f'zone:{mac}', 'bad', f'Pool radio "{name}": distance sensor not found',
                   'The board printed "[ERROR] VL53L4CD" at boot.', 'No slider readings, so no pool member is ever held.',
                   'Check the sensor wiring on SDA 4 / SCL 3 (shared with the PN532) and its power.', [], [evidence('console', '[ERROR] VL53L4CD')])


def _live(ctx, z, hours=1):
    """A registry row that describes a board still in service: heard recently, in range or on USB."""
    seen = z.get('last_seen_epoch')
    return bool(z.get('in_range') or ctx.usb_device(z['mac']) or (seen and ctx.now - seen < hours * 3600))


def rule_pool_ids(ctx):
    by_point = {}
    for z in ctx.reg_zones.values():
        if z.get('zone_type') == 3 and z.get('point_id') and _live(ctx, z):
            by_point.setdefault(z['point_id'], []).append(z)
    for point, zones in by_point.items():
        if len(zones) > 1:
            macs = sorted(z['mac'] for z in zones)
            actions = []
            for z in zones:
                d = ctx.usb_device(z['mac'])
                if d and d.get('candidate'):
                    free = next((i for i in range(1, 7) if i not in by_point), None)
                    actions.append(action(f'assign-{z["mac"][-5:]}', f'Assign radio id {free or "…"} to {z.get("name") or z["mac"]} (on USB)',
                                          'pool.assign_radio_id', dict(device=d['id'], new_id=free or point), 'hardware'))
            yield make('pool.radio_id_clash', 'global', 'bad', f'Two pool radios share radio id {point}',
                       f'{", ".join(f"{z.get("name") or z["mac"]} ({z["mac"]}, seen {ago(ctx.now, z.get("last_seen_epoch"))})" for z in zones)}.',
                       'Two sliders with one id contradict each other about that member; the central reports id clashes and lamps flicker.',
                       'Plug one in and assign it a free radio id (its identity sector only; calibration is kept).',
                       actions, [evidence('registry', f'point {point}: {", ".join(macs)}')], key=str(point))
    for d in ctx.devices:
        if d.get('role') != 'poolcentral':
            continue
        s = ctx.sessions.get(d['id']) or {}
        status = s.get('status') or {}
        if status.get('id_clashes'):
            yield make('pool.central_id_clash', f'mac:{d.get("mac") or d["id"]}', 'bad', 'Pool central sees live radios sharing an id',
                       f'PoolCentral status: id_clashes={status.get("id_clashes")}.', 'Lamps served by the clashing id flicker.',
                       'Assign distinct radio ids (1-6) to the sliders.', [], [evidence('central status', f'id_clashes={status.get("id_clashes")}')],
                       device=d['id'])
        for r in s.get('radios') or []:
            if r.get('legacy'):
                yield make('pool.legacy_packet', f'mac:{d.get("mac") or d["id"]}', 'warn', f'Pool radio id {r.get("id")} sends the legacy packet',
                           f'The central marks {r.get("mac")} as legacy: pre-2026 firmware still accepted by the shim.',
                           'The shim is insurance, not a supported configuration; the radios and central are a matched set.',
                           'Reflash that radio with the current PoolZone build.', [], [evidence('central radio', str(r.get('mac')))],
                           key=str(r.get('mac')), device=d['id'])
        for t in s.get('tags') or []:
            if t.get('tag') == 'central.radio_timeout' and ctx.now - (t.get('t') or 0) < WINDOW['port']:
                label = (t.get('fields') or {}).get('label', '?')
                yield make('pool.radio_timeout', f'mac:{d.get("mac") or d["id"]}', 'warn', f'Pool central lost radio {label}',
                           f'"RADIO TIMEOUT: {label}" — heartbeats stopped.', 'Idle radios keep heartbeating, so this is a real fault: power, range or a crash.',
                           'Check that radio\'s power and distance; query zones to see if it still answers over the air.',
                           [action('query', 'Query zones', 'zones.query')] if ctx.relay_ok else [], [evidence('central', t.get('text', ''), t.get('t'))],
                           key=label.replace(' ', '_'), device=d['id'])


def rule_preshow_points(ctx):
    by_point = {}
    for z in ctx.reg_zones.values():
        if z.get('zone_type') == 1 and z.get('point_id') and str(z.get('firmware') or '').startswith('preshow-') and _live(ctx, z):
            by_point.setdefault(z['point_id'], []).append(z)
    for point, zones in by_point.items():
        if len(zones) > 1:
            yield make('preshow.point_clash', 'global', 'bad', f'Two preshow plates are flashed as point {point}',
                       ', '.join(f'{z.get("name") or z["mac"]} ({z["mac"]})' for z in zones) + '.',
                       'Their cues fight over one TouchDesigner channel.', 'Reflash one of them with a free point.',
                       [], [evidence('registry', f'point {point}')], key=str(point))
    for d in ctx.devices:
        if d.get('role') == 'preshowbridge':
            s = ctx.sessions.get(d['id']) or {}
            if (s.get('status') or {}).get('point_clashes'):
                yield make('preshow.point_clash', f'mac:{d.get("mac") or d["id"]}', 'bad', 'The media bridge sees plates sharing a point id',
                           f'status point_clashes={s["status"]["point_clashes"]}.', 'Cues fight over one channel.', 'Reflash one plate.',
                           [], [evidence('bridge status', 'point_clashes')], key='bridge', device=d['id'])


def rule_cubes(ctx):
    expected = (ctx.builds.get('cube') or {}).get('version')
    for d in ctx.devices:
        if d.get('role') != 'cube' or not d.get('mac'):
            continue
        mac = d['mac']
        s = ctx.sessions.get(d['id']) or {}
        fw = d.get('fw_status') or s.get('fw_status') or {}
        flags = s.get('flags') or {}
        row = ctx.by_mac.get(mac, {})
        number = row.get('cube_id')
        label = f'Cube #{number}' if number else f'Cube {mac}'
        if fw.get('status') == 'different':
            yield make('cube.fw_different', f'mac:{mac}', 'warn', f'{label} runs {fw.get("version")}; the local build is {fw.get("expected")}',
                       f'USB "?" reported FW: {fw.get("version")} on {d["port"]}. Local manifest: {fw.get("expected")}.',
                       'A matching version is not a hash verification; a differing one means the cube missed an update.',
                       ('It will be upgraded automatically once Register and Flash are off (Settings › Automatic updates); '
                        'or flash it now (NVS registration preserved; boot is re-checked).') if ctx.auto_firmware_usb else
                       'Flash it (NVS registration preserved; boot is re-checked).',
                       [action('flash', 'Flash cube firmware', 'cube.flash_firmware', dict(device=d['id']), 'hardware')],
                       [evidence('USB', f'FW: {fw.get("version")}')])
        elif fw.get('status') == 'unknown' or (not fw and d.get('state') in ('idle', 'session') and expected):
            yield make('cube.fw_unverified', f'mac:{mac}', 'info', f'{label} firmware version not verified',
                       'No matching "FW:" + "Cube MAC:" + "Cube READY" answer yet. Missing response means unverified, not current.',
                       '', 'Re-check the boot answer; unplug/replug an older cube to capture its boot log.',
                       [action('check', 'Check boot', 'cube.check_boot', dict(device=d['id']))], [evidence('USB', 'no verified answer')])
        if flags.get('unregistered') and ctx.now - flags['unregistered'].get('at', 0) < WINDOW['flag']:
            actions = []
            if ctx.station_ok and row.get('uid'):
                actions.append(action('transmit', 'Send the saved mapping', 'pairing.transmit', dict(macs=[mac]), 'hardware'))
            elif ctx.station_ok:
                actions.append(action('register', 'Register at the station', 'pairing.register', dict(mac=mac), 'hardware'))
            yield make('cube.unregistered', f'mac:{mac}', 'warn', f'{label} says it is UNREGISTERED',
                       f'Its boot log printed UNREGISTERED: the cube\'s NVS holds no ID. Inventory: #{number} uid {row.get("uid")} status {row.get("status")}.',
                       'It ignores every zone command addressed by ID until it stores a registration.',
                       'Transmit the saved mapping (or register it) and wait for the cube\'s ACK.', actions,
                       [evidence('USB', 'UNREGISTERED', flags['unregistered'].get('at'))], fired_at=flags['unregistered'].get('at', 0))
        if flags.get('espnow_init_error'):
            yield make('cube.espnow_init_error', f'mac:{mac}', 'bad', f'{label}: ESP-NOW failed to start',
                       'Boot printed ESP-NOW INIT ERROR; the cube stays unresponsive to every radio command and never answers "?".',
                       'Nothing reaches this cube.', 'Power-cycle it; reflash if it repeats.',
                       [action('flash', 'Flash cube firmware', 'cube.flash_firmware', dict(device=d['id']), 'hardware')],
                       [evidence('USB', 'ESP-NOW INIT ERROR')])
        channel = (flags.get('channel') or {}).get('channel') or (d.get('details') or {}).get('channel')
        if channel not in (None, 2, '2'):
            yield make('cube.wrong_channel', f'mac:{mac}', 'bad', f'{label} is on ESP-NOW channel {channel}, not 2',
                       f'USB reported ESP-NOW CHANNEL: {channel}. The channel is compiled in.', 'Stations and zones cannot reach it.',
                       'Flash the maintained build.', [action('flash', 'Flash cube firmware', 'cube.flash_firmware', dict(device=d['id']), 'hardware')],
                       [evidence('USB', f'channel {channel}')])
        ignored = flags.get('show_start_ignored')
        if ignored and ctx.now - ignored.get('at', 0) < WINDOW['show_start']:
            actions = [action('ready', f'Make {label} mainshow-ready (SET_ZONE 4)', 'mainshow.ready', dict(cube=mac), 'hardware')] if ctx.show.get('usable') else []
            yield make('cube.show_start_ignored', f'mac:{mac}', 'warn', f'{label} ignored a show start',
                       f'It printed "SHOW_START IGNORED / ZONE={ignored.get("zone")}": it was in zone {ignored.get("zone")}, not mainshow (4).',
                       'Only a mainshow-ready cube starts its timeline.', 'Send it mainshow-ready first, then trigger again.', actions,
                       [evidence('USB', f'SHOW_START IGNORED zone={ignored.get("zone")}', ignored.get('at'))], fired_at=ignored.get('at', 0))
        detection = d.get('detection') or {}
        if detection.get('kind') == 'cube' and d.get('presumed', {}).get('role') == 'cube':
            pass


def rule_registration(ctx):
    st = ctx.station
    feedback = st.get('feedback') or {}
    title = feedback.get('title') or ''
    active = st.get('active') or {}
    mac = active.get('mac') or ''
    scope = f'mac:{mac}' if mac else 'station'
    if title.startswith('NEOCORE #') and 'NOT CONFIRMED' in title or st.get('phase') == 'paused':
        actions = [action('retry', 'Retry the saved registration', 'pairing.retry', kind='hardware'), action('skip', 'Skip this cube', 'pairing.skip')]
        yield make('reg.unconfirmed', scope, 'warn', title or 'Registration not confirmed',
                   f'{feedback.get("detail") or "The tag was read but the cube did not acknowledge."} The saved ID/UID is reused on retry.',
                   'Radio delivery is not acknowledgment; the mapping stays pending until the cube answers.',
                   'Is the cube powered, in range and on channel 2?', actions, [evidence('station', feedback.get('detail') or title)])
    elif title == 'TAG NOT REGISTERED':
        yield make('reg.tag_conflict', scope, 'warn', 'Tag not registered', feedback.get('detail') or '',
                   'A scan during REGISTER DEVICE takes over a tag from another device atomically; the old cube keeps its number.',
                   'Retry to scan again, or Skip.', [action('retry', 'Retry', 'pairing.retry', kind='hardware'), action('skip', 'Skip', 'pairing.skip')],
                   [evidence('station', feedback.get('detail') or title)])
    elif title == 'REGISTRATION NEEDS ATTENTION':
        yield make('reg.needs_attention', scope, 'warn', 'Registration needs attention', feedback.get('detail') or '', '',
                   'Read the station error, then retry.', [action('retry', 'Retry', 'pairing.retry', kind='hardware')],
                   [evidence('station', feedback.get('detail') or title)])
    elif title in ('REGISTRATION STOPPED', 'REGISTRATION INTERRUPTED'):
        yield make('reg.stopped', scope, 'info', title.capitalize(), feedback.get('detail') or '',
                   'Registrations already transmitted are not undone.', 'Retry unconfirmed mappings when ready.', [],
                   [evidence('station', feedback.get('detail') or title)])
    unconfirmed = [r for r in ctx.rows if r.get('status') == 'unconfirmed' and (r.get('uid') or r.get('pending_uid')) and r.get('role') != 'excluded']
    if unconfirmed and not st.get('mode'):
        numbers = ', '.join(f'#{r["cube_id"]}' if r.get('cube_id') else r['mac'] for r in unconfirmed[:8]) + (' …' if len(unconfirmed) > 8 else '')
        actions = [action('retry', f'Retry {len(unconfirmed)} unconfirmed registration(s)', 'pairing.retry_unconfirmed', kind='hardware')] if ctx.station_ok else []
        yield make('reg.unconfirmed_rows', 'global', 'info', f'{len(unconfirmed)} registration(s) unconfirmed',
                   f'{numbers}: a saved ID/UID whose result is uncertain (interrupted, or no ACK).',
                   'Retrying the same ID/UID is safe.', 'Transmit them again from the station and watch for each ACK.', actions,
                   [evidence('inventory', numbers)])
    needs = [r for r in ctx.rows if r.get('status') == 'needs_number' and r.get('role') != 'excluded']
    live_needs = [r for r in needs if r.get('recent') or r.get('on_usb') or r.get('pinned')]
    if len(needs) > len(live_needs):
        rest = [r for r in needs if r not in live_needs]
        yield make('number.needs_number_many', 'global', 'info', f'{len(rest)} device(s) in the inventory have no number',
                   ', '.join(r['mac'] for r in rest[:6]) + (' …' if len(rest) > 6 else '') + '. None of them is on USB or answering discovery now.',
                   'Unnumbered devices stay out of the zone database.', 'Assign each one its physical label number when it is in hand.',
                   [], [evidence('inventory', f'{len(rest)} needs_number')])
    for r in live_needs[:12]:
        yield make('number.needs_number', f'mac:{r["mac"]}', 'info', f'{r["mac"]} has no number',
                   f'"{r.get("detail") or "Number cleared"}" (source {r.get("source")}, updated {r.get("updated_at")}).',
                   'Unnumbered devices stay out of the zone database.', 'Assign its physical label number.',
                   [action('rename', f'Assign #{ctx.inv.get("suggested_number")}', 'inventory.rename', dict(mac=r['mac'], number=ctx.inv.get('suggested_number')))],
                   [evidence('inventory', r.get('detail') or 'needs_number')])
    if ctx.inv.get('suggested_number') is None and ctx.rows:
        yield make('number.exhausted', 'global', 'bad', 'No free device numbers remain above 32',
                   'suggested_number() found none.', 'New cubes cannot be numbered automatically.', 'Free a number or assign manually.', [],
                   [evidence('inventory', 'no suggestion')])


def rule_devices(ctx):
    for d in ctx.devices:
        if d.get('role') == 'unknown' and d.get('state') == 'idle' and d.get('candidate'):
            presumed = d.get('presumed') or {}
            yield make('zone.silent', f'port:{d["port"]}', 'info', f'Board on {d["port"]} is not answering on serial',
                       f'No "?"/hello/STATUS answer in {d.get("attempts")} attempt(s).' + (f' The inventory says: {presumed.get("label")}.' if presumed else ''),
                       'It may still be booting, run a legacy sketch, or be a bare board.',
                       'A bootloader read identifies it by MAC and flash contents, but reboots it.',
                       [action('detect', 'Identify through the bootloader (reboots)', 'zone.detect', dict(device=d['id']), 'hardware'),
                        action('probe', 'Ask again on serial', 'device.probe', dict(device=d['id']))],
                       [evidence('usb', d.get('error') or 'silent')], device=d['id'])
        detection = d.get('detection') or {}
        if detection.get('kind') in ('cube', 'station', 'other') and d.get('role') != 'zone':
            reason = {'cube': 'Registered/recognised neocube: use the cube flashing station', 'station': 'This is the pairing station',
                      'other': 'Not a tag zone; flash it from its own sketch'}[detection['kind']]
            protected = (detection.get('mac') or '') == '3C:0F:02:AD:83:24'
            actions = []
            if not protected and ctx.esptool_ok:
                actions.append(action('force', 'Force flash as a zone (overwrites it)', 'zone.flash_force', dict(device=d['id']), 'destructive'))
            know = f'{detection.get("label")} ({detection.get("source")}). {reason}.'
            if detection['kind'] == 'cube':
                know += ' Force-flashing a registered cube unregisters it: its number and NFC tag are released in the inventory; no other cube is cleared.'
            yield make('flash.refused', f'port:{d["port"]}', 'bad' if protected else 'warn', f'Board on {d["port"]} is refused by the zone flasher',
                       know, 'The console never overwrites a known cube, the station or a foreign controller by accident.',
                       'Only force it if you are repurposing this exact board.' + ('' if ctx.esptool_ok else ' Fix the flashing tool first.'),
                       actions, [evidence('detect', detection.get('label') or detection['kind'])], device=d['id'])
        elif detection.get('kind') == 'nctzone' and (not detection.get('configured') or detection.get('ambiguous')):
            yield make('flash.ambiguous', f'port:{d["port"]}', 'warn', f'Zone identity on {d["port"]} is missing or ambiguous',
                       f'{detection.get("label")}: configured={detection.get("configured")} ambiguous={detection.get("ambiguous")} profile={detection.get("profile")}.',
                       'Auto-flash cannot choose a profile for it.', 'Flash it manually once with its zone, point and name.',
                       [action('flash', 'Flash with a chosen identity', 'zone.flash', dict(device=d['id']), 'hardware')],
                       [evidence('detect', detection.get('label') or 'ambiguous')], device=d['id'])
        elif detection.get('kind') == 'legacy_zone':
            yield make('flash.ambiguous', f'port:{d["port"]}', 'info', f'{detection.get("label")} on {d["port"]}',
                       f'Flash image signature: {detection.get("label")} (suggested profile {detection.get("profile")}).',
                       'Legacy sketches have no zone identity or database.', 'Flash it with the matching zone profile and its point.',
                       [action('flash', 'Flash with the suggested profile', 'zone.flash', dict(device=d['id'], profile=detection.get('profile')), 'hardware')],
                       [evidence('detect', detection.get('label') or 'legacy')], device=d['id'], key='legacy')


# ---------------------------------------------------------------------- tier 4: outcomes
def rule_jobs(ctx):
    for job in ctx.jobs:
        if job.get('state') not in ('done', 'failed') or ctx.now - (job.get('finished_at') or 0) > WINDOW['job']:
            continue
        record = job.get('result') if isinstance(job.get('result'), dict) else {}
        result = record.get('result') or record.get('ui_result') or ('failed' if job.get('state') == 'failed' else '')
        detail = record.get('detail') or record.get('ui_detail') or job.get('error') or ''
        device = job.get('device')
        d = next((x for x in ctx.devices if x.get('id') == device), None)
        scope = f'mac:{d["mac"]}' if d and d.get('mac') else f'port:{job.get("target")}'
        at = job.get('finished_at') or 0
        key = job.get('id')
        ev = [evidence('job', f'{job.get("title")}: {result} {detail}'.strip(), at)]
        if result == 'boot_unconfirmed':
            check = action('check', 'Check boot again', 'cube.check_boot', dict(device=device)) if job.get('kind', '').startswith('cube') and d else \
                action('check', 'Read the zone report', 'zone.check_report', dict(device=device)) if d else None
            yield make('flash.boot_unconfirmed', scope, 'warn', f'{job.get("title")}: written and verified, boot not confirmed',
                       detail, 'The flash contents were read back correctly; only the boot answer did not match.',
                       'Do not reflash. Check the boot answer once the board has restarted.', [check] if check else [], ev, key=key, device=device, fired_at=at)
        elif result == 'attention' or 'read-back mismatch' in detail or 'changed unexpectedly' in detail:
            yield make('flash.readback_mismatch' if 'mismatch' in detail or 'changed unexpectedly' in detail else 'flash.attention', scope, 'bad',
                       f'{job.get("title")}: needs attention', detail + (f' Receipt: {record.get("log_path") or record.get("id")}' if record else ''),
                       'Something was written and then did not verify; the board\'s state is uncertain.',
                       'Inspect the board and the receipt before retrying; a backup is kept when the pipeline made one.',
                       [], ev, key=key, device=device, fired_at=at)
        elif 'identity changed' in detail or 'disconnected or changed' in detail or 'Board identity changed' in detail:
            yield make('flash.identity_changed', scope, 'info', f'{job.get("title")}: the USB device changed mid-way', detail,
                       'Nothing (more) was written.', 'Reconnect the same board and retry.',
                       [action('probe', 'Probe again', 'device.probe', dict(device=device))] if d else [], ev, key=key, device=device, fired_at=at)
        elif 'refusing' in detail or 'refused' in detail.lower() or 'Protected' in detail:
            protected = '3C:0F:02:AD:83:24' in detail or 'pairing station' in detail
            actions = []
            if not protected and d and job.get('kind') in ('zone.flash', 'zone.db_usb') and ctx.esptool_ok and 'neocube' in detail:
                actions.append(action('force', 'Force flash (unregisters the cube)', 'zone.flash_force', dict(device=device), 'destructive'))
            yield make('flash.refused', scope, 'bad' if protected else 'warn', f'{job.get("title")}: refused', detail,
                       'The pipelines never overwrite a known cube, the station or a foreign controller by accident.',
                       'Only force it if you are repurposing this exact board.', actions, ev, key=key, device=device, fired_at=at)
        elif '4 MB' in detail:
            yield make('flash.wrong_size', scope, 'bad', f'{job.get("title")}: wrong flash size', detail, 'This board is not the right hardware.',
                       'Use a 4 MB ESP32-C3.', [], ev, key=key, device=device, fired_at=at)
        elif job.get('state') == 'failed' and job.get('kind', '').startswith(('cube.', 'zone.', 'dongle.', 'mainshow.', 'pool.')):
            yield make('flash.failed', scope, 'warn', f'{job.get("title")}: failed', detail, '', 'Read the job log; retry after fixing the cause.',
                       [], ev, key=key, device=device, fired_at=at)
    for z in ctx.reg_zones.values():
        if z.get('rx_gain_pending'):
            yield make('zone.rx_gain_pending', f'zone:{z["mac"]}', 'info', f'Waiting for "{z.get("name") or z["mac"]}" to confirm RX gain {z["rx_gain_pending"]} dB',
                       'A ZONE_SET_CONFIG was sent; success is only the zone\'s next ZONE_SETTINGS report (10 s).',
                       f'No answer means the zone or dongle firmware is too old (zone {RX_GAIN_FLOOR}; dongle 1.8).', '', [],
                       [evidence('registry', f'rx_gain_pending={z["rx_gain_pending"]}')])


RULES = [
    (0, rule_tools), (0, rule_builds), (0, rule_locks), (0, rule_ports),
    (1, rule_station), (1, rule_radio), (1, rule_mainshow), (1, rule_sync),
    (2, rule_zone_db_global), (2, rule_zone_db_each), (2, rule_zone_firmware),
    (3, rule_tags), (3, rule_nack), (3, rule_zone_health), (3, rule_pool_ids), (3, rule_preshow_points), (3, rule_cubes),
    (3, rule_registration), (3, rule_devices),
    (4, rule_jobs),
]


# ---------------------------------------------------------------------- evaluation
def evaluate(sections, now, dismissed):
    ctx = Ctx(sections, now, dismissed)
    out, seen = [], {}
    for tier in sorted({t for t, _ in RULES}):
        for t, fn in RULES:
            if t != tier:
                continue
            for s in fn(ctx) or ():
                if s['id'] in seen:
                    continue
                seen[s['id']] = s
                out.append(s)
                ctx.fired.add(s['rule'])
                ctx.fired.add(s['id'])
    out = _supersede(out)
    out = _strip(out, ctx)
    out = [s for s in out if s['id'] not in ctx.dismissed and f'{s["rule"]}@{s["scope"]}' not in ctx.dismissed
           and f'{s["rule"]}@*' not in ctx.dismissed]
    out.sort(key=lambda s: (SEVERITY_RANK.get(s['severity'], 3), 0 if s['actions'] else 1, -(s.get('fired_at') or 0),
                            0 if s['scope'] == 'global' else 1, s['id']))
    return out


def _supersede(suggestions):
    silenced = set()
    by_scope = {}
    for s in suggestions:
        by_scope.setdefault(s['scope'], []).append(s)
    for s in suggestions:
        for other in by_scope.get(s['scope'], []):
            if other is not s and other['rule'] in SUPERSEDES.get(s['rule'], ()):
                silenced.add(other['id'])
        if s['rule'] in ('tools.esptool', 'zone.unpublished', 'zone.cache_inconsistent', 'tag.known_unpublished'):
            for other in suggestions:
                if other is not s and other['rule'] in SUPERSEDES.get(s['rule'], ()):
                    silenced.add(other['id'])
    return [s for s in suggestions if s['id'] not in silenced]


AIR_RULES = ('tag.known_zone_behind', 'zone.db_behind', 'zone.publish_timeout', 'cube.nack_mac_mismatch')


def _strip(suggestions, ctx):
    """Drop actions that cannot work right now, and say why."""
    station_down = any(s['rule'] == 'station.disconnected' for s in suggestions) or not ctx.relay_ok
    for s in suggestions:
        kept = []
        note = ''
        if station_down and s['rule'] in AIR_RULES and not any(a['command'] in AIR_COMMANDS for a in s['actions']):
            note = ' Over-the-air actions need a connected station or dongle with zone support.'
        for a in s['actions']:
            if not ctx.esptool_ok and a['command'] in FLASH_COMMANDS:
                note = ' Fix the flashing tool first (see the flashing-tool card).'
                continue
            if station_down and a['command'] in AIR_COMMANDS:
                note = note or ' Over-the-air actions need a connected station or dongle with zone support.'
                continue
            kept.append(a)
        if note and note not in s['check']:
            s['check'] = (s['check'] + note).strip()
        s['actions'] = kept
        running = {j.get('target') for j in ctx.jobs if j.get('state') == 'running'} | \
                  {j.get('device') for j in ctx.jobs if j.get('state') == 'running'}
        if s.get('device') and s['device'] in running:
            s['actions'] = []
            s['check'] = (s['check'] + ' A job is running on this device; actions return when it finishes.').strip()
    return suggestions


def section(suggestions):
    by_scope, counts = {}, dict(bad=0, warn=0, info=0)
    for s in suggestions:
        by_scope.setdefault(s.get('scope', 'global'), []).append(s['id'])
        if s.get('device'):
            by_scope.setdefault(f'device:{s["device"]}', []).append(s['id'])
        counts[s.get('severity', 'info')] = counts.get(s.get('severity', 'info'), 0) + 1
    return dict(suggestions=suggestions, by_scope=by_scope, counts=counts)


ALL_COMMANDS = sorted({
    'tools.check', 'docs.open', 'build.cube', 'build.zone', 'build.dongle', 'device.probe', 'device.connect', 'dongle.flash',
    'station.nfc_status', 'station.nfc_recover', 'sync.signin', 'sync.status', 'sync.run', 'sync.download', 'inventory.rename',
    'pairing.register', 'zone.pull', 'zone.update_db_usb', 'zones.update', 'zones.query', 'device.console', 'pairing.retry',
    'pairing.transmit', 'pairing.start_pair', 'pairing.discover', 'pairing.flash', 'zone.flash', 'zone.nfc_recover',
    'zones.reboot', 'pool.flash_firmware', 'pool.assign_radio_id', 'cube.flash_firmware', 'cube.check_boot', 'mainshow.ready',
    'pairing.skip', 'pairing.retry_unconfirmed', 'zone.detect', 'zone.flash_force', 'zone.check_report'})
