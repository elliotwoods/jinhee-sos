# ESP-NOW range test

Measures how reliably ESP-NOW reaches the back room from the exhibition space, on
channel **2**, using two boards identical to the Neocore cubes (XIAO ESP32-C3 +
external antenna + battery + eight WS2812s on `D10`).

**TX** (blue) is carried around the space on battery and shows link quality on its
own LEDs. **RX** (red) stays in the back room and answers every ping with an ACK
carrying the RSSI it measured. A Tk console on the RX shows the link live.

| MAC | Role | Port at time of writing |
|---|---|---|
| `1C:DB:D4:F0:C3:E0` | TX | `/dev/cu.usbmodem1101` |
| `1C:DB:D4:F0:D2:20` | RX | `/dev/cu.usbmodem101` |
| `AC:27:6E:82:68:54` | TX | `/dev/cu.usbmodem1101` |
| `1C:DB:D4:F0:CF:4C` | RX | `/dev/cu.usbmodem101` |

Roles come from a MAC table in the sketch, so there is **one binary** and no way
to flash the wrong role onto the wrong board. An unrecognised board runs as TX
and says so loudly. `ROLE TX|RX` swaps roles at runtime, without a reflash, for
measuring directional asymmetry. USB paths are not stable — identify boards by
the MAC in their USB serial descriptor, never by port order.

Attach the external antennas. The XIAO's antenna is selected in hardware; nothing
in firmware can compensate for a missing one.

## Reading the LEDs

Both boards run the **same display**, and differ only in hue: the TX is **blue**,
the RX is **red**. All eight pixels carry packet information — no pixel is spent
on a role marker, because the colour already says which board you are holding.

One dot lights for each packet and then fades, so a comet travels once round the
ring every eight packets. Read it as:

- **speed** — the packet rate, 5 Hz by default
- **brightness** — signal strength: full above −65 dBm, down to a quarter at
  −85 dBm and below
- **gaps** — a lost packet leaves its dot dark, so loss reads as a stutter in the
  flow
- **frozen** — the board has crashed or browned out

On the TX a dot only brightens once the RX's **ACK** comes back, at the strength
the RX measured, so the TX really is displaying acknowledgements rather than its
own transmissions. It advances the comet on every ping it *sends*, though: a dim
but still-moving comet means "board alive, link dead", while a frozen one means
the board itself has stopped. Collapsing those two states would hide the worse
fault.

The RX can genuinely fall silent, so when it has heard nothing for two seconds it
breathes instead: **red** if it was hearing the TX and lost it, **amber** if it
has heard nothing at all since boot.

## Running a survey

```sh
./rangetest/Launch.command --port /dev/cu.usbmodem101
```

The console watches the **receiver** only — during a real walk the transmitter is
untethered on battery and reports through its LEDs, so the back-room end is where
the measurement actually lands. It connects on its own and stays connected,
reconnecting if the board is unplugged; there is nothing to start or stop.

It shows packet loss, signal, signal-to-noise and packet rate; signal and loss
over the **last minute** (every packet) and the **last 30 minutes** (one-second
averages); and a live mirror of the receiver's eight LEDs, driven by the board's
own `LEDS` frames rather than by a reimplementation of the animation, with a
legend for reading them.

Everything is held in memory and drawn on screen. **Nothing is written to disk**,
so close the window and the history is gone.

Walk the path, then swap the two boards physically and repeat, and separately swap
roles with `ROLE` without moving anything. Three datasets separate path loss from
board-to-board hardware variation from directional asymmetry. Report distributions,
not means: 95 % average with three-second dropouts is a completely different
problem from a uniform 95 %.

## Firmware

ESP32 Arduino core 3.3.11, Adafruit NeoPixel 1.15.5 from `live files/libraries`.
Same FQBN as the cube, so `Serial` is the native USB port (on this board
`CDCOnBoot=default` means CDC *enabled*).

```sh
pairing_station/.venv/bin/python scripts/build_all_firmware.py   # builds this among ten targets

arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32C3:CDCOnBoot=default,PartitionScheme=no_ota,FlashSize=4M \
  --libraries "live files/libraries" --output-dir rangetest/build rangetest/firmware/RangeTest
arduino-cli upload --fqbn esp32:esp32:XIAO_ESP32C3:CDCOnBoot=default,PartitionScheme=no_ota,FlashSize=4M \
  --port /dev/cu.usbmodem101 --input-dir rangetest/build rangetest/firmware/RangeTest
```

On this Mac the CLI is at
`/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli`.

No flash backups were taken of the two boards before they were flashed, at the
operator's instruction. Neither MAC appears in `inventory/devices/`, so whatever
they previously contained is not recorded anywhere.

### Serial

115200 baud, newline terminated. Commands:

| Command | Effect |
|---|---|
| `STATUS` / `?` | Banner and cumulative counters |
| `RESET` | Clear all counters and history |
| `ROLE TX\|RX` | Swap role now; not persisted, reboot restores the MAC default |
| `RATE <hz>` | Ping rate, 1–20, default 5 |
| `SLEEP ON\|OFF` | Wi-Fi power save; `ON` is `WIFI_PS_MIN_MODEM`, the cube default |
| `VERBOSE ON\|OFF` | Per-packet lines; `OFF` leaves only the 1 Hz `STAT` line |
| `MUTE ON\|OFF` | RX keeps receiving and counting but stops answering |
| `LEDS ON\|OFF` | Mirror the eight pixels over USB for the console |
| `MARK <label>` | Stamp a label into the log |
| `REBOOT` | Restart, for exercising TX-restart detection |

Output is `PKT` per packet and `STAT` once per second, both as `key=value` pairs.
Writes are non-blocking and capacity-checked: a log line is dropped (and counted
in `log_drops`) rather than delaying the radio. `VERBOSE OFF` is for a board left
plugged in with nothing reading it.

Logging is deliberately **not** gated on `if (Serial)`. The USB CDC connected flag
can latch false after a host toggles DTR/RTS, and a board that is happily running
the radio while reporting nothing over USB is the worst possible state for a
diagnostic tool.

Open these boards with `serial_open.open_serial()`, which follows the same
no-reset sequence as `pairing_station/transport.py`: assert DTR and RTS *before*
opening, then release RTS before DTR. Opening a native USB-JTAG ESP32-C3 with both
deasserted, or toggling them afterwards, resets the chip and can wedge its USB
serial peripheral. A wedged board keeps running the radio — the other end still
sees its packets — but goes completely silent on USB, and an `esptool` reset does
not clear it because that restarts the CPU, not the USB peripheral. **Unplug and
replug it.**

### Wire format

36 bytes, magic `0x314C5452` (`'R','T','L','1'`), broadcast to
`FF:FF:FF:FF:FF:FF` in both directions. Defined once in `RangeTestPacket.h`;
there is one sketch, so the two ends cannot drift apart.

Broadcast 802.11 frames get no MAC acknowledgement and no retries, so delivery is
measured purely at application level. The ESP-NOW send callback reports success
for a broadcast regardless of whether anything heard it; it is used only for
pacing, for the true departure timestamp, and for counting local PHY failures.

Non-interference is enforced by a `static_assert` on the frame length, not by
convention. Every live receiver on channel 2 rejects a 36-byte `0x314C5452` frame
before touching it: cubes and the registration console gate on length 24, the
preshow media bridge on length 2, the pool central on length 15 and then its own
magic, and zone boards reject lengths 2 and 24 and then require `'N','Z'`.

At 5 Hz in each direction this is roughly 0.8 % airtime — about an eighth of what
`PoolRadioTest` already puts on channel 2 continuously. Still: run with the
Poolzone GUI closed, not during a live show, and if you raise the rate above
10 Hz re-check that the pool central's 800 ms lease timeout is unaffected.

### Deliberate configuration choices

The radio is set up exactly as `flashing_station/firmware/neocore_usb` sets it up,
because the point is to predict cube behaviour rather than to beat it:

- **No `WiFi.setSleep(false)`.** The cube does not call it either, so both run the
  C3 default `WIFI_PS_MIN_MODEM`. `SLEEP OFF` A/Bs it in five seconds, and the
  effective value is printed in the banner and in every `STAT` line, so a captured
  log is self-describing.
- **TX power left at default** (20.00 dBm here) and printed at boot.
- `esp_wifi_get_max_tx_power()` returns `esp_err_t` and writes the power through
  an out parameter in units of 0.25 dBm — printing its return value would show a
  plausible-looking `0`.

`bootId`, a random value per boot, is carried in every frame. A battery-powered
board carried around a building will brown out; without it a restart would
register as a billion-packet sequence gap and silently corrupt the loss statistic
for the rest of the survey. The RX logs `EVENT tx_restart` and resets its window
instead. The boot banner prints the reset reason by name, so `BROWNOUT` is
unmistakable.

The receive callback runs in the high-priority Wi-Fi task and only copies into a
mailbox — no `esp_now_send`, no `Serial`, no LED work. This is the pattern
`poolzone_test/firmware/PoolCentralTest` was rewritten to use after an unsafe
callback caused a reproducible control failure. Because the ACK therefore leaves
after a variable loop delay, the RX stamps its own turnaround time into the ACK
and the TX reports both `rtt_us` and `air_us`.

## Tests

```sh
pairing_station/.venv/bin/python rangetest/tests/e2e_check.py /dev/cu.usbmodem1101 /dev/cu.usbmodem101
pairing_station/.venv/bin/python rangetest/tests/gui_check.py /dev/cu.usbmodem101
```

Close the GUI first; both tests hold the ports exclusively.

`e2e_check.py` runs 26 checks and writes evidence to `build/e2e-latest.log`. It
begins with the **negative control**: `MUTE ON` makes the RX keep receiving and
counting while it stops answering, and the TX must then report 100 % loss with its
`departed` counter still climbing. If that does not hold, every later pass is
meaningless — it is how you would otherwise ship a range test whose green light
only means `ESP_NOW_SEND_SUCCESS`. It then checks the positive control at bench
range, that RSSI is measured in both directions, that `air_us` excludes the
responder turnaround, that the driver-reported channel is 2 on every frame,
TX-restart detection via `bootId`, and that the radio is unaffected by USB
logging.

`gui_check.py` drives the real Tk console against the receiver: it checks the app
connects by itself, parses identity, statistics and per-packet RSSI, that the LED
mirror is live and actually moving with no colour but red, and that nothing is
written to disk.

## Limits

- RSSI is the receiver's own uncalibrated estimate. It is not comparable across
  different hardware and is not a measurement.
- A 36-byte broadcast at 5 Hz does not directly predict a 24-byte cube command at
  a different time of day with a room full of people.
- No 802.11 retries are exercised, so unicast application traffic may do better
  than these numbers suggest.
- An empty building is a best case.
- An RF and application-ACK pass says nothing about whether a cube's LEDs
  actually changed.
