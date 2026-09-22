# MainshowController — the main show trigger

Starts the cubes' main-show timeline over ESP-NOW. It replaces
`live files/ShowStarter_M5Stack_Core2`. That sketch broadcast `MSG_SHOW_START = 7`, but cube
firmware v1.4.x moved the start to **8** (7 became `MSG_TAG_STATE`), so cubes ignored it.

**Not a zone board.** It has no PN532 and no `zcfg`/`zdb` partitions, and it is not a zone-flasher target. The
zone flasher recognises the banner `NCT MAINSHOW CONTROLLER` and refuses it
(`zones/flasher/zone_detect.py`). Do not change that string.

## How a show starts

What the cube does (flashing_station/firmware/neocore_usb):

1. `MSG_SET_ZONE` with `ZONE_MAINSHOW` (4) makes a cube **mainshow-ready** (neon). The mainshow
   entrance plates (`TagPlateZone`) send this when a cube is tapped, and the app's **Mainshow ready** button sends it too.
2. `MSG_SHOW_START` (8) with a showId in `Packet.cubeID` starts the cube's local ~4:58 timeline. It only starts
   on a cube that is ready. A repeated showId is ignored, and when the timeline ends the cube leaves ready mode.

Every trigger uses a fresh random showId. Each trigger is sent **5 times, 30 ms apart**, as the Core2 did.

### Show timecode (mainshow-1.3.0)

While a show runs, the controller sends `SHOW_TIMECODE` (showId and the show time,
`NctShowProtocol.h`) once a second to the start's target: broadcast for the button, the trigger input and
a broadcast start, or the one cube for a unicast start. The first timecode goes straight after the burst.
- A cube on v1.5.0 or later that is mainshow-ready but missed the start **joins** at that time.
- A running cube snaps its clock back when it has drifted more than 100 ms.
- Cubes older than v1.5.0 ignore timecode (they accept only 24-byte frames), and no cube needs it: the
  start is unchanged, so an older controller still works.

The show length bounds the timecode and the green status. It comes from `show_config` and is kept in NVS;
the default is 298 s. The console's Show editor sends it after a publish. `show_stop` ends the timecode.
It does not stop the cubes; `SET_ZONE 0` does.

## Triggers

| Source | Target | Notes |
|---|---|---|
| USB (`zones/mainshow/app.py`) | one cube (unicast) or broadcast | JSON lines, below |
| BOOT button (GPIO9) | broadcast | on-board button; works with no computer attached |
| Trigger input, XIAO **D1 = GPIO3** | broadcast | internal pull-up; pull to **GND** to trigger (contact closure / open-collector) |

- The inputs have a 50 ms debounce and fire on a press, never on a release.
- A held input fires once. It must be released before it can fire again, and an input already held at power-on does not fire.
- The show wiring may hold the trigger input closed for the whole show (about 10 minutes). The input must have been **open for at
  least 1 s** (`TRIGGER_REARM_MS`) before a closure counts as a new trigger.
  - A dropout in the held signal is therefore ignored: under 50 ms it is invisible, and from 50 ms to 1 s it is reported as `ignored`
    with `open_ms`.
  - After power-up the input also needs 1 s open before it is armed.
- All sources share a **3 s lockout** (the Core2's `SHOW_LOCK_MS`). A trigger inside the lockout is refused and reported as `locked`.
- The desert zone drives its lights from GPIO1, but GPIO1 is not broken out on the XIAO ESP32-C3. D1 is
  not a strapping pin, and D10 is avoided because an ex-cube board may still have its LED data line on it.
- The BOOT button is a strapping pin. Holding it **while powering up** starts the ROM bootloader instead of the show firmware.

## Status LEDs

This runs on ex-cube boards, which carry the cube's eight WS2812s on XIAO **D10** (GPIO10).

| State | LEDs |
|---|---|
| Waiting for a show start | faint red (12 of 255) scrolling slowly, one pixel per 180 ms |
| Show running | strong green (100, the cube's cap) scrolling fast, one pixel per 60 ms |
| `led_test` on | red, green, blue, white (1 s each), then each pixel alone in white, repeating |

- The controller hears nothing back from the cubes, so **"running" means within the show length of the last trigger**
  (298 s unless `show_config` set another; `show_stop` ends it early). It covers every trigger source, including a unicast trigger from the app.
- Green therefore means "a show was started less than 4:58 ago", not "cubes are playing". A cube that was not
  mainshow-ready, or did not hear the start, is not playing.
- The status also doesn't follow a trigger input that stays closed longer than the show. It turns red again at 4:58 while the input is still held.
- `{"cmd":"led_test","on":1|0}` switches the bench cycle on or off. Off returns to the status scroll.

## USB protocol (115200, one JSON object per line)

| Request | Reply |
|---|---|
| `{"cmd":"hello","id":"…"}` | `hello` with `firmware`, `mac`, `channel`, `radio_ok`, `button_pin`, `trigger_pin`, `lockout_ms`, `rearm_ms`, `last_show_id`, `shows`, `led_pin`, `led_test`, `show_running`, `show_length_ms`, and from 1.3.0 `timecode:true`, `timecode_ms`, `show_elapsed_ms`, `show_version`, `show_crc` |
| `{"cmd":"show_config","id":"…","length_ms":N,"version":V,"crc":C}` | `show_config` echoing them (1.3.0; stored in NVS) |
| `{"cmd":"show_stop","id":"…"}` | `show_stop` with `was_running`, `show_id` (1.3.0; ends the timecode only) |
| `{"cmd":"ping","id":"…"}` | `pong` |
| `{"cmd":"set_zone","id":"…","mac":"AA:BB:…","zone":0-4}` | `zone_sent` with `status`: `delivered` \| `unconfirmed` \| `rejected` \| `no_result` |
| `{"cmd":"show_start","id":"…","target":"broadcast"\|"AA:BB:…"}` | `show_start` with `source`, `show_id`, `target`, `sent`, `repeats` and, for unicast only, `delivered` (out of `repeats`) |

- The same `show_start` event is sent unsolicited, with `id:""` and `source` `button` or `pin`, when a physical input triggers.
- Other events are `locked` (with `retry_ms`), `ignored` (a trigger-input dropout, with `open_ms` and `rearm_ms`) and `error` (with `detail`).
- A plain `?` prints the text report (`NCT MAINSHOW CONTROLLER`, `FW:`, `MAC:`, `CHANNEL:`, `READY`).
- There is no heartbeat requirement: the board must trigger the show with nothing attached.

`delivered` means the cube's **radio** acknowledged the frame. It is not proof that the cube changed zone or started
the show; only its LEDs show that. A broadcast is never acknowledged.

## Build, flash, test

- Built by `scripts/build_all_firmware.py` (`esp32:esp32:esp32c3:CDCOnBoot=cdc`, the same board recipe as the
  pairing-station dongles), into `zones/build/MainshowController`.
- Flash it from the Mainshow app (**Flash controller firmware…**). That reuses the dongle pipeline in
  `zones/dbmanager/dongle.py`: it refuses cubes, zone boards and the pairing station, takes a first-time full backup, preserves NVS and ends with a watchdog reset.
- The board is then recorded as the controller (metadata `mainshow_controllers`), and the dongle flasher refuses to turn it back into a relay.
- Host test: `zones/tests/test_MainshowController.cpp`, run by `zones/tests/run_firmware_tests.py`.
