# Neocore USB Flash Station

Double-click **Launch.command** (Windows: **Launch.bat**). The separate Tkinter window shares the device studio's SQLite inventory. **Auto starts disarmed.** The attached registration station (`3C:0F:02:AD:83:24`) is protected by USB identity before its serial port is opened, and by MAC before any write. Do not use it as a test cube.

## Flash cubes

1. Connect a XIAO ESP32-C3 cube using a USB data cable.
2. Click **Arm Auto** to process eligible attached and newly connected cubes, or select a USB row and click **Flash selected / Retry**.
3. Wait for the green success message and ascending completion sound. Success requires firmware verification, unchanged registration storage, and a matching firmware/MAC/channel/ready response after reboot.
4. Unplug the cube and connect the next one. Leave an empty USB location disconnected for at least two seconds when its adapter has no unique serial number.

The app runs one upload at a time. Known station/reader identities and excluded database roles are blocked. Other recognized USB serial adapters are candidates: USB identity alone cannot prove an unprogrammed ESP32-C3 is physically a cube. Auto treats eligible connected boards as intended targets.

A successful MAC/build combination is skipped on subsequent automatic attempts, including after restarting the app. Manual flashing deliberately permits a repeat. Failures do not loop; inspect the result and select Manual Retry. **Stop after current** disarms intake while allowing the active operation to finish. Closing also waits for active work.

Select a history row to inspect its outcome and NFC mapping. For `boot_unconfirmed`, select that result and its connected USB row, then **Check boot of selected result**; this does not reflash. **Recover saved results** imports a completed local receipt if the database save failed. Logs and NVS backups remain under `data/runs/<attempt-id>/`.

Audio cues cover connection, start, progress, success and failure. Mute, volume and a test sound are available. Audio is nonblocking and optional.

## Firmware

The supplied build is **v1.4.1-USB.2**, derived from `live files/neocore_cube_OTA_1.4/neocore_cube_OTA_1.4.ino` (v1.4.1-STABLE-TEST). It removes the ArduinoOTA service, Wi-Fi credentials and access-point connection attempts. ESP-NOW uses fixed channel 2. The original show timeline, LED limits, registration NVS layout and packet numbers remain; packet type 5 is reserved and ignored.

A USB `?` query reports firmware version, station MAC, ESP-NOW channel and readiness. It only reports ready after ESP-NOW initialized successfully.

Build target: `esp32:esp32:XIAO_ESP32C3:CDCOnBoot=default,PartitionScheme=no_ota,FlashSize=4M`, Arduino-ESP32 **3.3.11**, esptool **5.3.1**, bundled Adafruit NeoPixel library. Click **Rebuild firmware** after editing the maintained USB-only source. No Internet firmware discovery occurs. SHA-256 checks reject modified or stale artifacts.

The uploader writes bootloader, partition table, boot selection data and application separately, never a full-chip erase. NVS at `0x9000`, length `0x5000`, is backed up and compared after writing, before boot. Blank flash and the compatible NVS layout are supported; unfamiliar layouts stop before upload. Other filesystem partitions are not promised preservation when moving to this no-OTA layout. Secure-boot/encryption protections are not bypassed.

## Shared inventory

The default database is `../pairing_station/data/devices.sqlite3`. New target MACs receive the next cube ID and `awaiting_tag` with NFC unknown. This is a database reservation only: flashing does not send that ID or an NFC tag to the cube. Complete registration through the pairing app later. Existing database mappings and device NVS registrations are preserved.

Both apps may run together. Atomic ID allocation, WAL, bounded SQLite waits, CSV export locking, and shared serial-port ownership prevent competing updates. Restart the pairing app when convenient to load its new station-identity persistence and shared port-lock code; its currently running session was not interrupted. Pyserial exclusive ownership and the built-in station exclusion protect the current station in the meantime.

Flash results have their own `flash_runs` table and never replace NFC registration statuses. Back up the database with its WAL/SHM files while running, or close both apps before copying the database alone.

## Development and validation

The launcher reuses `../pairing_station/.venv` (Python 3.14, Tk and pyserial 3.5). Arduino CLI is resolved from the installed Arduino IDE, with a PATH fallback. Audio cues use `afplay` on macOS and `winsound` on Windows. Flashing runs the Python `esptool_entry.py` launcher, which explicitly loads esptool 5.3.1 from the project environment, avoiding the slow startup of Arduino’s bundled executable. Install dependencies with `../pairing_station/.venv/bin/pip install -r requirements.txt`.

From the workspace root:

```sh
pairing_station/.venv/bin/python flashing_station/build.py
pairing_station/.venv/bin/python -m unittest discover -s flashing_station/tests -v
pairing_station/.venv/bin/python -m unittest discover -s pairing_station/tests -v
pairing_station/.venv/bin/python flashing_station/tests/gui_smoke.py
pairing_station/.venv/bin/python flashing_station/app.py --simulate
```

Simulation uses `flashing_station/data/simulation.sqlite3` and no serial hardware. The GUI acceptance test uses a temporary database. `--database PATH` selects a different inventory; do not use the production database for simulation.

The USB firmware compiles and automated tests cover database concurrency, pending-pairing preservation, automatic intake, deduplication, protected devices, partition checks, upload failure, boot uncertainty, and GUI auto/manual operation. **A physical upload on test cube AC:27:6E:82:A0:94 completed successfully in 12.58 seconds, including firmware verification, unchanged NVS and confirmed boot.** The registration station remains protected. LED, radio and show behavior still require their own validation.

The flashing path keeps the bootloader helper running between its four hardware commands (preceded by a hardware-free tool-version check), combines partition/NVS backup reads, and logs command durations. Hash verification and NVS preservation checks are retained.

Native USB-Serial/JTAG cubes use a watchdog reset and a monitor open with DTR/RTS released; external UART adapters retain the normal hard-reset sequence. The measured complete USB workflow improved from 99s to 12.58s on the test cube.

`v1.4.1-USB.2` flashes white three times at startup (RGB 30, 150 ms on / 150 ms off), before starting the radio, then returns to the normal dim-white idle state. The marker adds 0.9 seconds to startup.

The MAC is read by esptool from the ESP32 bootloader before writing; the cube does not need Neocore firmware installed. If the tool cannot start, the app now reports the dependency/runtime error instead of treating it as a missing MAC.

## Recognizing connected devices

The connected-device panel prominently shows the current cube number and bolds known devices in the USB list. Native USB MAC identities are looked up immediately, before uploading or opening the serial port. The original-32 number is shown separately from the current database assignment. A cleared current number is labelled as unassigned; its original number is historical and is not restored automatically. Saved devices without a number show **KNOWN DEVICE**. Other adapters update their identity after the bootloader reports a MAC. Database number changes made in the pairing app appear on the next USB-list refresh.
