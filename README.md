# Jinhee SOS

Python desktop tools and ESP32 firmware for Neocore cubes, the NFC pairing station, and exhibition zones.

**Coding agents:** start with [AGENTS.md](AGENTS.md). For a complete new-machine setup, inventory migration, firmware builds, tests and troubleshooting, use [docs/SETUP.md](docs/SETUP.md).

## Flash cubes on another Mac

Install Git and Python 3.14 with Tk (using Homebrew):

```sh
brew install git python@3.14 python-tk@3.14
git clone https://github.com/elliotwoods/jinhee-sos.git
cd jinhee-sos
./Setup.command
./flashing_station/Launch.command
```

Setup creates a local Python environment, installs pinned dependencies, and verifies the included firmware hashes. An internet connection is needed for setup. Arduino is **not required** to flash the included cube firmware.

1. Connect a Neocore cube using a USB data cable.
2. Check the detected device and its prominently displayed database/original number.
3. Use manual flashing first. Enable automatic flashing when ready to process cubes as they are connected. Automatic flashing starts disarmed each time the app opens.
4. Wait for the success indication and audio cue before disconnecting the cube.

The bundled firmware is **v1.4.1-USB.2**, for XIAO ESP32-C3 / 4 MB, with ESP-NOW on channel 2 and no OTA upload feature. It includes three short white startup flashes. USB upload, preserved NVS settings, and station-controlled red/blue LEDs were verified on a physical cube. The startup marker has not yet been independently confirmed through a cold power cycle.

The flasher preserves NVS, verifies uploaded data, records the MAC, and registers cubes with NFC unknown when no NFC mapping exists. Known registration stations are protected from cube flashing; keep the station separate from the cube flashing workflow.

## Share the inventory through Git

The public `inventory/devices/` directory has one JSON record per MAC, including cube number, NFC mapping, pending state, and device role. SQLite remains the local working database. Setup imports the shared inventory automatically.

**Close both desktop apps before synchronizing.** After provisioning on any computer:

```sh
pairing_station/.venv/bin/python scripts/sync_inventory.py
git add inventory/
git commit -m "Update device inventory"
git pull --no-rebase
pairing_station/.venv/bin/python scripts/sync_inventory.py
git push
```

Different MACs merge automatically. If both computers change the same device, Git deliberately reports a conflict: edit that device's JSON to the correct complete record, `git add` it, and finish the merge with `git commit`. Run sync again before reopening the apps. Duplicate cube numbers or NFC tags across devices stop import with an actionable error; correct the JSON and retry. Existing unexported local edits also cause an explicit conflict instead of being overwritten.

Shared inventory uses physical label numbers assigned explicitly in the pairing app, avoiding independent computers assigning the same next number. Clear fields with `null`; deleting a device file is deliberately unsupported. Sync does not transmit changes to cube firmware; use the pairing app when a registration needs transmission. Git sync requires no connected hardware.

Runtime SQLite files, API tokens, logs, and flash backups stay private. Git contains MAC/NFC mappings intentionally. Flash history and backups can be transferred separately by privately copying `flashing_station/data/` with the apps closed.

## Share the inventory through the web

The same records can also be kept in step through a small web service ([web/](web/README.md)), so computers stay current without commit/pull. It works alongside Git sync: both exchange identical records and keep separate baselines, so they can run in any order.

```sh
./inventory_web/Launch.command
```

The app asks for the shared web inventory password each time it opens (it is never saved; ask the team for it). Click **Sync now**. Local changes upload; web changes download. Web changes are written locally only while the pairing and cube-flasher apps are closed; otherwise they wait for the next sync. The read-only web view is https://nct-inventory.auroravision.xyz: sign in with the same password to see devices, recent changes and **Last seen** (which computer and app last contacted the inventory, and how long ago).

If the same device changed on this computer and on the web, the app lists a conflict and changes nothing until you choose **keep local** or **take web** for it. The pairing, cube-flasher, zone-flasher and calibration apps show a one-line web inventory status (up to date / newer web changes / local changes not uploaded / offline). They never block or fail when the web is unreachable. Headless equivalent: `pairing_station/.venv/bin/python scripts/web_sync.py status|sync`.

## Applications and source

- [Cube flasher](flashing_station/README.md): manual/automatic upload, identity display, audio, and recovery backups.
- [Web inventory](web/README.md): shared web copy of the inventory; desktop sync app in `inventory_web/`.
- [Pairing station](pairing_station/README.md): NFC registration and radio LED tests. Launch with `./pairing_station/Launch.command` after setup.
- [Zone tools](zones/README.md): zone firmware, database distribution, and a separate zone flasher. Zone firmware needs its own build; only cube binaries are bundled here.
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
