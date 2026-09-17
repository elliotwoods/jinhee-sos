# Validation — 2026-09-17

- Station: ESP32-C3, 4 MB flash, USB identity/MAC `3C:0F:02:AD:83:24`.
- Original flash backed up to `data/station-before-pairing.bin` before the first upload.
- Arduino-ESP32 3.3.11 build passed; flash writes verified by esptool.
- Twelve desktop controller/database/transport tests passed, including the no-reset USB connection sequence.
- The actual firmware passed host simulation for packet compatibility, fresh-tag gating, ACK validation, retries, flashing, heartbeat cleanup, reconnect cleanup, UID rejection, peer cleanup, and bus recovery.
- GUI opened and layout inspected on macOS.
- Discovery found 21 distinct responding MAC addresses across repeated rounds, including MACs outside the imported 32.
- Cube 3 acknowledged re-registration of its existing mapping. Its two-second flash sequence completed; the final idle command reported radio delivery. Physical LED appearance was not observed by the agent.
- All original 32 mappings were transmitted: **17 acknowledged; 15 unconfirmed** after up to three attempts each.
- Unconfirmed cube IDs: **1, 4, 6, 10, 12, 15, 17, 18, 20, 21, 23, 25, 27, 29, 31**. These are retained for Retry unconfirmed.
- NFC initially reported I²C timeout (`nfc_i2c_status=5`) on SDA GPIO4/SCL GPIO3; user confirmed these pins. Line diagnostics then measured **SDA high, SCL held low** even with the ESP32 peripheral released. Clock-pulse recovery cannot proceed while SCL is held low. With SCL disconnected, GPIO3 rose high, isolating the issue to the reader/cable side. After the user checked and reconnected the jumper, both lines read high, I²C acknowledged (status 0), and PN532 initialization succeeded (`nfc_ok=true`, firmware word 838927879). A later USB reconnection exposed an unintended ESP32 reset that could interrupt I²C and wedge the powered reader. Transport now follows esp-idf-monitor’s no-reset DTR/RTS ordering. After power cycling both devices, two consecutive open/close checks retained `nfc_ok=true` and produced no boot/reset output. Live tag pairing is the remaining physical verification.

Hardware evidence is in `data/hardware-check.log`, `data/one-cube-check.log`, and `data/bulk-registration.log`, and `data/nfc-recovery-check.log`, and `data/nfc-reconnected-check.log`. SQLite/CSV hold the latest per-device results; later retries may change them.

Stable reconnection evidence: `data/nfc-final-connect-1.log` and `data/nfc-final-connect-2.log`.

HTTP API verification:
- Fifteen desktop tests passed, including real loopback HTTP authentication, browser-origin rejection, request validation, main-thread execution, persistent Python state, captured output, exception isolation, job polling, and shutdown cancellation.
- An actual curl POST executed inside the live app and confirmed `threading.current_thread() is threading.main_thread()`, `controller.connected=true`, and `controller.reader_ok=true`.
- Cube 33 remains `awaiting_tag` with neither committed nor pending UID after the user's unsuccessful scan. Pairing was stopped for the app restart; no successful scan is claimed.

Graphical dashboard verification:
- Eighteen desktop tests passed, including persistent role exclusion, exclusion enforcement in auto-pair/selected/bulk operations, selected unregistered-device pairing, idle discovery refresh, inventory filters, and distinguishing LED commands from measured output.
- The live macOS dashboard was visually inspected; device cards, scrolling grid, selected-device inspector, role controls, filters and logs are visible. Card selection was exercised through the app's click handler using its actual card bounds; it populated the correct MAC, UID and action states.
- Live inventory combined 33 stored mappings/reservations with additional discovery responders (48 cards at inspection; counts change with discovery).
- Neocore 3 completed a two-second flash operation and returned to the static-command display. This checks command completion and UI state, not physical LED appearance.
- The station remained connected with NFC initialized. No new tag scan or registration was performed in this dashboard validation.

Unattended testing subsequently expanded the desktop suite to 20 passing tests and rechecked the firmware build/simulation. Seven more original mappings acknowledged, bringing the total to **24/32**; **1, 4, 10, 15, 20, 25, 27, 29** remain unconfirmed. See `TEST_REPORT_2026-09-17.md` for live reconnect, flash, API concurrency, integrity and regression results. The original MAC/ID/UID tuples remain unchanged.
