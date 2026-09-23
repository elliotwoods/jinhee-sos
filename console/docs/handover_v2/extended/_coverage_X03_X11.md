# Coverage: old chapters 03, 04, 05, 11 → X03 / X11

Working file for the handover v2 restructure. Not published. Every `##` / `###` section and every toggle of the four
source drafts is listed with where its content now lives. "H" pages hold only the short operator version; the facts
are in the X page named. Korean prose was dropped (English only).

## 03-daily-operation.md

| Source section | Destination |
|---|---|
| Purpose callout + intro ("proposed procedure… Engineering Six should adopt") | X11 › Summary; X11 › Known issues (To confirm with Engineering Six) |
| ## At a glance (day flow mermaid) | X11 › Facts › Daily checklist, technical items (before opening → zone tests → opening → closing → shift log, as lists) |
| ## Before opening (open console, read Attention first) | X11 › Daily checklist › Before opening |
| ### Cubes and power | X11 › Daily checklist › Before opening (count, spares, damaged; preshow power banks; LiPo trial failed) |
| ### Zone tests with a known-good cube (table, Jisung/Jimin, controller LEDs / Show clock not enough, bridge **Disconnect** warning) | X11 › Daily checklist › Zone tests table + Before opening (Disconnect) |
| ### If cube registrations changed | X11 › Daily checklist › If registrations changed |
| ### Leave the console safe | X11 › Daily checklist › Leave the console safe; X11 › Temporary controls (leases) |
| ## Automatic updates (four switches, defaults, needs, TIP safe to leave on) | X11 › Facts › Settings (full table incl. keys, defaults, behaviour) |
| ## During opening (swap spare, record fields, USB diagnosis, WARNING no batch re-register, DANGER hot equipment) | X11 › Daily checklist (During opening); X11 › Procedures WARNING + DANGER + §13 |
| ## First response (symptom → first check → chapter table) | X11 › Facts › First response and symptom index |
| ## Closing and handover (7 steps, battery WARNING) | X11 › Daily checklist › Closing; X11 › Result status (battery not from radio dot); X11 › Known issues (battery endurance unmeasured) |
| ## What success looks like | X11 › Daily checklist (Success state line); Zone database pills |
| ## Shift log template | X11 › Facts › Shift-log fields |
| Sources and evidence toggle (advisor/uitext/intake/hub/sections sources; To confirm; automatic updates Simulation-verified, test list) | X11 › Sources; X11 › Known issues |
| ## Related guides | Replaced by `{{page:…}}` links in X11 |

## 04-register-cubes.md

| Source section | Destination |
|---|---|
| Purpose callout + intro (three things linked; zones learn later; two ways) | X03 › Summary; X03 › Registration model |
| ## At a glance (mermaid USB → number → scan → REGISTERED → Sync → zones → test) | X03 › Register page (steps) + Procedures › Register page |
| ## Before you start (Launch.command / .bat; NFC scanning / NFC not responding; reader needed INFO) | X03 › Procedures › Register page step 1; X03 › Registration model (Scan hardware) |
| ## Register cubes as they are plugged in (Register page) | X03 › Facts › Register page (`#/register`, ⌘3) |
| ### 1. Open Register and switch it on | X03 › Register page (switch, saved, off by default, chip texts) |
| ### 2. Plug in a cube and write its number on the label | X03 › Register page › Number card; Number allocation |
| ### 3. Scan the cube's tag | X03 › Register page (prompt) + Station banners |
| ### 4. Lift the tag: the console syncs | X03 › Register page (prompt table, **This session** table, Zone database not published) |
| ### 5. Let the zones learn the tag (+ WARNING) | X03 › Register page (zone update not part of the flow); Procedures step 6; X11 §2 |
| ### When the page is waiting | X03 › Register page › Waiting messages (complete, from `regflow.py`) |
| ### When something goes wrong (buttons, interrupted, switch-off, same rules) | X03 › Register page › Failure texts, Buttons, Other behaviour |
| ## Register one cube from its card (manual path) | X03 › Manual path; Procedures › Manual registration |
| ### 1. Check the Workstation | X03 › Procedures › Manual registration step 1 |
| ### 2. Identify the cube (pin, Discover / Identify) | X03 › USB identification of a cube; Manual path table |
| ### 3. Give it its label number | X03 › Number allocation |
| ### 4. Press Register (scan a tag) | X03 › Manual path table (tooltip, hazard) |
| ### 5. Wait for READY TO SCAN, then scan | X03 › Station banners |
| ### 6. Wait for REGISTERED (Log attempt → Delivered → answer; Registered · ACK) | X03 › Station banners; Registration status pills |
| ### 7. Sync, update the zones, test | X03 › Procedures › Manual registration step 6 |
| ### 8. Unpin | X03 › Manual path table (**Unpin**); X11 › USB identification rules |
| ## What success looks like (+ Delivered WARNING, power-cycle proof) | X03 › Registration model; Procedures step 8; Known issues |
| ## Edge cases (table) | X03 › Edge cases (all rows), Register unavailable reasons, NFC ownership transfer |
| Two kinds of "flash" WARNING | X03 › WARNING under Edge cases |
| Protected station DANGER | X03 › DANGER under Edge cases |
| Engineering detail toggle (MAC, `Cube MAC:`/`FW:`, `Controller.repair`, ACK criterion, `uid`/`pending_uid`, USB REGISTERED line, `--simulate` web guard) | X03 › Registration model; USB identification of a cube |
| Sources and evidence toggle | X03 › Sources; Known issues (Simulation-verified 13 tests, docscenes shots, Bench-verified #17 pin + discover) |
| ## Related guides | Replaced by links |

## 05-cube-firmware-show.md

| Source section | Destination |
|---|---|
| Purpose callout + intro (USB identity, Unidentified board WARNING) | X03 › Summary; X03 › USB identification; X11 › USB identification rules (Unidentified board) |
| ## At a glance (mermaid firmware → show) + "everything over USB" | X03 › Flash page (USB only; steps) |
| ## Where the fleet is today (+ TIP information only) | X03 › Firmware versions (On site column); Flash page (card is information); X11 card catalogue (`cube.fw_different`) |
| ## Flash cubes as they are plugged in (Flash page) | X03 › Facts › Flash page |
| ### 1. Clear the bench and switch the page on | X03 › Flash page (switch, chips, off at launch); Procedures › Flash page; Known issues (silent boards are taken) |
| ### 2. Plug in a cube and wait (Firmware / Show bullets, show result table, NVS note) | X03 › Firmware pipeline; Show stage; Flash page › Result lines; NVS |
| ### 3. Done: unplug, plug in the next cube | X03 › Flash page (toast, **This session** table) |
| ### 4. On failure the page stops | X03 › Flash page (**Retry (rewrite the firmware)**) |
| ### Register and Flash together | X03 › Flash page (Register and Flash together; Automatic intake link) |
| ### Sounds (+ WARNING skip after success, 2 s gap) | X03 › Flash page (Sounds table; skip rule; 2 s Scheduler rule) |
| ## Update one cube from its panel | X03 › Single cube from its panel; Procedures › Single cube |
| ### 1. Plug in the cube and read the Firmware tab | X03 › Single cube (Overview, Firmware, Main show row) |
| ### 2. Press Flash cube firmware (+ Update show over USB) | X03 › Single cube |
| ### 3. Read the result (Verified; boot not confirmed) | X03 › Firmware pipeline › Results; Recovery table |
| ### 4. Unplug only after it finishes (close refused, History, Check boot) | X03 › Single cube |
| ## What success looks like (+ Version matches WARNING) | X03 › USB identification (verdict texts); Firmware pipeline results; X11 Result status |
| ## Recovery (mermaid + table + DANGER full-chip erase) | X03 › Procedures › Recovery (mermaid, table, DANGER) |
| ## What is preserved and what is changed | X03 › What is preserved and what is changed |
| ## Firmware versions (table, moving the fleet) | X03 › Firmware versions; Known issues (fleet move To confirm) |
| ## Editing the main-show animation (v1 path, publish, OTA vs USB, plays table, WARNING default show = firmware release) | X03 › Main show onto cubes; Firmware versions (plays line); detail in X07 |
| Engineering detail toggle (NVS offsets/namespaces, pipeline, show stage, show results, run folder, OTA rules, SHOW_LIVE, build target) | X03 › NVS; Firmware pipeline; Show stage; Run folder; Main show onto cubes (live mirroring); Firmware versions (build target) |
| Sources and evidence toggle (simulation tests; 04:39–04:59 bench record; race; v6 OTA; underlying flasher; #17 serial-log checks) | X03 › Known issues; Sources |
| ## Related guides | Replaced by links |

## 11-troubleshooting.md

| Source section | Destination |
|---|---|
| Purpose callout + intro (card titles always English) | X11 › Summary |
| ## Symptom index | X11 › Facts › First response and symptom index |
| ## 1. First: one cube, or one board? (mermaid, pattern table, Monitor/Cube panel, WARNING) | X11 › Procedures §1 (mermaid, lists, WARNING) |
| ## 2. A cube is not recognised at a zone (mermaid, card table, checks, automatic updates note, site case, evidence) | X11 §2; card rows in X11 › Attention cards catalogue (tier 2 and 3). Decision mermaid reduced to the ordered checks list |
| ## 3. Registration fails (mermaid, cards, checks, TIP Log, site case, evidence) | X11 §3; X03 › Edge cases |
| ## 4. A zone reads no tags at all (cards, checks, WARNING RX gain, evidence) | X11 §4; catalogue (zone.nfc_down, nfc_fast_fail, rx_gain_unconfirmed) |
| ## 5. The zone reads the tag but the cube does not change colour | X11 §5; catalogue (cube.nack_*, cube.unregistered, cube.wrong_channel, cube.espnow_init_error) |
| ## 6. Preshow: cube is red but no butterfly (mermaid path, stage table, TIP Cue test, ack meaning, evidence) | X11 §6 (path as one line) |
| ## 7. The main show does not start (mermaid, indicator table, checks, WARNING trigger-all, DANGER 5 V, show clock, evidence) | X11 §7 (indicators, checks, trigger-all warning, 5 V trigger-input hazard, show clock, evidence); wiring detail in X07 |
| ## 8. Pool frame lamps wrong or flickering | X11 §8; catalogue (pool.*) |
| ## 9. A flash stops with a warning | X11 §9; X03 › Recovery; catalogue tier 4 |
| ## 10. A board plugged in by USB is not identified (+ port-name WARNING) | X11 §10; X11 › USB identification rules |
| ## 11. The console or an old app refuses to start | X11 › Instance locks; §11; Known issues (message correction) |
| ## 12. Sync problems | X11 §12; catalogue tier 1 (sync.*) |
| ## 13. Equipment is hot, damaged or has unstable power | X11 §13 + DANGER |
| ## Record a new case | X11 › Shift-log fields (new case record) |
| Engineering detail toggle (I²C status 2/5, result status, zone DB versions ahead card) | X11 catalogue (`station.nfc_down`, `zone.db_ahead`); X11 › Result status; Zone database pills |
| Sources toggle | X11 › Sources |
| ## Related guides | Replaced by links |

## Not placed in X03 / X11

- Nothing factual. The day-flow and decision mermaids of 03 and 11 §2/§3/§7 were reduced to ordered lists (one structural mermaid kept in X11 §1 and one in X03 Recovery).
- Screenshot ids referenced by the old chapters (03-1…03-5, 03-A1…03-A3, 04-F1, 04-F2, 04-1…04-4, C-2, C-9, 08-1, 08-2) are not used in extended pages (no screenshots by rule). They are cited as evidence only.

## Audit changes (23 Sept, final audit)

- X03 › Troubleshooting table: card placeholder `<error>` → `‹error›` (matches X11).
- X11 › Registration cards: **NEOCORE #n NOT CONFIRMED** → **NEOCORE #N NOT CONFIRMED** (matches X03 and the code's title).
- X03, X11: title line moved above the byline.
- No old-chapter fact was missing from X03/X11 (see `_coverage_SUMMARY.md`).
