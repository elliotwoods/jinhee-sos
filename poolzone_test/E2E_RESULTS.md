> **Superseded.** This file records hardware evidence for the v2 central when the radios
> still broadcast the 15-byte packet with no acknowledgement. The I2C and concurrency
> findings below still hold and are carried into `zones/firmware/PoolCentral`, but the
> radio link has since been replaced (beacon, unicast, sequence numbers, bursts, repeated
> releases). **Equivalent hardware evidence for the new link has not yet been collected.**

# Receiver v2 reliability fix — verified on hardware

After the initial test, an intermittent failure was reproduced: the original receiver timed out member 23 **152 ms** after receiving it despite its 800 ms radio lease. Shared callback/loop state was unsynchronized, and USB writes were made inside the Wi-Fi callback. Original I2C writes also updated the frame cache even on failure.

The installed v2 firmware uses a protected receive mailbox, loop-owned state, non-blocking logs, verified PCA9685 register writes, periodic configuration/output audits, bounded I2C transactions, and automatic bus/driver recovery. The Python GUI can monitor the receiver USB port for live register verification.

Hardware verification (`build/i2c-soak.log`, approximately 96 seconds):

| Check | Result |
| --- | --- |
| PCA9685 0x40 and 0x41 | Both respond; MODE1=0x20, MODE2=0x04 |
| SDA/SCL | Both high at idle; no stuck-low bus observed |
| Three complete cycles of 23 members ON/OFF | 138 transitions verified by register readback |
| Six-slot changing patterns | 30 patterns verified |
| Normal operation errors | No I2C errors, readback mismatches or premature radio timeouts |
| Injected sleep/auto-increment loss at 0x40 | Detected, reinitialized, requested outputs restored |
| Injected sleep/auto-increment loss at 0x41 | Detected, reinitialized, requested outputs restored |
| Explicit open-drain bus recovery | Passed; both boards reinitialized and current selections restored |
| Receiver USB monitor closed for 45 seconds | 222 switches; 1,770 additional received packets; no reboot or I2C errors |
| Non-blocking USB behavior | 592 diagnostic log lines dropped rather than blocking control |
| Physical light response | User confirmed “responding well” and “Yes, lights are cycling” |

At the end of the soak all 23 output registers were verified off, both boards were healthy, and the I2C error count was zero. The 337 readback/configuration mismatches and three recoveries in this log came from the deliberate sleep/AI-loss injections and explicit recovery test. There were no mismatches during normal toggling or the USB-monitor-absent phase.

Evidence of the original failure: `build/e2e-premature-timeout.log`. Original receiver flash remains backed up at `build/backup-central-48f6ee158ee0.bin`. Current firmware: `firmware/PoolCentralTest`.

---

# Initial Poolzone end-to-end test — historical

Hardware tested:

- USB sender: ESP32-C3 `3C:0F:02:AF:2C:20`, `/dev/cu.usbmodem101`, PoolRadioTest.
- USB receiver: ESP32-C3 `48:F6:EE:15:8E:E0`, `/dev/cu.usbmodem2101`, PoolCentralTest.
- ESP-NOW channel: **2**, broadcast original 15-byte Poolzone RadioPacket.

The receiver originally contained **POOL ESP-NOW SNIFFER v0.1**, built with USB CDC disabled (`CDCOnBoot=default`). The first test produced no receiver logs. The installed image was backed up to `build/backup-central-48f6ee158ee0.bin`, then replaced with the repository's central-controller code plus USB/I2C diagnostics. Upload hashes were verified.

`tests/e2e_check.py` passed against both physical ESP32s:

| Check | Result |
| --- | --- |
| Each member 1–23 ON, then OFF | All 46 transitions observed in receiver FRAME logs |
| Radio IDs 1–6 simultaneously | Members 1, 5, 9, 13, 17, 23 received and enabled |
| Sustained heartbeats | Six selections held for 2 seconds without timeout/release |
| All Off | All six receiver frames released |
| USB host watchdog | Receiver FRAME 23 OFF after sender's 1500 ms watchdog |
| Sender enqueue errors | 0 |
| Receiver I2C write errors | 0 across both PCA9685 address ranges |

Example timestamped evidence (seconds since test start):

```text
1.001 COMMAND SET 1 0 0 0 0 0
1.026 RX RADIO 1 -> MEMBER 1
1.026 RX FRAME 1 ON
1.032 COMMAND OFF
1.173 RX RADIO 1 RELEASE
1.179 RX FRAME 1 OFF
...
11.637 TX EVENT USB watchdog: all off
11.680 RX RADIO 1 RELEASE
11.680 RX FRAME 23 OFF
11.693 RESULT PASS: USB -> ESP-NOW channel 2 -> central frame ON/OFF handler.
11.693 I2C write errors observed during test: 0. Physical light emission not measured.
```

Full raw evidence is saved locally in `build/e2e-latest.log`. The test proves command transmission, receiver interpretation, and successful I2C write return codes. Actual LED illumination was not visually or electrically measured. All radio slots were left off, and the GUI was reopened on the sender.
