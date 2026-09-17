# PoolZone integration comparison

Baseline: `live files/laser_sensor/laser_sensor.ino` (v1.2.0, the NFC-enabled radio), `live files/PoolZone_Central_Controiler/central_controller/central_controller.ino`, and the current `ForKimchi.ino` NeoCube firmware (v1.4.2-ESPNOW-ONLY). `live files/Poolzone_Radio_Control` is a different, slider-only transmitter: its 3-sample filter / 60 ms settling were not used as the tagged-interaction baseline.

## Preserved / restored

| Function | Integrated PoolZone behavior |
|---|---|
| NeoCube/NFC activation | Restored; no tag means no light command unless Python override is explicitly armed. |
| NFC timing | Same 30 ms polling interval, 80 ms read timeout, 700 ms tag-removal grace. |
| GPIO5 strip | ON while activated, OFF after deactivation; independent of whether an index is selected, as before. |
| Slider filter / settling | One Euro adaptive smoothing now replaces the two-sample average; same 20 ms polling interval and 50 ms position settling; valid distances 10–1000 mm. |
| Central packets | Same packed 15-byte packet, magic `0x4E435450`, radio ID 1–6, active/member/UID fields. Immediate state-change packets and 150 ms active heartbeat. |
| Central fail-safe | Existing receiver retains its 800 ms radio timeout; no receiver changes needed for this packet format. |
| Cube command | Registered UID → database lookup → unicast `MSG_SET_ZONE=6`, `success=ZONE_POOL=3`, compatible 24-byte cube Packet. |
| Unknown tags | Still activate pool interaction, but no cube command is sent. Explicitly marked unknown in diagnostics. |
| Removing cube | Releases central/strip after grace period. Does not reset the cube's blue POOL state; the original also did not send a reset on leave. |
| Cube firmware | Existing ForKimchi firmware handles the POOL command, stops any running main show, and displays POOL color. No new cube binary or cube reflash was needed/performed. Its other show/pairing behavior is untouched. |
| Existing zone tools | Flash-seeded cube database, database updates, reader recovery, cube command console and flasher event protocol remain available. |

## Intentional differences / additions

- One Euro filtering is shared by display, index/light selection and captured control points. Raw distance is diagnostic only; min cutoff 0.8 Hz, beta 0.03 per mm/s, derivative cutoff 1 Hz.
- Piecewise control-point calibration in flash replaces two hard-coded endpoints. ±33% windows have unselected gaps; invalid/stale readings release the central member instead of retaining the old selection.
- Non-blocking laser reads with a 20 ms sensor budget, 100 ms initialization timeout (legacy used 250 ms), and a 400 ms freshness limit. Scheduling remains cooperative: NFC calls can extend the time between reads/heartbeats, as in the original design.
- Python override: explicit ARM, 350 ms keepalive, 1500 ms device watchdog, explicit disarm on disconnect. A real tag remains authoritative after disarming. Restart/reconnect never auto-arms.
- Central member output pauses during a calibration upload until SAVE or LOAD succeeds. This avoids transmitting partially applied tick data.
- Channel **2**, matching current NeoCube/zone firmware and the repository's central controller. The archived laser/radio sketches used channel 6. Any receiver/cube still running channel-6 firmware must be updated to the current channel-2 build.
- Cube tables and radio ID are stored in flash instead of compiled constants. A missing/invalid radio ID prevents central transmission.
- Diagnostics report the current cube even if the UI connects mid-tap, plus UID/MAC, link delivery result, NFC health, activation source, commanded light and packet queue/errors.

## Remaining limitations / checks

No core tagged PoolZone interaction from the NFC-enabled baseline is intentionally omitted. These items are **not proven by sender-side tests**:

1. A real registered NeoCube must be tapped to verify physical blue LEDs and wireless delivery on site. Host tests verify command bytes, successful and failed acknowledgements, and 700 ms removal behavior.
2. Central receipt and actual frame illumination need a live receiver/visual check. The broadcast protocol has no acknowledgement. The calibration interface reports requested member and queued packets, not measured light output. The separate `poolzone_test` receiver diagnostic UI remains available for I2C register verification.
3. The NeoCube must be present in the PoolZone flash database and on channel 2. Unknown tags activate the pool but cannot receive POOL color commands.
4. As in the original, the cube POOL command is sent once per tag entry; a failed delivery is shown, not automatically retried. Retap to retry. There is no application-level LED-state acknowledgement.
5. Archived router/OTA features were already removed from the current ForKimchi ESP-NOW-only firmware; this integration does not reintroduce them. They are not part of the original NFC PoolZone radio interaction.

## Validation

- ASan/UBSan host suite: shared zone core and all four zone sketches; PoolZone covers boundary/gap handling, flash reload, NeoCube POOL packet and ACK/failure, unknown tags, strip activation, member changes, heartbeat, tag removal, override renewal/expiry/late-ping refusal, real-tag precedence and calibration-upload interlock.
- Python interpolation/noisy-capture unit tests and Tk arming/debug/stale-state checks pass.
- Attached PoolZone `3C:0F:02:9F:D4:E4`: `pool-2.5.0` installed with application-only flash; latest control points preserved. Live test passed NFC/radio readiness, no-tag OFF, armed member transmission/heartbeat, watchdog release, late-ping refusal and explicit disarm. Evidence: local ignored `build/integration-hardware.log`.

- Firmware-tab updater: connected-board identity check, source/build fingerprint comparison, validated local-build reuse, full backup, application-only write, data verification and automatic disarmed reconnect. The updater now also syncs the current published cube mappings into the inactive slot and reports the installed/local database versions, counts and CRC. Database-only updates reuse the current firmware without rewriting it. Older firmware without a fingerprint is offered a one-time update.
