# Open items & acceptance

<span color="red">*This document was written by Kimchi and Chips*</span>

## Summary

The latest field reports say the exhibition interactions broadly work. This page lists what is still open, what the NCT Console still has to prove on real hardware, and the acceptance walk and sign-off that turn the reports into an accepted operating handover. Suggested owners are routing suggestions, not agreed contractual assignments.

## Facts

### Open items

| Item | Status | Owner / decision | Evidence |
|---|---|---|---|
| **Pool printed names:** cover, remove or otherwise treat the printed names the sliders cannot match exactly | Open | Amberin / Lotte decide; Engineering Six implement and check repeatability | To confirm |
| **Desert alignment:** identify the reported Jisung / Jimin positions, record their physical point IDs, correct the mounting, retest through the finished table | Open | Engineering Six, carpentry | To confirm |
| **Battery endurance:** measure preshow USB-battery runtime and cube charging turnaround in real use; set swap intervals. The small LiPo trial failed | Open | Operator | To confirm |
| **Failed main-show cube:** find the cube that failed in Elliot's 1-of-10 test, record number and MAC, diagnose, reflash or re-register, retest | Open; identity not in the report | Cube desk | Field-reported (Elliot, 22 Sept) |
| **Cube stock:** count usable, spare, faulty and charging cubes against the audience and show plan | Open | Operator | To confirm |
| **Cube firmware roll-out:** six cubes (#17, #33, #39, #52, #58, #95) run v1.7.0-USB.1; the rest run v1.4.1-USB.2 and keep playing the compiled-in original show. Decide whether to flash the fleet with the **Flash cubes** page ({{page:X03}}) | Partly done | Cube desk; Elliot to confirm the plan | Bench-verified (six cubes) |
| **Published main show v6:** watch it play on many cubes across the room with the media cue; decide whether v6 is the site show. The next publish is numbered by the web | Open | Media team, Elliot | Bench-verified (cube reports only) |
| **Mainshow controller #134:** decide whether to update mainshow-1.2.0 → mainshow-1.3.0 (adds the show clock for late cubes) | Decision needed | Engineering Six, Elliot | To confirm |
| **Zone database v38 clean-up:** v38 was published by a simulated console run that uploaded fake records (MACs `A4:CF:12:34:56:…`). Check the web inventory, remove the fake records, publish a clean version before distributing ({{page:X08}}) | Open | Elliot (web inventory owner) | Code-checked (`console/TEST_REPORT_2026-09-23.md`) |
| **Zones behind:** 19 known zone boards out of bench range held older zone databases (v4–v32) on 23 Sept: Preshow Exit 1 v4, Preshow 2 v29, two old Preshow 4 boards v28, Desert 3/4/11/13 v4–v14, Desert 12 v32, the six Pool Radios v32, Mainshow 1 v32, both Reset 1 boards v31/v32. Update by walking the Workstation or over USB | Open | Cube desk | Bench-verified (zone query) |
| **Other computers:** a laptop running old sync code reverted cube unregistrations twice. Every computer must run current code before it syncs | Open | Engineering team | Field-reported (Elliot's bench computer, 23 Sept) |
| **Media handover:** record the TouchDesigner project and version, Serial DAT identity, points 1–4 routing, start-up procedure and main-show cue timing | Open | Media team | To confirm |
| **Mainshow signal interface:** photograph and document the installed 5 V → controller interface, connector labels, polarity and pinout before any replacement | Open | Engineering Six, media technicians | To confirm |
| **Pool relay supply:** the fitted SRD-05VDC relays were found fed 12 V on JD-VCC (about 5.7× rated coil power). Target wiring: JD-VCC 5 V from a buck, VCC 3.3 V; confirm it was done. PCA9685 supply never measured | To confirm | Engineering Six, Hojun | Field-reported (`RELAY_BOARD_FINDINGS.md`) |
| **Pool radio ids:** six pool radios report ids 1, 2, 3, 3, 4, 4. Give each a distinct id 1–6 ({{page:X06}}) | Open | Engineering Six | Field-reported (`RELAY_BOARD_FINDINGS.md`) |
| **Reset plate names:** two boards both named "Reset 1" (v31, v32); rename and update ({{page:X09}}) | Open | Cube desk | Bench-verified (registry read) |
| **Release package:** agree one source revision (`origin/main` is at `5996e10`, one commit past the documentation copy) and matching verified builds; reconcile the PoolCentral 40 MHz flash recipe with the aggregate build ({{page:X02}}, {{page:X06}}); record the installed firmware and zone database version per board | Open | Engineering team | Code-checked |
| **Automatic updates:** agree whether Settings › Automatic updates (all on by default) stay on during opening hours | Decision needed | Operator, Engineering Six | Simulation-verified |
| **Windows:** if used, run the Windows bring-up checklist (`docs/SETUP.md` §2b) with real boards; WebView2 window and browser fallback untested on Windows hardware | Open if used | Receiving team | Code-checked, Simulation-verified (CI) |

### Console hardware verification

The console's logic is covered by its headless suite. Each path below needs one real run before the console replaces the old app for that job; until then the old separate apps remain the proven route.

| Path | What to prove | Status | Evidence |
|---|---|---|---|
| Registration through the console | Workstation + real cube: **Register** → READY → TAG DETECTED → REGISTERED, acknowledgement recorded, **Send saved mapping**, tag transfer, a new USB cube stopping an active operation | Not run | Simulation-verified |
| **Register** page | Plug in → number → tag scan → Sync with real cubes and tags, incl. an interrupted cube and a failed acknowledgement with **Retry** | Not run | Simulation-verified (`console/tests/test_regflow.py`, 13 tests) |
| Cube flash (**Flash cubes** page) | Firmware verified, NVS kept, boot confirmed, receipt recorded, show written | Done on five cubes plus a USB show update on #17, 23 Sept; LEDs and power-cycle not recorded | Bench-verified |
| Zone flash and **Update database over USB** | Spare zone board; Monitor on a real zone board; unknown-tag card leading to a working tap | Not run | Simulation-verified |
| Zone database over the air | An installed zone from its version to the current publication, confirmed | Not run (deliberately; needs an explicit go) | Simulation-verified |
| Pool calibration | Calibration, guided recording and **Apply & save** on a real pool radio; pool central telemetry | Not run in the console | Simulation-verified |
| Preshow **Cue test** | Real zone board and bridge, acknowledged in modern mode | Not run | Simulation-verified |
| **Show** section ① / ② / **Stop → idle** | One cube through the Mainshow controller and through the Workstation | Not run through the console | Simulation-verified |
| Show editor and wireless show update | Update deferred until the show ends, NVS kept, fanning, live preview; then **Update all** on many cubes and watch them play | Bench-checked on #17; v6 reported by six cubes; room-wide playback not watched | Bench-verified (serial logs) |
| **Workstation** firmware | Flash workstation-1.0.0 onto a spare (or #138); check relay, cube and show verbs, pool lamp, preshow cue, and a real registration scan with a PN532 on SDA GPIO4 / SCL GPIO3 | Not flashed | Simulation-verified, build only |
| Automatic updates | Zone databases over the air (one relay) and over USB, main show over the air, web pulls, on real zones and cubes | Not run | Simulation-verified (`console/tests/test_auto_update.py`, 6 tests) |
| USB intake (Auto-flash zones) | Real zone boards plugged in one after another | Not run | Simulation-verified |
| Receipt recovery | Against real `flashing_station/data/runs` receipts | Not run | Simulation-verified |
| Instance locks | Both directions | Old app refused while the console ran; reverse direction by test only | Bench-verified (one direction) |

Until the Workstation is flashed, the installed pairing station (nct-pairing-1.8-zones) and the General Radio on #138 (general-radio-1.2.0) are the proven radio boards.

### Bench pass, 23 September

- Board: ex-cube radio #138 (`AC:27:6E:82:68:54`) driven through the live console on the real inventory, API on 127.0.0.1:8765, jobs polled never repeated.
- It started on `nct-pairing-1.7-zones`; another task reflashed it to `general-radio-1.1.0` mid-pass; results are from the 02:59–03:02 rerun (`app.py --browser --no-open`).
- Wording: *delivered* = radio confirmed; *acknowledged* = device answered; *verified* = read back. The table uses the report's words ("dongle-verified" = Bench-verified).
- Nothing was flashed; no installed zone database was changed; no show_start, set_zone, lease or inventory write.
- Cube #17 (1C:DB:D4:F0:A8:30) on the bench was identified and pinned only.

{{test-report-table}}

Additional observations from the report: advisor census on the real inventory = 9 cards (`build.stale` ×6, `reg.unconfirmed_rows` ×1, `zone.db_behind_many` ×1, `number.needs_number_many` ×1: 20 devices without a number); the earlier `apps.legacy_open` false positive (the console's own locks read as another app) was fixed; radio discovery statuses: acknowledged ×108, not_transmitted ×3 (#106, #108, #115), awaiting_tag ×1 (#90), unconfirmed ×1 (#23); General Radio counters `tx sent 208 = delivered 208`, `rx zone 1130, dropped 0`; PoolCentral beacon not heard at the bench; preshow bridge AC:27:6E:83:21:C4 beacons every 5 s.

### Acceptance walk checklist

Do the walk in a maintenance window with the receiving operator and a technical witness. Write the actual result, not the expected one.

| # | Area | Check | Result | Initials |
|---|---|---|---|---|
| 1 | Inventory | Sample physical labels against MAC and tag in **Inventory › Cubes**; explain pending, unknown and excluded; register a test cube and do a controlled retry | ☐ | |
| 2 | Firmware | Flash one cube through the console or the old app; keep the receipt; confirm boot and real LEDs; power-cycle if persistence is part of acceptance | ☐ | |
| 3 | Zone database | Change a test mapping, **Sync**, update every intended zone, record version and CRC from the **Zone relay** table. A zone the relay cannot see is an exception, not a success | ☐ | |
| 4 | Preshow | All four points through the finished enclosure: cube red, correct butterfly cue, release. Repeat after a bridge restart | ☐ | |
| 5 | Desert | All 23 positions; zone light and cube yellow checked separately; retest corrected mountings; reconcile the seven reported failures and eight replacements with the stock | ☐ | |
| 6 | Pool | Six radios and 23 frames; shared-frame selection, tag removal, radio-loss release, stable lamps; run beyond the earlier 10–30 minute heat and flicker window and record the duration | ☐ | |
| 7 | Main show | Entrance tagging, the real scheduled media trigger, playback watched across the room; repeat after re-arming. Tell a sent trigger apart from cube playback | ☐ | |
| 8 | Close-out | **Auto-flash zones** and the **Flash cubes** page off; Settings › Automatic updates as agreed; every temporary control released (status bar empty); logs archived privately; spare stock and contact route confirmed; accepted exceptions recorded | ☐ | |

## Procedures

### Sign-off template

| Field | Value |
|---|---|
| Date and venue | |
| Receiving operator | |
| Technical witness | |
| Source revision (commit) and build manifests | |
| Console version | |
| Computer (Mac / Windows) and Python version | |
| Tested boards: MAC and role | |
| Cube numbers tested | |
| Zone database version and CRC per zone | |
| Published main show version | |
| Scenarios and actual results | |
| Remaining exceptions | |
| Responsible owner and agreed date | |
| Acceptance signatures | |

> [!WARNING] Don't fill this form with values from the simulated screenshots. No acceptance signature was entered by this documentation task. The only hardware results are the bench pass above, the show-system bench checks, the six-cube flash and Hojun's pool relay work ({{page:X12}}).

## Known issues / open questions

| Issue | Evidence |
|---|---|
| The test-report-table placeholder above is rendered by `console/tools/handover_render.py` as an English-only table of the 23 Sept dongle pass. Its "168 tests" and "34 screenshot scenarios" are the historical counts of that pass, labelled as such; the console suite now runs 247 tests (OK, 1 skipped) | Code-checked |
| Identify blink on a zone: delivered, not visually verified | Bench-verified (delivered only) |

## Sources

- `console/TEST_REPORT_2026-09-23.md`
- `zones/firmware/PoolCentral/RELAY_BOARD_FINDINGS.md` (`origin/main`)
- `docs/SETUP.md` §2b and §10
- Local inventory tables `flash_runs`, `show_cubes` and publication metadata (read-only, 23 Sept)
- Field reports listed in {{page:X12}}
- Old draft `17-open-items-acceptance.md`

<span color="red">*This document was written by Kimchi and Chips*</span>
