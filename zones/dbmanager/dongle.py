"""ESP-NOW dongle: an ESP32-C3 running the pairing-station firmware, used only for its zone relay.

The pairing-station firmware relays zone frames (`zone_send` / `zone_frame`) without needing its
NFC reader, so a bare ESP32-C3 with that firmware is a complete dongle. Flashing writes the
bootloader, partition table, boot selector and application separately so NVS is preserved,
and refuses boards the inventory knows as cubes or zones.
"""
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'flashing_station'))
from backend import MAC_RE, Runner, ports, tool_command  # noqa: E402
from core import PROTECTED, PortLock  # noqa: E402

FIRMWARE = 'nct-pairing-1.7-zones'  # what the dongle must report in `hello` (1.7 adds signal strength)
SKETCH = ROOT / 'pairing_station/firmware/pairing_station'
BUILD = ROOT / 'pairing_station/build'
BOARD = 'esp32:esp32:esp32c3:CDCOnBoot=cdc'  # same recipe as scripts/build_all_firmware.py
LIBRARIES = (ROOT / 'pairing_station/.arduino/libraries', ROOT / 'zones/firmware/libraries')
IDE_CLI = Path('/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli')
SEGMENTS = [(0x0, 'bootloader'), (0x8000, 'partitions'), (0xE000, 'boot_app0'), (0x10000, 'app')]
BOOT_APP0 = slice(0xE000, 0x10000)  # taken from the merged image the build also produces
BACKUPS = ROOT / 'pairing_station/data/dongle/backups'  # full 4 MB image before the first write to a board


def artifacts():
    return dict(bootloader=BUILD / 'pairing_station.ino.bootloader.bin', partitions=BUILD / 'pairing_station.ino.partitions.bin',
                app=BUILD / 'pairing_station.ino.bin', merged=BUILD / 'pairing_station.ino.merged.bin')


def sources():
    files = [p for p in SKETCH.iterdir() if p.suffix in ('.ino', '.h', '.cpp')]
    files += [p for p in (ROOT / 'zones/firmware/libraries/NctZone/src').iterdir() if p.suffix in ('.h', '.cpp')]
    return files


def build_state():
    """'current', 'missing' or 'stale' (a source is newer than the build)."""
    files = artifacts()
    if not all(p.is_file() for p in files.values()):
        return 'missing'
    built = min(p.stat().st_mtime for p in files.values())
    return 'stale' if max(p.stat().st_mtime for p in sources()) > built else 'current'


def build(runner):
    cli = str(IDE_CLI) if IDE_CLI.exists() else shutil.which('arduino-cli')
    if not cli:
        raise RuntimeError('Install Arduino IDE or arduino-cli with ESP32 core 3.3.11 to build the dongle firmware')
    BUILD.mkdir(parents=True, exist_ok=True)
    args = [cli, 'compile', '--fqbn', BOARD]
    for library in LIBRARIES:
        args += ['--libraries', str(library)]
    runner(args + ['--build-path', str(BUILD / 'cache'), '--output-dir', str(BUILD), str(SKETCH)], 900)


def segment_files(folder):
    """Copy the build into `folder` (frozen for this attempt) and return [(offset, path)]."""
    files = artifacts()
    merged = files['merged'].read_bytes()
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for offset, name in SEGMENTS:
        data = merged[BOOT_APP0] if name == 'boot_app0' else files[name].read_bytes()
        path = (folder / f"{name}.bin").resolve()  # esptool runs with another working directory
        path.write_bytes(data)
        out.append((offset, path))
    return out


def known_boards(db, zones):
    """Snapshot (on the Tk/SQLite thread) of what the inventory knows, for refusal() on a worker."""
    roles = db.roles()
    return dict(cubes={r['mac']: r['cube_id'] for r in db.rows() if roles.get(r['mac']) != 'excluded'},
                zones={z['mac'] for z in zones}, excluded={m for m, role in roles.items() if role == 'excluded'})


def refusal(mac, known):
    """Why this board must not become a dongle, or None."""
    if mac in PROTECTED:
        return 'This is the installed pairing station; it already runs the relay firmware — just connect to it'
    if mac in known['zones']:
        return f'{mac} is a known zone board; flashing it would take a zone out of the show'
    if mac in known['cubes']:
        number = known['cubes'][mac]
        return f'{mac} is a cube{f" #{number}" if number else ""} in the inventory; refusing to overwrite cube firmware'
    return None


def flash(port, known, folder, emit, force_build=False):
    """Build if needed, identify, refuse cubes/zones, write the relay firmware. Returns the dongle MAC.

    Runs on a worker thread (no SQLite here: `known` comes from known_boards()); the caller records
    the dongle's excluded role afterwards so the cube and zone flashers leave it alone.
    """
    runner = Runner(emit, folder / 'dongle.log')
    folder.mkdir(parents=True, exist_ok=True)
    state = build_state()
    if force_build or state != 'current':
        emit('stage', f'Build pairing-station firmware ({state})')
        build(runner)
    segments = segment_files(folder / 'firmware')
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
        reason = refusal(mac, known)
        if reason:
            raise RuntimeError(reason + '; nothing was written')
        backup = BACKUPS / f'{mac.replace(":", "")}.bin'
        if not backup.is_file():
            emit('stage', f'Back up {mac} (full flash, first time only)')
            BACKUPS.mkdir(parents=True, exist_ok=True)
            partial = backup.with_suffix('.partial')
            tool('read-flash', '0x0', '0x400000', str(partial), timeout=300)
            if not partial.is_file() or partial.stat().st_size != 0x400000:
                raise RuntimeError('Backup incomplete; nothing was written')
            partial.rename(backup)
        emit('stage', f'Write relay firmware to {mac}')
        args = ['write-flash', '--flash-mode', 'keep', '--flash-freq', 'keep', '--flash-size', 'keep']
        for offset, path in segments:
            args += [hex(offset), str(path)]
        # As zone_flash: an RTS hard reset can leave native USB-Serial/JTAG boards in download mode.
        tool(*args, after='watchdog-reset' if 'USB-Serial/JTAG' in identity else 'hard-reset')
    return mac

