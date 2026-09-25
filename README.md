# Jinhee SOS

Python desktop tools and ESP32 firmware for Neocore cubes, the NFC pairing station, and exhibition zones.

**Coding agents:** start with [AGENTS.md](AGENTS.md). For a complete new-machine setup, inventory migration, firmware builds, tests and troubleshooting, use [docs/SETUP.md](docs/SETUP.md).

## Install the NCT Console (standalone app)

Operators only need the standalone app. Download it from the
[GitHub releases page](https://github.com/elliotwoods/jinhee-sos/releases) (latest `console-v…` release). No Python,
Git or Arduino software is needed, and every maintained firmware is included, prebuilt and verified.

- **Mac** (Apple Silicon, macOS 13 or later): open `NCT-Console-<version>.dmg` and drag **NCT Console** to
  Applications. It is signed and notarized, so it opens without a security warning.
- **Windows** (x64, Windows 10/11): unzip `NCT-Console-<version>-windows-x64.zip` somewhere permanent (for example
  `C:\NCT Console`) and run `NCT Console.exe`. It is not code-signed yet: at the first start SmartScreen says
  *Windows protected your PC*; click **More info → Run anyway**. It needs the Microsoft Edge WebView2 runtime
  (already on Windows 11).

Each computer starts with its own device database (holding only the 32 original mappings), in `~/Library/Application Support/NCT Console` (Mac) or
`%LOCALAPPDATA%\NCT Console` (Windows). Enter the shared web password when the console asks and the inventory
downloads. Installing a newer release replaces the program files and keeps the database, password, flash runs and
backups. The app never compiles firmware: new firmware comes with a new app release. The handover PDF
(`NCT_Console_Handover_v2_<build>.pdf`) is attached to the same release.

## Run from a checkout (developers)

Install Git and Python 3.14 with Tk (using Homebrew):

```sh
brew install git python@3.14 python-tk@3.14
git clone https://github.com/elliotwoods/jinhee-sos.git
cd jinhee-sos
./Setup.command
./console/Launch.command
```

On **Windows**: install Python 3.14 from python.org (with tcl/tk) and Git, clone, then double-click `Setup.bat` and
`console\Launch.bat`. Windows is ported and CI-tested but not yet bench-tested: see
[docs/SETUP.md section 2b](docs/SETUP.md#2b-prepare-a-windows-pc). Wherever this page says
`pairing_station/.venv/bin/python`, use `pairing_station\.venv\Scripts\python.exe`.

Setup creates a local Python environment, installs pinned dependencies, and verifies the included firmware hashes. An internet connection is needed for setup. Setup also installs the Arduino firmware toolchain (Arduino CLI, ESP32 core 3.3.11, pinned libraries) and rebuilds any firmware that is missing or out of date; that part is optional (`--no-firmware` skips it) and Arduino is **not required** to flash the included cube firmware. Building the standalone apps and publishing a release: [docs/SETUP.md](docs/SETUP.md) and `packaging/`.

## Flash cubes

In the console, open **Flash** (⌘2) and turn it on; every cube plugged in then gets the current firmware and the published main show over USB. The older separate cube flasher (`./flashing_station/Launch.command`) still works from a checkout:

1. Connect a Neocore cube using a USB data cable.
2. Check the detected device and its prominently displayed database/original number.
3. Use manual flashing first. Enable automatic flashing when ready to process cubes as they are connected. Automatic flashing starts disarmed each time the app opens.
4. Wait for the success indication and audio cue before disconnecting the cube.

The bundled firmware is **v1.7.0-USB.1** (v1.5.0 made the show data; v1.6.0 adds per-cube fanning; v1.7.0 lets bench cubes mirror the Show editor live), for XIAO ESP32-C3 / 4 MB, with ESP-NOW on channel 2 and no OTA firmware upload. It includes three short white startup flashes. Its compiled-in main show is identical to v1.4.1's hard-coded timeline (proved frame by frame in the firmware tests); a newer show published from the console's **Show editor** reaches it over the air (not a firmware update) and is kept in NVS. It also joins a running show from the controller's timecode if it missed the start. Older controllers keep working unchanged. USB upload, preserved NVS, the old show start, the timecode join and the wireless show update were verified on cube #17 (see [flashing_station/README.md](flashing_station/README.md)).

The flasher preserves NVS, verifies uploaded data, records the MAC, and registers cubes with NFC unknown when no NFC mapping exists. Known registration stations are protected from cube flashing; keep the station separate from the cube flashing workflow.

## Share the inventory through the web

Every computer keeps its device records in step through a small web service ([web/](web/README.md)). It is the only shared copy of the inventory: the Git inventory (`inventory/devices/`, `scripts/sync_inventory.py`) was retired on 23 September 2026. The NCT Console syncs by itself (Settings › Automatic updates); the separate Web Sync app below does the same by hand.

```sh
./inventory_web/Launch.command
```

Enter the shared web inventory password once when asked (ask the team for it); it is stored on this computer in `pairing_station/data/web_password`, outside Git, and every app reuses it. Click **Sync now**. Local changes upload; web changes download. Web changes are written locally only while the pairing and cube-flasher apps are closed; otherwise they wait for the next sync. The read-only web view is https://nct-inventory.auroravision.xyz: sign in with the same password to browse cubes as a grid or table with search and filters, see when and how each cube was last seen (radio, NFC, USB, zone taps), and see computers, zone boards and recent activity. Cube sightings are uploaded whenever a computer runs Web Sync.

Sync never stops to ask for a decision. If the same device changed on this computer and on the web, the newest change to a device wins (its number, tags and their status are taken together; the role merges on its own, the more cautious role winning), and a number or NFC tag claimed by two devices stays with the newest claim, exactly like a local take-over: the other device drops to "needs number" or loses the tag. Every such decision is logged as a `sync_resolved` event, and when a device on this computer gives way, Sync says so afterwards (that cube stays out of the zone database until it is numbered/registered again). To reverse a decision, make the change again on either computer and Sync. A failed or interrupted Sync never loses anything: click Sync again. The pairing, cube-flasher, zone-flasher and calibration apps show a one-line web inventory status (up to date / newer web changes / local changes not uploaded / offline). They never block or fail when the web is unreachable. Headless equivalent: `pairing_station/.venv/bin/python scripts/web_sync.py status|sync`.

## Applications and source

- **NCT Console** (`./console/Launch.command`, [console/README.md](console/README.md)): every tool below in one window. Boards are identified when plugged in, tasks start from the device, and situations the console can explain (an unknown tag that is registered here but missing from a plate's older database, a stale firmware, a reader fault…) appear as suggestion cards with one-click actions. It keeps every database current on its own (zone databases over the air and over USB, the main show over the air, newer publications pulled from the web); switch any of it off in Settings › Automatic updates. **Flash cubes** (⌘2) brings cubes up to date one after another as they are plugged in: every cube gets the current firmware and the published main show over USB (off at every launch). **Register** (⌘3) registers cubes the same way: it gives a new cube the next number to write on its label, asks for its tag at the pairing station and syncs. The interface can be switched between English and Korean (EN | KR, top right). `--simulate` runs it without hardware. The separate apps still work; they cannot run at the same time as the console on one database.
- [Cube flasher](flashing_station/README.md): manual/automatic upload, identity display, audio, and recovery backups.
- [Web inventory](web/README.md): shared web copy of the inventory. Every app that uses the device database has the same **Sync** button: `⟳ Sync ↑3 ↓2` means 3 things to upload and 2 to download (inventory changes and the zone database). One click does both directions, and publishes a new zone database only when the cube mappings changed. The password is asked for once and stored on this computer (outside git). The **Web Sync…** view (`inventory_web/`) holds the manual operations: check, upload only, download only, publish/pull the zone database, and a record-by-record view of what a sync moves and what it decided.
- [Pairing station](pairing_station/README.md): NFC registration and radio LED tests. Launch with `./pairing_station/Launch.command` after setup.
- [Zone tools](zones/README.md): zone firmware, database distribution, and a separate zone flasher (which also updates the cube database on any zone board plugged into it, automatically by default). Zone firmware needs its own build; only cube binaries are bundled here.
- **Mainshow Controller**: `./zones/mainshow/Launch.command`. Uses a spare ESP32-C3 dongle flashed as the show trigger (**Flash controller firmware…**). **① Mainshow ready** turns a cube neon; **② Trigger mainshow** starts its show timeline (one cube, or broadcast to every ready cube). The board's BOOT button and trigger input (XIAO D1 to GND) start the show without a computer. See [zones/mainshow/README.md](zones/mainshow/README.md).
- **Show editor** (NCT Console › Show editor): the main show as a list of cues (solid, fade, blink, pulse, cycle, random) on a timeline with a preview that renders exactly what a cube plays. Every cube gets the same show; **Preview cubes** (e.g. `1-8`) shows several cube numbers side by side, and **Fanning** on a fade/blink/pulse/cycle cue offsets each cube by its number (sequential steps or a scatter) so the show ripples across the cubes. **Publish** gives the show the next web-allocated version; **Update all** (or **Auto update**) sends it to cubes in range through a Workstation (or a legacy General Radio, general-radio-1.2.0). Cubes need firmware v1.5.0 once, over USB. A cube never switches shows mid-show.
- **Workstation**: one ESP32-C3 for every ESP-NOW function (relay, cube zones, show start and timecode, main-show updates, a pool lamp, a TouchDesigner cue) plus the pairing station's NFC reader, with a Python client and bench command line (`zones/tools/workstation.py`); see [zones/firmware/Workstation/README.md](zones/firmware/Workstation/README.md). It merges the pairing-station and General Radio firmwares; boards still running either (the installed station on nct-pairing-1.8-zones, general-radio-1.x dongles) keep working but are no longer flashed. The GUI apps below accept it in place of their own dongle.
- **Zone Database Manager**: `./zones/dbmanager/Launch.command`. Plug in an ESP32-C3 as an ESP-NOW dongle (**Flash dongle…** installs the Workstation firmware). The app shows every zone in range with its database version. Update a selected zone, **Update all** out-of-date zones in range, or turn on **Auto update all** and walk the space to update everything out of date automatically. A progress window blocks the main window while an update runs. Its **Sync** button, like the one in every app, syncs the web inventory and publishes the zone database; the web allocates the version, so versions only increase across computers. The **Signal** column shows each zone's signal (▂▄▆ strong, ▂▄· fair, ▂·· weak) with dongle firmware nct-pairing-1.7 or later, a General Radio or a Workstation. Existing zone firmware is unchanged. See [zones/README.md](zones/README.md#update-zones-over-the-air-zone-database-manager).
- [Registration console](registration_console/README.md): firmware-side registration utility.
- `live files/`: legacy exhibition sketches. Network credentials are replaced with placeholders in this public copy.

Internal exhibition PDFs and generated documents are not distributed here. This repository starts with a clean public history; older local commits contained installation credentials.

## Rebuilding cube firmware (optional)

Install Arduino IDE / Arduino CLI, Espressif ESP32 core **3.3.11**, and Adafruit NeoPixel **1.15.5**. The build expects the Arduino libraries under `live files/libraries/` (create that directory and install/copy the library there). See `flashing_station/build.py` for the exact board and partition settings. The macOS Arduino package directory is used by the build helper.

```sh
pairing_station/.venv/bin/python flashing_station/build.py
```

The bundled binaries include third-party components; see [THIRD_PARTY.md](THIRD_PARTY.md).

## Tests (no connected hardware required)

```sh
pairing_station/.venv/bin/python -m unittest discover -s flashing_station/tests -p 'test_*.py'
pairing_station/.venv/bin/python -m unittest discover -s pairing_station/tests -p 'test_*.py'
pairing_station/.venv/bin/python flashing_station/tests/gui_smoke.py
```

GUI tests require a desktop session and use simulated devices.

## Pool central controller

[Pool central](zones/firmware/PoolCentral/README.md) is the ESP32-C3 that listens to the six PoolZone slider radios and
drives the 23 member frame lights through two PCA9685 boards. A frame is lit while **any** radio holds that member. It
replaces the archived `live files/PoolZone_Central_Controiler`.

The radios and the central are a **matched set** and must be reflashed together; flash the central first, since it still
accepts the old packet while the sliders are updated one at a time. Their link is defined once in
[`NctPoolProtocol.h`](zones/firmware/libraries/NctZone/src/NctPoolProtocol.h) — see
[zones/README.md](zones/README.md) for how it works.

[Poolzone test console](poolzone_test/README.md) provides a USB ESP32-C3 bridge and Python GUI that emulates all six
radios, for exercising the lights without sliders. Run `./poolzone_test/Launch.command` for member toggles, sequential
testing, and All Off.

## ESP-NOW range test

[Range test](rangetest/README.md) measures link reliability between the exhibition space and the back room on channel 2, using two cube-identical XIAO ESP32-C3 boards. Carry the blue TX unit and read its LEDs; the red RX unit stays in the back room and answers every ping with the RSSI it measured. Run `./rangetest/Launch.command --rx /dev/cu.usbmodemXXXX` to capture the survey.
