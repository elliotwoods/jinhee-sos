# General radio (`general-radio-1.1.0`)

1.1.0 (2026-09-23) adds the main-show relay for the console's Show editor, and the show timecode.
Everything in 1.0.0 is unchanged. The zone tools still accept 1.0.0 (`dongle.RELAY_VERSIONS`).

One ESP32-C3 USB dongle for every ESP-NOW host function in the installation. It speaks a
strict superset of the pairing-station relay protocol, so the pairing app and the Zone Database
Manager drive it unchanged; the Mainshow app drives it too (it is *not* recorded as the Mainshow
controller). `zones/tools/general_radio.py` is the Python client and bench command line.

- Board: a spare/ex-cube XIAO ESP32-C3 (native USB, 8 WS2812 status LEDs on GPIO10). No NFC reader.
- Build: `scripts/build_all_firmware.py` target *General radio* (FQBN `esp32:esp32:esp32c3:CDCOnBoot=cdc`,
  libraries `zones/firmware/libraries` + `live files/libraries`), output `zones/build/GeneralRadio/`.
- Flash: `pairing_station/.venv/bin/python zones/tools/general_radio.py --port <port> flash` — the
  `zones/dbmanager/dongle.py` pipeline: full-flash backup first, bootloader/partitions/boot selector/app
  only (NVS kept), refuses cubes, zones, the station and the recorded Mainshow controller, records the
  board as an `excluded` role.
- Host test: `zones/tests/test_GeneralRadio.cpp` (`python zones/tests/run_firmware_tests.py`).
- Radio: ESP-NOW channel 2, no encryption. Broadcast peer pinned; unicast peers added around one send.
  Sends wait up to 100 ms for the MAC-layer result; three sends in a row with no result at all mark
  the radio failed (`fatal`, reboot the board).

## Serial protocol

115200 baud, one JSON object per line each way. Every request carries `"id"` (1–40 chars), and its
reply echoes it; unsolicited events carry `"id":""` (the pairing station's cube events carry the
operation's id). A bare `?` line prints the plain-text report:

```
NCT GENERAL RADIO
FW: general-radio-1.0.0
MAC: AC:27:6E:82:68:54
CHANNEL: 2
RADIO: OK
READY
```

**Host gate.** Everything except `ping`, `hello`, `status`, `stop`, `led_test` and `nfc_*` needs
`radio_ok` and a `hello` or `ping` within the last 5 s (`Send hello/ping before operating`). The pool
lamp and the preshow cue are leased on the same heartbeat, 1.5 s: a host that goes quiet has its lamp
released (`pool_watchdog`) and its cue turned OFF (`preshow_watchdog`). A held cube (identify/register)
is returned to idle after 5 s of silence (`watchdog`), as on the station.

| Command | Fields | Reply / events |
|---|---|---|
| `ping` | | `pong` |
| `hello` | | `hello{protocol:1, firmware, zones:1, show:1 (1.1.0), mac, channel, radio_ok, nfc_ok:false, nfc_polling:false, tag_present:false, roles:[cube,zone,pool,preshow], led_pin, led_test, host_fresh, busy, lockout_ms, last_show_id, shows, show_running, show_length_ms, timecode, show_elapsed_ms, show_version, show_crc, tx{…}, rx{zone,zone_dropped,show,show_dropped,serial_overflows}, pool{armed,member,radio_id,central_mac,unicast,radio_mask,epoch}, preshow{armed,point,state,seq,acked,ack_ms,bridge_mac,unicast,mode,bridge_sees_me}}`. Releases a held cube, like the station |
| `status` | | the same body, event `status`, no side effects |
| `stop` | | `stopped`: releases a held cube (SET_ZONE 0), cancels pending colour repeats. Pool/preshow untouched |
| `nfc_status` / `nfc_poll` / `nfc_recover` | | `error "No NFC reader on this radio"` |
| `discover` | | `radio{…}`, `discover_sent`, then `device{mac}` per cube that answers |
| `identify` | `mac`, `duration_ms` ≤ 60000 (0 = until stop) | `identifying`, `radio{…}` per frame (zone 3/1 blink every 500 ms), `flash_done` |
| `register` | `mac`, `cube_id`, `uid` (4 or 7 bytes, colon hex) | `attempt{attempt,mac}` ×≤3 at 2 s, `radio{…}`, `ack_received`, `registered{mac,cube_id,acknowledged,detail}` |
| `zone_send` | `mac` (unicast or `FF:FF:FF:FF:FF:FF`), `hex` (frame built by `zones/tools/zonedb.py`) | `zone_sent{mac,kind,status}`. Kinds allowed: DB_ANNOUNCE, DB_CHUNK, ZONE_QUERY (broadcast ok), ZONE_IDENTIFY, ZONE_REBOOT, ZONE_SET_CONFIG (unicast only) |
| `set_zone` | `mac` (one cube) or `"broadcast"`, `zone` 0–4 | `zone_sent{mac,zone,status,repeats:3}` after the first frame, `zone_repeat{mac,zone,n,status}` (id `""`) at +120 and +400 ms, as the tag plates send a colour |
| `show_start` | `target`: `"broadcast"` or a MAC | `show_start{source:"usb",show_id,target,sent,repeats:5[,delivered]}` (fresh showId ×5 at 30 ms) or `locked{source,retry_ms}` inside the 3 s lockout |
| `pool` | `member` 1–23 (0 = release), `radio_id` 1–6 (default 1) | `pool_state{armed,member,radio_id,central_mac,unicast,radio_mask,epoch}` |
| `preshow` | `point` 1–4, `state` 1/0 | `preshow_state{…}`; later `preshow_ack{point,state,seq,ms,applied}` from the bridge, or `preshow_fail{point,state,seq}` once after 3 s unacknowledged |
| `led_test` | `on` 1/0 | `led_test{on,pin}` |
| `show_send` | `mac` (unicast or `FF:FF:FF:FF:FF:FF`), `hex` (frame built by `pairing_station/showfile.py`) | `show_sent{mac,kind,status}`. Kinds allowed: SHOW_ANNOUNCE, SHOW_CHUNK, SHOW_QUERY (never timecode or status). 1.1.0 |
| `show_config` | `length_ms` 1–3600000, `version`, `crc` | `show_config{…}`: the show length that bounds the timecode (RAM only; the console sends it on connect). 1.1.0 |
| `show_stop` | | `show_stop{was_running,show_id}`: ends the timecode (cubes keep playing until SET_ZONE 0). 1.1.0 |

Zone values: 0 idle (white), 1 preshow (red), 2 desert (amber), 3 pool (blue), 4 mainshow-ready (neon).
A cube checks neither `cubeID` nor the destination on `SET_ZONE`/`SHOW_START`, which is why
`set_zone` to every cube must be spelled `"broadcast"`. Send statuses: `delivered` (the receiver's
radio acknowledged — not proof it acted), `unconfirmed`, `rejected`, `no_result`, `peer_error`; a
broadcast is never acknowledged.

Unsolicited: `show_frame{mac,kind:83,rssi,hex}` for a cube's SHOW_STATUS (cube firmware v1.5.0+; 1.1.0),
`zone_frame{mac,kind,rssi,hex}` for zone status/log/settings replies (other registries'
announce/chunk/query traffic is dropped), `pool_beacon{mac,epoch,uptime_s,radio_mask,version}` and
`preshow_beacon{mac,epoch,uptime_s,point_mask,version}` (first sighting, address/epoch change, then at most
every 5 s), `watchdog` / `pool_watchdog` / `preshow_watchdog`, `fatal` (radio driver stopped answering).

## Roles

- **Cube** (`GrCube.h`): the pairing station's discover/identify/register state machine, plus the
  Mainshow controller's `set_zone` and `show_start`, and (1.1.0) the controller's `SHOW_TIMECODE`: once a
  second to the start's target while the show runs, bounded by `show_config`. `set_zone` repeats the colour three times because
  a cube's mailbox holds one frame and its loop idles on `delay(2)`.
- **Zone** (in the sketch): the station's relay, unchanged rules.
- **Pool** (`GrPool.h`): one emulated slider radio, the link `PoolRadioTest` and the real `PoolZone`
  speak (`NctPoolProtocol.h`): latch the central's beacon, unicast `PoolState` (broadcast until a beacon),
  burst 3×20 ms on a change, heartbeat every 150 ms while a member is held, release re-asserted for 1 s,
  a broadcast copy every 450 ms. **One lamp at a time per dongle:** the central keys its slots by sender
  address (`PoolCentral/PoolArbiter.h`), so `radio_id` is cosmetic there. Nothing is transmitted while no
  member is held.
- **Preshow** (`GrPreshow.h`): a fifth plate for the media bridge (`NctPreshowProtocol.h`): latch the
  bridge's beacon, burst 3×20 ms per edge, retry every 120 ms until the acknowledgement matching
  bootId+seq+point arrives (reported once after 3 s), re-assert the state every second forever, a broadcast
  copy every second; until a beacon has ever been heard, also the pre-2026 2-byte packet to the original
  bridge board. One cue per sender at the bridge: switching points is OFF then ON.
- **LEDs** (`GrLeds.h`): faint red scroll = no host, faint green = host lease fresh, strong green while a
  show it triggered should be running (298 s), `led_test` colour cycle. The BOOT button does nothing.

Not covered: the desert light panel, which only the desert plate's own reader drives. The cube-side half
of a desert tap is `set_zone … 2`.
