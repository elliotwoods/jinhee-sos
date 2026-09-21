# PreshowBridge — the TouchDesigner media bridge

Receives cue events from the four preshow tag plates over ESP-NOW and writes one line per cue
to USB serial, where a TouchDesigner Serial DAT reads it.

```
PreshowZone x4 ──PreshowEvent (unicast, ESP-NOW ACK + retries)──▶ PreshowBridge ──USB──▶ TouchDesigner
        ◀────────PreshowAck   (unicast, echoes bootId+seq)────────┤
        ◀────────PreshowBeacon (broadcast, 500 ms)────────────────┘
```

It replaces `live files/Preshow_MediaServer_SerialDAT`, which is kept as the archived
original. That sketch was a pure listener: a hardcoded two-byte packet, no sequence number, no
acknowledgement, no retry. One lost frame meant the cue never fired, or the OFF never arrived
and the point stayed lit — and nothing anywhere could tell you it had happened.

**Not a zone board.** No PN532, no `zcfg`/`zdb` partitions, not a zone-flasher target. The
flasher recognises it by the banner string `NCT PRESHOW MEDIA BRIDGE` and refuses to touch it
(`zones/flasher/zone_detect.py`). Do not change that string.

## The TouchDesigner contract

```
PRESHOW,1,ON
PRESHOW,1,OFF
```

115200 baud. This format is a contract with a TouchDesigner project that does not live in this
repo, and it is byte-identical to what the legacy bridge emitted — nothing on the TD side
needed changing for any of this.

Two rules follow from TouchDesigner reading this port:

- **A line is written only when a point's state actually changes.** Retransmissions, the
  plates' periodic re-assert and duplicate frames are all silent.
- **Nothing is printed unless a human typed something.** The boot banner is the only
  unsolicited non-cue output, and the legacy bridge printed one too.

## What makes the link reliable

| Mechanism | What it buys |
|---|---|
| The bridge **broadcasts a beacon**; plates latch its address and **unicast** back | MAC-layer acknowledgement and hardware retries, which plain broadcast never had. And the bridge's MAC is no longer compiled into the plates, so swapping this board needs no reflash |
| The bridge **acknowledges every well-formed event** by `bootId`+`seq` | The plate retries until the serial line has really been written, not merely until the radio claimed delivery |
| Duplicates are acknowledged **too** | Otherwise one lost ack would leave a plate retrying for its whole window and then reporting a failure that never happened |
| `bootId`+wrapping-`seq` filter, one entry **per sender MAC** | A retry is recognised as a duplicate; a rebooted plate is taken back at once; two plates flashed with the same point cannot corrupt each other |
| Plates **re-assert** their current state every second; the bridge de-duplicates it | A cue lost while the bridge was rebooting or out of range heals itself within a second, invisibly to TouchDesigner |
| `PreshowBeacon.pointMask` reports what TouchDesigner **was told** | Each plate can show `bridge_sees_me` on its own console. A cue line that could not be written is not counted as delivered, and is retried |
| `WiFi.setSleep(false)`, and a receive callback that only hands the frame over | The two faults that made the legacy pool controller drop frames |

Timings and the wire format live in one place:
[`NctPreshowProtocol.h`](../libraries/NctZone/src/NctPreshowProtocol.h).

## Rollout

**Either order works.** This bridge accepts the pre-2026 two-byte packet, so plates that have not
been updated yet keep working while you do them one at a time. And a `preshow-3.2.0` or later plate *sends*
that packet as well until it has heard a beacon, so a plate can be replaced while this board is
still the original listener-only sketch — which is how Preshow 1 was brought up. A plate stops
sending the old packet the moment it hears a beacon from here, and never resumes.

So: flash whichever end needs it, whenever. Only once both ends are current do you get
acknowledged delivery, and a plate's `?` report tells you which mode it is in
(`MEDIA: mode=legacy` or `mode=modern`).

## Build and flash

```
pairing_station/.venv/bin/python scripts/build_all_firmware.py       # builds this among the rest
```

Or directly:

```
arduino-cli compile --fqbn esp32:esp32:esp32c3:CDCOnBoot=cdc \
  --libraries zones/firmware/libraries \
  --output-dir zones/build/PreshowBridge zones/firmware/PreshowBridge
arduino-cli upload --fqbn esp32:esp32:esp32c3:CDCOnBoot=cdc --port <port> \
  --input-dir zones/build/PreshowBridge
```

The board was rebuilt with a different antenna and power supply. If it is not a plain
ESP32-C3, the FQBN above and the one in `scripts/build_all_firmware.py` are the only things
that need changing.

## Console

Type into the serial port at 115200. Nothing is printed unless you do.

| Command | Effect |
|---|---|
| `?` or `STATUS` | One JSON status line, one per point, one per known plate (by MAC) |
| `TEST <1-4> ON\|OFF` | Drive a cue by hand, to check the TouchDesigner end without a plate. The owning plate's next re-assert puts the point back |
| `help` | The above |

Worth reading in the status line: `cue_drops` (lines TouchDesigner's port would not accept —
they are retried, not lost), `rx_duplicates` (normal; retries and re-asserts), `ack_errors`,
`point_clashes` (two plates flashed with the same point id), and `emitted_mask` versus
`desired_mask` (they differ only while a cue line is waiting to be written).

## Tests

```
pairing_station/.venv/bin/python zones/tests/run_firmware_tests.py
```

`zones/tests/test_PreshowBridge.cpp` compiles this sketch for the host against the same stubs
the zone firmwares use and checks the serial contract, the de-duplication, the acknowledgement
of duplicates, the bridge-reboot self-heal and the callback discipline.
`zones/tests/test_PreshowProtocol.cpp` checks the wire format itself.
