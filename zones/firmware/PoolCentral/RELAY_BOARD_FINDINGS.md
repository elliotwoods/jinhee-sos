# Pool relay board findings (2026-09-22/23)

Session notes from investigating "all pool lamps come on and stay on". Written so the
next session does not have to re-measure. Everything under **Measured** was read off the
hardware or a datasheet; everything under **Open** was not.

## Symptom

With the ESP32 on separate power and the PCA9685 boards holding their dark state,
cycling only the 12 V leaves the **16-channel** relay module with every relay energised
while the **8-channel** module stays de-energised. Before the cycle all relays were off.

## Measured

### The firmware is not at fault

Boot log and `OUT DUMP` over `/dev/cu.usbmodem101` at 115200:

```
I2C BUS sda_before=1 scl_before=1 sda_after=1 scl_after=1 pulses=0
I2C READY addr=0x40 mode1=0x20 mode2=0x04
I2C READY addr=0x41 mode1=0x20 mode2=0x04
FRAME 1..23 OFF
POOL CENTRAL poolcentral-4.1.0 MAC=D4:05:92:E7:D0:C4 channel=2 outputs=dark
```

`OUT DUMP` reports all 23 frames as `regs=00100000 level=HIGH lamp=OFF`: LEDn_ON_H bit 4
(FULL_ON), statically driven, `mode2=0x04` so OUTDRV=1, totem pole. `STATUS` holds at
`known=0x7FFFFF verified=0x000000 i2c_errors=0 mismatches=0 recoveries=0`, and a 180 s
capture showed no `I2C MODE MISMATCH`. The PCA9685s never lost power and the firmware
never rewrote anything. The same HIGH is on both boards throughout.

### The board is running firmware that is not in this repository

It reports `poolcentral-4.1.0`. Git has only `poolcentral-3.0.0` (24370f4) and
`poolcentral-4.2.0` (bf869f8). The running build prints
`OUTPUT polarity=active-low  (lamp ON drives the channel LOW)`; 4.2.0 prints
`OUTPUT polarity by output: active-low mask=0x%06lX`. **Do not treat a PoolCentral
reflash as a small delta from what is installed.**

### Both relay boards are active LOW, with the same input topology

The optocoupler LED sits between the board's reference rail (via a 1 k resistor) and the
IN pin, so the relay is off only while IN is close to that reference. It is a voltage
*difference*, not a logic threshold.

- 8-channel (handsontec MDU1064): `VCC` (opto input reference) is a separate pin with a
  VCC/JD-VCC jumper. The document says that for 3.3 V signalling, `VCC` should be tied to
  the 3.3 V device's supply. Its own text, title and schematic all say active LOW; only a
  pasted **4-channel** demo sketch in the same PDF comments the opposite.
- 16-channel: the schematic shows the opto LED anode and the opto collector on one 5 V
  net produced onboard by an `LM2576` buck from 12 V, then a `ULN2083` sinking coils that
  run off `+12 V`. There is no VCC/JD-VCC split, so the reference cannot be lowered to
  3.3 V. Matches the Arduino forum report of this board ("no user selectable opto
  isolation", and its "5 V output" pin measured at 12 V).

### Relay coils are being overdriven

Installed relays are `SRD-05VDC-SL-C` and `JD-VCC` is fed **12 V**. Songle's COIL DATA
CHART for that part: 5 VDC nominal, 70 ohm, 71.4 mA, about 0.36 W, pull-in at 75 % of
nominal, **max allowable voltage 120 % = 6.0 V**. At 12 V that is 171 mA and 2.06 W per
coil, 5.7x rated power. This is independent of the stuck-relay symptom and needs fixing
on its own.

## Outcome (2026-09-23)

Done. Three 8-channel modules are fitted and all relays start de-energised. Relay-to-lamp
wiring changed with them, so the frame table was re-measured with the sliders and replaced
(`poolcentral-4.2.2`, see `PoolOutput.h`). Relay 16 has no lamp; frame 14 is on relay 24,
driven by output 24 (`0x41` channel 7), which the firmware now supports. Every slider 1-23 was
checked on the installation and lights its own lamp. The 4.1.0 image previously on the board
is backed up locally in the ignored `poolzone_test/build/backup-central-d40592e7d0c4-poolcentral-4.1.0.bin`
(sha256 `8e95a6c0...a7083a`).

## Decision taken

Replace the 16-channel module with two more 8-channel modules (3 x 8 = 24 channels, 23
used), same model as the one that already behaves.

Target wiring:

| Pin | Value | Source |
|---|---|---|
| `JD-VCC` | 5 V, sized for 23 coils at once (1.64 A) so 3 A | 12V->5V buck off the existing 12 V |
| `VCC` | 3.3 V | the same rail that feeds the PCA9685 |
| `GND` | common | |

With `VCC` equal to the PCA9685's output HIGH, the opto LED can never see a forward
voltage, including while the 12 V ramps back up.

## Open

- The PCA9685 `VDD` was never measured. Assumed 3.3 V.
- The 16-channel board's `VCC` was never measured. Its `LM2576` power module is not
  populated on the boards on hand, so that 5 V comes from somewhere external that was not
  identified. A 1.7 V gap alone does not explain the fault, because the 8-channel board
  currently runs `VCC`=5 V against a 3.3 V IN and is fine.
- Dropping `VCC` to 3.3 V also lowers the opto output supply. Test one board before
  converting all of them; the handsontec document notes `R1` may need to go from 1 k to
  about 220 ohm if relays become sluggish.
- Radio ids clash: six radios report ids 1, 2, 3, 3, 4, 4 (`id_clashes=4`), ids 5 and 6
  unused. Harmless for lighting because slots are keyed by MAC, but it makes logs
  ambiguous.

## After any relay board or loom change

Re-measure the wiring map. `POOL_OUTPUT_FOR_MEMBER` is a measured table, not a
convention.

```sh
pairing_station/.venv/bin/python poolzone_test/tests/frame_map.py /dev/cu.usbmodem101
```

It composes readings with the table already in `PoolOutput.h`, so the correction cannot
be applied backwards. Then power-cycle the 12 V once more and confirm all three modules
stay de-energised.
