# NCT Console test report — 2026-09-23

Verification of the NCT Console (`console/`) against the operations handover
("Operations & Technical Handover by Kimchi and Chips", chapters 01–16), as the basis for
the console edition of that handover.

## Scope and evidence classes

| Class | Meaning |
|---|---|
| **simulation-verified** | Proven by the headless console suite (`console/tests`, fake boards from `simulate.py` / `simdocs.py`). No hardware involved. |
| **dongle-verified** | Observed on the live console with a real board on this bench. Wording follows AGENTS.md: *delivered* is a radio ACK only; *acknowledged* is an application reply; *verified* is an independent read-back. |
| **unverified** | Not exercised on hardware in this pass. Listed plainly at the end. |

Hardware on the bench during the pass: the ex-cube dongle **AC:27:6E:82:68:54** on
`/dev/cu.usbmodem1101` and, unexpectedly, cube **#17** (1C:DB:D4:F0:A8:30) on `/dev/cu.usbmodem101`.
No other zone board or reader was attached.

Test suite state at the time of the pass (all headless, no uploads):

| Suite | Result |
|---|---|
| `pairing_station/.venv/bin/python -m unittest discover -s console/tests -p 'test_*.py'` | 163 tests, OK |
| of which `test_docscenes` (every handover scenario settles in-process) | 34 scenarios, OK |
| of which `test_pool_recording`, `test_sync_check`, `test_receipts`, `test_hub.UsbPinningTests` | OK |

## Matrix: handover chapter → console feature → method → outcome

Methods: **U** unit/simulation test, **S** scripted simulation scenario (`console/docscenes.py`),
**D** live console with the dongle, **X** not testable on this bench.

| Ch. | Handover workflow | Console feature | Method | Outcome | Evidence |
|---|---|---|---|---|---|
| 03 | Connect station, NFC ready; USB identify + pin; number prompt; REGISTER → READY TO SCAN → TAG DETECTED → REGISTERED; transmit saved mapping; Retry/Skip; tag transfer; rename refusals; Register-disabled reasons; new USB cube stops the active operation before replacing the pin | Pairing station panel, Cube panel (Register, number field, Send saved mapping), `capabilities` reasons on inventory rows, `hub.identified()` stop-before-pin | U, S | **simulation-verified**: `test_docscenes` 03-1…03-5 (pin → armed → READY TO SCAN → TAG DETECTED·REGISTERING with a held station → REGISTERED with the committed tag); `test_hub.UsbPinningTests.test_identifying_another_cube_stops_the_active_operation`; `test_commands` catalogue. Register/transmit/rename/role reasons come from `state.capabilities()` mirroring `pairing_station/dashboard.py`. | D: cube #17 was identified and pinned on the live console (see below); no NFC reader was attached, so the scan path is simulation only. |
| 04 | Cube flasher: flash selected/retry, arm auto / stop after current, result + history, Check boot, Recover saved results, export, refusals | Cube › Firmware (verdict, Flash, Check boot, History), USB intake, `cube.recover_receipts` | U, S | **simulation-verified**: 04-1…04-4 (version differs → job at 55 % → verified → History/Check boot); `test_receipts` (imports a receipt for a run still marked running or failed, never for a success, idempotent). | D: the live console reported cube #17 `v1.5.0-USB.1`, status *current* against the local build `v1.5.0-USB.1` ("Reported version matches local build"). No flash was performed. |
| 05 | Three copies, fields, sync decisions, web password stored locally, offline behaviour | Inventory section, Sync button, Web sync tab + plan | U, S | **simulation-verified**: `test_sync_check` (plan against `FakeWebInventory`: upload/download rows, `sync.plan_clear`); C-4, C-5, C-6 scenarios; the legacy `test_sync_convergence` / `test_sync_all` suites are unchanged. | — |
| 06 | Zone DB Manager: connect dongle, published version, query/refresh, in range, Update selected / Update all, progress + confirmed, Auto update all, Stop, zone states, RX gain, signal, Identify, Show log, Reboot, Flash dongle | Station/dongle panel › Zone relay, Zone entries, Attention cards | U, S, D | **simulation-verified**: 06-1…06-4 (relay table → publishing progress with a held station → "v32 confirmed" on the plate → Auto-update all); `test_zone_registry` unchanged. **dongle-verified (rerun)**: connect, published version, zone query (47 known zones, 27 in range with RSSI, states current/behind assigned against v37), Identify + Show log on one plate (log frame received = acknowledged), RX gain set on that plate acknowledged with result `ok` (value unchanged). Not exercised: Update selected / Update all / Auto update all over the air (not authorised), Reboot, Flash dongle. | The station registry snapshot uses the published version from `store.published()` = **v37** (133 records, CRC 3738672143, published 2026-09-22 16:42 UTC). |
| 07 | Zone flasher: identification, NEEDS BUILD / unpublished warnings, provisioning form, Flash, Detect, Check report, auto-flash, force flash, Cube monitor | Zone panel › Firmware & database, Monitor; USB intake zones | U, S | **simulation-verified**: 07-1…07-4 (blank board form → zone flash job → verified report → monitor with a found cube); `zones/tests/test_zone_flasher` unchanged. Stale-build warnings appear as `build.stale` cards (six of them on this machine right now: Desert/Pool/Preshow/TagPlate zones, dongle relay, Mainshow controller — the sources changed after the last build). | — |
| 08 | Preshow signal path; bridge; failing-stage diagnosis; HOST override (lease) | PreshowZone › Cue test; PreshowBridge panel; General Radio › Preshow cue | U, S | **simulation-verified**: 08-1, 08-2 (lease taken; point 2 ON acknowledged by the simulated bridge in `mode=modern`). | — |
| 09 | Desert two-checks triage | Zone › Monitor + Attention (`zone.nfc_down`, `zone.not_acknowledged`) | U | **simulation-verified** (advisor tests). | — |
| 10 | Calibration: lease, control points, Set/Apply & save/Reload, guided recording, tuning, firmware/database/radio id; central; pool test | PoolZone › Calibration/Diagnostics/Firmware & database; PoolCentral; PoolRadioTest | U, S | **simulation-verified**: 10-1…10-4 (lease + live reading → capture point 12 → Apply & save with `saved=true` read back → guided recording holding at the prompted tick); `test_pool_recording` (plan → Reached → hold → analysis; RAW ON/OFF; abort). | — |
| 11 | Mainshow: ① ready → neon, ② trigger, Stop → idle, clock, BOOT/GPIO3 | Show section, Mainshow controller panel, General Radio verbs | U, S | **simulation-verified**: 11-1…11-4 (① delivered, ② armed, show clock running) with `simdocs.FakeMainshow`; `zones/tests/test_mainshow` unchanged. **dongle-verified (rerun)**: `hub.show_session()` resolves to the General Radio session (`show:1`, `timecode:true` in its hello); no show was started and no zone was set. | — |
| 12 | Setup, launchers, instance locks vs the other apps, backups | `console/Launch.*`, `locks.py` | U, D | **simulation-verified**: `test_locks`. **dongle-verified (rerun)**: the old pairing app started while the console ran was refused (exit code 1 within 8 s; its refusal is the Tk dialog "This database is already open in another pairing window.", `pairing_station/app.py:341`). The reverse direction (console refused while an old app runs) was not run on hardware; `test_locks` covers it. | See the observation on `apps.legacy_open` below. |
| 13 | Versions, protocol boundaries, partitions, tests, local API | unchanged + console architecture, `/execute` namespace with `hub`, `sessions`, `store` | U, D | **dongle-verified (API)**: every step below used the loopback API (`pairing_station/data/api.curl`, port 8765); 202 jobs were polled, never repeated. | — |
| 16 | "NFC unknown" after registration → publish + distribute; "cannot connect to the ESP32" | Attention cards `tag.known_zone_behind` / `tag.known_unpublished` with **Update database over USB**; `station.disconnected` | U, S | **simulation-verified**: C-2, C-3 (the card fires only when the plate's own `?` report is behind; a stale report or a running Auto-update all masks it — both found and fixed in the scenario staging). | — |

Cross-cutting (simulation-verified): destructive commands refuse without a confirmation token
(`test_hub.test_destructive_commands_need_a_confirmation_token`); hardware commands run on one
click with a warning; leases end with Esc/Stop and between documentation chapters; the initial
page pull carries the timeline history (`test_initial_pull_carries_the_timeline_history`).

## Dongle pass (live console, real database) — 2026-09-23, KST

The pass was **cut off**: another session shut down the previous live console, reflashed the
dongle from `nct-pairing-1.7-zones` to **general-radio-1.1.0** and took `/dev/cu.usbmodem1101`
for its own bench work. Consequences:

- The RX-gain refusal and the `dongle.old` card (steps 5) **no longer apply**: those were specific to the
  1.7 relay firmware. The rerun will exercise the **General Radio session** (`sessions/general_radio.py`)
  instead: discovery, zone relay, set_zone/show_start, leased pool lamp and preshow cue.
- Steps 2–7 are **pending** the rerun on a fresh console once the port is released.

What was captured before the cut-off (console PID 98926, started 02:53:45, database
`pairing_station/data/devices.sqlite3`, API on 127.0.0.1:8765):

| Step | Status | Evidence (timeline, local time) |
|---|---|---|
| 0. Console boot on the real database | done | `NCT Console started · database …/pairing_station/data/devices.sqlite3`; published zone database read back as v37 / 133 records / CRC 3738672143. |
| 1a. Dongle identified without reset | **done (identification only)** | 02:53:45 `USB: USB JTAG/serial debug unit on /dev/cu.usbmodem1101 · Recorded as a General Radio` (the inventory row already said General Radio). 02:53:46 `USB port is owned by another Neocore application` (the other session held the advisory PortLock; the console marked the port *foreign* and did not reset it). 02:54:43 `Identified General Radio (all-in-one dongle) on /dev/cu.usbmodem1101 · general-radio-1.1.0 · AC:27:6E:82:68:54`, `Station link opened … waiting for hello`. The role probe therefore worked on the new firmware. |
| 1b. Station session on the dongle | **cut off** | The session was closed by me at 02:55 (`device.disconnect` → `disconnected by operator`) and the device set to manual-off as soon as the coordinator reported the port in use, so `controller.connected` / hello were never read. The port was confirmed free of this console afterwards (`lsof`). |
| 1c. Cube identified without reset | done | 02:53:48 `Identified Neocore cube on /dev/cu.usbmodem101 · v1.5.0-USB.1 · 1C:DB:D4:F0:A8:30` → pinned as **Cube #17** (inventory: #17, tag 53:1F:D4:CF:33:00:01, status acknowledged); firmware verdict *current* against local build v1.5.0-USB.1. A cube console session opened. |
| 2. Discover cubes over the radio | pending | not run |
| 3. Query zones (versions/states/signal) | pending | not run |
| 4. Identify one zone + request its log | pending | not run |
| 5. `zones.set_rx_gain` refusal / `dongle.old` card | **obsolete** | dongle no longer runs the 1.7 relay firmware |
| 6. Instance-lock refusal both ways | partial | Console `locks` section: `.lock`, `.flasher.lock`, `.zonedb.lock`, `.mainshow.lock` all held. Old pairing app not started (cut off). |
| 7. Advisor on the real inventory | done | 10 cards: `build.stale` ×6, `reg.unconfirmed_rows` (1 registration unconfirmed), `zone.db_behind_many` (19 known zones out of range hold an older database), `apps.legacy_open`, `number.needs_number_many` (20 devices without a number). Readable; the aggregate rules keep it to one card per situation. |
| 8. Zone update over the air (v32 → v37) | **not performed (needs explicit go)** | — |

Observation to check on the rerun: the advisor showed **`apps.legacy_open`** ("Another app is
open on this database: the Pairing station app, the Cube USB flasher, the Zone Database Manager,
the Mainshow controller app") while none of those apps was running and the console itself held
all four lock files. The rule probably reads the lock files' existence, or the console's own
holds, as "another app is open". Not fixed in this pass (report only).

Deviation from the brief: the previous live console was already gone when this pass started
(no `api.curl`, no process), so a console was restarted per the fallback instruction at
02:53:45. When the coordinator's notice arrived, the requested clean shutdown was blocked by the
session's permission classifier; instead the dongle session was closed and the device marked
manual-off, which released the port. **That console (PID 98926) is still running** on the real
database with cube #17's session open and must be stopped before the rerun starts a fresh one.

## Not verified on hardware

- Cube firmware flash through the console (job pipeline, NVS preservation, reboot check, receipts).
- Zone database update over USB (`zone.update_db_usb`) and zone provisioning flash.
- Pool calibration (control points, Apply & save, guided recording, tuning) on a real radio.
- Preshow cue test through a real plate and bridge.
- Mainshow ready / trigger through the console (Mainshow controller or General Radio).
- USB intake (auto-flash cubes / zones) on real boards.
- Receipt recovery against real `flashing_station/data/runs` receipts.
- Zone database update over the air (opt-in; not authorised in this pass).
- Identify blink on a zone: delivered, not visually verified.
- Instance-lock refusal in the reverse direction (console refused while an old app runs): unit test only.

## Dongle pass, rerun — 2026-09-23 02:59–03:02 KST (General Radio general-radio-1.1.0)

Both ports were free again; the board stays on **general-radio-1.1.0** (hello: `show:1`, `timecode:true`,
roles `cube, zone, pool, preshow`). Console started in browser mode (`app.py --browser --no-open`, PID 1721,
02:59:12) on the real database; every step went through the loopback API; the console was shut down
cleanly at the end (`hub.shutdown()` → process exited on its own, `lsof` shows nothing on either port).
Cube #17 on `/dev/cu.usbmodem101` was identified only, never flashed. No show_start, no set_zone, no
pool/preshow lease, no OTA update, no flashing, no inventory write.

| Step | Status | Evidence |
|---|---|---|
| 1. Identification without reset | **done** | `Identified General Radio (all-in-one dongle) on /dev/cu.usbmodem1101 · general-radio-1.1.0 · AC:27:6E:82:68:54`, then `Station link opened … waiting for hello` → a `GeneralRadioSession` opened; `controller.connected=true`, `reader_ok=false` (no reader on this board), `is_dongle=true`. `Identified Neocore cube on /dev/cu.usbmodem101 · v1.5.0-USB.1 · 1C:DB:D4:F0:A8:30` → Cube #17 pinned, firmware verdict *current* (local build v1.5.0-USB.1), cube console session opened. |
| 2. Discover cubes over the radio | **done** | `pairing.discover` → **113 cubes answered** within 3 s, e.g. #17, #37, #110, #126, #73, #70, #40, #82, #43, #150 … Every MAC heard is in the inventory (statuses: acknowledged ×108, not_transmitted ×3 (#106, #108, #115), awaiting_tag ×1 (#90), unconfirmed ×1 (#23)). Discovery = radio reply only; it says nothing about NVS content. |
| 3. Query zones | **done** | `zones.query` → status frames from **27 zones in range** (RSSI −61 … −96 dBm); the registry lists 47 known zones in total. Published database from `store.published()`: **v37**, 133 records, CRC 3738672143. States assigned: *current* for every zone that answered with v37/CRC 3738672143 (Preshow 1/2/3/4 on preshow-3.4.0 at −61…−71 dBm; Desert 1, 2, 4, 5, 6, 7, 8, 10, 15 on desert-2.3.0/2.4.0 at −78…−96 dBm); *behind* for the 19 out-of-range records (older boards: Preshow Exit 1 v4, Preshow 2 v29, two old Preshow 4 boards v28, Desert 3/4/11/13 v4–v14, Desert 12 v32, the six Pool Radios v32, Mainshow 1 v32, both Reset 1 boards v31/v32). No zone reported a *newer-differs* state. `bars`/`signal` fields are null in the snapshot (the RSSI number is present; the bar glyph is computed in the page). |
| 4. Identify one zone + request its log | **done** | Target **Preshow 4, 1C:DB:D4:F0:C3:E0** (preshow-3.4.0, v37, −61 dBm, in range). `zones.identify` (10 s) and `zones.request_log` both accepted by the relay; the General Radio's `tx` counters stayed `sent == delivered` (98 → 208 over the pass, `unconfirmed 0`, `rejected 0`), i.e. **delivered**. The log frame came back within 6 s: timeline `Zone 1C:DB:D4:F0:C3:E0 log: 8 recent tag(s)` with entries for cubes #142, #77 ×2, #54, #44 ×3, #140, all `delivered`, nonce 1790100007 — that reply is the **acknowledgment** of the log request. The identify blink itself was not observed (nobody in the space): delivered, not verified. |
| 5. RX gain through the General Radio | **done (no change)** | The dongle is no longer the 1.7 relay, so the old refusal / `dongle.old` card no longer applies (and no such card appeared). `zones.set_rx_gain` (args `mac`, `db`) on Preshow 4 with **48 dB, equal to its reported stored 48 / applied 48**: timeline `Zone 1C:DB:D4:F0:C3:E0: set RX gain 48 dB requested` → `Zone Preshow 4: RX gain 48 dB — ok` → `Resolved: Waiting for "Preshow 4" to confirm RX gain 48 dB`; registry row `set_result=1 (ok)`, `rx_gain=48`, `rx_gain_applied=48`, `rx_gain_pending=null`. **Acknowledged** by the zone's SET_RESULT reply; nothing changed on the board. |
| 6. Instance lock, old app refused | **done (one direction)** | `pairing_station/app.py` launched while the console ran: exited with code 1 after showing its refusal dialog ("This database is already open in another pairing window."); no stdout. The console's `locks` section during the rerun reported every lock `false` — after the coordinator's fix the section now lists *foreign* holders only (the console's own holds are skipped), so "all false" means no other app holds a lock. |
| 7. Advisor census (real inventory) | **done** | 9 cards: `build.stale` ×6 (Desert/Pool/Preshow/TagPlate zone firmware, dongle relay, Mainshow controller — sources changed since the last build on this machine), `reg.unconfirmed_rows` ×1 (1 registration unconfirmed), `zone.db_behind_many` ×1 (19 known zones out of range hold an older database), `number.needs_number_many` ×1 (20 devices without a number). **The `apps.legacy_open` false positive is gone.** |
| General Radio session snapshot | **done** | `roles ["cube","zone","pool","preshow"]`, `busy idle`, `host_fresh true`, `led_test false`, `shows 2`, `last_show_id 403086437`, `show_running false`; `tx {sent 208, delivered 208, unconfirmed 0, no_result 0, rejected 0}`, `rx {zone 1130, zone_dropped 0, show 14, show_dropped 0, serial_overflows 0}`; pool `{armed false, member 0, radio_id 1}`, `pool_held 0`, `pool_beacon null` (PoolCentral not heard at the bench); preshow `{armed false, point 0, state 0, mode modern, bridge_mac AC:27:6E:83:21:C4, bridge_sees_me false}`, `preshow_held 0`, preshow beacons arriving every 5 s (bridge uptime ≈ 90 000 s). Leases untouched. `hub.show_session()` → `GeneralRadioSession` on AC:27:6E:82:68:54. |
| 8. Zone update over the air | **not performed (needs explicit go)** | — |
| Shutdown | **done** | `hub.shutdown()` returned true at 03:01:46; `console/app.py` exited on its own within 12 s; `api.curl` removed; `lsof` shows no holder on `/dev/cu.usbmodem1101` or `/dev/cu.usbmodem101`. |

Observations from the rerun (report only, nothing changed):
- The zone registry rows carry `rssi` but `bars`/`signal` are null; the signal glyph is derived in the page. Fine for the UI, but a script reading the snapshot gets no bars.
- The `zones.set_rx_gain` command takes `db`, not `rx_gain`; the first attempt with `rx_gain=` failed with a TypeError (operator-facing UI passes the right name; noted for scripts).
- Desert boards answer at −86…−96 dBm from the bench, the preshow plates at −61…−71 dBm: the "in range" rule (a status frame within 20 s) held for all 27 without a walk-around.

## Screenshot pipeline and front-end verification — 2026-09-23 03:20–04:05 KST (simulation)

- `console/docscenes.py` stages 36 documented situations on the `docs` simulation bench (`simdocs.py`); `tests/test_docscenes.py`
  proves every one of them settles in-process, and `tests/test_docshots.py` proves every highlighted control (`hl`/`open` token)
  exists in the page (`data-doc`) or is a command name. Console suite: 168 tests OK (1 opt-in Chrome smoke skipped);
  `node --test console/web/tests`: 23 OK; `test_static` (no literal colours, no inline spacing) green.
- `console/tools/docshots.py` captured all 36 scenarios from headless Chrome at 1440×1000 @2x into `console/docs/shots/`
  (`manifest.json`: every capture `settled: true`, console 0.1.0, git de08bb0 + working tree). Two independent review passes
  (chapters 03–07 and 08–C) checked every PNG for rendering, highlight visibility, state-vs-title agreement, leaked host data
  and legibility; the 30 findings were fixed (canned firmware builds and a seeded v32 publication in simulation, publication
  CRCs on the fake boards, per-card dismiss-menu tokens, table outlines no longer clipped, gentler outlines on text rows,
  tooltip kept open for captures, free-point prefill on the zone form, humanised inventory statuses, `?cube=` and
  `show.controller` on the Show section, sync/plan/lease/job state reset between steps, a fake station MAC that is not
  in the shared inventory) and the set was recaptured. Spot-checked by the coordinator: 06-2 (publishing v32, 2 pending,
  Stop publishing outlined) and 07-1 (blank board, identity form prefilled Point 2 / Preshow 2, Flash outlined).
- Evidence class for everything in this section: **simulation-verified**. The captures show the console's behaviour against
  fake boards; they are not hardware evidence.

## Show system bench checks — 2026-09-23 (cube #17, spare #138)

Reported by the show/timecode task; details in `flashing_station/README.md`, `zones/firmware/MainshowController/README.md`
and `zones/firmware/GeneralRadio/README.md`. Evidence class: **hardware, serial logs only** (the LEDs were not watched).

- Cube #17 (`1C:DB:D4:F0:A8:30`), v1.5.0-USB.1: the old-style SET_ZONE 4 + SHOW_START still starts the show; timecode
  join; wireless show update; an update is deferred while a show runs and committed when it ends; the stored show
  survives a reboot.
- #17 on v1.6.0-USB.1: accepted a fanned show over the air (it now holds show v4, recorded in `show_cubes`).
- #17 on v1.7.0-USB.1: `SHOW_LIVE` starts live mode and the lease ends it; frames for other cube numbers are ignored;
  a unicast live frame is refused by the radio; a running show ignores live frames; mirroring through the real
  console's `show.live` command.
- #138 (`AC:27:6E:82:68:54`) temporarily on mainshow-1.3.0: normal start with no drift; a cube that missed the start
  joined from the timecode at T = 3132 ms. #138 was then flashed back and runs general-radio-1.2.0.
- Not on hardware: the Show editor UI (headless Chrome + simulator, including video sync and a synthetic file drop), a
  real Finder drag into the pywebview window, audio. The installed controller #134 is still on mainshow-1.2.0; every
  other cube is on v1.4.1-USB.2. Web `/api/show*` is deployed; no show is published on the site dataset.

## Register page and automatic updates — 2026-09-23 (simulation and unit tests only)

- Register page (`console/regflow.py`): `tests/test_regflow.py` (13 tests: new number, reserved numbers skipped,
  existing number, scan → ACK → sync against `FakeWebInventory`, unconfirmed with no automatic retry, second cube
  interrupting, no station, renumber, the simulation web guard). Screenshots 03-A1…03-A3 settle in `test_docscenes`.
  Not run with a real station, cube or tag.
- Automatic updates (Settings › Automatic updates): `tests/test_auto_update.py` (6 tests: persistence across restart,
  one walking relay with General Radio fallback, the show toggle, a behind zone gets exactly one USB update in
  simulation, the USB switch, pull gating). Not run against real zones, the dongle or the web pull.
- Safety: a simulated console refuses every non-loopback web server (`jobs/sync.client`, `SimulatedWeb`), after a
  simulated run at about 03:48 KST synced fake cubes to the real web inventory and published zone database v38.

## Workstation firmware merge — 2026-09-23 (simulation, host tests and build only)

The General Radio and the pairing-station firmware became one Workstation firmware (`workstation-1.0.0`,
`zones/firmware/Workstation`); the console has one `workstation` role and panel for every station. Verified by all
Python suites, the node tests, the firmware host simulations (including the ported reader tests: fresh-tag gating,
bus recovery, bare-dongle degradation) and a real arduino-cli build (1,031,248 B, 78 % of app0). **Nothing has been
flashed**: the bench dongle #138 still runs general-radio-1.2.0 and the installed station nct-pairing-1.8-zones, so
the dongle-pass results above were obtained with those firmwares.

## Flash page and USB show stage on real cubes — 2026-09-23 04:39–04:59 KST (device database record)

Reconstructed from the live device database (`flash_runs` and `show_cubes`, read-only); the operator's own notes
were not available. Evidence class: **hardware, as recorded by the console** (LEDs not recorded).

- 04:39 KST: #17 (`1C:DB:D4:F0:A8:30`) show-only update over USB: firmware not touched, show v5 written, read back,
  reported by the cube. At 04:46 a second pass found firmware and show v5 already current (skipped).
- 04:47–04:49 KST: the Flash page took five cubes in turn, each **firmware v1.7.0-USB.1 verified, boot confirmed,
  registration preserved, show v5 written, read back and reported by the cube**: #52 (`AC:27:6E:82:6B:28`),
  #95 (`1C:DB:D4:F0:D1:DC`), #33 (`AC:27:6E:80:03:68`), #58 (`1C:DB:D4:F0:DE:28`), #39 (`1C:DB:D4:EF:6D:60`).
- Between them, and in five more attempts at 04:50–04:51, runs failed with "USB port is owned by another Neocore
  application" before identifying a cube (no MAC recorded, nothing written). That is the intake race fixed later
  that day: auto-flash now waits until the console has finished probing a new port.
- 04:52 KST: show **v6** was published from the NCT Console on this computer (web-allocated). At 04:59 KST all six
  cubes (#17, #33, #39, #52, #58, #95) reported show v6 from NVS on v1.7.0-USB.1 in `show_cubes`. No USB run
  follows 04:51, so v6 reached them **over the air** through the show relay.
- State after this: six cubes on v1.7.0-USB.1 holding show v6; the rest of the fleet unchanged (v1.4.1-USB.2).

<!-- web/screenshot results to be appended -->
