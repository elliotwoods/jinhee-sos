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

All are built on the shared tag-plate core (`NctTagPlate.h`). It handles PN532 polling, database lookup and `SET_ZONE` delivery with acknowledgment tracking, plus the update link and serial console. All run on the ESP32-C3 SuperMini with PN532 on SDA 4 / SCL 3.

| Flasher choice | Firmware | Replaces (`live files/`) | Behaviour |
|---|---|---|---|
| Preshow plate (points 1-4) | `PreshowZone` | `PreshowZone1` | cube → PRESHOW; media bridge `POINT n ON/OFF` |
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
- **The radios and the central are a matched set.** They must be reflashed together. Flash the central first: it still
  accepts the old 15-byte packet, so the existing sliders keep working while they are updated one at a time.

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

A member frame is lit while **any** radio holds it. Each `PoolState` carries a lease (clamped 600-2000 ms, default 800),
a per-boot identity and a sequence number, so a late frame cannot re-assert an old member and a rebooted radio is still
accepted at once. Changes are sent as a short burst and releases are repeated for a second, because a lost release
leaves a light stuck on for a whole lease. Idle radios keep heartbeating, so `RADIO TIMEOUT` at the central now means a
real fault, and the beacon's `radioMask` lets each radio report `central_sees_me` on its own USB console.

Pool frames share the `NZ` header but are deliberately **not** routed by `NctZoneProtocol.h::frameType()`; they reach
the sketch through `TagPlate::onFrame`. See the comment at the top of `NctPoolProtocol.h` for why.

## Flash zones (zones/flasher/Launch.command)

Boards are **identified automatically** when plugged in, using the first of these that works:

1. The running firmware's own report.
2. The MAC looked up in the shared database (neocube or pairing station).
3. The zone identity stored in flash.
4. Text signatures of the legacy sketches in the firmware image.

Steps 2-4 briefly put the board in its bootloader. The table shows what each port is and what flashing would do.

- **Manual:** select the port. The form is pre-filled from what was detected: zone, point, name and pool calibration. Click **Flash selected**.
- **Auto-flash:** click **Arm auto-flash** and plug boards in one after another.
  - A board that already has a zone identity is updated in place, keeping its zone, point and name. It is skipped if its firmware and database are already current.
  - A legacy sketch is flashed when it matches the selected zone. With *Next point after each new board* ticked, the point then advances.
  - An unidentified board is flashed only if *Flash unidentified boards…* is ticked.
  - Neocubes, the pairing station and non-zone controllers are always refused.
- **Every flash** does the following:
  - backs up the original flash (first time per MAC, in `data/backups/`)
  - writes the firmware, the zone identity and the published cube database
  - reads the data back
  - reboots
  - checks the zone's own report
- **Build all firmware** rebuilds all four sketches. Headless: `python zones/flasher/zone_build.py`.

Headless flashing: `zone_flash.py --profile pool --point 4 --param 383 --param 43`, `--detect`, `--check`.

Restore a board's original firmware from its backup:
`pairing_station/.venv/bin/python -m esptool --chip esp32c3 --port <port> write-flash 0 zones/flasher/data/backups/<MAC>_<time>.bin`

## Cube monitor (second tab)

The monitor connects by itself to a detected zone on USB (untick *Connect automatically* to stop that), so just tap a neocube. A tap brings this tab to the front, and the banner shows whether the cube acknowledged.

- **Card and LED ring.** The card shows the cube number, NFC UID, MAC, registry status, the zone command sent, and whether the **cube acknowledged it**. The LED ring is drawn in the colour the cube was last told to show. Check the real cube against it.
- **Unknown tags** are shown with a hint to pair them.
- **History** lists every tap: time, cube, result, time on plate.
- **Buttons** act on the cube on the plate, or on a selected history row: **Flash 5 s**, **Clear (idle white)**, **Preshow / Desert / Pool / Mainshow**, **Stop flashing**. They send real ESP-NOW commands through the connected zone.
  - A real tap always wins over a test flash.
  - The same commands work on the zone's serial console: `cube|zone|clear|flash <cubeID>`, `stop`.

## Update zones over the air

Open the pairing station app and click **Zones…** (or use the **Zones** menu).

- **Publish database** snapshots the committed mappings (the same rows as *Export reader table*: UID and cube ID, not pending, not excluded).
  - The version increases only when the content changed.
  - The station broadcasts an announce followed by all chunks, repeating about once a second.
  - It stops when every zone seen in the last 15 minutes reports the new version and CRC, or after 3 minutes.
  - Zones that answer during publishing are added to the wait list.
- **Query zones** broadcasts a status request. This also happens automatically every 30 s.
  - The table shows each zone's name, point, firmware and database version: green when current, amber when behind.
  - It also shows update progress, last seen, tag/unknown/failed-delivery counters and the last error.
- **Show log** fetches the zone's last 8 tags: UID, cube, and whether delivery was acknowledged.
- **Identify** blinks the zone's onboard LED. **Reboot** restarts it.
- Through the HTTP API (`zones` in the execute namespace; `/status` includes `zones`) you can also force a single zone back to an older version:
  `zones.publish(target='<zone MAC>', force=True)`. Forcing only works when targeted at one zone.

Serial commands on a zone (115200 baud): `?` report, `db` records, `log` recent tags, `help`.

The pairing station needs firmware **nct-pairing-1.6-zones** (see *Build* below). Older station firmware is reported as having no zone support.

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
| `firmware/libraries/NctZone/` | Shared Arduino library: `NctTagPlate.h` (tag-plate application core), `NctCubeProtocol.h` (cube Packet), `NctZoneProtocol.h` (zone wire format), `NctPoolProtocol.h` (pool wire format), `NctZoneDb` (slots/config/params), `NctZoneLink` (ESP-NOW updates, status, log, peers), `NctZonePartition.h` |
| `firmware/<Zone>/` | `PreshowZone`, `TagPlateZone`, `DesertZone`, `PoolZone` sketches, each with the same `partitions.csv` |
| `firmware/PoolCentral/` | Pool central controller: not a zone board, no zone partitions, its own board profile |
| `tools/zonedb.py` | Python definition of every image/frame (used by the pairing app, flasher and tests) |
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
