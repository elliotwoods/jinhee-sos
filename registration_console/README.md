# NCT screenless registration console

Standalone replacement for the M5Core2 registration console, using the 32 existing mappings from `mainshow_enter/mainshow_enter.ino`. No display, buttons, NFC scans, NFC library, or router is required. The PN532 can stay connected; this sketch does not use its pins. Nothing is transmitted until a registration or test command is entered.

## Build and upload

Open `registration_console.ino` in Arduino IDE. Use **esp32 by Espressif Systems 3.3.11** (the version used to compile this sketch). The connected device was identified as an ESP32-C3 with 4 MB flash at `/dev/cu.usbmodem101` (MAC `3C:0F:02:AD:83:24`). Select **ESP32C3 Dev Module**, **USB CDC On Boot: Enabled**, and its USB port. Do not select M5Core2. Upload only to the replacement console, not the installation cubes. This replaces the entrance-reader program on that board; the original sketch remains available in `mainshow_enter`.

Open Serial Monitor at **115200 baud**, with **Newline** or **Both NL & CR** enabled. Enter `help` if startup output was missed. Startup should report channel 2 and 32 mappings. All cubes must be powered and within radio range on channel 2.

## Commands

| Command | Effect |
| --- | --- |
| `list` | Print all mappings as `CubeID,MAC,NFC`. |
| `register 1` | Restore cube 1's stored ID and NFC UID using its mapped MAC. |
| `register all` | Restore all 32 entries in order. |
| `test 1` | Set cube 1 to neon for two seconds, then dim idle. |
| `test all` | Perform that light test on cubes 1 through 32 in order. |
| `stop` | Stop a sequence; attempt idle on the currently tested cube. |
| `help` | Print commands. |

Replace `1` with any cube ID from 1 to 32. Commands are lowercase. A new sequence is rejected while another runs; `list`, `help`, and `stop` remain available. Radio completion waits can delay command handling by up to 500 ms.

Start with `register 1`: the matching cube should blink green twice and the console should report `ACK Cube #1`. Then try `test 1` before the all-device commands. Registration does not require placing the tag on the reader.

## What results mean

Registration uses **individual unicast packets**, never a broadcast. The console allows two seconds for a matching application acknowledgment and retries up to three total attempts, then continues to the next cube. It pauses one second after acknowledgment for the cube's green blink. Duplicate or unrelated acknowledgments do not advance the sequence. Each temporary peer is removed after processing, avoiding a buildup of 32 peers.

`registration acknowledged` means the cube processed the registration request. Its existing firmware does not check/report successful flash writes, so this cannot prove persistence. `unconfirmed` can mean the cube is off, out of range, on another channel, or that an acknowledgment was lost; it does not prove that registration failed. Retry specific IDs as needed.

Light tests use the existing `MSG_SET_ZONE` behaviour. `sent` means accepted for transmission; the separate radio status reports link delivery. Neither proves the LEDs changed, because the cube does not send an application acknowledgment for zones. Observe the physical cube. Zone tests interrupt any running show, and idle is dim white rather than off. An interrupted USB connection does not automatically stop a running console sequence; use `stop` first. If the console loses power while a cube is neon, run `test N` again to return it to idle afterward.

The table is authoritative for this utility. Replaying it cannot determine whether physical tags have been swapped. Stop does not undo registrations already sent. A radio callback timeout aborts further radio operations until reboot; the current cube may remain illuminated.

## Verification

Run `python3 registration_console/tests/run_tests.py` from the parent folder. This host simulation exercises the actual sketch with mocked radio/time APIs: original table and packet declaration agreement, malformed/wrong acknowledgments, bounded retries, offline continuation, peer cleanup, light sequence and stop, busy/invalid commands, timer rollover, and radio faults.

The sketch also checks packet size/offsets at compile time and table validity at startup. Build validation used ESP32-C3 with USB CDC enabled. Hardware LED behaviour and persistence require a powered installation cube and have not been verified by the simulation.

ESP-NOW callback and radio delivery semantics follow [Espressif's ESP-NOW documentation](https://docs.espressif.com/projects/esp-idf/en/latest/esp32c3/api-reference/network/esp_now.html).
