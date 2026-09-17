# Unattended test report — 17 September 2026

The app, HTTP API and live ESP-NOW station passed the tests below. Existing MAC/cube ID/NFC UID mappings were preserved. No LED device or reader firmware was reflashed during this test session.

## Live hardware

| Check | Result |
| --- | --- |
| Five consecutive USB disconnect/reconnect cycles | Passed; connection restored and PN532 initialization flag retained |
| Two-second flashes on Neocores 2, 3, 5, 7, 11 | Completed; final static commands reported radio delivery |
| Stop during indefinite flashing | Completed; controller returned idle |
| Re-register unchanged mappings on 2, 3, 5 | All three acknowledged |
| Retry the 15 previously unconfirmed original mappings | Seven additional acknowledgments; 24/32 now acknowledged |
| Two-minute discovery/heartbeat stability observation | No controller errors or lost connection; sampled USB receive age stayed below 1.2 seconds |
| 60 HTTP execution requests with six concurrent clients | All returned correct results; maximum latency 0.73 seconds |
| Connect to a nonexistent serial port, then reconnect correctly | Expected failure cleaned up; live station connection restored |
| Deliberately invalid MAC, flash duration and UID commands | All rejected with specific station errors; connection remained ready and idle |

Still unconfirmed: **1, 4, 10, 15, 20, 25, 27, 29**. Lack of acknowledgment does not distinguish power, range, channel, firmware or packet-loss problems. No claim is made about visible physical LED appearance or registration surviving a cube power cycle.

## Automated and interface checks

- **20 desktop tests passed**: registration and discovery state transitions, duplicate/stale ACK and scan rejection, pending transaction recovery, tag conflicts, CSV/header exports, role exclusions, selected-device pairing, UI inventory filters, serial fragmentation/open/retry behavior, HTTP authentication, exception isolation, owner-thread execution and job lifecycle.
- Actual station firmware compiled for ESP32-C3: 1,022,937 bytes flash, 37,440 bytes static RAM.
- Host simulation of the actual firmware passed fresh-tag gating, ACK validation, registration retries, flash timing, heartbeat cleanup, reconnect cleanup, peer cleanup, invalid-input rejection, spoofed discovery rejection and late ACK rejection after Stop.
- Packet layouts match ForKimchi and all three supplied Neocore variants. The supplied media-server bridge uses channel 1 and a separate two-byte packet; the pairing station uses channel 2 and the cube protocol.
- Grid selection populated the expected MAC/UID and enabled the proper actions. Search/status filtering and the minimum 1120×820 layout were checked. The details panel remains scrollable at that size.
- SQLite `integrity_check` returned `ok`. Before/after MAC, cube ID and committed UID tuples matched exactly. CSV still contains 33 database rows (32 original mappings plus the unpaired reservation for Neocore 33).

## Fixes made during testing

- Clean up the serial handle after an unsuccessful open, allowing a subsequent Connect attempt.
- Do not leave an active-device highlight when a re-pair request is rejected because a registration is already pending.
- Clear NFC-ready state when disconnected.
- Apply reader/base-station exclusions consistently to the native-menu bulk action.
- Remove routine discovery/broadcast traffic from the human activity log and include tag-state transitions, making future scan failures easier to inspect. Raw discovery events remain available through the HTTP API.

## NFC limitation

The station reports successful PN532 initialization, and reconnects do not reset the station. There was no person available to present/remove a tag, so actual NFC detection and end-to-end pairing have **not** been confirmed. Firmware simulation covers the software's scan handling; it does not establish that the attached reader detects a real tag. The earlier unsuccessful scan of Neocore 33 remains unresolved. No synthetic scan was used to create a real pairing.

Evidence: `data/away-live-test.jsonl`, `data/http-stress-result.json`, `data/away-retry-result.json`, `data/away-integrity-result.json`, `data/away-final-result.json`. Pretest database snapshot: `data/before-away-tests.sqlite3`. The current SQLite database and CSV contain the updated acknowledgment statuses.
