# PN532 I²C investigation — 2026-09-17

Station: ESP32-C3, SDA GPIO4, SCL GPIO3, red PN532 board in I²C mode,
powered from station 5V/GND. Two modules tested. No successful physical tag
read has been observed yet. Firmware-version responses alone do not verify
RF/tag reading. Preserve all cube mappings while testing.

## Reference comparison

`../mainshow_enter/mainshow_enter.ino` initializes standard Wire on pins 4/3,
waits 300 ms, calls `nfc.begin()`, `getFirmwareVersion()`, and `SAMConfig()`.
It reads ISO14443A tags with an 80 ms host timeout. Its bundled Adafruit PN532
source is identical to the installed project library.

The pairing station had added `setPassiveActivationRetries(0x01)`. The library
waits for its RFConfiguration response to become ready but does not consume
that response. This is a hypothesis to test, not an established root cause.
A custom ESP-IDF transport with 20 ms SCL-stretch allowance in station v1.4
did not resolve the first tag-read failure (593 ms, no tag).

## v1.5-reference diagnostic build

Uses standard Arduino TwoWire transfers, with a wrapper that records bytes,
requested lengths, return status and elapsed time in `nfc_i2c` JSON events.
Removes the additional passive-retry configuration, matching the reference
initialization sequence. Radio and host protocol remain available. Automatic
NFC polling remains disabled to avoid repeatedly disturbing a failed bus.

After connection, `nfc_poll` with `once: true` attempts one read. Capture its
preceding `nfc_i2c` events. `nfc_recover` releases the bus and tries reference
initialization again; a physically held-low SCL can still require power removal.
Do not interpret `nfc_poll_result.ready` as a live health check: it is the cached
initialization result. A failed read is not proof the tag is absent.

Validation: host firmware simulation passed; all 27 Python tests passed.
Physical reference-build result: firmware, SAM configuration, scan command and
ACK all had successful I²C transfers. First scan returned RDY=0 until the 80 ms
host deadline (85 ms total), no tag. A subsequent firmware query also succeeded
with valid response `010000FF06FAD50332010607E800`, both bus lines high. This
is a clean no-result scan, unlike the earlier bus timeouts; tag-present testing
is still pending. This does not yet isolate which earlier change caused failure.

## First confirmed tag read

After the user replaced the tag (same replacement reader and v1.5-reference),
a single scan returned UID `53:21:D4:CF:33:00:01` in 38 ms. All I²C transfers
succeeded. Response prefix/frame payload:
`010000FF0FF1D54B0101004400075321D4CF330001`.
This is the first confirmed physical tag read in the session. The previous tag
was not detected within 80 ms; its failure cause is not established. No mapping
was changed by this diagnostic read (station was idle).

## Live app registration verified

App now enables scanning on an initialized station after the hello handshake
and waits for the station's polling confirmation before enabling registration.
Successful per-transfer diagnostics remain in the HTTP recent-events stream but
are omitted from the GUI log to avoid flooding it. All 28 Python tests passed.

After reopening the app, the user exercised registration for Neocore #2,
MAC `AC:27:6E:82:60:4C`. The station observed tag removal then read
`53:21:D4:CF:33:00:01`, transmitted registration, received a matching cube ACK
on attempt 1, sent static/idle, and the GUI displayed its green success feedback.
Physical LED appearance and persistence across cube power loss were not verified.
