# Pool central controller

One ESP32-C3 that listens to the six `PoolZone` slider radios and drives the 23 member
frame lights. **It is not a zone board**: it has no PN532, no `zcfg`/`zdb` partitions, no
cube database, and it is not a target of the zone flasher.

Arbitration is pure OR, any-wins: a member frame is lit while **any** radio holds it.

```
PoolZone x6 ──PoolState (unicast, ESP-NOW ACK + retries)──▶ PoolCentral ──I2C──▶ 2x PCA9685
        ◀──────────── PoolBeacon (broadcast, 500 ms) ──────────┘
```

| | |
|---|---|
| Board | ESP32-C3, FQBN `esp32:esp32:esp32c3:CDCOnBoot=cdc,FlashFreq=40` (**not** the SuperMini profile) |
| I2C | SDA GPIO8, SCL GPIO9, 100 kHz, 25 ms transaction timeout |
| Outputs | Output index 1-16 = `0x40` channels 0-15, 17-23 = `0x41` channels 0-6; full-on/full-off only, no PWM |
| Wiring | Outputs are **not** wired to frames in order — see `POOL_OUTPUT_FOR_MEMBER` |
| Polarity | **Active low.** Channels drive relays, not lamps: lamp ON = channel LOW = relay energised |
| Radio | ESP-NOW channel 2, shared with the cubes, all zones and the pairing station |
| Wire format | [`NctPoolProtocol.h`](../libraries/NctZone/src/NctPoolProtocol.h) |

## The link

The central does not know a radio's MAC until it has heard from it, so the beacon is
broadcast. Each radio latches the beacon's source as a pinned peer and unicasts its state
back, which is what buys MAC-layer acknowledgement and hardware retries — the thing plain
broadcast could never provide. Each radio also keeps sending one broadcast copy every
450 ms, which costs nothing (the central de-duplicates on sequence) and rescues a radio
that latched a stale address.

- **Leases.** Every `PoolState` carries a requested lease, clamped to 600-2000 ms
  (default 800 ms, matching the original controller). A member stays lit while its holder's
  lease is good. Expiry is derived on every read, never swept by a timer, so there is no
  window in which a timeout can stomp a frame that just arrived.
- **Sequence and boot identity.** A late frame cannot re-assert an old member. Duplicates
  are ignored. A radio that reboots takes a new `bootId` and is accepted immediately
  despite restarting its sequence at zero, and a radio silent longer than any lease is
  likewise let back in.
- **`radioMask`.** Still in claimed-id space, since the radios read it back as
  `central_sees_me` and their firmware is unchanged. The beacon tells each radio whether the
  central is currently hearing it.
  Radios send idle heartbeats forever, so this distinguishes an idle slider from a dead
  one — and it means `RADIO TIMEOUT` in the log is now a genuine fault, not normal traffic.
- **Release hold.** A member stays lit for `POOL_RELEASE_HOLD_MS` (400 ms) after its radio
  last held it. Lighting a lamp is instant; only letting go is damped. Without this the
  central faithfully follows every momentary gap in a radio's reporting — a dropped range
  sample, a filter settling, a lost packet — and a relay switches off and straight back on.
  Set it to 0 in [`PoolArbiter.h`](PoolArbiter.h) for strict instantaneous OR.
- **One slot per sender, keyed by MAC.** Slots are allocated by the ESP-NOW source address,
  never by the radio id in the packet. A MAC is unique by construction, so two boards
  configured with the same id simply get a slot each and both work — the id is a label, not
  an address. There are `POOL_SLOT_COUNT` (8) slots for six sliders, so a replacement board
  can be brought up alongside the one it replaces. When every slot belongs to a board that is
  still live, a newcomer is refused and counted as `rx_no_slot` rather than evicting a slider
  that is currently lighting something; slots are reclaimed once a board falls out of its
  lease. `id_clashes` still reports boards sharing an id, because it means the labels are
  wrong even though nothing misbehaves.
- **Legacy frames.** The pre-2026 15-byte packet is still accepted, logged as `(LEGACY)`,
  so a slider missed during a rollout keeps working. A legacy frame can never displace a
  radio already speaking the current protocol while its lease is good.

## Frame-to-output wiring

The driver outputs are not wired to the frames in order, so **frame number and output index
are different things**. `POOL_OUTPUT_FOR_MEMBER` in [`PoolOutput.h`](PoolOutput.h) maps one to
the other, and the comment above it records the raw measurement it was derived from: each
slider index was selected in turn and the frame that actually lit was noted.

Everything else — the radio protocol, `desired`/`verified`/`known`, `FRAME n ON`, the whole
telemetry — stays in **frame numbers**. Only `verifyMember()` and `boardMask()` know about
output indices. Note that `boardMask()` is therefore not a contiguous range: the map scatters
frames across both driver boards, so which frames a board carries must be derived, never
assumed.

A compile-time check rejects a table that is not a permutation of 1..23, and the host tests
re-derive the map from the raw readings independently, so a transcription error cannot pass.

If the looms are re-terminated, re-measure, update the comment, and regenerate the table.

## Output polarity

The channels do not drive the lamps. Each one drives a relay whose coil is energised by a
**LOW** output. Since the 2026-09-21 rewire the lamps sit on the **energised** contact:

| Lamp | PCA9685 channel | Relay |
|---|---|---|
| ON | LOW (`FULL_OFF`) | energised |
| OFF | HIGH (`FULL_ON`) | de-energised |

`POOL_OUTPUT_ACTIVE_LOW` in [`PoolOutput.h`](PoolOutput.h) is the single switch. Writes,
readback comparisons, the periodic audit and the `ALL_LED` clear all derive from
`encodeOutput()`, and logs and telemetry (`FRAME n ON`, `desired`/`verified`) are always in
terms of the **lamp**, never the relay. If the relays are ever wired back the other way,
flip that one constant — do not hand-edit register values anywhere else.

### Boot

A PCA9685 powers up, and comes out of reset, with **every channel `FULL_OFF`** — which drives
it LOW. Under the rewired relays LOW means *energised*, so from the instant the driver boards
have power the hardware is asking for all 23 lamps to be on. Twenty-three coils pulling in at
once also sags the supply, so which of them actually latch varies from boot to boot.

`setup()` therefore darkens and **verifies** every channel before it does anything else —
before Wi-Fi and ESP-NOW, which take hundreds of milliseconds on this chip. It retries what is
still unproven, so a glitched transaction costs milliseconds rather than leaving lamps lit, and
it assumes nothing about the drivers or the bus, since resetting this chip resets neither. The
boot line reports `outputs=dark` or `outputs=UNVERIFIED`; the latter means a driver did not
answer and its lamps may still be on.

> **Still outside the firmware's control.** The window between the relay boards receiving power
> and this firmware running cannot be closed in software, and a board that never answers cannot
> be darkened at all. If that matters, it needs a hardware answer — driving `OE` from a pin that
> idles the relays off, or holding the coils de-energised with pull-ups.

## Output integrity

Every PCA9685 write is read back before it is cached as applied, so a NACKed write stays
pending and is retried instead of desynchronising a light until reboot. A board is only
declared offline after `I2C_FAILURES_BEFORE_OFFLINE` (3) **consecutive** failures: since the
rewire it is the lit state that energises a relay coil, and coil switching injects exactly
the supply dips and EMI that corrupt a transaction. One glitch must not trigger recovery,
because recovery bit-bangs the bus and rewrites `ALL_LED`, darkening every lamp on that
board for tens of milliseconds — long enough for a relay to drop out and pick up again. MODE1/MODE2 are
checked every 500 ms and one member register is audited every 20 ms, so a driver that
silently resets is detected and reinitialised, and only **currently leased** members are
restored. A stuck bus is cleared with the NXP nine-clock sequence, open-drain only.

## Build and flash

Back up the board's existing flash first (see `poolzone_test/README.md` for how the
original was preserved). Builds also run as part of `python scripts/build_all_firmware.py`.

```sh
arduino-cli compile --fqbn esp32:esp32:esp32c3:CDCOnBoot=cdc,FlashFreq=40 \
  --libraries zones/firmware/libraries \
  --output-dir zones/build/PoolCentral zones/firmware/PoolCentral
arduino-cli upload --fqbn esp32:esp32:esp32c3:CDCOnBoot=cdc,FlashFreq=40 \
  --port /dev/cu.usbmodem2101 --input-dir zones/build/PoolCentral zones/firmware/PoolCentral
```

### Flash speed — 40 MHz, deliberately

The installed board (`48:F6:EE:15:8E:E0`) could not read its own flash reliably at the default
80 MHz. It boot-looped on `esp_image: Checksum failed`, and the giveaway was that the
bootloader's **calculated** checksum differed on every boot (`0x1a`, then `0xf8`) while the
stored one stayed `0x78` — with the flash contents byte-for-byte identical to the build and
the image validating under `esptool image-info`. Correct data, non-deterministic reads: the
image was never the problem. At 40 MHz the same build boots and runs cleanly.

The speed lives in the **bootloader** header, which is what reads the app, so the bootloader
and the app must be flashed as a pair at the same setting. An 80 MHz bootloader will not
reliably read a 40 MHz app on this board, and vice versa. If a replacement board is fitted,
80 MHz can be tried again — but this costs nothing here, so there is little reason to.

Flash the central **before** the radios: the legacy shim keeps the existing sliders working
while they are updated one at a time.

## USB console (115200 baud)

- `STATUS` — one telemetry line plus one line per known sender.
- `OUT DUMP` — read every frame's registers back and report the **electrical level** as well
  as the lamp state, flagging any that disagree with what was requested. Read-only, safe at
  any time, and the way to answer a wiring question without a meter.
- `OUT ARM` / `OUT <1-23|ALL> ON|OFF` / `OUT DISARM` — drive the lamps directly, to check
  wiring without a slider. Arming takes the lamps off the radios and puts them all out. The
  override **leases itself**: any command renews it, and it releases back to the radios after
  two minutes on its own, so a forgotten arm cannot hold the show.
- `RECOVER` — clear and restart the I2C bus, then reapply the live selections.
- `TEST_SLEEP 64` / `TEST_SLEEP 65` — **maintenance fault injection.** Puts that driver to
  sleep to exercise automatic recovery. This briefly interrupts live lights.

Telemetry is emitted once a second as a `"type":"status"` line followed by one
`"type":"radio"` line per radio; both carry `"device":"PoolCentral"`, so a consumer must
select on `type` rather than taking the last matching line. The status line carries
`channel`, `epoch`, `radio_mask`, `rx_packets`,
`rx_legacy`, `rx_rejected`, `rx_no_slot`, `rx_overruns`, `id_clashes`, `slots_used`,
`desired`/`verified`/`known` bitmasks, `i2c_errors`,
`mismatches`, `recoveries`, `log_drops`, line levels and board state; then per radio
`mac`, `id`, `member`, `seq`, `lease_ms`, `legacy` and `seen_ms` — one line per known
sender, addressed by MAC, with `id` being only what that board calls itself. Log lines are dropped rather than
allowed to block light control, and `log_drops` counts them.

`rx_rejected` and per-slot `seq` gaps are the numbers to read first when diagnosing
instability: they measure how much of the link is actually being lost. `rx_no_slot` means
more boards are transmitting than there are slots.

## What the tests prove

`zones/tests/test_PoolCentral.cpp` covers initialisation, the beacon, OR arbitration,
sequence/`bootId` filtering, lease clamping and expiry, verified-write retry, driver-reset
and bus recovery, the receive-callback discipline, the legacy shim, and a six-radio lossy
load simulation run against both this sender and the previous one.

None of that proves radio delivery or light emission. Register readback verifies driver
state, not the OE pin, the 12 V supply or an actual lit lamp.
