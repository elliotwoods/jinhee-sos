# Zones — flash-seeded, ESP-NOW-updatable cube database

Zone boards (tag plates such as PreshowZone) no longer have a hard-coded `cubeTable[]`. Each zone keeps the cube
database (`cubeID`, NFC UID, cube MAC) in its own flash, written when the zone is flashed. After that it is updated
over ESP-NOW by the pairing station, with no reflash. **Neocube firmware is unchanged.**

```
pairing_station (USB, SQLite master DB) ──ESP-NOW ch 2 broadcast──▶ every zone in range
        ▲  zone status / logs  ◀──────────────── unicast replies ─────────┘
zone ──SET_ZONE (unicast, 24-byte cube Packet)──▶ neocube        zone ──2-byte event──▶ media bridge
```

Everything uses **ESP-NOW channel 2**: cubes, zones, the pairing station and the preshow media bridge (SerialDAT).

## Zone firmwares

All are built on the shared tag-plate core (`NctTagPlate.h`). It handles PN532 polling, database lookup and `SET_ZONE` delivery with acknowledgment tracking, plus the update link and serial console. All run on the ESP32-C3 SuperMini with PN532 on SDA 4 / SCL 3. The exception is the replacement preshow plates. These are ex-cube XIAO ESP32-C3 boards with the reader on the XIAO's labelled SDA/SCL pads (D4/D5 = GPIO6/7). From `preshow-3.4.0`, `PreshowZone` tries 4/3 and then 6/7, and keeps the pair the reader answers on. The `NFC:` report line ends with `pins=<sda>/<scl>`. The fallback is opt-in (`TagPlateOptions::altSdaPin/altSclPin`), and no other zone enables it.

| Flasher choice | Firmware | Replaces (`live files/`) | Behaviour |
|---|---|---|---|
| Preshow plate (points 1-4) | `PreshowZone` | `PreshowZone1` | cube → PRESHOW; acknowledged `PreshowEvent` to the media bridge, which cues TouchDesigner |
| Preshow exit / safety plate | `TagPlateZone` | `preshow_enter`, `Tag_Plate` | cube → PRESHOW |
| Mainshow entrance plate | `TagPlateZone` | `mainshow_enter`, `Mainshow_Tagplate` | cube → MAINSHOW |
| Desert plate | `DesertZone` | `desert_zone_tagplate(_OTA)` | light panel MOSFET on GPIO1; cube → DESERT; `MSG_TAG_STATE` 1/0 |
| Pool radio | `PoolZone` | `laser_sensor` | VL53L4CD slider → member 1-23, LED strip on GPIO5, `PoolState` unicast to the pool central controller with a 150 ms heartbeat; cube → POOL |

- **No router dependency.** No zone joins the Wi-Fi router any more; the channel is fixed at 2.
- **Desert OTA is gone.** The cube table now updates over ESP-NOW, so OTA is no longer needed.
- **Pool calibration and diagnostics.** PoolZone restores NeoCube-gated pool light output and provides an explicitly armed, watchdog-protected Python override. Use [`calibration/Launch.command`](calibration/README.md) for live hardware tracking, control-point interpolation across 23 ticks, ±33% acceptance windows and persistent flash calibration.
- **Legacy Pool radio settings.** The radio ID (1-6) is the zone point. The slider calibration (mm at member 1 and member 23) is entered in the flasher and stored in flash. Serial `dist` streams the measured distance so you can read the two values off.
- **Pool central controller is maintained here.** It lives at [`firmware/PoolCentral`](firmware/PoolCentral/README.md),
  replacing the archived `live files/PoolZone_Central_Controiler`. It is **not** a zone board and **not** a zone-flasher
  target: no PN532, no `zcfg`/`zdb` partitions, and a different board profile (`esp32:esp32:esp32c3`, not the SuperMini).
  Build it with `scripts/build_all_firmware.py` or the `arduino-cli` commands in its README.
- **Pool outputs are active low** since the 2026-09-21 relay rewire: a lit lamp drives its PCA9685 channel LOW,
  energising the relay. `POOL_OUTPUT_ACTIVE_LOW` in `firmware/PoolCentral/PoolOutput.h` is the only switch, and
  logs and telemetry stay in terms of the lamp. Note the boards power up with outputs low, so the frames light
  until the controller boots and darkens them.
- **The radios and the central are a matched set.** They must be reflashed together. Flash the central first: it still
  accepts the old 15-byte packet, so the existing sliders keep working while they are updated one at a time.
- **The TouchDesigner media bridge is maintained here.** It lives at
  [`firmware/PreshowBridge`](firmware/PreshowBridge/README.md), replacing the archived
  `live files/Preshow_MediaServer_SerialDAT`. Like the pool central it is **not** a zone board and **not** a zone-flasher
  target: no PN532, no `zcfg`/`zdb` partitions, and its own board profile. Build it with `scripts/build_all_firmware.py`.
- **The preshow plates and the bridge are a matched set too.** Flash the bridge first: it still accepts the old 2-byte
  packet, so the plates keep working while they are updated one at a time.
- **The main show is started by [`firmware/MainshowController`](firmware/MainshowController/README.md).** It replaces the
  M5 Core2 show starter, whose `MSG_SHOW_START = 7` current cubes ignore. It is not a zone board either.
  - The [Mainshow app](mainshow/README.md) (`mainshow/Launch.command`) flashes it onto a spare dongle board, makes a cube
    mainshow-ready and triggers the show (to one cube or broadcast).
  - The board's BOOT button and trigger input (XIAO D1 to GND) trigger the show without a computer.

### Pool link protocol

Defined once in [`libraries/NctZone/src/NctPoolProtocol.h`](firmware/libraries/NctZone/src/NctPoolProtocol.h).

```
PoolZone x6 ──PoolState (unicast, ESP-NOW ACK + retries)──▶ PoolCentral ──I2C──▶ 2x PCA9685
        ◀──────────── PoolBeacon (broadcast, 500 ms) ──────────┘
```

The central broadcasts a beacon, because it cannot know a radio's MAC until it has heard from it. Each radio latches
that address as a pinned peer and unicasts its state back, which is what provides acknowledgement and retries; plain
broadcast had neither, and losing frames under six-slider load is what made the lights unstable. Each radio also keeps
one broadcast copy going every 450 ms, free because the central de-duplicates on sequence, which rescues a radio that
latched a stale address.

The central tracks one slot per **sender MAC**, not per configured radio ID, so two boards set to the same ID
simply get a slot each and both work; the ID is a label the central reports but never routes on.
A member frame is lit while **any** radio holds it. Each `PoolState` carries a lease (clamped 600-2000 ms, default 800),
a per-boot identity and a sequence number, so a late frame cannot re-assert an old member and a rebooted radio is still
accepted at once. Changes are sent as a short burst and releases are repeated for a second, because a lost release
leaves a light stuck on for a whole lease. Idle radios keep heartbeating, so `RADIO TIMEOUT` at the central now means a
real fault, and the beacon's `radioMask` lets each radio report `central_sees_me` on its own USB console.

Pool frames share the `NZ` header but are deliberately **not** routed by `NctZoneProtocol.h::frameType()`; they reach
the sketch through `TagPlate::onFrame`. See the comment at the top of `NctPoolProtocol.h` for why.

### Preshow link protocol

Defined once in [`libraries/NctZone/src/NctPreshowProtocol.h`](firmware/libraries/NctZone/src/NctPreshowProtocol.h).

```
PreshowZone x4 ──PreshowEvent (unicast, ESP-NOW ACK + retries)──▶ PreshowBridge ──USB──▶ TouchDesigner
        ◀────────PreshowAck   (unicast, echoes bootId+seq)────────┤
        ◀────────PreshowBeacon (broadcast, 500 ms)────────────────┘
```

The same shape as the pool link, for the same reason: the bridge broadcasts a beacon, each plate latches that address
as a pinned peer and unicasts back, which is what provides acknowledgement and retries. The bridge's MAC is no longer
compiled into the plates, so swapping the bridge board needs no reflash.

A show cue is a one-shot edge rather than a stream, so two things are added on top. The bridge **acknowledges every
well-formed event** by `bootId`+`seq` — including retries, because a lost acknowledgement would otherwise be
indistinguishable from a lost cue — and the plate retries every 120 ms until that acknowledgement arrives or 3 s have
passed, at which point it prints `MEDIA FAIL` and bumps the counter the pairing station's *Query zones* table shows.
A sequence number identifies an **edge**, not a frame, so every retransmission is byte-identical.

The plate then keeps re-asserting its current state once a second, forever. That costs TouchDesigner nothing, because
the bridge writes a serial line only when a point's state actually changes — and it means a cue lost while the bridge
was rebooting or out of range heals itself within a second. `PreshowBeacon.pointMask` reports what TouchDesigner was
actually told, which each plate shows as `bridge_sees_me` on its own console.

The serial format TouchDesigner reads (`PRESHOW,<n>,ON|OFF`) is unchanged from the legacy bridge.

Preshow frames are absent from `frameType()` for the same reason pool frames are.

**The rollout works from either end.** The bridge accepts the pre-2026 2-byte packet, so a plate
missed during an update keeps working. A plate *also sends* that packet until it has heard a beacon,
so a plate can be replaced while the bridge is still the original listener-only board — which is the
situation today. A plate stops sending it the moment a real bridge announces itself, and never
resumes; `MEDIA:` on the plate's `?` report says `mode=legacy` or `mode=modern`. In legacy mode
there is nothing that could acknowledge a cue, so the plate reports `MEDIA LEGACY` once per edge
rather than pretending the link failed.

### Bench-testing a plate with no reader — `preshow_test/Launch.command`

`PreshowZone` has a leased host override (the same shape as PoolZone's): `HOST ARM`, `HOST PING`,
`HOST ON [1-4]`, `HOST OFF`, `HOST DISARM`, `HOST STATUS`. [`preshow_test/`](preshow_test/app.py)
is a small window that drives it — ON/OFF per point, plus mode, bridge address, acknowledgement
latency and the send/retry/failure counters. It is how you check the TouchDesigner end without a
cube, and how you compare one plate's radio reach against another's.

The lease is 1.5 s and the app pings at 0.35 s, so closing the window, unplugging the laptop or
losing the port all drop any held cue rather than latching it ON for the rest of the show. A real
tag always takes the plate back from the override.

## Flash zones (zones/flasher/Launch.command)

Boards are **identified automatically** when plugged in, using the first of these that works:

1. The running firmware's own report.
2. The MAC looked up in the shared database (neocube or pairing station).
3. The zone identity stored in flash.
4. Text signatures of the legacy sketches in the firmware image.

Steps 2-4 briefly put the board in its bootloader. The table shows what each port is and what flashing would do.

- **Manual:** select the port. The form is pre-filled from what was detected: zone, point, name, pool calibration and RX gain. Click **Flash selected**.
- **RX gain** (18, 23, 33, 38, 43 or 48 dB, default 48) is the PN532 reader's receiver gain. It is stored in the zone
  identity (`zcfg` byte 7) and shown in the port list; *(not applied)* there means the reader did not accept it.
  Higher gain reads a weakly coupled tag but also amplifies noise, so lower it on a plate that misreads.
  Auto-flash keeps each board's gain. A board flashed before this setting existed runs, and reflashes, at 48 dB.
  The Zone Database Manager can change it over the air.
- **Auto-flash:** click **Arm auto-flash** and plug boards in one after another.
  - A board that already has a zone identity is updated in place, keeping its zone, point, name and RX gain. It is skipped if its firmware and database are already current.
  - A legacy sketch is flashed when it matches the selected zone. With *Next point after each new board* ticked, the point then advances.
  - An unidentified board is flashed only if *Flash unidentified boards…* is ticked.
  - Neocubes, the pairing station and non-zone controllers are refused by auto-flash.
  - **Force flash:** *Flash selected* on a REFUSED board asks (default No) whether to overwrite it anyway, e.g. a
    board the database still lists as a neocube/excluded device, or a range-test / pool-central board being
    repurposed. The known pairing station MAC and non-ESP32 USB devices can never be forced. The receipt records
    `forced: true`. Force-flashing a board registered as a **neocube** unregisters it once the zone firmware is
    written: its number, NFC tag and pending tag are released (event `unregistered`, receipt `unregistered`), its
    role stays `auto`, and later reflashes need no force. The flashed zone database is the one that was already
    published and still contains the old mapping. Publish a new zone database in the Zone Database Manager, and run
    Sync so the web copy and other computers take the release. An excluded device's record is not changed.
- **Every flash** does the following:
  - writes the firmware, the zone identity and the published cube database
  - reads the data back
  - reboots
  - checks the zone's own report
- **Build all firmware** rebuilds all four sketches. Headless: `python zones/flasher/zone_build.py`.

Headless flashing: `zone_flash.py --profile pool --point 4 --param 383 --param 43 [--rx-gain 38]`, `--detect`, `--check`, `--force` (overwrite a board listed as a neocube, unregistering it, or an excluded device).

Flashing takes no backup of the old firmware. Boards backed up by earlier versions can be restored from `data/backups/`:
`pairing_station/.venv/bin/python -m esptool --chip esp32c3 --port <port> write-flash 0 zones/flasher/data/backups/<MAC>_<time>.bin`

## Cube monitor (second tab)

The monitor connects by itself to a detected zone on USB (untick *Connect automatically* to stop that), so just tap a neocube. A tap brings this tab to the front, and the banner shows whether the cube acknowledged.

- **Card and LED ring.** The card shows the cube number, NFC UID, MAC, registry status, the zone command sent, and whether the **cube acknowledged it**. The LED ring is drawn in the colour the cube was last told to show. Check the real cube against it.
- **Unknown tags** are shown with a hint to pair them.
- **History** lists every tap: time, cube, result, time on plate.
- **Buttons** act on the cube on the plate, or on a selected history row: **Flash 5 s**, **Clear (idle white)**, **Preshow / Desert / Pool / Mainshow**, **Stop flashing**. They send real ESP-NOW commands through the connected zone.
  - A real tap always wins over a test flash.
  - The same commands work on the zone's serial console: `cube|zone|clear|flash <cubeID>`, `stop`.

## Update zones over the air: Zone Database Manager

`zones/dbmanager/app.py` (Finder: `zones/dbmanager/Launch.command`, VS Code: *Zone Database Manager*;
the pairing app's **Zones → Zone Database Manager…** opens it too).

- **ESP-NOW dongle.** Any ESP32-C3 running the pairing-station firmware **nct-pairing-1.8-zones** (1.7 works without
  RX gain control, 1.6 also without signal bars). Its zone
  relay needs no NFC reader. **Flash dongle…** builds that firmware if it is missing or stale, identifies the board
  and writes bootloader, partitions, boot selector and app separately, so NVS is kept. It refuses known cubes, known
  zone boards and the installed station (3C:0F:02:AD:83:24). It then records the dongle MAC as an `excluded` role so
  the cube and zone flashers leave it alone. Afterwards it reconnects and requires the `hello` to report that firmware.
  The real pairing station also works as the dongle when the pairing app is not holding its port.
- **Refresh / Auto-refresh (default on).** A broadcast status query, every 3 s with auto-refresh (30 s without).
  Zones that answered in the last 20 s are *in range*. States:
  - **current**: version and CRC match.
  - **out of date**: lower version.
  - **updating**: staging the published version.
  - **newer / differs**: a higher or equal version with different content, typically a legacy per-computer counter.
    Only a new publication fixes it.
- **Update selected** sends a unicast (never forced) announce to that zone, then broadcast chunks, until the zone
  reports the new version and CRC (45 s limit).
- **Update all** starts one broadcast run for every in-range zone that is out of date (after a confirmation).
  Zones that come into range during the run and need the version join it.
- **Progress window.** Every update run opens a window listing its zones with per-zone chunk progress; it
  blocks the main window until the run ends (Stop is in the window), then shows the result until closed.
  Automatic runs close it by themselves after 2 s.
- **Auto update all** (formerly *Walkaround*; `--auto-update-all`) needs auto-refresh. When no update is running, it starts one broadcast run for every in-range zone
  that is out of date. A zone that does not confirm is retried after 30 s. It never touches newer/different zones.
- **Signal** column: the dongle's RSSI for each zone, smoothed. `▂▄▆` at −67 dBm or better, `▂▄·` down to
  −80 dBm, `▂··` below that. Requires dongle firmware 1.7.
- **RX gain** column: the NFC reader gain stored on each zone. *(not applied)* means the reader did not accept it
  (absent, failing or disabled); it is applied again when the reader recovers. `—` means it was never reported:
  zone firmware before desert/tagplate-2.4.0, pool-3.2.0, preshow-3.3.0, or a dongle before 1.8.
- **Set RX gain…** (selected, in-range, configured zone; dongle 1.8) sends a unicast `ZONE_SET_CONFIG`. The zone
  rewrites `zcfg` (identity and calibration are kept), applies the gain to the reader at once without a reboot and
  answers with its settings. The column shows `→ N dB …` until that answer arrives; no answer in 10 s is logged as
  not confirmed. A radio delivery alone is never reported as success.
- **Actions for the selected zone** sit beneath the list: Update selected (only for an out-of-date zone),
  Update all, Identify, Show log, Reboot, Set RX gain….
- **Sync** (the same widget as in every app) uploads local inventory changes, downloads web changes and pulls or
  publishes the zone database. `↑` and `↓` count what is pending. Conflicts stop it and open **Web Sync…**. The
  **web allocates the version**: identical content keeps the current version; otherwise it becomes
  `max(current, min_version) + 1`, where `min_version` is the highest version this computer has seen on any zone
  or published locally. Versions are therefore universal and only increase, whichever computer publishes. Every
  computer must run this software: an old pairing-station app still publishes from its own counter.
- **Drop-outs.** If the dongle's USB drops mid-update, the update stops and Auto update all stays on. The same dongle
  is reopened automatically when it reappears. Zones keep a partial update for 60 s, and a repeated announce
  for the same version resumes it. If the dongle stops answering, the app re-handshakes and does not replay the
  interrupted command. A zone that leaves range times out (45 s) and discards its partial update itself.
- **Status line in every app** (pairing, both flashers, calibration, this manager). It warns when this computer's
  cube mappings are not in the published zone database (*N mapping changes not published*). It also warns when the
  web has a newer publication than this computer (*vN on the web … — Pull*), using the public
  `/api/zonedb/head` (no password). When offline it compares locally only and never blocks an app.
- The web password is asked for once and stored on this computer (`pairing_station/data/web_password`).

The zone flasher and PoolZone calibration write the **published** image (`ZoneStore.current()`). They warn when
this computer's mappings differ from it; they never allocate a version. Before the first web publication, a legacy
local publication is still used while the local mappings match its hash.

Serial commands on a zone (115200 baud): `?` report, `db` records, `log` recent tags, `rfcfg` (the gain the reader
is actually running), `rxgain` (stored/applied gain), `rxgain <dB>` (store and apply, as Set RX gain…), `help`.

Radio frames for settings: `ZONE_SET_CONFIG` 0x25 (9 bytes: confirm word `SCFG`, gain in dB; unicast only) and
`ZONE_SETTINGS` 0x26 (11 bytes: nonce, stored gain, applied gain or 0, result of the last change), sent after every
`ZONE_STATUS`. The status frame is unchanged, so older dongles and apps simply drop the settings frame.

## How updates stay safe

- **Two slots, A and B.** A new database is written to the inactive slot, read back and CRC-checked, then activated. The header is written last, so a power cut mid-write leaves that slot invalid and the zone boots the previous one. On boot the zone picks the valid slot with the highest version, then the highest generation.
- **Versions only go forward.** Zones accept a strictly newer version. An equal or older one needs a unicast `FORCE`.
- **Integrity is checked, not authenticity.** Updates are validated by CRC-32 over the whole record set, a chunk bitmap and record checks (sorted, unique UIDs, unicast MACs). There is no signing (by decision). Anything speaking the protocol on channel 2 can publish.
- **No frame collisions.** Zone frames start with `NZ` plus a protocol byte and are never 2 or 24 bytes long, so neocubes (which accept only 24 bytes) and the media bridge (only 2 bytes) ignore them. Chunks are at most 227 bytes, under the 250-byte ESP-NOW limit.
- **Partial updates expire.** Staging is discarded after 60 s without chunks. A reply to any announce or query includes staging progress.

Capacity: 1,819 records per slot (0x8000). A full chunk carries 12 records.

## Layout

| Path | Contents |
|---|---|
| `firmware/libraries/NctZone/` | Shared Arduino library: `NctTagPlate.h` (tag-plate application core), `NctCubeProtocol.h` (cube Packet), `NctZoneProtocol.h` (zone wire format), `NctPoolProtocol.h` (pool wire format), `NctPreshowProtocol.h` (preshow media wire format), `NctZoneDb` (slots/config/params), `NctZoneLink` (ESP-NOW updates, status, log, peers), `NctZonePartition.h` |
| `firmware/<Zone>/` | `PreshowZone`, `TagPlateZone`, `DesertZone`, `PoolZone` sketches, each with the same `partitions.csv` |
| `firmware/PoolCentral/` | Pool central controller: not a zone board, no zone partitions, its own board profile |
| `firmware/PreshowBridge/` | TouchDesigner media bridge: not a zone board, no zone partitions, its own board profile |
| `firmware/MainshowController/` | Main show trigger (SET_ZONE 4 / SHOW_START over ESP-NOW, BOOT button, trigger input): not a zone board |
| `tools/zonedb.py` | Python definition of every image/frame (used by the database manager, flasher and tests) |
| `dbmanager/` | Zone Database Manager (`app.py`) and ESP-NOW dongle flashing (`dongle.py`, also used for the Mainshow controller) |
| `mainshow/` | Mainshow Controller app (`app.py`): cube mainshow-ready, show trigger, controller flashing |
| `flasher/` | GUI (`app.py`), pipeline/CLI (`zone_flash.py`), board identification + auto-flash plan (`zone_detect.py`), cube monitor parsing (`zone_monitor.py`), builds (`zone_build.py`: `SKETCHES`, `PROFILES`) |
| `tests/` | Host-compiled firmware tests and Python tests |
| `ZONE_PORTING_NOTES.md` | How to move the other zone firmwares onto this system |

## Build

- Zone firmware: `pairing_station/.venv/bin/python zones/flasher/zone_build.py` (all sketches; pass names to build only some)
  - FQBN `esp32:esp32:nologo_esp32c3_super_mini:CDCOnBoot=cdc,PartitionScheme=no_ota`, Arduino-ESP32 3.3.11.
  - The sketch's own `partitions.csv` replaces the scheme's table.
- Pairing station firmware: add `--libraries zones/firmware/libraries` to its compile, e.g.
  `arduino-cli compile --fqbn esp32:esp32:esp32c3:CDCOnBoot=cdc --libraries pairing_station/.arduino/libraries --libraries zones/firmware/libraries pairing_station/firmware/pairing_station`
- Arduino IDE users: copy `zones/firmware/libraries/NctZone` into the sketchbook `libraries` folder.

## Tests

```
pairing_station/.venv/bin/python zones/tests/run_firmware_tests.py        # real library + PreshowZone sketch, ASan/UBSan
pairing_station/.venv/bin/python -m unittest discover -s zones/tests       # zonedb, flasher pipeline, Tk smoke
pairing_station/.venv/bin/python pairing_station/tests/run_firmware_test.py
pairing_station/.venv/bin/python -m unittest discover -s pairing_station/tests
```

The firmware tests use databases generated by `zonedb.py` from `pairing_station/original_32.json`, so Python and C++ are checked against the same bytes.
