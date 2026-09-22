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

The previous build, **v1.4.1-USB.2**, was derived from `live files/neocore_cube_OTA_1.4/neocore_cube_OTA_1.4.ino` (v1.4.1-STABLE-TEST). It removes the ArduinoOTA service, Wi-Fi credentials and access-point connection attempts. ESP-NOW uses fixed channel 2. The original show timeline, LED limits, registration NVS layout and packet numbers remain; packet type 5 is reserved and ignored.

**v1.5.0-USB.1** (2026-09-23) makes the main show data. Registration, zones, `MSG_SHOW_START` and the packet ABI are unchanged.
- The compiled-in `DefaultShow.h` is generated from `shows/mainshow.json` (`python pairing_station/showfile.py --header`) and renders v1.4.1's hard-coded timeline exactly: `zones/tests/test_ShowEngine.cpp` compares them every millisecond of the show.
- A newer show published from the console's Show editor arrives over ESP-NOW (`SHOW_ANNOUNCE`/`SHOW_CHUNK`, `zones/firmware/libraries/NctShow`), is checked (CRC, format) and kept in NVS namespace `show` (keys `img`, `ver`, `crc`; the `cube` registration keys are untouched). A torn or invalid stored show falls back to the compiled-in one. Only a higher version is accepted (FORCE: unicast only), and never while a show is running: a complete update waits for the show to end.
- `SHOW_TIMECODE` from mainshow-1.3.0 / general-radio-1.1.0: a mainshow-ready cube that missed the start joins at the broadcast time, and a running cube corrects drift above 100 ms.
- The build now also compiles `zones/firmware/libraries/NctShow` (`build.py --library`), and the manifest's `source_hash` covers the sketch, `DefaultShow.h` and NctShow.
- Updating the fleet: flash v1.5.0 once over USB (the normal pipeline; bootloader and partition table are byte-identical to v1.4.1, only the app changes). Later shows go over the air.

Hardware check on cube #17 (1C:DB:D4:F0:A8:30), 2026-09-23. All results are from serial logs; the LEDs were not watched.
- USB flash succeeded with NVS preserved (run `07f6136475b14697ba39dda34f80fce3`).
- An old-style SET_ZONE 4 + SHOW_START started the show, repeats were ignored, and SET_ZONE 0 stopped it.
- A unicast show start while the cube was idle was ignored; made ready afterwards, it joined from the timecode (T = 3131 ms).
- The wireless update of a 516-byte show (3 chunks) was confirmed about 0.3 s after sending.
- A second update was held by the host while a show ran; with the cube still playing, it was staged and committed when the cube went idle.
- The stored show survived a watchdog reset.
- The cube was left holding show v2 (content identical to the default).

**v1.6.0-USB.1** (2026-09-23) adds **fanning**: a fade/blink/pulse/cycle cue can offset each cube by its registered number (sequential: step × position in a repeating group; scatter: a fixed pseudo-random offset within a spread), so one show ripples across the cubes while every cube still receives the same show. A cube with no number has no offset; the number follows re-registration. v1.5.0 refuses a fanned show (the byte was reserved) and keeps its current one; unfanned shows are byte-identical. Hardware check on #17: flashed with NVS preserved (run `8ef8975de7ac4bc397e9c2bc3d7a15a2`), kept show v2, accepted a fanned show v3 and then v4 (default content) over the air; it now holds v4.

**v1.7.0-USB.1** (2026-09-23) adds **live authoring**: `SHOW_LIVE` (0x55), broadcast by the Show editor about 20 times a second through general-radio-1.2.0, lists registered cube numbers with a colour each. A registered cube that finds its number shows that colour for the frame's lease (clamped to 1–2000 ms; the first entry for its number wins, a frame without its number leaves the lease running) and, when the lease lapses, restores exactly the colour it showed when live mode began (zone colour, idle, or off after a show end). `currentZone` never changes. A cube playing a show or without a number ignores the frame; `SET_ZONE` (restores, then applies the zone), `REGISTER`, `SHOW_START` and a timecode join end live mode. Live frames use their own one-deep queue that a newer frame overwrites, so they never crowd out show-update chunks; `ShowFrame` now holds a full 247-byte live frame. Older cubes drop the frame. Host tests: `zones/tests/test_NeocoreShow.cpp`. Hardware check on #17, 2026-09-23 (serial logs only; LEDs not watched): live mode started and ended with the lease, frames without #17's number were ignored, a unicast live frame was refused by the radio (broadcast only), a running show ignored live frames, and the console's Show editor mirrored to it through `show.live`. #17 is the only cube on v1.7.0; the rest of the fleet is still on v1.4.1-USB.2.

A USB `?` query reports firmware version, station MAC, ESP-NOW channel, the active show (`SHOW: v=<n> crc=<hex> src=builtin|nvs`, v0 = compiled-in) and readiness. It only reports ready after ESP-NOW initialized successfully.

Build target: `esp32:esp32:XIAO_ESP32C3:CDCOnBoot=default,PartitionScheme=no_ota,FlashSize=4M`, Arduino-ESP32 **3.3.11**, esptool **5.3.1**, bundled Adafruit NeoPixel library. Click **Rebuild firmware** after editing the maintained USB-only source. No Internet firmware discovery occurs. SHA-256 checks reject modified or stale artifacts.

The uploader writes bootloader, partition table, boot selection data and application separately, never a full-chip erase. NVS at `0x9000`, length `0x5000`, is backed up and compared after writing, before boot. Blank flash and the compatible NVS layout are supported; unfamiliar layouts stop before upload. Other filesystem partitions are not promised preservation when moving to this no-OTA layout. Secure-boot/encryption protections are not bypassed.

### Show stage (NCT Console only)

`Flasher.execute(..., show=None, show_only=None)` can also bring the cube's main show up to date over USB. The Tk flasher does not pass a show and behaves exactly as before; the console's Flash page, Cube panel › Firmware › Flash and **Update show over USB** do.

- With `show` (the published show: version, CRC, image) the stage reads NVS (`0x9000`, `0x5000`) after the firmware step, also when auto mode skipped the firmware because this MAC already has this build. If the NVS show is missing, older or damaged (CRC mismatch), it writes `nvs.with_show(...)` to `0x9000`, reads it back byte for byte, checks that nothing outside namespace `show` changed, resets, and the boot check additionally requires `SHOW: v=<n> crc=<8 hex> src=nvs` in the `?` reply.
- `show_only=<firmware version the cube reported>` writes only the show; firmware is untouched.
- Result (`flash_runs.show_result`, with `show_version`; migrated in `core.Store`): `current` (already held), `written`, `newer` (the cube holds a newer show than the published one and is left alone), `unsupported` (firmware older than v1.5.0 cannot hold a show).
- Run-folder files: `nvs-show-before.bin`, `nvs-show.bin` (what was written), `nvs-show-after.bin`. A failure after the NVS write starts is result `attention`; its detail names `nvs-show-before.bin` for restoring.

`nvs.py` is a pure-Python reader/writer for ESP-IDF NVS format-2 partitions: `parse(image)` → `(namespaces, entries)`, `build(namespaces, entries)`, `show_of(image)`, `with_show(image, version, crc, img)` (replaces only `show`'s `ver`/`img`/`crc` and keeps every other value: `cube`/`cubeID`, `uidLen`, `uid`, PHY calibration, Wi-Fi/BT driver state) and `same_except_show(a, b)`. It raises `NvsError` on anything it cannot parse completely (any page, entry or data CRC mismatch, freeing/corrupt page states, unknown types), so it never rewrites a partition it does not fully understand. `build()` output is byte-identical to Espressif's `esp-idf-nvs-partition-gen` 0.3.0 (SHA-256 vectors in `tests/test_nvs.py`), and every local NVS backup under `data/runs` (342 at writing) parses and round-trips; that test runs only where backups exist, since they are private and never committed. The official generator is not used at runtime: it drops Wi-Fi station keys (`sta.pswd`).

## Shared inventory

The default database is `../pairing_station/data/devices.sqlite3`. New target MACs receive the next cube ID and `awaiting_tag` with NFC unknown. This is a database reservation only: flashing does not send that ID or an NFC tag to the cube. Complete registration through the pairing app later. Existing database mappings and device NVS registrations are preserved.

Both apps may run together. Atomic ID allocation, WAL, bounded SQLite waits, CSV export locking, and shared serial-port ownership prevent competing updates. Restart the pairing app when convenient to load its new station-identity persistence and shared port-lock code; its currently running session was not interrupted. Pyserial exclusive ownership and the built-in station exclusion protect the current station in the meantime.

Flash results have their own `flash_runs` table (including `show_result`/`show_version` from the show stage) and never replace NFC registration statuses. Back up the database with its WAL/SHM files while running, or close both apps before copying the database alone.

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
