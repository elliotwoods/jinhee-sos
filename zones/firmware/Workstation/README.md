# Workstation (`workstation-1.0.0`)

One ESP32-C3 USB dongle for every ESP-NOW host function in the installation, *including the pairing
station's NFC reader*. It speaks a strict superset of the pairing-station protocol
(`pairing_station/firmware/pairing_station`, frozen) and of the General Radio it replaces (its
protocol lineage is below), so the pairing app, the Zone Database Manager, the Mainshow app and the
NCT Console drive it unchanged. `zones/tools/workstation.py` is the Python client and bench command line.

- Board: a spare/ex-cube XIAO ESP32-C3 (native USB, 8 WS2812 status LEDs on GPIO10) with a PN532
  reader on I2C, SDA GPIO4 / SCL GPIO3, as on the station. Without a reader wired the board still
  boots and answers every command (`nfc_ok:false`, `ready:false`, `i2c_status:5`); the radio is unaffected.
- Build: `scripts/build_all_firmware.py` target *Workstation* (FQBN `esp32:esp32:esp32c3:CDCOnBoot=cdc`),
  output `zones/build/Workstation/`. Libraries: `zones/firmware/libraries` (the NctZone/NctShow protocol
  headers), `live files/libraries` (Adafruit_NeoPixel, Adafruit_PN532, Adafruit_BusIO) and
  `pairing_station/.arduino/libraries` (the station's Adafruit_PN532/BusIO). By hand:
  ```
  arduino-cli compile --fqbn esp32:esp32:esp32c3:CDCOnBoot=cdc --libraries zones/firmware/libraries \
      --libraries "live files/libraries" --libraries pairing_station/.arduino/libraries \
      --build-path zones/build/Workstation/cache --output-dir zones/build/Workstation zones/firmware/Workstation
  ```
- Flash: `pairing_station/.venv/bin/python zones/tools/workstation.py --port <port> flash` — the
  `zones/dbmanager/dongle.py` pipeline: full-flash backup first, bootloader/partitions/boot selector/app
  only (NVS kept), refuses cubes, zones, the station and the recorded Mainshow controller, records the
  board as an `excluded` role.
- Host test: `zones/tests/test_Workstation.cpp` (`python zones/tests/run_firmware_tests.py`), including the
  station's fresh-tag gating ported from `pairing_station/tests/firmware_test.cpp`.
- Radio: ESP-NOW channel 2, no encryption. Broadcast peer pinned; unicast peers added around one send.
  Sends wait up to 100 ms for the MAC-layer result; three sends in a row with no result at all mark
  the radio failed (`fatal`, reboot the board).

## Serial protocol

115200 baud, one JSON object per line each way. Every request carries `"id"` (1–40 chars), and its
reply echoes it; unsolicited events carry `"id":""` (the pairing station's cube events carry the
operation's id). A bare `?` line prints the plain-text report; the `NFC:` line is the tag plates' format,
the rest is byte-identical to the General Radio's (the console's probe and `zone_detect.py` parse it):

```
NCT WORKSTATION
FW: workstation-1.0.0
MAC: AC:27:6E:82:68:54
CHANNEL: 2
RADIO: OK
NFC: ok=1 fw=32010607 polling=0 polls=0 found=0 last_ms=0 max_ms=0 fast_fail=0 recoveries=0 sda=1 scl=1
READY
```

Boot: `nfc_bus` (the bus clear), up to three `nfc_init{attempt,i2c_status,firmware,ready}` (or `nfc_error`
when a line is held low), then the report and an unsolicited `hello` carrying the reader's real state.
About 1.8 s at worst without a reader.

**Host gate.** Everything except `ping`, `hello`, `status`, `stop`, `led_test` and `nfc_*` needs
`radio_ok` and a `hello` or `ping` within the last 5 s (`Send hello/ping before operating`). The pool
lamp and the preshow cue are leased on the same heartbeat, 1.5 s: a host that goes quiet has its lamp
released (`pool_watchdog`) and its cue turned OFF (`preshow_watchdog`). A held cube (identify/register)
is returned to idle after 5 s of silence (`watchdog`), as on the station.

**The reader polls only while a host asks** (`nfc_poll enabled:true`, which the pairing app and the console
send on connect, as the station required), so a bare dongle relaying zone or show frames is never slowed
by the 80 ms read, and never toggles GPIO3/4 after boot. Automatic reader recovery (every 5 s after a
`PN532 lost` error) also runs only while polling is wanted.

| Command | Fields | Reply / events |
|---|---|---|
| `ping` | | `pong` |
| `hello` | | `hello{protocol:1, firmware, zones:1, show:1, mac, channel, radio_ok, nfc_ok, nfc_polling, nfc_firmware, nfc_i2c_status, tag_present, roles:[cube,zone,pool,preshow,nfc], led_pin, led_test, host_fresh, busy, lockout_ms, last_show_id, shows, show_running, show_length_ms, timecode, show_elapsed_ms, show_version, show_crc, tx{…}, rx{zone,zone_dropped,show,show_dropped,serial_overflows}, pool{armed,member,radio_id,central_mac,unicast,radio_mask,epoch}, preshow{armed,point,state,seq,acked,ack_ms,bridge_mac,unicast,mode,bridge_sees_me}}`. Releases a held cube (and ends its scan), like the station |
| `status` | | the same body, event `status`, no side effects |
| `stop` | | `stopped`: releases a held cube (SET_ZONE 0), ends its scan, cancels pending colour repeats. Pool/preshow untouched |
| `nfc_recover` | | idle only (`Stop before reader recovery`). Stops polling, clears the bus (`nfc_bus{sda_before,scl_before,sda_after,scl_after,pulses}`), restarts the reader: `nfc_recovered{bus_clear,ready,firmware,i2c_status}` |
| `nfc_poll` | `enabled` 1/0, `once` 1, `trace` 1/0 | idle only (`Stop before reader diagnostics`). `enabled` switches polling on/off; `once` reads now and leaves polling off (the station's semantics); `trace` switches the `nfc_i2c` transaction trace on. `nfc_poll_result{ready,enabled,polls,found,duration_ms,tag_present[,uid]}` |
| `nfc_status` | | idle only (`Stop the current operation before reader diagnostics`). `nfc_status{sda,scl,i2c_status,status_source:"firmware_response",firmware_now,nfc_polling,polls,found,last_poll_ms,max_poll_ms,trace}`; `firmware_now` is queried now, not cached |
| `discover` | | `radio{…}`, `discover_sent`, then `device{mac}` per cube that answers |
| `identify` | `mac`, `duration_ms` ≤ 60000 (0 = until stop) | `tag_state{present:true}` (synthetic: the reader must see its interval clear first), `radio{…}`, `identifying`, `radio{…}` per frame (zone 3/1 blink every 500 ms), `tag{id,uid}` once per tag placed after the clear interval, `flash_done` |
| `register` | `mac`, `cube_id`, `uid` (4 or 7 bytes, colon hex) | `attempt{attempt,mac}` ×≤3 at 2 s, `radio{…}`, `ack_received`, `registered{mac,cube_id,acknowledged,detail}`. Ends the identify scan |
| `zone_send` | `mac` (unicast or `FF:FF:FF:FF:FF:FF`), `hex` (frame built by `zones/tools/zonedb.py`) | `zone_sent{mac,kind,status}`. Kinds allowed: DB_ANNOUNCE, DB_CHUNK, ZONE_QUERY (broadcast ok), ZONE_IDENTIFY, ZONE_REBOOT, ZONE_SET_CONFIG (unicast only) |
| `set_zone` | `mac` (one cube) or `"broadcast"`, `zone` 0–4 | `zone_sent{mac,zone,status,repeats:3}` after the first frame, `zone_repeat{mac,zone,n,status}` (id `""`) at +120 and +400 ms, as the tag plates send a colour |
| `show_start` | `target`: `"broadcast"` or a MAC | `show_start{source:"usb",show_id,target,sent,repeats:5[,delivered]}` (fresh showId ×5 at 30 ms) or `locked{source,retry_ms}` inside the 3 s lockout |
| `pool` | `member` 1–23 (0 = release), `radio_id` 1–6 (default 1) | `pool_state{armed,member,radio_id,central_mac,unicast,radio_mask,epoch}` |
| `preshow` | `point` 1–4, `state` 1/0 | `preshow_state{…}`; later `preshow_ack{point,state,seq,ms,applied}` from the bridge, or `preshow_fail{point,state,seq}` once after 3 s unacknowledged |
| `led_test` | `on` 1/0 | `led_test{on,pin}` |
| `show_send` | `mac` (unicast or `FF:FF:FF:FF:FF:FF`), `hex` (frame built by `pairing_station/showfile.py`) | `show_sent{mac,kind,status}`. Kinds allowed: SHOW_ANNOUNCE, SHOW_CHUNK, SHOW_QUERY (never timecode or status). SHOW_LIVE (kind 85, up to 247 bytes) to `FF:FF:FF:FF:FF:FF` only; unicast is refused (`SHOW_LIVE is broadcast only`) |
| `show_config` | `length_ms` 1–3600000, `version`, `crc` | `show_config{…}`: the show length that bounds the timecode (RAM only; the console sends it on connect) |
| `show_stop` | | `show_stop{was_running,show_id}`: ends the timecode (cubes keep playing until SET_ZONE 0) |

Zone values: 0 idle (white), 1 preshow (red), 2 desert (amber), 3 pool (blue), 4 mainshow-ready (neon).
A cube checks neither `cubeID` nor the destination on `SET_ZONE`/`SHOW_START`, which is why
`set_zone` to every cube must be spelled `"broadcast"`. Send statuses: `delivered` (the receiver's
radio acknowledged — not proof it acted), `unconfirmed`, `rejected`, `no_result`, `peer_error`; a
broadcast is never acknowledged.

Unsolicited: `tag_state{present}` on every tag arrival/departure while polling (departure 700 ms after the
last read), `tag{id,uid}` during identify, `nfc_error{detail}` (`Unsupported UID length; remove this tag`,
`PN532 lost: …`, the held-low line at boot), `nfc_init{…}` and `nfc_bus{…}` at boot and on recovery,
`nfc_i2c{direction,requested,status,ms,hex}` for I2C failures only (every transaction with `trace:1`;
skipped when the USB port is not being drained), `show_frame{mac,kind:83,rssi,hex}` for a cube's
SHOW_STATUS (cube firmware v1.5.0+), `zone_frame{mac,kind,rssi,hex}` for zone status/log/settings replies
(other registries' announce/chunk/query traffic is dropped), `pool_beacon{mac,epoch,uptime_s,radio_mask,version}`
and `preshow_beacon{mac,epoch,uptime_s,point_mask,version}` (first sighting, address/epoch change, then at most
every 5 s), `watchdog` / `pool_watchdog` / `preshow_watchdog`, `fatal` (radio driver stopped answering).

## Roles

- **Cube** (`WsCube.h`): the pairing station's discover/identify/register state machine, plus the
  Mainshow controller's `set_zone` and `show_start`, and the controller's `SHOW_TIMECODE`: once a
  second to the start's target while the show runs, bounded by `show_config`. `set_zone` repeats the colour three times because
  a cube's mailbox holds one frame and its loop idles on `delay(2)`.
- **Reader** (`WsNfc.h`, `Pn532Wire.h`): the station's PN532 handling (nine-clock bus clear, three init
  attempts, the fresh-tag gating during identify, the `nfc_*` diagnostics with the station's field names)
  plus the tag plates' supervision: the PN532 IC byte (0x32) is checked on every firmware query, a live
  firmware query runs every 3 s while no tag is present, ten fast-failing scans in a row (a read that
  returns in under 20 ms never reached the chip) drop the reader with one `PN532 lost` error, and it is
  brought back every 5 s while a host wants polling.
- **Zone** (in the sketch): the station's relay, unchanged rules.
- **Pool** (`WsPool.h`): one emulated slider radio, the link `PoolRadioTest` and the real `PoolZone`
  speak (`NctPoolProtocol.h`): latch the central's beacon, unicast `PoolState` (broadcast until a beacon),
  burst 3×20 ms on a change, heartbeat every 150 ms while a member is held, release re-asserted for 1 s,
  a broadcast copy every 450 ms. **One lamp at a time per dongle:** the central keys its slots by sender
  address (`PoolCentral/PoolArbiter.h`), so `radio_id` is cosmetic there. Nothing is transmitted while no
  member is held.
- **Preshow** (`WsPreshow.h`): a fifth plate for the media bridge (`NctPreshowProtocol.h`): latch the
  bridge's beacon, burst 3×20 ms per edge, retry every 120 ms until the acknowledgement matching
  bootId+seq+point arrives (reported once after 3 s), re-assert the state every second forever, a broadcast
  copy every second; until a beacon has ever been heard, also the pre-2026 2-byte packet to the original
  bridge board. One cue per sender at the bridge: switching points is OFF then ON.
- **LEDs** (`WsLeds.h`): faint red scroll = no host, faint green = host lease fresh, strong green while a
  show it triggered should be running (298 s), `led_test` colour cycle. The BOOT button does nothing.

Not covered: the desert light panel, which only the desert plate's own reader drives. The cube-side half
of a desert tap is `set_zone … 2`.

## Version history

- **workstation-1.0.0** (2026-09-23): the General Radio 1.2.0 protocol plus the pairing station's PN532
  reader (`nfc_recover` / `nfc_poll` / `nfc_status`, `tag` / `tag_state` during identify, `nfc` in `roles`,
  the `NFC:` report line). Banner `NCT WORKSTATION`. The `nfc_i2c` trace is off for successful transactions
  unless `nfc_poll trace:1`, and is skipped when the USB port is not being drained.

### Lineage (General Radio, `zones/firmware/GeneralRadio`, replaced by this sketch)

- **general-radio-1.2.0** (2026-09-23): `show_send` relays the Show editor's SHOW_LIVE frames (0x55, broadcast
  only; cube firmware v1.7.0+ mirrors the editor's colour for a lease). Nothing else changed.
- **general-radio-1.1.0** (2026-09-23): the main-show relay for the console's Show editor, and the show
  timecode. Everything in 1.0.0 unchanged. The zone tools accept 1.0.0 and 1.1.0 (`dongle.RELAY_VERSIONS`).
- **general-radio-1.0.0**: the pairing-station relay protocol (no reader: `nfc_ok:false`, `nfc_*` answered
  with `No NFC reader on this radio`), the Mainshow verbs, the emulated pool radio and preshow plate.
