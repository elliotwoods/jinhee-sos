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
| Board | ESP32-C3, FQBN `esp32:esp32:esp32c3:CDCOnBoot=cdc` (**not** the SuperMini profile) |
| I2C | SDA GPIO8, SCL GPIO9, 100 kHz, 25 ms transaction timeout |
| Outputs | `0x40` channels 0-15 → members 1-16; `0x41` channels 0-6 → members 17-23; full-on/full-off only, no PWM |
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
- **`radioMask`.** The beacon tells each radio whether the central is currently hearing it.
  Radios send idle heartbeats forever, so this distinguishes an idle slider from a dead
  one — and it means `RADIO TIMEOUT` in the log is now a genuine fault, not normal traffic.
- **Legacy frames.** The pre-2026 15-byte packet is still accepted, logged as `(LEGACY)`,
  so a slider missed during a rollout keeps working. A legacy frame can never displace a
  radio already speaking the current protocol while its lease is good.

## Output integrity

Every PCA9685 write is read back before it is cached as applied, so a NACKed write stays
pending and is retried instead of desynchronising a light until reboot. MODE1/MODE2 are
checked every 500 ms and one member register is audited every 20 ms, so a driver that
silently resets is detected and reinitialised, and only **currently leased** members are
restored. A stuck bus is cleared with the NXP nine-clock sequence, open-drain only.

## Build and flash

Back up the board's existing flash first (see `poolzone_test/README.md` for how the
original was preserved). Builds also run as part of `python scripts/build_all_firmware.py`.

```sh
arduino-cli compile --fqbn esp32:esp32:esp32c3:CDCOnBoot=cdc \
  --libraries zones/firmware/libraries \
  --output-dir zones/build/PoolCentral zones/firmware/PoolCentral
arduino-cli upload --fqbn esp32:esp32:esp32c3:CDCOnBoot=cdc \
  --port /dev/cu.usbmodem2101 --input-dir zones/build/PoolCentral zones/firmware/PoolCentral
```

Flash the central **before** the radios: the legacy shim keeps the existing sliders working
while they are updated one at a time.

## USB console (115200 baud)

- `STATUS` — one telemetry line plus one line per radio.
- `RECOVER` — clear and restart the I2C bus, then reapply the live selections.
- `TEST_SLEEP 64` / `TEST_SLEEP 65` — **maintenance fault injection.** Puts that driver to
  sleep to exercise automatic recovery. This briefly interrupts live lights.

Telemetry is emitted once a second: `channel`, `epoch`, `radio_mask`, `rx_packets`,
`rx_legacy`, `rx_rejected`, `desired`/`verified`/`known` member bitmasks, `i2c_errors`,
`mismatches`, `recoveries`, `log_drops`, line levels and board state; then per radio
`member`, `seq`, `lease_ms`, `legacy` and `seen_ms`. Log lines are dropped rather than
allowed to block light control, and `log_drops` counts them.

`rx_rejected` and per-radio `seq` gaps are the numbers to read first when diagnosing
instability: they measure how much of the link is actually being lost.

## What the tests prove

`zones/tests/test_PoolCentral.cpp` covers initialisation, the beacon, OR arbitration,
sequence/`bootId` filtering, lease clamping and expiry, verified-write retry, driver-reset
and bus recovery, the receive-callback discipline, the legacy shim, and a six-radio lossy
load simulation run against both this sender and the previous one.

None of that proves radio delivery or light emission. Register readback verifies driver
state, not the OE pin, the 12 V supply or an actual lit lamp.
