# Poolzone light test

USB-connected ESP32-C3 test bridge + Python/Tk GUI for the pool central controller, which is maintained at
[`zones/firmware/PoolCentral`](../zones/firmware/PoolCentral/README.md). The bridge emulates all six slider
radios so the lights can be exercised without sliders.

**The bridge speaks the current pool protocol and will not drive a legacy central.** Flash
`zones/firmware/PoolCentral` first.

Run using the existing project Python environment:

```sh
./poolzone_test/Launch.command --port /dev/cu.usbmodem101
```

Or install `requirements.txt` into a Python environment with Tk and run `python app.py`. Connect the bridge, choose a USB port, and click Connect. Toggle member lights 1–23; up to six can be selected simultaneously. Sequential test cycles one light at a time. All Off / Escape stops testing and releases all six radio slots. Channel defaults to **2**, matching the central source; turn everything off before applying another channel.

Power off other Poolzone radio transmitters during testing. The bridge emulates **all six radio IDs**, including release packets for unselected slots, so real radios using those IDs would compete with it. Brightness, colour and all-23-on are not supported by the existing central protocol. PCA9685 output indices 1–16 are 0x40 channels 0–15 and 17–23 are 0x41 channels 0–6, but the outputs are **not** wired
to the frames in order — the central applies `POOL_OUTPUT_FOR_MEMBER` — so the GUI's member numbers are frame numbers,
not channel numbers. Those channels drive relays and are
**active low** since the 2026-09-21 rewire, so a lit lamp reads as `FULL_OFF` in a register dump; the GUI and the
central's telemetry both report the lamp, not the relay.

The GUI displays requested/bridge-reported state, not measured light output. `queued` counts successful
`esp_now_send` submissions. An ESP-NOW unicast acknowledgement proves MAC-layer delivery to the central's radio,
not that its loop processed the frame; the per-radio `seq`/`seen_ms` in the central's telemetry, and the
`radio_mask` echoed in its beacon, are the application-level confirmation. ESP-NOW requires matching channels ([Espressif reference](https://docs.espressif.com/projects/esp-idf/en/v5.5/esp32/api-reference/network/esp_now.html)). Check central power, channel and PCA9685 wiring if packets are queued but lights do not change.

## Firmware

Requires Espressif Arduino ESP32 core 3.3.11. No sensor or external Arduino libraries required. Tested build target: ESP32-C3 Super Mini, 4 MB, USB CDC enabled. No local GPIOs are driven.

```sh
arduino-cli compile --fqbn esp32:esp32:nologo_esp32c3_super_mini:CDCOnBoot=cdc,PartitionScheme=no_ota --output-dir poolzone_test/build poolzone_test/firmware/PoolRadioTest
arduino-cli upload --fqbn esp32:esp32:nologo_esp32c3_super_mini:CDCOnBoot=cdc,PartitionScheme=no_ota --port /dev/cu.usbmodem101 --input-dir poolzone_test/build poolzone_test/firmware/PoolRadioTest
```

On this Mac the CLI is `/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli`.

Serial at 115200 baud, newline terminated:

- `STATUS`: JSON identity, channel, six members, queue/error counts.
- `SET m1 m2 m3 m4 m5 m6`: member 0 (release) or 1–23 for each radio ID.
- `PING`: renew 1500 ms host watchdog; GUI sends every 350 ms.
- `OFF`: clear every slot.
- `CHANNEL n`: channel 1–13; requires all slots off.

Frames are `PoolState` from [`NctPoolProtocol.h`](../zones/firmware/libraries/NctZone/src/NctPoolProtocol.h), the same
definition the real radios and the central use. The bridge listens for the central's `PoolBeacon`, then unicasts
to it (gaining ESP-NOW acknowledgement and retries) while still sending a periodic broadcast copy; with no beacon
it broadcasts only. Each emulated radio has its own boot identity and sequence. One slot is sent every 25 ms,
giving each radio a 150 ms heartbeat. The central's lease is 800 ms. USB loss clears slots in 1500 ms, followed by releases over the next 150 ms; if RF also fails the central timeout applies. Startup is all off. A full original flash backup for USB device `3c:0f:02:af:2c:20` is kept locally in ignored `build/backup-3c0f02af2c20.bin`.

## Receiver diagnostics and E2E test

The receiver firmware is no longer kept here. It is the production sketch,
[`zones/firmware/PoolCentral`](../zones/firmware/PoolCentral/README.md), which carries the same `STATUS`, `RECOVER` and
`TEST_SLEEP` diagnostics; see that README for build and upload commands. Keeping a second implementation of the same
protocol is what let the radios and the central drift apart in the first place.

The attached receiver `48:f6:ee:15:8e:e0` initially contained `POOL ESP-NOW SNIFFER v0.1` with `CDCOnBoot=default`,
rather than the central controller. Its full original flash is backed up locally at `build/backup-central-48f6ee158ee0.bin`.

Close the GUI to release the sender port before running:

```sh
pairing_station/.venv/bin/python poolzone_test/tests/e2e_check.py /dev/cu.usbmodem101 /dev/cu.usbmodem2101
```

The test checks receiver-side `RADIO` and `FRAME` logs for all 23 ON/OFF selections, six simultaneous radio slots, sustained heartbeats, All Off, and host watchdog release. It leaves all slots off and writes timestamped evidence to `build/e2e-latest.log`. An RF/handler pass does not prove physical illumination. I2C write errors are reported separately; `FRAME ON` in the original controller means an output write was attempted, even if its LED driver did not acknowledge.


## Receiver reliability fixes (history)

An intermittent failure was reproduced in the first receiver build: `FRAME 23 ON` at 10.507 seconds was followed by `RADIO TIMEOUT: 1` and `FRAME 23 OFF` at 10.659 seconds, just 152 ms later despite an 800 ms timeout and continuing heartbeats. The original receive callback shared state unsafely with the loop and printed to USB from the high-priority Wi-Fi task. The old code also cached failed I2C writes as successful, preventing a retry until a later state change.

These fixes now live in `zones/firmware/PoolCentral`. The receiver:

- Copies latest packets into a protected mailbox, and processes radio leases and output state only in the main loop. No serial or I2C calls run in the receive callback.
- Uses non-blocking, capacity-checked USB logging. Losing a log line is counted, and never delays light control.
- Runs I2C at 100 kHz with a 25 ms transaction timeout. Performs open-drain nine-clock bus clearing at startup and when a stuck line is detected.
- Reads back each output write before marking it applied. Failed writes remain pending; boards that disappear are retried once per second.
- Checks MODE1/MODE2 every 500 ms and audits all member output registers approximately twice per second, including unchanged outputs. A reset/sleeping driver is reinitialized and the latest live selections are restored. Expired selections are not restored.
- Reports receiver telemetry once per second: channel, received packet count, desired/verified/known member bitmasks, I2C errors, readback mismatches, recoveries, dropped logs, line levels and board state.

Run the GUI with both USB connections to see live receiver/I2C verification:

```sh
./poolzone_test/Launch.command --port /dev/cu.usbmodem101 --central /dev/cu.usbmodem2101
```

Receiver USB commands: `STATUS` reports telemetry; `RECOVER` clears/restarts the I2C bus and reapplies live selections. Maintenance test commands `TEST_SLEEP 64` / `TEST_SLEEP 65` deliberately put the respective LED driver to sleep with auto-increment disabled, exercising automatic recovery. These commands can briefly interrupt the selected lights and are intended only for testing.

`tests/i2c_soak.py` tests repeated member toggles and six-slot patterns against actual register readback, both driver sleep/reset recovery paths, explicit bus recovery and 45 seconds of wireless switching with the receiver USB monitor closed. Stop the GUI before running it. It uses the two ports above and saves evidence in `build/i2c-soak.log`.

Sources: [NXP PCA9685 register definitions](https://www.nxp.com/docs/en/data-sheet/PCA9685.pdf), [Espressif guidance on short ESP-NOW callbacks](https://docs.espressif.com/projects/esp-idf/en/v5.5/esp32/api-reference/network/esp_now.html). I2C readback verifies driver configuration and commands, not the physical OE pin, downstream supply or actual light emission.
