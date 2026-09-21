# Adding or changing zone firmwares

All current tag zones are already ported (see the table in `README.md`). A new zone is normally a sketch of 40 lines or fewer on top of `NctTagPlate.h`. Use `firmware/DesertZone/DesertZone.ino` as the template for "tag plate plus local hardware", and `PoolZone` for "plus a sensor and a second ESP-NOW peer".

## New zone checklist

1. **Create the sketch.** `zones/firmware/<Name>/<Name>.ino` with a copy of `partitions.csv` (unchanged, so the flasher offsets stay identical).
2. **Set the version.** `constexpr const char *FIRMWARE_VERSION = "<prefix>-<semver>";` (at most 15 chars). Add the prefix to `FIRMWARE_PREFIX` in `flasher/zone_build.py`.
3. **Configure the plate.**
   - Create `TagPlate plate;`.
   - Set `TagPlateOptions` (`banner`, `zoneType`, or `0` to take the zone from flash).
   - Set the hooks:
     - `onTagEnter(uid, len, cube)` and `onTagLeave(uid, len, cube)`. `cube` is null for unregistered tags. The core has already sent `MSG_SET_ZONE` before `onTagEnter` runs, and keeps repeating it for up to three seconds (see `ZONE_REPEAT_MS` in `NctTagPlate.h`); set `options.repeatZone = false` only if a plate has a reason not to. Anything the hook sends to the same cube straight afterwards can overwrite the colour inside the cube, which is exactly what those repeats are for.
     - `onSerial(line)` for extra console commands, and `onReport()` for extra `?` lines (printed before `READY`).
   - Call `plate.begin(options)`, then `plate.printReport()` at the end of `setup()`.
   - Call `plate.loop()` in `loop()`. Never block. The PN532 poll already costs up to 80 ms per pass.
4. **Send frames.**
   - Extra messages to the cube: `plate.sendToCube(cube, MSG_…, value)`.
   - Anything else: `plate.sendFrame(mac, data, len, /*pinned*/true)`. Never send 24-byte frames that are not a cube `Packet`, and never send 2-byte frames.
5. **Use flash for zone identity.** Read `plate.config.pointId` and `plate.params.values[]` (integers, written by the flasher). Validate them, and set `ERR_PARAMS`/`ERR_SENSOR` via `plate.link.setError()` when something is missing. Never guess a point or radio ID.
6. **Register it.** In `flasher/zone_build.py`, add the sketch to `SKETCHES` and a `PROFILES` entry (label, sketch, `zone_type`, points, default name, params as `(label, default, multiplier)`). If legacy boards with a recognisable banner exist, add a signature to `zone_detect.SIGNATURES`.
7. **Test it.** Write `tests/test_<Name>.cpp` (include the sketch, then `sketch_test.h`), add the name to `SKETCHES` in `tests/run_firmware_tests.py`, and add stubs in `tests/stubs/zone_stubs.h` for new hardware APIs.

## Decisions made while porting (keep consistent)

- **Channel 2 everywhere.** Devices that join the router (`ShowStarter_M5Stack_Core2`) follow the AP's channel, so the AP must stay on channel 2.
- **Desert zone:**
  - `MSG_TAG_STATE=7` is still sent, as the original did. The current cube firmware (v1.4.2) reserves but ignores it.
  - OTA was dropped (no OTA slot in `partitions.csv`).
  - The PN532 chip-ID check (0x32) moved into the shared core for all zones.
- **Pool zone:**
  - The legacy radios and central controller were on channel 6 and could not reach cubes, which sit on channel 2.
  - Both are on channel 2 now: `PoolZone`, and `central_controller.ino` via a one-line change that needs a reflash.
  - `Poolzone_Radio_Control` (the slider debug sketch without NFC) is left on channel 6 and is superseded by `PoolZone` + serial `dist`.
- **Not zones:** `ShowStarter_M5Stack_Core2`, `m5core2_controlloer` (old registration console), the preshow media bridge (`SerialDAT`, now maintained at `firmware/PreshowBridge`) and the pool central controller have no cube table. They are not flashed by the zone flasher, which recognises and refuses the ESP32-C3 ones.
- **Show start (resolved by `firmware/MainshowController`):**
  - `ShowStarter_M5Stack_Core2.ino` broadcasts `MSG_SHOW_START = 7`.
  - Cube firmware v1.4.2 (`ForKimchi.ino`) expects `MSG_SHOW_START = 8`, because 7 became `MSG_TAG_STATE`, so cubes ignore the Core2.
  - `MainshowController` sends 8 through the shared `NctCubeProtocol.h` and supersedes the Core2. Don't bring the Core2 back without fixing its enum.

## Rules that keep the system compatible

- Keep `NctCubeProtocol.h` byte-identical to the cube firmware. The test runner checks it against `ForKimchi.ino`, and sketches must not carry private copies of `Packet`.
- New zone-management messages go in `NctZoneProtocol.h`, with `frameType()` length checks, the matching `zonedb.py` struct, and a test. Bump `PROTO` only for incompatible changes: zones and the station both drop other protocol versions.
- The flasher and the cube monitor parse these lines: the `?` report (`FW:` … `READY`), `EVT TAG|SENT|LEAVE|FLASH` and `DB UPDATE:`. Treat them as an interface.
