# PoolZone radio and laser calibration

Run `./zones/calibration/Launch.command --port /dev/cu.usbmodem101` from the repository root. Uses the existing `pairing_station/.venv` (Python with Tk and pyserial). Close other serial monitors first.

1. Choose a tick in the table, move the physical slider to that position, and **Capture control point**. Capture records the latest displayed One Euro filtered value (fresh within 0.4 seconds), with no hold-still or spread threshold.
2. Set control points at **1 and 23** to bound the whole slider. Add intermediate control points anywhere the spacing needs adjustment. Ticks between points are interpolated linearly; no extrapolation outside the endpoints. Increasing and decreasing distances are supported.
3. Use **Remove selected control point** to simplify the curve, or enter an exact distance using **Set control point (mm)**.
4. **Apply & save to flash** sends the 23 interpolated distances and the control-point mask, then saves and reads back one versioned NVS blob. Captures and manual edits are drafts until applied. Calibration survives restart. **Reload saved ticks** discards a draft.

The live circle follows the One Euro filtered hardware distance. The same filtered value drives index selection, light commands and control-point captures. The green tick and large index come from firmware. Amber draft marks show pending edits. Each tick accepts readings within ±33% of the distance to its neighbor on the reading's side; an endpoint uses its only neighbor for the outer margin. Outside those windows the index is **—**, represented by -1 in serial telemetry. Selection requires 50 ms stability; leaving a window clears immediately. Sensor errors and stale USB telemetry clear selection. Distances must be 10–1000 mm and interpolated ticks at least 1 mm apart.

`pool-2.7.0` restores the original tagged interaction. A tag activates the GPIO5 strip; when a valid index is selected, the radio broadcasts its member to the pool central on channel 2, immediately on change and every 150 ms while active. A missing tag is released after 700 ms. Registered NeoCubes receive the existing POOL command (blue); unknown tags still activate the pool as in the original source. Gaps or invalid sensor readings release the member. Tracking and calibration remain available without a tag.

**Arm without NeoCube** explicitly enables the Python override. The app renews it every 350 ms; the board expires it after 1500 ms without renewal. Disconnect/close sends DISARM; a stopped/crashed app is covered by the board watchdog. Reconnect never auto-arms, and late keepalives cannot re-arm an expired lease. Disarming only removes the override: a real tag continues to activate the system. The strip indicates activation even when the slider is between indexes. During a calibration upload, member output pauses until SAVE or LOAD succeeds.

**NeoCube & output diagnostics** shows current tag/cube ID, UID, MAC, POOL command delivery result, NFC health, radio identity, queued packets/errors and event history. The current-cube snapshot works even when connecting while a cube is already on the reader. Cube delivery means ESP-NOW link acknowledgement, not measured LED output. Central broadcasts provide no acknowledgement; queued is not proof of illumination.

See [functionality comparison](FUNCTIONALITY.md) for preserved behaviors, intentional changes and remaining physical checks.

Legacy flasher endpoints seed an unsaved two-control-point calibration only if no saved NVS calibration exists. Saved NVS calibration takes precedence over the flasher's endpoint fields. A full flash erase removes it; normal application-only updates retain it.

Build: `pairing_station/.venv/bin/python zones/flasher/zone_build.py PoolZone`.

Serial protocol, 115200 baud, newline terminated:

- `HOST ARM`: explicitly start a 1500 ms override lease.
- `HOST PING`: renew an unexpired armed lease only.
- `HOST DISARM`: remove override (real-tag activation remains).
- `HOST STATUS`: report activation, output, current cube and radio counters.
- `CAL GET`: JSON calibration (`ticks`, `anchors` bitmask, `valid`, `saved`).
- `CAL SET <1..23> <mm>`: update one RAM tick; invalidate saved status.
- `CAL ANCHORS <mask>`: set control-point membership; endpoints required.
- `CAL SAVE`: validate, persist, verify and report.
- `CAL LOAD`: reload saved blob and clear selection.
- `interaction` JSON accompanies samples; `NFC:` health is reported once per second.
- Sample JSON at approximately 10 Hz: `device: PoolZoneCalibration`, `type: sample`, `sensor`, `distance` (null on error), `index`, `valid`, `saved`.

Storage uses ESP32 [Preferences](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/preferences.html), namespace `pool-slider`, key `ticks-v1`. The GUI waits for and verifies each command response before proceeding. Interrupted application may leave a partial RAM draft, but flash is only changed by a successful final save; reconnect/reload to recover.

Checks: `pairing_station/.venv/bin/python zones/tests/run_firmware_tests.py` and `pairing_station/.venv/bin/python -m unittest discover -s zones/calibration`.

GUI tests: `pairing_station/.venv/bin/python zones/calibration/gui_check.py`. Hardware test (briefly commands real lights): `pairing_station/.venv/bin/python zones/calibration/hardware_check.py /dev/cu.usbmodem101`.

## Position smoothing

The firmware uses the [One Euro algorithm](https://gery.casiez.net/1euro/): minimum cutoff 0.8 Hz, speed coefficient 0.03 Hz per mm/s, derivative cutoff 1 Hz. It uses the actual elapsed sample time, accommodating NFC polling. It replaces the two-sample average. Smoothing is stronger near rest and more responsive during movement. Invalid readings or gaps over 400 ms reset filter history and release selection; recovery seeds directly from the next valid measurement.

Diagnostics show raw versus filtered millimeters. Only filtered distance is used for the on-screen marker, index/light selection, and Capture. After a move, allow the display to reach the intended point before capturing; the app does not force a hold. Filtering reduces jitter but does not correct sensor bias or a bad calibration.

## Firmware tab

Connect to a configured PoolZone. The **Firmware** tab automatically identifies the board and compares its installed version/build fingerprint with the current local firmware source and build recipe. **Check installed firmware** refreshes the check after edits. It shows **Up to date** or **Update available**; older builds without fingerprints are reported as unverified and offered an update.

The updater also supports identified legacy PoolZone firmware without a calibration response. Firmware identification enables the update independently of calibration readiness. The full-flash backup and byte-for-byte NVS verification still protect existing settings. When the old firmware returns calibration, its ticks and anchors are additionally compared after reboot; otherwise the new firmware must return calibration and its matching build fingerprint, without a before/after tick comparison. Cube database updates use the verified inactive-slot procedure described below.

**Update firmware** performs the identity check again before uploading, reuses a checksum-verified current build (compiles only if missing/stale), disarms the Python override, backs up the complete 4 MB flash, validates the existing partition layout, and writes the application only if needed and syncs the current committed cube mappings from the shared pairing database. It verifies the program plus unchanged NVS calibration and zone identity, plus the expected cube database, confirms the rebooted version/fingerprint, then reconnects with the override disarmed. The tab shows progress and tool output; backups and logs are retained under `build/firmware-runs/`. Matching firmware builds are skipped; a stale database can be updated on its own without recompiling or rewriting the application.

Unsaved calibration drafts must be applied/saved or reloaded before updating. While updating, connection changes and app closure are disabled. A failed update leaves its evidence in the Firmware tab. This is an updater for configured PoolZone boards; use Zone Flasher for blank boards, other firmware types or partition migrations.

### Cube database / shared zone features

PoolZone uses the shared `NctTagPlate` / `NctZoneDb` / `NctZoneLink` implementation: UID → cube ID/MAC lookup, compatible NeoCube POOL commands and delivery results, database announcements/chunks over ESP-NOW, status/log queries, identification and reboot. Registered mappings come from `pairing_station/data/devices.sqlite3`; pending UID edits, incomplete mappings and excluded devices are not published.

The Firmware and NeoCube diagnostics tabs display the **board database version, cube count, CRC and local target version/count**. Status refreshes every five seconds. Checking the master is read-only; updating publishes through the same `ZoneStore.publish()` used by Zone Flasher, incrementing the version only when mapping content changes.

**Update firmware & database** backs up the board and writes the database into the inactive A/B slot. It verifies staged records before committing the header sector, preserving the previous active slot as fallback. After reboot it verifies the selected version/count/CRC and records the result in the shared zone registry. Calibration and radio identity are preserved. Missing master files or a board database newer than the local master block the update instead of silently clearing or rolling back mappings.
