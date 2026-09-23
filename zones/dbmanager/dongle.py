"""Workstation device: an ESP32-C3 USB dongle for every ESP-NOW host function, and the boards it succeeds.

Three firmware families answer the same JSON-line protocol on USB, and every host here tells them
apart by what `hello` reports, not by the firmware name:
  - the Workstation (`WORKSTATION`, zones/firmware/Workstation): PN532 reader, cube pairing, zone relay,
    the Mainshow verbs, pool-lamp and preshow-cue emulation, main-show relay. `roles` lists what it does.
  - the legacy pairing station (`PAIRING`, pairing_station/firmware, frozen): reader + pairing + zone
    relay; the installed station runs it. No `roles`.
  - the legacy General Radio (general-radio-1.x, superseded by the Workstation): everything but the
    reader (`nfc_ok` false).
Capability helpers below (`has_reader`, `relay_capable`, `show_capable`, ...) take the hello dict, or
a firmware string for the older call sites.

Flashing writes the bootloader, partition table, boot selector and application separately so NVS
is preserved, and refuses boards the inventory knows as cubes or zones. The same pipeline writes the
Mainshow controller firmware (`MAINSHOW`, zones/mainshow). A board recorded as the controller is
refused when writing anything else, so the dongle flasher cannot quietly turn the show trigger back
into a relay. A Workstation is just an `excluded` board, like a relay dongle: the cube and zone
flashers leave it alone by role.
"""
from pathlib import Path
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'flashing_station'))
sys.path.insert(0, str(ROOT / 'zones/tools'))
from backend import MAC_RE, Runner, ports, tool_command  # noqa: E402
from core import PROTECTED, PortLock  # noqa: E402
import hostos  # noqa: E402  (core puts pairing_station on the path)
import zonedb  # noqa: E402

BOARD = 'esp32:esp32:esp32c3:CDCOnBoot=cdc'  # same recipe as scripts/build_all_firmware.py
SEGMENTS = [(0x0, 'bootloader'), (0x8000, 'partitions'), (0xE000, 'boot_app0'), (0x10000, 'app')]
BOOT_APP0 = slice(0xE000, 0x10000)  # taken from the merged image the build also produces
BACKUPS = ROOT / 'pairing_station/data/dongle/backups'  # full 4 MB image before the first write to a board
CONTROLLERS_KEY = 'mainshow_controllers'  # metadata: JSON list of boards flashed as the Mainshow controller
WORKSTATIONS_KEY = 'general_radios'  # metadata: JSON list of Workstations / General Radios (the key predates the name)


class Firmware:
    """One firmware that this pipeline can put on a spare ESP32-C3."""

    def __init__(self, label, version, sketch, build, libraries):
        self.label, self.version, self.sketch, self.build, self.libraries = label, version, sketch, build, libraries

    @property
    def stem(self):
        return self.sketch.name + '.ino'


# `version` is what the board must report in `hello`.
PAIRING = Firmware('pairing-station relay', 'nct-pairing-1.8-zones',  # 1.7 adds signal strength, 1.8 RX gain control
                   ROOT / 'pairing_station/firmware/pairing_station', ROOT / 'pairing_station/build',
                   (ROOT / 'pairing_station/.arduino/libraries', ROOT / 'zones/firmware/libraries'))
MAINSHOW = Firmware('Mainshow controller', 'mainshow-1.3.0',  # 1.3 adds the show timecode
                    ROOT / 'zones/firmware/MainshowController',
                    ROOT / 'zones/build/MainshowController',
                    (ROOT / 'zones/firmware/libraries', ROOT / 'live files/libraries'))  # Adafruit_NeoPixel, as the cube build
WORKSTATION = Firmware('Workstation', 'workstation-1.0.0',  # the General Radio 1.2.0 protocol plus the station's PN532 reader
                       ROOT / 'zones/firmware/Workstation',
                       ROOT / 'zones/build/Workstation',
                       (ROOT / 'zones/firmware/libraries', ROOT / 'live files/libraries',  # NeoPixel, PN532, BusIO
                        ROOT / 'pairing_station/.arduino/libraries'))
FIRMWARE = PAIRING.version  # what the installed (protected) station runs
RELAY_FIRMWARE = WORKSTATION.version  # what "Flash dongle…" writes to a spare board
# The General Radio (zones/firmware/GeneralRadio, superseded by the Workstation) is no longer a flash
# target, but boards still running it are recognised. 1.0.0: zone relay only; 1.1.0: show relay and
# timecode; 1.2.0: SHOW_LIVE.
LEGACY_GENERAL = 'general-radio-1.2.0'
GENERAL_VERSIONS = ('general-radio-1.0.0', 'general-radio-1.1.0', LEGACY_GENERAL)
# Relays with RX gain control (ZONE_SET_CONFIG): what the Zone Database Manager accepts without asking
# for a reflash. Not the same as `zones == PROTO`: nct-pairing-1.6/1.7 relay zones but cannot set the gain.
RELAY_VERSIONS = {PAIRING.version, WORKSTATION.version, *GENERAL_VERSIONS}
CURRENT = {'pairing': PAIRING.version, 'mainshow': MAINSHOW.version, 'workstation': WORKSTATION.version,
           'general': LEGACY_GENERAL}


def _firmware(hello_or_firmware):
    if isinstance(hello_or_firmware, dict):
        return str(hello_or_firmware.get('firmware') or '')
    return str(hello_or_firmware or '')


def family(hello_or_firmware):
    """'workstation', 'general', 'pairing', 'mainshow' or None, by the firmware name's prefix."""
    firmware = _firmware(hello_or_firmware)
    for prefix, name in (('workstation-', 'workstation'), ('general-radio-', 'general'), ('nct-pairing-', 'pairing'),
                         ('mainshow-', 'mainshow')):
        if firmware.startswith(prefix):
            return name
    return None


def is_general(hello_or_firmware):
    """A legacy General Radio."""
    return family(hello_or_firmware) == 'general'


def is_workstation(hello_or_firmware):
    return family(hello_or_firmware) == 'workstation'


def is_controller(hello_or_firmware):
    """The Mainshow controller: the one board with the physical show trigger."""
    return family(hello_or_firmware) == 'mainshow'


def radio_roles(hello):
    """The `roles` a Workstation / General Radio lists in hello (cube, zone, pool, preshow, nfc); [] for the rest."""
    return list(hello.get('roles') or []) if isinstance(hello, dict) else []


def has_reader(hello):
    """A PN532 answered at boot (or after nfc_recover): the pairing flow can read tags here."""
    return bool(isinstance(hello, dict) and hello.get('nfc_ok'))


def relay_capable(hello):
    """Relays zone-management frames (hello `zones` is the protocol version this host speaks)."""
    if isinstance(hello, dict):
        return hello.get('zones') == zonedb.PROTO
    return _firmware(hello) in RELAY_VERSIONS  # the older string call: the relays known to have it


def rx_gain_capable(hello_or_firmware):
    """Relays ZONE_SET_CONFIG (RX gain over the air): the 1.8 relay, a General Radio or a Workstation."""
    return _firmware(hello_or_firmware) in RELAY_VERSIONS or is_workstation(hello_or_firmware)


def show_capable(hello_or_firmware):
    """Answers the Mainshow verbs (set_zone / show_start): the controller, a Workstation or a General Radio."""
    if isinstance(hello_or_firmware, dict) and 'cube' in radio_roles(hello_or_firmware):
        return True
    return is_controller(hello_or_firmware) or is_general(hello_or_firmware) or is_workstation(hello_or_firmware)


def show_relay(hello):
    """Relays main-show frames (show_send / show_frame): hello reports show:1 (General Radio 1.1.0+, Workstation)."""
    return bool(isinstance(hello, dict) and hello.get('show'))


def current(hello_or_firmware):
    """The board runs its family's current version (a legacy General Radio: its last release)."""
    return _firmware(hello_or_firmware) == CURRENT.get(family(hello_or_firmware))


def label(hello):
    """What to call the board on screen, from what it reports."""
    kind = family(hello)
    if kind == 'mainshow':
        return 'Mainshow controller'
    if kind == 'workstation':
        return 'Workstation'
    if kind == 'general':
        return 'General Radio'
    return 'Pairing station' if has_reader(hello) else 'ESP-NOW dongle'


def artifacts(firmware=PAIRING):
    build, stem = firmware.build, firmware.stem
    return dict(bootloader=build / f'{stem}.bootloader.bin', partitions=build / f'{stem}.partitions.bin',
                app=build / f'{stem}.bin', merged=build / f'{stem}.merged.bin')


def sources(firmware=PAIRING):
    files = [p for p in firmware.sketch.iterdir() if p.suffix in ('.ino', '.h', '.cpp')]
    for library in ('NctZone', 'NctShow'):
        files += [p for p in (ROOT / 'zones/firmware/libraries' / library / 'src').iterdir() if p.suffix in ('.h', '.cpp')]
    return files


def build_state(firmware=PAIRING):
    """'current', 'missing' or 'stale' (a source is newer than the build)."""
    files = artifacts(firmware)
    if not all(p.is_file() for p in files.values()):
        return 'missing'
    built = min(p.stat().st_mtime for p in files.values())
    return 'stale' if max(p.stat().st_mtime for p in sources(firmware)) > built else 'current'


def build(runner, firmware=PAIRING):
    cli = hostos.arduino_cli()
    if not cli:
        raise RuntimeError(f'Install Arduino IDE or arduino-cli with ESP32 core 3.3.11 to build the {firmware.label} firmware')
    firmware.build.mkdir(parents=True, exist_ok=True)
    args = [cli, 'compile', '--fqbn', BOARD, *hostos.arduino_build_args()]
    for library in firmware.libraries:
        args += ['--libraries', str(library)]
    runner(args + ['--build-path', str(firmware.build / 'cache'), '--output-dir', str(firmware.build), str(firmware.sketch)], 900)


def segment_files(folder, firmware=PAIRING):
    """Copy the build into `folder` (frozen for this attempt) and return [(offset, path)]."""
    files = artifacts(firmware)
    merged = files['merged'].read_bytes()
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for offset, name in SEGMENTS:
        data = merged[BOOT_APP0] if name == 'boot_app0' else files[name].read_bytes()
        path = (folder / f"{name}.bin").resolve()  # esptool runs with another working directory
        path.write_bytes(data)
        out.append((offset, path))
    return out


def controllers(db):
    """MACs recorded as Mainshow controllers (Tk/SQLite thread)."""
    try:
        return set(json.loads(db.metadata(CONTROLLERS_KEY) or '[]'))
    except ValueError:
        return set()


def set_controller(db, mac, is_controller):
    """Record (or forget) that `mac` runs the Mainshow controller firmware, so the dongle flasher leaves it alone."""
    macs = controllers(db)
    macs = macs | {mac} if is_controller else macs - {mac}
    db.set_metadata(CONTROLLERS_KEY, json.dumps(sorted(macs)))


def known_boards(db, zones):
    """Snapshot (on the Tk/SQLite thread) of what the inventory knows, for refusal() on a worker."""
    roles = db.roles()
    return dict(cubes={r['mac']: r['cube_id'] for r in db.rows() if roles.get(r['mac']) != 'excluded'},
                zones={z['mac'] for z in zones}, excluded={m for m, role in roles.items() if role == 'excluded'},
                controllers=controllers(db))


def refusal(mac, known, firmware=PAIRING):
    """Why this board must not be given `firmware`, or None."""
    if mac in known.get('controllers', ()) and firmware is not MAINSHOW:
        return f'{mac} is the Mainshow controller; reflash or retire it from the Mainshow app (zones/mainshow)'
    if mac in PROTECTED:
        return 'This is the installed pairing station; it already runs the relay firmware — just connect to it'
    if mac in known['zones']:
        return f'{mac} is a known zone board; flashing it would take a zone out of the show'
    if mac in known['cubes']:
        number = known['cubes'][mac]
        return f'{mac} is a cube{f" #{number}" if number else ""} in the inventory; refusing to overwrite cube firmware'
    return None


def flash(port, known, folder, emit, force_build=False, firmware=PAIRING, backup='first'):
    """Build if needed, identify, refuse cubes/zones, write `firmware` (the relay by default). Returns the board MAC.

    Runs on a worker thread (no SQLite here: `known` comes from known_boards()); the caller records
    the dongle's excluded role afterwards so the cube and zone flashers leave it alone.
    `backup`: 'first' reads the full flash once per board (the GUIs); 'always' reads it again into a
    timestamped file before this write (the command line, for a board being moved between roles).
    """
    runner = Runner(emit, folder / 'dongle.log')
    folder.mkdir(parents=True, exist_ok=True)
    state = build_state(firmware)
    if force_build or state != 'current':
        emit('stage', f'Build {firmware.label} firmware ({state})')
        build(runner, firmware)
    segments = segment_files(folder / 'firmware', firmware)
    with PortLock(port['port']):
        emit('stage', 'Check flashing tool')
        if '5.3.1' not in runner(tool_command() + ['version'], timeout=10):
            raise RuntimeError('Flashing tool did not start correctly; expected esptool 5.3.1')
        connected = False

        def tool(*args, after='no-reset-stub', timeout=180):
            nonlocal connected
            current = next((p for p in ports() if p['port'] == port['port']), None)
            if current is None or current['key'] != port['key']:
                raise RuntimeError('USB device disconnected or changed; reconnect and retry')
            output = runner(tool_command() + ['--chip', 'esp32c3', '--port', port['port'], '--baud', '460800',
                                              '--before', 'no-reset' if connected else 'default-reset', '--after', after,
                                              *args], timeout)
            connected = True
            return output

        emit('stage', 'Identify')
        identity = tool('flash-id')
        match = MAC_RE.search(identity)
        if not match:
            raise RuntimeError('ESP32-C3 bootloader did not report a MAC; nothing was written')
        mac = match[1].upper()
        reason = refusal(mac, known, firmware)
        if reason:
            raise RuntimeError(reason + '; nothing was written')
        stem = mac.replace(':', '')
        image = BACKUPS / (f'{stem}.bin' if backup == 'first' else f'{stem}-{time.strftime("%Y%m%d-%H%M%S")}.bin')
        if backup == 'always' or not image.is_file():
            emit('stage', f'Back up {mac} (full flash{", first time only" if backup == "first" else ""})')
            BACKUPS.mkdir(parents=True, exist_ok=True)
            partial = image.with_suffix('.partial')
            tool('read-flash', '0x0', '0x400000', str(partial), timeout=300)
            if not partial.is_file() or partial.stat().st_size != 0x400000:
                raise RuntimeError('Backup incomplete; nothing was written')
            partial.replace(image)
        emit('stage', f'Write {firmware.label} firmware to {mac}')
        args = ['write-flash', '--flash-mode', 'keep', '--flash-freq', 'keep', '--flash-size', 'keep']
        for offset, path in segments:
            args += [hex(offset), str(path)]
        # As zone_flash: an RTS hard reset can leave native USB-Serial/JTAG boards in download mode.
        tool(*args, after='watchdog-reset' if 'USB-Serial/JTAG' in identity else 'hard-reset')
    return mac

