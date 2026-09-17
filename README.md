# Jinhee SOS

Python desktop tools and ESP32 firmware for Neocore cubes, the NFC pairing station, and exhibition zones.

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

## Applications and source

- [Cube flasher](flashing_station/README.md): manual/automatic upload, identity display, audio, and recovery backups.
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

## Poolzone central light test

[Poolzone test console](poolzone_test/README.md) provides a USB ESP32-C3 bridge and Python GUI for the legacy central controller on ESP-NOW channel 2. Run `./poolzone_test/Launch.command` for member toggles, sequential testing, and All Off.
