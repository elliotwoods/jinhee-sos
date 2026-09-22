# Setup, migration, and verification on another machine

This guide covers running the desktop tools, preserving installation data, and
building firmware. Coding agents should also read [AGENTS.md](../AGENTS.md).
All shell commands below start in the repository root unless stated otherwise.

## 1. Choose the setup you need

| Goal | Needed |
|---|---|
| Run pairing/zone/calibration GUIs | Python with Tk, Python dependencies, appropriate already-programmed hardware |
| Flash the bundled Neocore cube build | Above plus bundled binaries/manifest; esptool is installed by setup |
| Build changed cube, station, or zone firmware | Arduino CLI/IDE, ESP32 core, Arduino libraries, build scripts |
| Move ongoing registration work | Shared inventory sync or a private SQLite backup; a clone alone is not the full local state |
| Run software tests | Python dependencies; desktop session for Tk; C++ compiler for host firmware tests |

**macOS is the bench-tested workstation environment.** The setup script accepts
Python 3.11+, but Python 3.14 with Tk is the tested configuration. Python environments
are not portable: recreate `.venv` on the destination machine.

**Windows is ported but has never touched the hardware.** Every host difference lives in
`pairing_station/hostos.py` (file locks, temp/lock folder, port names, venv layout, Arduino
paths, fonts, child processes); the Windows branches are unit-tested through a fake `msvcrt`
and run for real in the GitHub Actions `windows-latest` job (`.github/workflows/tests.yml`).
Serial ports, esptool flashing and audio cannot be covered there: work through the
[Windows bring-up checklist](#windows-bring-up-checklist) the first time, see section 2b.

Linux uses the macOS (POSIX) branches and is not verified: install Tk, give your user
serial-port permission (`dialout`), and expect no audio cues and no bundled launchers.

## 2. Prepare another Mac

Install Homebrew first if it is not already present, then:

```sh
brew install git python@3.14 python-tk@3.14
xcode-select --install
```

The Xcode command installs command-line developer tools (including `c++`) needed
for host firmware tests. If already installed, do not reinstall them.

Clone the project into a user-writable directory:

```sh
git clone https://github.com/elliotwoods/jinhee-sos.git
cd jinhee-sos
python3.14 -m tkinter
```

The last command must open a small Tk test window. Close it before continuing.
If it fails, fix the interpreter/Tk installation first; `pip install tkinter` is
not the solution. Ensure `python3.14` is the Homebrew interpreter matching the Tk
package, especially if an old Python is earlier on PATH.

Then run:

```sh
./Setup.command
```

Equivalent explicit command:

```sh
python3.14 scripts/setup.py
```

Setup creates `pairing_station/.venv`, installs the pinned flasher dependencies
(currently pyserial 3.5 and esptool 5.3.1, also sufficient for the other Python
apps) and the NCT Console's pywebview (`console/requirements.txt`; on Windows also pythonnet, and
the WebView2 runtime that ships with Edge is used for the window), validates the bundled cube manifest/binary hashes, and synchronizes the
shared inventory. It needs network access for package installation. It does not
flash connected hardware.

Check the environment:

```sh
pairing_station/.venv/bin/python -c 'import sys, tkinter, serial, esptool; print(sys.executable); print("Tk", tkinter.TkVersion, "pyserial", serial.VERSION, "esptool", esptool.__version__)'
pairing_station/.venv/bin/python -m serial.tools.list_ports -v
```

If setup reports missing or modified firmware artifacts, obtain the complete
bundled files from the repository or rebuild them. Do not suppress hash validation.
If inventory sync reports conflicts, follow section 4 instead of deleting the DB.

## 2b. Prepare a Windows PC

1. Install **Python 3.14** from python.org (keep *tcl/tk and IDLE* and the *py launcher* ticked) and
   **Git for Windows**. `py -3 -m tkinter` must open a small test window.
2. Clone into a short path without deep nesting, e.g. `C:\nct\jinhee-sos`. ESP32 builds create very
   long object paths: run `git config --global core.longpaths true`, and enable Windows long paths if you
   will build firmware. `.gitattributes` forces LF on checkout whatever `core.autocrlf` says; firmware
   source hashes and the bundled build manifest depend on that, so do not convert line endings.
3. Double-click **`Setup.bat`** (or `py -3 scripts\setup.py`). Then start any app with the
   **`Launch.bat`** beside its `Launch.command`. The launchers keep a console window open: a startup
   error stays readable there. From a terminal the equivalent of every `pairing_station/.venv/bin/python`
   in this document is `pairing_station\.venv\Scripts\python.exe`.
4. Ports are `COM3`-style names. An ESP32-C3 on its native USB needs no driver on Windows 10/11;
   CP210x/CH340 adapter boards need the vendor driver. Close Arduino Serial Monitor first: Windows
   serial ports are always exclusive.
5. Firmware builds look for Arduino IDE 2's bundled `arduino-cli.exe` (per-user or Program Files install),
   then `arduino-cli` on PATH; the ESP32 core is expected in `%LOCALAPPDATA%\Arduino15`.
6. Host firmware simulations need a `g++` or `clang++` on PATH (MinGW-w64 or LLVM), or set `CXX`.
   They run without sanitizers on Windows.
7. Secrets: the stored web password and the local API token are owner-only (0600) on macOS. Windows has
   no mode bits, so they rely on the folder's ACL: keep the checkout inside your own user profile.

### Windows bring-up checklist

CI proves imports, locks, paths, encodings and the sync logic. With a board plugged in, confirm once:

- [ ] Pairing station **Connect** does not reset the board (DTR/RTS are set before the port opens in
      `pairing_station/transport.py`, `usb_identify.py`, `rangetest/serial_open.py`; the Windows USB
      serial driver is the unknown).
- [ ] Cube flasher: a cube is detected with its MAC, flashes, verifies, and reboots. Watch for a spurious
      *USB identity changed*: the identity key is serial number, then USB location, then the COM name
      (`flashing_station/backend.py: ports`), and some drivers report neither of the first two.
- [ ] Zone flasher detect + flash, and the Zone Database Manager dongle flash (first-time 4 MB backup).
- [ ] Two copies of one app: the second is refused. Pairing app open + cube flasher: the port is refused.
- [ ] Audio cues and the volume slider in the cube flasher; monospace log panes (Consolas); mouse-wheel
      scrolling in the pairing dashboard.
- [ ] Web Sync stores the password and a second app reuses it; `git status` is clean after
      `scripts\sync_inventory.py` (no CRLF churn in `inventory/devices/`).

## 3. Launch the tools

| Tool | Command from repository root |
|---|---|
| NCT Console (everything in one window) | `pairing_station/.venv/bin/python console/app.py` (`--simulate` without hardware, `--browser` without a native webview) |
| Pairing station | `pairing_station/.venv/bin/python pairing_station/app.py --connect` |
| Cube USB flasher | `pairing_station/.venv/bin/python flashing_station/app.py` |
| Cube flasher simulation | `pairing_station/.venv/bin/python flashing_station/app.py --simulate` |
| Zone flasher | `pairing_station/.venv/bin/python zones/flasher/app.py` |
| Zone Database Manager | `pairing_station/.venv/bin/python zones/dbmanager/app.py` |
| Pool calibration | `pairing_station/.venv/bin/python zones/calibration/app.py` |
| Pool light test | `pairing_station/.venv/bin/python poolzone_test/app.py` |

The component `Launch.command` files provide Finder launchers (`Launch.bat` on Windows). Consult each app's
README/`--help` for port and database overrides. Choose ports on the new machine;
never assume this Mac's `/dev/cu.usbmodem101` or `/dev/cu.usbmodem2101` still applies.
Close Arduino Serial Monitor and any other process holding the same serial port.

For VS Code, open the **repository root**, install the recommended Python/Python
Debugger extensions, and use Run and Debug:

- NCT Console
- Pairing Station
- USB Flash Station
- Zone Flasher
- PoolZone Calibration & Diagnostics
- Poolzone Light Test
- Install prerequisites (both apps)
- Build all firmwares

Some pool launch entries contain explicit example port arguments: change them for
your machine (the Windows variants drop them: pick the port in the app). These configs use
`pairing_station/.venv/bin/python`, or `.venv/Scripts/python.exe` on Windows. The prerequisite
entry creates that environment using `python3` on PATH (`py -3` on Windows) and runs pip; unlike
`Setup.command`, it does **not** verify bundled firmware or synchronize inventory.
Use full setup for a fresh workstation. Check `python3 -m tkinter` if using the
VS Code prerequisite entry with a different interpreter than `python3.14`.

## 4. Transfer the real inventory and private state

A new clone does not contain the original computer's private runtime database.
There are two different transfer mechanisms; choose deliberately.

### Shared Git inventory

`inventory/devices/` contains one JSON record per MAC. It shares device fields and
roles with conflict checks. SQLite remains the local working database.

Close the pairing and cube flashing apps before sync. On the source machine:

```sh
pairing_station/.venv/bin/python scripts/sync_inventory.py
git status --short
```

Review the changed inventory records. Commit/push them through the team's normal
Git workflow when authorized. On the destination, pull the intended revision and
run setup or:

```sh
pairing_station/.venv/bin/python scripts/sync_inventory.py
```

If both machines edited the same MAC the newest change wins, and if two records now
share a cube number or NFC tag (also after Git merged two people's files) the newest
claim keeps it; both are logged as `sync_resolved` events (see the web inventory rules
below). Records are never deleted: a deleted JSON file is restored from SQLite. Clear
nullable fields with `null` when appropriate. A successful
sync does not transmit registrations to cubes or publish the zone database.

Shared inventory is **not** a complete SQLite backup. Local audit events (`nfc_seen`),
flash history, extra metadata, zone state, tokens, and binary backups are not all
represented by per-device JSON. A new machine may therefore show a known mapping
as not yet scanned locally. The four permanent number reservations (2, 22, 39, 43)
are seeded by current code when opening the database.

### Shared web inventory

The web inventory (`web/`, deployed at https://nct-inventory.auroravision.xyz)
holds the same per-MAC records as Git. The two mechanisms interoperate: each keeps
its own baseline in SQLite metadata (`git_inventory_baseline_v1`,
`web_inventory_baseline_v1`), and a change arriving through one is simply a local
change to the other. Run them in any order.

No per-computer setup is needed. All computers use one shared password, which is
never stored in Git or on disk: Web Sync and `scripts/web_sync.py` ask for it each run,
and the other apps' status lines compare only against the last sync. The server reads
it from the `INVENTORY_PASSWORD` Vercel environment variable. The server keeps the
inventory as a single private Vercel Blob JSON document with conditional writes, so
two computers pushing at once are re-checked rather than overwritten.

**Sync now** uploads local changes at any time. Downloaded changes are applied
only while the pairing and cube flasher apps are closed (same locks as Git sync);
otherwise they wait and the apps' status line says so. Sync never needs a decision
(`inventory_sync.merge_records`): a number, tag or role changed on one side only wins
over the other side's bookkeeping change; when both sides changed a device differently,
the newest change to a device wins (its number, tags and their status are taken together; the role merges on its own, the more cautious role winning), and a number or NFC tag claimed by two devices stays with the newest claim, exactly like a local take-over: the other device drops to "needs number" or loses the tag
(`inventory_sync.reconcile`). Each decision is a `sync_resolved` event, every record
written by a sync is a `sync_applied` event, and Sync tells the operator when a device
on this computer gave way. Retransmitting a saved mapping is not a change and never
takes a tag. A local write that lands while a sync is running is merged, not
overwritten, and only one app per computer syncs at a time (`devices.sync.lock`). The
server rejects a push that would create a duplicate number or NFC tag, using the
same rules as `inventory_sync.validate`; the desktop then merges again by itself. The first sync of a fresh database lets
web records replace its untouched original seeds, as the Git sync does.

As with Git, web sync does not transmit registrations to cubes, publish the zone
database, or carry events, flash history, zone state or reservations.

### Preserve complete local SQLite state

Close every app using the shared database before copying
`pairing_station/data/devices.sqlite3`. Keep a destination backup before replacing
an existing database. Do not run a blind file copy of a live SQLite database:
committed data may still be in its WAL.

To create a consistent snapshot while the DB exists, Python's SQLite backup API
can be used (choose a new output filename):

```sh
pairing_station/.venv/bin/python - <<'PY'
from pathlib import Path
import sqlite3
source = Path('pairing_station/data/devices.sqlite3')
target = Path('inventory-private-backup.sqlite3')
if not source.exists() or target.exists():
    raise SystemExit('Source missing or backup filename already exists')
with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
    src.backup(dst)
    print(dst.execute('PRAGMA integrity_check').fetchone()[0])
PY
```

This example creates a private file outside ignored `data/`: move it privately and
**do not commit it**. Prefer storing routine backups inside a private ignored data
folder. Restore only while all destination apps are closed, then reopen and verify
IDs, UIDs, pending states and roles before operating hardware.

Privately transfer relevant evidence as needed:

- `flashing_station/data/`: cube flash receipts, logs and NVS backups.
- `zones/flasher/data/`: zone identities/backups and flashing evidence.
- Calibration firmware-run backups and private build evidence, where required.
- `pairing_station/data/`: scan/audit DB and historical station backup.

Do not copy `.venv`, serial lock files, database instance locks, or `api.curl` as
configuration. Tokens/locks are local runtime artifacts. Preserve source and local
calibration backup evidence; calibration itself can also live in the board's NVS.

## 5. Hardware bring-up checklist

1. Start with automatic flashing and pool output override **disarmed**.
2. Enumerate USB devices and identify roles/MACs. USB paths are not identities.
3. Connect the pairing station separately from the cube. The original station is
   MAC `3C:0F:02:AD:83:24`; preserve its exclusion from cube flashing.
4. Select the correct station serial port and connect. Confirm a fresh hello,
   ESP-NOW channel 2, radio readiness and NFC scanning readiness.
5. Verify an actual known NFC tag read. PN532 firmware/init success alone is not
   evidence that tags can be read.
6. Discover a cube, identify it visually, then run one deliberate registration.
   Require the matching application ACK, not just radio delivery.
7. If using USB cube identification, enable its checkbox, connect the cube, check
   its MAC and firmware result, accept/enter its ID, then unplug if desired. The
   selection remains pinned until Unlock or the next USB cube.
8. Update downstream mappings deliberately: publish to modern NctZone readers or
   export/rebuild legacy fixed-table readers when necessary.

Pairing-station PN532 wiring on the installed hardware: SDA GPIO4, SCL GPIO3,
red board in I²C mode, VCC from station 5V and common ground. The reader power-cycles
with the station. Do not infer that every zone or third-party PN532 board has
identical electrical requirements. See the component firmware and wiring notes.

Only use the cube flasher for a confirmed cube. Zone flashing and pool calibration
have different partition/configuration preservation requirements. Follow their
READMEs; do not substitute a raw erase/write command for the validated pipelines.

## 6. Install the Arduino build toolchain

This is optional when only running apps or flashing verified bundled cube binaries.
A clean clone excludes `live files/libraries/`, `pairing_station/.arduino/`, most
build outputs, and the entire machine's Arduino package installation. Recreate them.

Install Arduino CLI (or Arduino IDE, whose bundled CLI the builders prefer):

```sh
brew install arduino-cli
arduino-cli core update-index --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core install esp32:esp32@3.3.11 --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core list
```

Keep the tested core **3.3.11**. ESP-NOW callback signatures and I²C behavior are
version-sensitive. The build helpers verify the core directory. On macOS they
expect `~/Library/Arduino15/packages/esp32/hardware/esp32/3.3.11` (Windows:
`%LOCALAPPDATA%\Arduino15\...`, Linux: `~/.arduino15/...`; see `hostos.arduino_data_dir`). A custom
Arduino data directory needs corresponding build-helper changes. If IDE and CLI are both
installed, ensure they use the same core installation: the builders prefer
`/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli`.

Install the Arduino libraries into the directories the build scripts use. Two
project-specific CLI config files avoid changing the global sketchbook setting:

```sh
python3 - <<'PY'
import json
from pathlib import Path
root = Path.cwd()
config = root/'pairing_station/.arduino'
config.mkdir(parents=True, exist_ok=True)
for filename, user in [('live-libs.json', root/'live files'),
                       ('station-libs.json', config)]:
    (config/filename).write_text(json.dumps({'directories': {'user': str(user)}}))
PY
arduino-cli --config-file pairing_station/.arduino/live-libs.json lib update-index
arduino-cli --config-file pairing_station/.arduino/live-libs.json lib install 'Adafruit NeoPixel@1.15.5' 'Adafruit PN532@1.3.4' 'Adafruit BusIO@1.17.4' 'VL53L4CD@1.0.0'
arduino-cli --config-file pairing_station/.arduino/station-libs.json lib install 'Adafruit PN532@1.3.4' 'Adafruit BusIO@1.17.4' 'ArduinoJson@7.4.3'
```

The config content is JSON, which is also valid YAML for Arduino CLI's configuration
reader. Libraries go under each selected user directory's `libraries/` folder.
The VL53L4CD library is the **Pololu** implementation (see its `library.properties`);
other vendors' similarly named libraries can have incompatible APIs. If a pinned
version is no longer available from Library Manager, obtain that exact release
from its upstream or an existing verified installation; do not silently switch APIs.
The custom `NctZone` library is already tracked under `zones/firmware/libraries/`.

Library setup is separate from Python prerequisites. `pip install` cannot install
Arduino headers, board packages or the C++ toolchain.

## 7. Build firmware

First inspect the intended targets:

```sh
pairing_station/.venv/bin/python scripts/build_all_firmware.py --dry-run
```

Then build:

```sh
pairing_station/.venv/bin/python scripts/build_all_firmware.py
```

Or choose **Build all firmwares** in VS Code and press F5. Fourteen targets are included (the
`--dry-run` output is the authoritative list); the zone and diagnostic rows below are the main ones:

| Target | Board/settings | Output |
|---|---|---|
| Neocore USB | XIAO ESP32-C3, 4 MB, no OTA; exact FQBN in `flashing_station/core.py` | `flashing_station/build/` |
| PreshowZone | ESP32-C3 SuperMini, CDC on, no OTA | `zones/build/PreshowZone/` |
| TagPlateZone | Same | `zones/build/TagPlateZone/` |
| DesertZone | Same | `zones/build/DesertZone/` |
| ResetZone | Same | `zones/build/ResetZone/` |
| PoolZone | Same, including custom data partitions | `zones/build/PoolZone/` |
| Pairing station | ESP32-C3 dev module, CDC on | `pairing_station/build/` |
| Pool radio diagnostic | ESP32-C3 SuperMini, CDC on, no OTA | `poolzone_test/build/` |
| Pool central diagnostic | ESP32-C3 dev module, CDC on | `poolzone_test/build/central/` |
| Registration console | ESP32-C3 dev module, CDC on | `registration_console/build/` |

The command never uploads. It continues to report other targets if one fails and
returns nonzero if any failed. Only use outputs from successful builds; files from
an older build may still exist after a failure. Cube and zone builders publish
manifests with hashes and check the core/source. Do not launch two builds into the
same output/cache directory concurrently.

Individual builds:

```sh
pairing_station/.venv/bin/python flashing_station/build.py
pairing_station/.venv/bin/python zones/flasher/zone_build.py PoolZone
arduino-cli compile --fqbn esp32:esp32:esp32c3:CDCOnBoot=cdc --libraries pairing_station/.arduino/libraries --libraries zones/firmware/libraries --output-dir pairing_station/build pairing_station/firmware/pairing_station
```

Archived `live files` sketches and duplicate historical root sketches are not all
built by the aggregate command. Their board, pin, library and network assumptions
must be reviewed separately before intentionally reviving one.

## 8. Run tests before hardware work

The same suites run on every push in GitHub Actions on `macos-latest` and `windows-latest`
(`.github/workflows/tests.yml`). On Windows use `pairing_station\.venv\Scripts\python.exe` in the
commands below; the Windows host-firmware step is informative only (MinGW, no sanitizers).

Python suites (no real device required):

```sh
pairing_station/.venv/bin/python -m unittest discover -s pairing_station/tests -p 'test_*.py'
pairing_station/.venv/bin/python -m unittest discover -s flashing_station/tests -p 'test_*.py'
pairing_station/.venv/bin/python -m unittest discover -s zones/tests -p 'test_*.py'
pairing_station/.venv/bin/python -m unittest discover -s zones/calibration -p 'test_*.py'
pairing_station/.venv/bin/python -m unittest discover -s poolzone_test/tests -p 'test_*.py'
pairing_station/.venv/bin/python -m unittest discover -s console/tests -p 'test_*.py'
```

Host firmware simulations (need `c++`; pairing simulation also needs its installed
ArduinoJson headers):

```sh
pairing_station/.venv/bin/python pairing_station/tests/run_firmware_test.py
pairing_station/.venv/bin/python zones/tests/run_firmware_tests.py
pairing_station/.venv/bin/python registration_console/tests/run_tests.py
```

Additional GUI checks:

```sh
pairing_station/.venv/bin/python flashing_station/tests/gui_smoke.py
pairing_station/.venv/bin/python zones/calibration/gui_check.py
```

Tk tests need a real desktop session; sandbox/window-server restrictions can abort
Python before a unittest assertion. HTTP tests need loopback socket access. Use a
suitable execution environment rather than removing these tests. Simulator data
belongs in temporary or simulation databases, never the production inventory.

Scripts named `hardware_check.py`, `e2e_check.py`, `i2c_soak.py` and similar can
command actual lights or change board state. Read them and the component README
before running; they are not substitutes for harmless unit tests.

## 9. Common setup and operation failures

| Symptom | Check / response |
|---|---|
| Missing `_tkinter` or no window | Use a Python with matching Tk; test `python -m tkinter`; use a desktop session |
| `.venv/bin/python` missing | Run setup from the repository root; recreate, don't copy a virtualenv |
| Firmware manifest/hash error | Restore the full verified artifacts or rebuild; do not edit hashes |
| `ArduinoJson.h`, PN532, NeoPixel or VL53L4CD missing | Install Arduino libraries in the two locations above; inspect selected library paths |
| Unexpected ESP32 core | Check IDE and CLI use core 3.3.11 and the expected data directory |
| `read failed: Device not configured` | USB disappeared/re-enumerated; refresh ports and reconnect the correct station |
| Register disabled | Read the reason under Register: station disconnected, NFC unavailable, excluded role, or active operation |
| USB cube identified but Register unavailable | Cube USB is not the NFC station connection; keep/connect the station too |
| Pending mapping after stop | Register can start a fresh scan; Transmit saved mapping retries the saved assignment |
| No tag detected but PN532 initialized | Check actual tag reads/I²C responses; try a known tag, wiring and power, not just cached readiness |
| Port owned by another app | Close Serial Monitor/other controller; respect `PortLock` and pyserial exclusivity |
| API fails | App must be running; use fresh `api.curl`, correct API port, and allowed loopback access |
| A cube lost its number/tag after Sync | Another computer used the same number/tag more recently (see the `sync_resolved` event and the record's detail). Assign the physical label number / register again, then Sync |
| Pool controls appear inert | Check board role, serial connection, calibration validity and explicit override arming |

Do not solve a wrong-port or missing-library problem by erasing hardware, deleting
inventory, disabling protections, or claiming a successful physical test from a
cached status flag.

## 10. Acceptance on the destination machine

Before considering migration complete, record:

- Python executable/version, Tk availability, dependency versions.
- Whether the inventory was synchronized or privately restored; counts and a few
  known MAC/ID/UID mappings; integrity check for restored SQLite.
- Relevant tests and firmware builds actually run, with their results.
- Identified USB roles/MACs and any port changes made to launch configurations.
- For hardware work, separate confirmation of serial response, NFC read, radio
  discovery, registration ACK, physical LEDs, and persistence if tested.
- Any remaining limitations (headless GUI, unbuilt targets, untested hardware).

A workstation can be ready for coding before every hardware acceptance step is
possible. State precisely what is ready instead of implying unperformed checks.
