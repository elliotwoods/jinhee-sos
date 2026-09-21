# NCT NFC pairing station

Double-click **Launch.command** to open the Python GUI and connect to the detected USB station. If needed, select the station USB port and click **Connect**. A discovery round runs on connection; click **Discover** to refresh it. The station uses ESP-NOW channel 2 and the PN532 on SDA GPIO4 / SCL GPIO3. The GUI should say `Connected · NFC ready`.

## Existing devices

The original 32 UID–MAC–ID mappings are imported once, as trusted mappings with `not_transmitted` status. Click **Transmit existing 32** to send each registration directly to its MAC. The cube should blink green twice after processing it. An offline device is retried three times, marked `unconfirmed`, and skipped so the batch can continue.

Use **Transmit selected** for one mapping and **Retry unconfirmed** for failed/interrupted transactions. No tag scan is necessary to retransmit a stored mapping. If an original mapping has subsequently been changed, the original-32 button refuses to overwrite that change; transmit the current selected mapping instead.

**Flash selected** alternates a cube's existing red/blue colours until stopped. **Flash all sequentially** flashes each database device for two seconds and returns it to dim static white before advancing. Use **Pause / Stop** to stop an operation and attempt to restore the active cube to white. These zone commands interrupt a running show.

## Pair new devices

1. Power the cubes, connect the station, and click **Start pairing new**.
2. The app repeatedly discovers compatible cubes and selects a new MAC. Existing imported mappings are skipped. New cube IDs are assigned automatically on first discovery, starting after the highest saved ID (initially 33), and retained across restarts and retries. Excluded readers and the station do not receive cube IDs. Numbered devices remain unregistered until their NFC tags are paired.
3. Find the cube flashing red/blue. Remove anything already on the NFC reader, then place that cube's tag on it.
4. Registration happens automatically. Wait for the acknowledgment and green confirmation blink.
5. Remove the tag. The selected cube returns to static white and the next new device is selected.

Use **Re-pair selected** to deliberately change an existing device's tag while preserving its cube ID. Scanning a tag already assigned or reserved to another cube transfers its local association to the selected cube. **Retry paused** reuses an unconfirmed saved registration, or starts a fresh scan after a tag conflict. **Skip** moves on. After stopping, use **Start pairing new** to resume; pending registrations are recovered through **Retry unconfirmed**.

The clear-reader check is enforced in the station: a tag held over the reader cannot accidentally be reused for the next cube. Only 4-byte and 7-byte NFC UIDs are accepted, matching the cube packet capacity.

## Data and exports

- `data/devices.sqlite3` is the authoritative database. Keep it and its `-wal`/`-shm` files together while the app is running; close the app before copying the database alone.
- `data/devices.csv` is automatically refreshed after database changes and opens in spreadsheet software. **Export CSV…** saves another copy. Spreadsheet edits do not change the database.
- `pending_uid` retains a proposed UID until acknowledgment. For an existing mapping, the prior `uid` is retained until the replacement is acknowledged.
- **Export reader table…** produces a `CubeTable.h` with the current committed mappings. Pending replacement UIDs and newly pending devices are excluded. Replace the entrance-reader's existing `CubeRecord`, `cubeTable`, and `CUBE_COUNT` definitions with this header/include, then rebuild that reader when mappings change. Its radio must also be on channel 2.
- **Zones → Zone Database Manager…** opens the separate manager (`zones/dbmanager/`), which updates zones over its own ESP-NOW dongle. The station itself can serve as the dongle while this app is disconnected from it. Station firmware `nct-pairing-1.7-zones` adds signal strength; `1.8` adds zone RX gain control. See `zones/README.md`.
- **Sync** in the footer uploads and downloads the web inventory and publishes the zone database; web changes are written here only while no registration is running.
- `original_32.json` preserves the original mappings. It is not reimported on every launch.
- `data/station-before-pairing.bin` is the attached station's original 4 MB flash backup.

Statuses: `not_transmitted` means an imported trusted mapping has not been sent by this app; `awaiting_tag` reserves a new cube ID; `pending` is an operation in progress; `acknowledged` means a matching application ACK arrived; `unconfirmed` retains a retryable request whose result is uncertain.

A radio `delivered` result alone does not confirm registration or visible LEDs. Zone commands have no application ACK. Even registration ACKs cannot verify flash persistence because the existing cube firmware does not report flash-write errors. A lost ACK can leave a successfully registered cube marked unconfirmed; retrying the same ID/UID is supported.

## Connection and recovery

Current replacement station installed on 2026-09-19: ESP32-C3 MAC
**30:ED:A0:5B:6D:D8**, running `nct-pairing-1.6-zones`. The GUI records it as
excluded from cube operations. USB connection, radio channel 2, PN532
initialization and a fresh PN532 firmware response were verified. NFC polling is
active; an actual tag read on this board remains unverified. Its private
full-flash backup and upload receipt are under
`data/station-30EDA05B6DD8-20260919-065531/`.

The earlier replacement **AC:27:6E:80:37:18** had PN532 initialization failures
with I²C status 5, including after power cycling and bus recovery with both lines
high. Its private backup and receipt remain under
`data/station-AC276E803718-20260919-060325/`.

The native Station menu exposes the primary controls; Escape stops the active operation. Only one operation runs at a time, and only one GUI may open a given database. Close Arduino Serial Monitor before connecting; it otherwise holds the USB port. USB port names can change after reconnecting, so use Refresh ports. Stop before disconnecting; the GUI also sends Stop on disconnect/close. Serial connection uses Espressif’s no-reset DTR/RTS sequence so reconnecting does not reset the ESP32 mid-I²C transaction. If the app stops responding, the station attempts to restore the selected cube after five seconds without a heartbeat. A station power loss cannot send that cleanup packet; reconnect and use Flash selected, then Stop.

Startup first checks SDA/SCL with pull-ups and attempts the standard nine-clock I²C bus clear if SDA is held low while SCL is high. It reports the before/after line levels as `nfc_bus`. If a line remains low it leaves NFC disabled, allowing radio operations to continue. The startup log includes `nfc_i2c_status`: 0 is an I²C acknowledgment, 2 is an address NACK, and 5 is a bus timeout. If the NFC reader is unavailable, bulk registration and light controls can still be used. Check the PN532 wiring, I2C mode, power, and reboot the station before interactive pairing. Discovery finds compatible protocol responders, not arbitrary nearby ESP32s. Multiple rounds reduce missed replies; devices must be powered, in range, and on channel 2.

## Development

Runtime: Python 3.14 with Tk, `pyserial==3.5`. This Mac's project environment is `.venv`. To recreate it:

```sh
brew install python-tk@3.14
python3.14 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

Firmware: open `firmware/pairing_station/pairing_station.ino`. Select **ESP32C3 Dev Module**, **USB CDC On Boot: Enabled**, and the attached USB port. Install the listed libraries through Arduino IDE Library Manager when building in the IDE. Tested with Arduino-ESP32 **3.3.11**, Adafruit PN532 **1.3.4**, Adafruit BusIO **1.17.4**, and ArduinoJson **7.4.3**. Installed project-local libraries are under `.arduino/libraries`. Flash only the station; installation cube firmware is unchanged.

From the parent workspace:

```sh
pairing_station/.venv/bin/python -m unittest discover -s pairing_station/tests -v
pairing_station/.venv/bin/python pairing_station/tests/run_firmware_test.py
pairing_station/.venv/bin/python pairing_station/hardware_check.py --port /dev/cu.usbmodem101
```

Close the GUI serial connection before hardware_check or uploading. The hardware check only sends discovery; it never changes cube registration or lights. Firmware simulation compiles the actual sketch with fake NFC/radio/time implementations and the installed ArduinoJson headers.

The station serial protocol is newline-delimited JSON at 115200 baud. Every command has a nonempty `id` (max 40 characters). Commands are `hello`, `ping`, `discover`, `identify` (`mac`, `duration_ms`; zero means until stopped), `register` (`mac`, `cube_id`, `uid`), and `stop`. Heartbeats are sent every second. `hello` stops any stale operation before reporting capabilities. The app correlates tag/registration/flash/stop events by request ID and matches registration MAC/ID. Firmware checks ACK source MAC and payload MAC/ID independently.

References: [ESP-NOW delivery and callbacks](https://docs.espressif.com/projects/esp-idf/en/latest/esp32c3/api-reference/network/esp_now.html), [ArduinoJson parsing](https://arduinojson.org/v7/api/json/deserializejson/), [Homebrew Tk runtime](https://formulae.brew.sh/formula/python-tk%403.14), [Espressif serial monitor connection sequence](https://github.com/espressif/esp-idf-monitor/blob/master/esp_idf_monitor/base/serial_reader.py), [NXP I²C bus-clear specification](https://www.nxp.com/docs/en/user-guide/UM10204.pdf).

## Local HTTP Python API

The app starts an HTTP API at `http://127.0.0.1:8765`. No MCP server or additional dependencies are required. Launch with `--api-port NUMBER` to change the port, or `--api-port 0` to disable it. Each launch creates a new bearer token in `data/api.curl` (owner-only permissions), next to the selected database. The server binds only to loopback and rejects browser Origin headers.

From the project root, read the current controller, device table, and recent station events:

```sh
curl -sS --config pairing_station/data/api.curl \
  http://127.0.0.1:8765/status
```

Execute Python directly inside the running app:

```sh
curl -sS --config pairing_station/data/api.curl \
  -H 'Content-Type: application/json' \
  --data-binary '{"code":"controller.discover()\n{\"connected\": controller.connected, \"nfc_ready\": controller.reader_ok}"}' \
  http://127.0.0.1:8765/execute
```

The persistent Python namespace contains `app`, `controller`, `db`, and `root`. Execution runs on Tk's main thread, which also owns the SQLite connection. The last expression becomes `result`; responses also include `stdout`, `stderr`, and an exception `traceback` on failure. Earlier statements are not rolled back when a later statement fails. This is trusted local Python execution with the app's permissions, not a sandbox.

Useful code snippets for the `code` field:

- Stop and restore the active cube: `controller.stop()`
- Start pairing new cubes: `controller.start_pair()`
- Transmit the original 32 mappings: `controller.transmit(db.original_batch())`
- Flash a known cube: `controller.flash([db.get("1C:DB:D4:F0:A8:A4")])`
- Inspect scan events: `[e for e in app.recent_events if e.get("event") in ("tag", "tag_state", "nfc_error", "registered")]`
- Read devices: `db.rows()`

Keep calls short: blocking loops or sleeps block GUI updates and the station heartbeat. Start operations through the controller, then query their state in a later request. For delayed work use `root.after(...)`. Avoid UI methods that open modal dialogs.

Requests that have not completed within two seconds return HTTP 202 with an `id` and `state`. Fetch `GET /jobs/ID` to obtain the eventual result; **do not resubmit the code**, which could repeat device actions. A timeout does not cancel execution. The API retains the latest 100 completed/active job records (temporarily more if all are unfinished). `state: done` means the Python finished; an asynchronous registration still needs a station ACK. Closing the app cancels queued work and removes its token file.

## Graphical device studio

The device grid combines saved database mappings with live cube-protocol discovery replies. Select a card to inspect its MAC, committed and pending NFC UID, registration status, last discovery, radio delivery and most recent LED command. Use **Register / scan selected** for a new Neocore; it uses the automatically assigned ID, flashes that particular device and waits for its NFC tag. For an existing mapping, the same action asks before replacing its tag. **Transmit saved mapping** retries/sends the stored UID without another scan. **Flash selected** continues until **Stop / static**; **Flash all in grid** runs a short sequence over the currently filtered cards.

Filters include recent responders, registrations with ACK, unregistered devices, mappings needing attention, and all devices including exclusions. Search accepts ID, MAC or UID. Green registration status means an ACK was recorded, not that a device is currently reachable. Radio dots turn green for discovery replies within ten seconds; a grey dot does not prove power is off. Discovery refreshes automatically while connected, except during registration/stop operations. LED rings animate the app's most recent command; physical LED state is not reported by this protocol.

Device role overrides are stored in SQLite. Set **Reader / base station** to exclude a device from the default grid and pairing/flash/registration operations. Use **All incl. excluded** to restore it. Bulk GUI actions omit excluded devices; direct controller calls reject a batch containing one. Classification does not change the registration CSV format.

Discovery uses the legacy 24-byte `DISCOVER_REPLY` packet and checks that its MAC matches the radio sender. The provided `neocore_cube`, `neocore_cube_OTA` and `neocore_cube_OTA_1.4` sources implement this reply. It contains no firmware/version identifier, so the interface says **Cube protocol responder** rather than claiming an exact firmware identity. This is not a scan of every ESP32 nearby: nonresponding readers/base stations remain absent, and any other firmware implementing the same reply cannot be automatically distinguished.

Firmware roles provided by the operator: `live files/neocore_cube*` run on the LED devices (Neocores); `Preshow_MediaServer_SerialDAT` runs on the media server; `m5core2_controlloer` is the old registration server whose role this station takes over; `laser_sensor` belongs to another, currently nonworking part of the installation. These sources are reference files and were not modified for the dashboard.

**Auto-flash selection (1s)** is enabled by default. Changing the selected card sends a one-second flash, then restores static lighting. The checkbox above the grid disables it. Re-selecting the same card does not retrigger. Rapid selection changes finish the current short flash and keep only the latest selection queued. Excluded readers are skipped, previews are disabled when the station is disconnected, and selection flashes never interrupt pairing, registration or manual flashing. Turning the checkbox off or pressing Stop cancels pending selection flashes. Previewing a new device does not allocate an ID or change its registration.

### Guided registration

Select a card and press the blue **REGISTER DEVICE** button. It also works during the one-second selection preview: the station first stops that preview, discards other queued previews, then continuously flashes the chosen Neocore. Clear the NFC reader and wait for the blue **READY TO SCAN** banner before presenting its tag. Scanning changes the banner to **TAG DETECTED / REGISTERING** and stops the identification flashing. The app saves the pending match and waits for the device's registration acknowledgment.

A successful acknowledgment shows a large green **NEOCORE #… REGISTERED** banner with the UID, requests static lights and sounds the system bell. This feedback remains visible after tag removal. A missing acknowledgment, conflicting tag or station error shows red feedback with retry guidance, never a success indication. Stop cancels the process; already transmitted registrations cannot be undone. The protocol reports radio/registration results, not measured LED output.

## Separate USB firmware flasher

`../flashing_station/Launch.command` opens the separate Neocore USB flasher. It shares this inventory, adding new MACs with a reserved cube ID and NFC unknown, while keeping firmware results separate from registration statuses. Both applications may run simultaneously. New database ID reservations and CSV exports are serialized. The station's reported MAC is persisted as excluded, and both apps cooperate on USB port ownership. Restart an already-running pairing app when convenient to load these additions; no restart is required for the flasher's built-in protection of the current station. See `../flashing_station/README.md` for the USB-only firmware and operating instructions.

### Change a device number

Select a card and choose **Rename device…**, then enter its physical label number.
Numbers must be unique positive integers. If another device already uses that
number, first rename that device to an unused number. The MAC and NFC UID stay
with the selected device. A selection preview is stopped before renaming; other
active operations and pending registrations must finish first.

The database and CSV update immediately. For a paired device, the app sends the
new number with its existing NFC UID when connected and waits for the normal
registration acknowledgment. An offline rename is marked **Saved · not sent**;
use **Transmit saved mapping** after connecting. Unpaired devices remain
**Needs NFC tag**. After renumbering an original device, use individual saved
mapping transmission instead of **Transmit existing 32**, which rejects changed
original mappings. Export updated reader tables when required by fixed-table readers.

### Manual numbering after the number reset

The live database now uses manual numbering (`metadata.auto_number=0`). Unnumbered
devices stay visible as **New device / Needs number** after discovery and restart;
select one and click **REGISTER DEVICE** to enter its number and then scan its NFC tag. **Rename device…** can also assign a number separately before transmission. Clearing
a number preserves its MAC, saved UID and pending UID, and does not send an erase
command to its firmware. NFC scans associated with interactive registration are
now recorded separately as `nfc_seen` events, so bulk transmissions do not count
as scans. The 2026-09-17 reset preserved #2 and #6 and explicitly cleared #43/#49.
The pre-reset backup is `data/before-clearing-numbers-20260917.sqlite3`.

For an unnumbered device, **REGISTER DEVICE** prompts for the physical label number, rejects numbers already in use, then starts continuous flashing and waits for a fresh NFC scan. Cancelling the prompt leaves the number unchanged. Existing stored tag data is not transmitted by this flow before a scan.

### Transfer an existing NFC tag

A fresh scan during **REGISTER DEVICE** or interactive pairing takes over any
matching committed UID or pending reservation from other database devices. This
happens atomically, is recorded in the event history and CSV, and is shown in the
registration banner/log. The old device keeps its number; if it has no other tag
it changes to **Needs NFC tag** (or **Needs number** if unnumbered). Unrelated
saved or pending tags are retained. Failed delivery leaves the tag reserved to
the new device for retry. Saved-mapping bulk transmissions do not take over tags.
The old device's firmware is not remotely erased; fixed-table readers require
an updated exported mapping if they still contain the old association.

Original mappings are shown separately on device cards as **Original #N · NFC
unseen** (amber) or **Original #N · NFC scanned**. The details panel separates the
current assigned number, the original hardcoded table number, and local NFC scan
history. Original numbers are reference information, not live firmware readback,
and do not reserve cleared numbers. Search also matches the original number.

### Identify a cube over USB

Enable **Identify cubes over USB** in the pairing app, then plug in a cube.
The app detects its MAC, pins it at the top of the grid, and locks selection to
it even if search or filters would hide it. A new/unnumbered device prompts for
its physical label number; cancelling leaves it pinned and Register can ask again.
Unplug the cube and use the normal NFC registration procedure. **Unlock selection**
releases the pin. A newly identified USB cube replaces it, stopping any active
pairing operation first. The pin lasts for this app session. Disabling USB
identification stops watching but leaves the existing pin until Unlock.

Native Espressif USB uses the MAC exposed in its USB serial identity without
opening or resetting the device. This identifies the chip, not its firmware type.
Other USB serial adapters are queried with `?` for a `Cube MAC:` response or read
for the same boot-log line, using cross-app serial locks. Older firmware that
doesn't answer the query may need unplugging/reconnecting to capture its boot log.
No bootloader reset or firmware upload is performed. The registration station
and known excluded reader/base identities are skipped. Identification failures
appear beside the checkbox; reconnect to retry. Keep the optional watcher off
while using the USB flashing app to avoid competing for adapter serial ports.

USB identification also queries the cube's firmware version and compares it with
`flashing_station/build/manifest.json` on each connection. A matching cube MAC,
version line and ready response are required. A different version produces a red
**CUBE FIRMWARE UPDATE NEEDED** banner with installed and latest local versions;
no response produces **CUBE FIRMWARE NOT VERIFIED**. Cards and details retain the
result after unplugging. This compares the firmware's reported version, not its
binary hash, and does not automatically flash the cube. The latest version here
means the locally maintained build, not an internet release.

**REGISTER DEVICE** also works when an earlier attempt is unconfirmed or was
stopped. It starts a fresh scan while retaining the existing pending tag
reservation. Only a new accepted scan replaces that pending tag; the committed
mapping still waits for a matching cube acknowledgment. **Transmit saved mapping**
remains available to retry the saved tag without scanning again.

Unnumbered-device prompts prefill the lowest free ID above 32. Press **Enter**
to accept it or type the physical label number instead. The prompt explains this
shortcut. A suggestion does not reserve the number until accepted; duplicate
validation still applies, and a conflicting registration/USB prompt suggests a
new free number on retry. IDs 1–32 remain available for explicit manual entry.

IDs **2, 22, 39 and 43** are reserved for known physical modules in the
`reserved_numbers` table, independent of whether their MAC/NFC mapping is known.
Automatic allocations and suggested IDs skip these numbers. You can still type
one explicitly when identifying the corresponding labelled module. Reservations
survive clearing device numbers and app restarts; no placeholder MAC or UID is
invented for them.
