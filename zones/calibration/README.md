# PoolZone radio and laser calibration

Run `./zones/calibration/Launch.command --port /dev/cu.usbmodem101` from the repository root. Uses the existing `pairing_station/.venv` (Python with Tk and pyserial). Close other serial monitors first.

1. Choose a tick in the table, move the physical slider to that position, and **Capture control point**. Capture records the latest displayed One Euro filtered value (fresh within 0.4 seconds), with no hold-still or spread threshold.
2. Set control points at **1 and 23** to bound the whole slider. Add intermediate control points anywhere the spacing needs adjustment. Ticks between points are interpolated linearly; no extrapolation outside the endpoints. Increasing and decreasing distances are supported.
3. Use **Remove selected control point** to simplify the curve, or enter an exact distance using **Set control point (mm)**.
4. **Apply & save to flash** sends the 23 interpolated distances and the control-point mask, then saves and reads back one versioned NVS blob. Captures and manual edits are drafts until applied. Calibration survives restart. **Reload saved ticks** discards a draft.

The live circle follows the One Euro filtered hardware distance. The same filtered value drives index selection, light commands and control-point captures. The green tick and large index come from firmware. Amber draft marks show pending edits. Each tick accepts readings within `enter` (default 33%) of the distance to its neighbor on the reading's side; an endpoint uses its only neighbor for the outer margin. Outside those windows the index is **—**, represented by -1 in serial telemetry. A tick already selected keeps a wider `exit` window (default 45%), so noise at a window edge cannot toggle the output. Entering requires `confirm` ms of stability and leaving requires `release` ms of sustained disagreement. Invalid sensor readings are tolerated for `dropout` ms before the selection is released. All of these are tunable; see [Position smoothing](#position-smoothing). Distances must be 10–1000 mm and interpolated ticks at least 1 mm apart.

`pool-2.8.0` keeps the original tagged interaction. A tag activates the GPIO5 strip; when a valid index is selected, the radio broadcasts its member to the pool central on channel 2, immediately on change and every 150 ms while active. A missing tag is released after 700 ms. Registered NeoCubes receive the existing POOL command (blue); unknown tags still activate the pool as in the original source. Gaps or invalid sensor readings release the member. Tracking and calibration remain available without a tag.

**Arm without NeoCube** explicitly enables the Python override. The app renews it every 350 ms; the board expires it after 1500 ms without renewal. Disconnect/close sends DISARM; a stopped/crashed app is covered by the board watchdog. Reconnect never auto-arms, and late keepalives cannot re-arm an expired lease. Disarming only removes the override: a real tag continues to activate the system. The strip indicates activation even when the slider is between indexes. During a calibration upload, member output pauses until SAVE or LOAD succeeds.

**NeoCube & output diagnostics** shows current tag/cube ID, UID, MAC, POOL command delivery result, NFC health, radio identity, queued packets/errors and event history. The current-cube snapshot works even when connecting while a cube is already on the reader. Cube delivery means ESP-NOW link acknowledgement, not measured LED output. Central broadcasts provide no acknowledgement; queued is not proof of illumination.

See [functionality comparison](FUNCTIONALITY.md) for preserved behaviors, intentional changes and remaining physical checks.

Legacy flasher endpoints seed an unsaved two-control-point calibration only if no saved NVS calibration exists. Saved NVS calibration takes precedence over the flasher's endpoint fields. A full flash erase removes it; normal application-only updates retain it.

Build: `pairing_station/.venv/bin/python zones/flasher/zone_build.py PoolZone`.

A firmware update preserves both NVS blobs: an existing calibration and any saved tuning survive, and are verified after reboot.

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
- `TUNE GET`: JSON of every tuning parameter plus the firmware defaults.
- `TUNE SET <key> <value>`: validate and apply live; does not write flash or pause output.
- `TUNE SAVE` / `TUNE LOAD` / `TUNE DEFAULTS`: persist, reload, or apply defaults live.
- `RAW ON` / `RAW OFF`: stream every sensor sample as `{"type":"raw","t","mm","f","st","idx"}`.
  Never persisted and off at boot.
- `interaction` JSON accompanies samples; `NFC:` health is reported once per second.
- Sample JSON at approximately 10 Hz: `device: PoolZoneCalibration`, `type: sample`, `sensor`, `distance` (null on error), `index`, `valid`, `saved`.

Storage uses ESP32 [Preferences](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/preferences.html), namespace `pool-slider`, keys `ticks-v1` (calibration) and `tune-v1` (tuning). Tuning is written only by an explicit `TUNE SAVE`, never on boot, so a firmware update's NVS verification stays valid. A board with no saved tuning uses the firmware defaults. The GUI waits for and verifies each command response before proceeding. Interrupted application may leave a partial RAM draft, but flash is only changed by a successful final save; reconnect/reload to recover.

Checks: `pairing_station/.venv/bin/python zones/tests/run_firmware_tests.py` and `pairing_station/.venv/bin/python -m unittest discover -s zones/calibration`.

GUI tests: `pairing_station/.venv/bin/python zones/calibration/gui_check.py`. Hardware test (briefly commands real lights): `pairing_station/.venv/bin/python zones/calibration/hardware_check.py /dev/cu.usbmodem101`.

## Position smoothing

An isolated median (default 3 samples) rejects single wild readings, then the
[One Euro algorithm](https://gery.casiez.net/1euro/) smooths the result. One Euro uses
the actual elapsed sample time, accommodating NFC polling, and is stronger near rest and
more responsive during movement. A median in front of it matters because One Euro reads a
spike as enormous speed, which both passes the spike through and *unsmooths* the filter
for the following moment.

Diagnostics show raw versus filtered millimeters and the board's current parameters. Only
filtered distance is used for the on-screen marker, index/light selection, and Capture.
Filtering reduces jitter but does not correct sensor bias or a bad calibration.

### Tunable parameters

Filter and decision parameters live in a second NVS blob (`tune-v1`) and can be changed
live over serial without recompiling. Firmware defaults keep `pool-2.7.0`'s filter and
sensor timing; only the parameters that fixed an outright defect differ, because
smoothing trades directly against responsiveness and should be set from measured data
rather than changed blind.

| Key | Default | Meaning |
|---|---|---|
| `mincutoff` | 0.8 Hz | One Euro cutoff at rest: the main jitter control |
| `beta` | 0.03 | Hz per mm/s; responsiveness while moving |
| `dcutoff` | 1.0 Hz | One Euro speed cutoff |
| `enter` | 0.33 | acceptance window to enter a tick, as a fraction of the local spacing |
| `exit` | 0.45 | wider window to keep a selected tick: the hysteresis |
| `confirm` | 50 ms | stability required to enter |
| `release` | 120 ms | sustained disagreement required to leave |
| `dropout` | 400 ms | invalid readings tolerated before releasing |
| `budget` | 20 ms | VL53L4CD timing budget, 10–200 |
| `interval` | 0 | inter-measurement period; 0 or above the budget |
| `median` | 3 | raw median window, odd, 1–9; 1 disables |

`exit` must be at least `enter` and below 0.9, so a selected tick is always releasable by
moving onto its neighbour. A timing the sensor rejects is refused, and a saved one that
fails at boot falls back to the defaults rather than leaving the slider dead.

### Why the output used to flicker

`pool-2.7.0` released a selection on a **single** disagreeing sample and on a **single**
invalid sensor reading, while entry required 50 ms of stability — asymmetric in exactly
the wrong direction. A slider parked near a window edge, or one bad VL53L4CD reading,
dropped the member to 0 and released the relay. `release`, `dropout` and `exit` address
those three causes directly; `mincutoff`, `median` and `budget` address the underlying
noise.

## Tuning & recording tab

**Start guided recording** walks the operator through a series of positions — both
endpoints plus every Nth tick, default every 4th, so 1, 5, 9, 13, 17, 21, 23 in about a
minute. For each it prompts `MOVE TO n`, allows a settle time, then `HOLD` while it
records. The board streams every sensor sample (`RAW ON`, ~50 Hz) for the duration; the
10 Hz telemetry is too slow to tune a filter against.

From one recording the app derives **both** the calibration and the tuning:

- each tick's distance is the median of its hold window, with the settle samples discarded;
- noise is measured from successive differences, so it is not inflated by a slider still
  being adjusted, and a step that never came to rest is flagged for re-recording rather
  than silently poisoning that tick;
- the recommended parameters are each reported with the evidence that produced them.

**Auto-tuning is a constrained choice, not noise minimisation.** More smoothing always
means less flicker and more lag, so the app replays the recorded raw samples through a
mirror of the firmware pipeline and reports both objectives: output changes while the
slider was held still, and how long after the slider stops the correct member is
confirmed. It picks the least-flicker option that still meets the settling budget
(default 300 ms) and says so. If nothing meets both, it reports that instead of silently
smoothing the interaction into uselessness — that is the signal that the sensor mounting
or the timing budget is the real limit, not the filter.

Recordings are saved under `build/recordings/` and can be replayed offline, so a tune can
be re-derived or re-examined without the hardware present.

Tuning requires `pool-2.8.0` or newer on the board. Older firmware answers `CAL GET` but
has no `TUNE` command; the app probes a bounded number of times, then says so and disables
the recording controls rather than retrying for the whole session. Update the board on the
Firmware tab first. **Update cube database** does *not* require tuning or calibration
support, so a legacy board's mappings can still be refreshed on its own.

**Apply live** sends the parameters without saving, so a change can be judged on the real
slider before it is committed; **Apply & save to flash** persists them. The diagnostics
tab shows an **output stability** counter (index changes per 10 s and time since the last
change) so flicker is measured before and after rather than judged by eye.

## Firmware tab

Connect to a configured PoolZone. The **Firmware** tab automatically identifies the board and compares its installed version/build fingerprint with the current local firmware source and build recipe. **Check installed firmware** refreshes the check after edits. It shows **Up to date** or **Update available**; older builds without fingerprints are reported as unverified and offered an update.

The updater also supports identified legacy PoolZone firmware without a calibration response. Firmware identification enables the update independently of calibration readiness. The full-flash backup and byte-for-byte NVS verification still protect existing settings. When the old firmware returns calibration, its ticks and anchors are additionally compared after reboot; otherwise the new firmware must return calibration and its matching build fingerprint, without a before/after tick comparison. Cube database updates use the verified inactive-slot procedure described below.

**Update firmware** performs the identity check again before uploading, reuses a checksum-verified current build (compiles only if missing/stale), disarms the Python override, backs up the complete 4 MB flash, validates the existing partition layout, and writes the application only if needed and syncs the current committed cube mappings from the shared pairing database. It verifies the program plus unchanged NVS calibration and zone identity, plus the expected cube database, confirms the rebooted version/fingerprint, then reconnects with the override disarmed. The tab shows progress and tool output; backups and logs are retained under `build/firmware-runs/`. Matching firmware builds are skipped; a stale database can be updated on its own without recompiling or rewriting the application.

Unsaved calibration drafts must be applied/saved or reloaded before updating. While updating, connection changes and app closure are disabled. A failed update leaves its evidence in the Firmware tab. This is an updater for configured PoolZone boards; use Zone Flasher for blank boards, other firmware types or partition migrations.

### Cube database / shared zone features

PoolZone uses the shared `NctTagPlate` / `NctZoneDb` / `NctZoneLink` implementation: UID → cube ID/MAC lookup, compatible NeoCube POOL commands and delivery results, database announcements/chunks over ESP-NOW, status/log queries, identification and reboot. Registered mappings come from `pairing_station/data/devices.sqlite3`; pending UID edits, incomplete mappings and excluded devices are not published.

The Firmware tab has a dedicated **Cube database** panel showing the board's version,
mapping count and CRC beside the local master's, with a plain verdict (up to date, update
available, board ahead, unknown). **Check master database** is read-only. **Update cube
database** writes only the database, leaving a current application untouched, and is
enabled whenever the board's copy is stale even if the firmware is current. Updating
publishes through the same `ZoneStore.publish()` used by Zone Flasher, incrementing the
version only when mapping content changes.

A **Zone status registry** panel shows what is written to the shared `zones` table (name,
point, firmware, MAC, database version/count/CRC) and an **Update zone status in
registry** button writes that row without flashing anything. Previously this happened
only as a side effect of a flash, so a board that was merely inspected or tuned never
appeared in the registry; the applied tuning is recorded in the row's detail.

**Update firmware & database** backs up the board and writes the database into the inactive A/B slot. It verifies staged records before committing the header sector, preserving the previous active slot as fallback. After reboot it verifies the selected version/count/CRC and records the result in the shared zone registry. Calibration and radio identity are preserved. Missing master files or a board database newer than the local master block the update instead of silently clearing or rolling back mappings.
