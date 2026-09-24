# Intervention record & sources

<span color="red">*This document was written by Kimchi and Chips*</span>

## Summary

What Kimchi and Chips changed, when, and on what evidence, from 17 to 23 September 2026. Times are KST (+09:00). A commit records a code change; it is not proof that hardware was flashed or accepted. The operator-facing summary is {{page:H6}}.

## Facts

### Scope and authorship

- Engineering Six developed the exhibition's interactive systems.
- Kimchi and Chips joined on **Thursday 17 September 2026**, at Amberin's request, to help resolve technical difficulties.
- Covered here: added and reworked firmware, registration and maintenance tools, communication fixes, reported hardware repairs, and the NCT Console that gathers the tools into one window.
- The existing "Repair by Kimchi and Chips" page excludes ongoing cube assembly, testing, maintenance and operation from Kimchi and Chips' scope, except temporary assembly help during the on-site stay. Operating instructions in this handover do not transfer those duties. Amberin and Engineering Six should agree named owners and acceptance ({{page:X13}}).

### Dated progression

| Date / time (KST) | Change | Evidence |
|---|---|---|
| Thu 17 Sept | Public tools and repository baseline; cube USB flashing with verified builds; registration and inventory work; zone flasher fixes | Git `2e382c1`, `8b27c87`, `c268f5c` |
| Fri 18 Sept | Pool calibration and diagnostics; firmware update diagnostics; verified zone database slot updates; computer set-up and agent guidance written | Git `4c30c2f`, `6aa287f`, `2481810`, `2a39bd1` |
| Sun 20 Sept | Sangeun report: poor preshow reception and reader coupling; desert local/cube response differences and failed modules; pool flicker, dimming and slider imprecision; main show postponed. Historical, not the current state | Field-reported (Sangeun) |
| Mon 21 Sept | PoolCentral firmware and pool radio protocol; range-test tooling; external-antenna range test succeeded; pool firmware, communication and mapping improved; mechanical slider limits remain | Git `24370f4`, `bf869f8`; Field-reported (Elliot, Monday notes) |
| Mon 21 Sept evening | Web inventory and PreshowBridge; Zone Database Manager and web-published zone databases; universal Sync; tag colour repeat and PN532 RX gain (Hojun); Mainshow controller | Git `3a8bba5`, `08ec793`, `f1f165a`, `ed90640`, `13006cb` |
| Tue 22 Sept | Preshow test app and protocol updates; zone link updates; sync convergence (handover v1 baseline, Code-checked at `0a20d64`). Hojun: eight replacement desert tag-module sets. Elliot: preshow and enclosed NFC reading work, USB batteries work, main show triggers with one failed cube of ten | Git `2064967`, `a2591e6`, `0a20d64`; Field-reported (Hojun, Elliot) |
| Tue 22 Sept | Case "NFC unknown after registration": a zone still held zone database v31 while the tag was only in v32. Case "Cannot connect to the ESP32" during registration: fixed by reseating the antenna and resetting ({{page:X11}}) | Field-reported (reporter not named) |
| Wed 23 Sept 00:51 | Windows support, CI test workflow, ResetZone firmware; first Reset zone board (ex-Preshow 3 SuperMini) | Git `7191c5d` |
| Wed 23 Sept 01:05 | Unregistration of ex-cubes #134 (Mainshow controller) and #138 (radio dongle) re-applied after another laptop's old sync code had reverted it; synced as web revision 16 | Local backup `devices.backup-before-unregister-20260923-010542.sqlite3` |
| Wed 23 Sept 02:53–03:02 | Live console bench pass with ex-cube #138 (general-radio-1.1.0, AC:27:6E:82:68:54): identification without reset, 113 cubes discovered, 27 zones queried, identify + log, RX gain acknowledged, old pairing app refused ({{page:X13}}) | Bench-verified (`console/TEST_REPORT_2026-09-23.md`) |
| Wed 23 Sept 03:09 | **NCT Console** committed: owner-thread hub, USB identification without reset, per-role sessions, jobs over the existing pipelines, Attention rules, Preact front end, instance locks, `--simulate`; show system (cube v1.5.0 show as data, show clock, Show editor, web show versions); General Radio | Git `de08bb0`; Simulation-verified |
| Wed 23 Sept | Show system on the bench: cube #17 (1C:DB:D4:F0:A8:30) through v1.5.0 → v1.6.0 (fanning) → v1.7.0 (live preview); wireless show update deferred until the show ends; stored show survives reboot; mainshow-1.3.0 show clock on #138 (a late cube joined at T = 3132 ms); #138 then returned to general-radio-1.2.0 | Bench-verified, serial logs only (LEDs not watched) |
| Wed 23 Sept 03:48 | A simulated console run reached the real web inventory: fake records uploaded and zone database v38 published. A guard now refuses non-loopback web servers in simulation | `console/TEST_REPORT_2026-09-23.md`; clean-up open ({{page:X13}}) |
| Wed 23 Sept 04:19 | Handover v2 drafts and screenshots, Korean console text, guided Flash page (firmware + main show over USB via NVS), Register page fix | Git `d43eaa4` |
| Wed 23 Sept 04:39–04:59 | #17 (already on v1.7.0-USB.1) given show v5 over USB at 04:39 (second pass at 04:46 found both current, skipped). Five cubes flashed to v1.7.0-USB.1 with show v5 on the Flash page at 04:47–04:49: #52 (AC:27:6E:82:6B:28), #95 (1C:DB:D4:F0:D1:DC), #33 (AC:27:6E:80:03:68), #58 (1C:DB:D4:F0:DE:28), #39 (1C:DB:D4:EF:6D:60); each firmware verified, boot confirmed, registration preserved, show written, read back, reported. Main show v6 published at 04:52 (web-allocated). All six reported show v6, received over the air, by 04:59. Failed attempts between them and at 04:50–04:51 ("USB port is owned by another Neocore application", no MAC, nothing written) came from a USB intake race, fixed later that day (auto-flash waits until probing finishes) | Bench-verified, as recorded by the console (`flash_runs`, `show_cubes`; LEDs not recorded) |
| Wed 23 Sept 04:47 | Pool relays: the 16-channel relay module replaced by three 8-channel modules; frame map re-measured (poolcentral-4.2.2); every slider 1–23 lights its own lamp | Git `5996e10` (Hojun); Field-reported (Hojun) |
| Wed 23 Sept 04:58 | General Radio and pairing-station firmware merged into one **Workstation** firmware (workstation-1.0.0, arduino-cli build 1,031,248 B, 78 % of app0) with one console role | Git `c955d9f`; Simulation-verified and build only, not flashed |

- No zone board, controller or pairing station was flashed for this documentation, and no installed zone database was changed by it. The 23 Sept cube flashes were bench work, recorded here from local flash receipts.
- State after 23 Sept: six cubes (#17, #33, #39, #52, #58, #95) on v1.7.0-USB.1 holding show v6; the rest of the fleet on v1.4.1-USB.2. #134 still on mainshow-1.2.0.

### Git evidence

| Commit | Time (KST) | Author | Subject |
|---|---|---|---|
| [2e382c1](https://github.com/elliotwoods/jinhee-sos/commit/2e382c1) | 17 Sept 22:05 | Elliot Woods | Publish Neocore tools, verified USB firmware, and mergeable device inventory |
| [8b27c87](https://github.com/elliotwoods/jinhee-sos/commit/8b27c87) | 17 Sept 22:33 | Elliot Woods | Zone flasher: stop re-identifying a board after it reboots |
| [c268f5c](https://github.com/elliotwoods/jinhee-sos/commit/c268f5c) | 17 Sept 23:19 | Elliot Woods | Improve USB cube identification and registration; update device inventory |
| [4c30c2f](https://github.com/elliotwoods/jinhee-sos/commit/4c30c2f) | 18 Sept 01:50 | Elliot Woods | PoolZone calibration and diagnostics |
| [6aa287f](https://github.com/elliotwoods/jinhee-sos/commit/6aa287f) | 18 Sept 02:03 | Elliot Woods | Reuse verified PoolZone builds, firmware update diagnostics |
| [2a39bd1](https://github.com/elliotwoods/jinhee-sos/commit/2a39bd1) | 18 Sept 02:06 | Elliot Woods | Workstation setup, migration and coding-agent guidance |
| [2481810](https://github.com/elliotwoods/jinhee-sos/commit/2481810) | 18 Sept 02:49 | Elliot Woods | PoolZone cube mappings with slot verification |
| [24370f4](https://github.com/elliotwoods/jinhee-sos/commit/24370f4) | 21 Sept 01:14 | Elliot Woods | PoolCentral, pool radio protocol, range test |
| [bf869f8](https://github.com/elliotwoods/jinhee-sos/commit/bf869f8) | 21 Sept 05:00 | Elliot Woods | Pool zone mostly working |
| [3a8bba5](https://github.com/elliotwoods/jinhee-sos/commit/3a8bba5) | 21 Sept 19:25 | Elliot Woods | Web inventory, PreshowBridge, preshow protocol |
| [08ec793](https://github.com/elliotwoods/jinhee-sos/commit/08ec793) | 21 Sept 20:37 | Elliot Woods | Zone Database Manager, web-published zone database |
| [f1f165a](https://github.com/elliotwoods/jinhee-sos/commit/f1f165a) | 21 Sept 22:13 | Elliot Woods | Universal web Sync, stored password, zone signal, web sightings |
| [ed90640](https://github.com/elliotwoods/jinhee-sos/commit/ed90640) | 21 Sept 23:12 | hojun | Tag colour repeat, PN532 RX gain |
| [13006cb](https://github.com/elliotwoods/jinhee-sos/commit/13006cb) | 21 Sept 23:40 | Elliot Woods | Mainshow controller |
| [2064967](https://github.com/elliotwoods/jinhee-sos/commit/2064967) | 22 Sept 00:49 | Elliot Woods | Preshow test app, MainshowController, preshow protocol |
| [a2591e6](https://github.com/elliotwoods/jinhee-sos/commit/a2591e6) | 22 Sept 02:29 | Elliot Woods | Zone database, zone link and firmware updates |
| [0a20d64](https://github.com/elliotwoods/jinhee-sos/commit/0a20d64) | 22 Sept 04:44 | Elliot Woods | Sync convergence (handover v1 baseline) |
| [7191c5d](https://github.com/elliotwoods/jinhee-sos/commit/7191c5d) | 23 Sept 00:51 | Elliot Woods | Windows support, CI tests, ResetZone firmware |
| [de08bb0](https://github.com/elliotwoods/jinhee-sos/commit/de08bb0) | 23 Sept 03:09 | Elliot Woods | NCT Console, show system, General Radio, cube show engine |
| [d43eaa4](https://github.com/elliotwoods/jinhee-sos/commit/d43eaa4) | 23 Sept 04:19 | Elliot Woods | Handover docs, Korean UI text, guided Flash page |
| [5996e10](https://github.com/elliotwoods/jinhee-sos/commit/5996e10) | 23 Sept 04:47 | hojun | PoolCentral 4.2.2 frame map for three 8-channel relay modules |
| [c955d9f](https://github.com/elliotwoods/jinhee-sos/commit/c955d9f) | 23 Sept 04:58 | Elliot Woods | Workstation device (handover v2 baseline) |
| [6b26cdf](https://github.com/elliotwoods/jinhee-sos/commit/6b26cdf) | 23 Sept 18:52 | Elliot Woods | Handover handbook and extended reference (restructure); automatic firmware updates |
| [9261547](https://github.com/elliotwoods/jinhee-sos/commit/9261547) | 23 Sept 18:52 | Elliot Woods | Windows workstation handoff: setup builds firmware, console auto-build, Workstation reader view |
| [f498c6a](https://github.com/elliotwoods/jinhee-sos/commit/f498c6a) | 23 Sept 19:07 | Elliot Woods | Merge Windows workstation handoff |
| [c353997](https://github.com/elliotwoods/jinhee-sos/commit/c353997) | 23 Sept 19:26 | Elliot Woods | Forced Workstation flash override and handover text revisions |
| [5bc1b07](https://github.com/elliotwoods/jinhee-sos/commit/5bc1b07) | 23 Sept 19:44 | Elliot Woods | Git inventory removed (`inventory/devices/`, `scripts/sync_inventory.py`) |
| [63d82dc](https://github.com/elliotwoods/jinhee-sos/commit/63d82dc) | 23 Sept 19:44 | Elliot Woods | Git inventory code retired; padlock hold buttons; a board flashed as a Workstation loses its zone record |
| [83f8252](https://github.com/elliotwoods/jinhee-sos/commit/83f8252) | 23 Sept 20:21 | Elliot Woods | Korean for the forced Workstation flash override |
| [2739586](https://github.com/elliotwoods/jinhee-sos/commit/2739586) | 23 Sept 20:46 | Elliot Woods | Workstation: flash the cube when its tag is read |
| [c42fbf7](https://github.com/elliotwoods/jinhee-sos/commit/c42fbf7) | 23 Sept 20:46 | Elliot Woods | Handover v2 revisions: handbook restructure, web numbering, PDF tooling |
| [6471a94](https://github.com/elliotwoods/jinhee-sos/commit/6471a94) | 24 Sept 16:28 | Elliot Woods | Docs: flash on tag read and handover research factsheets |

Other commits in the range (second-laptop merges and inventory syncs, 21 Sept 00:26–18:58: `1b81371`, `c69b961`, `cc17e7c`, `935fdf9`, `06cb05c`, `7c23a1e`, `4639deb`, `4d34859`) are housekeeping; `c54c67e` (17 Sept 18:06) is the initial commit.

### Original Engineering Six document

- **NCT_전시_네오코어_관련_내용_정리.pdf**, supplied by Elliot, 27 pages, attached to the version 1 page {{v1-14}} with Elliot's explicit approval.
- Historical design reference: pp. 1–5 spatial renders; 6 colour and visitor journey; 7–9 cube and reader design; 10–14 preshow concept and media path; 15–18 desert table; 19–24 pool radio slider and portrait lights; 25–27 planned cube, charging station and tagging hardware (design references, not delivered stock or tested battery life).
- Instructions printed in the PDF are historical content, not instructions to change the installation.

### Field sources

| Source | Date | Content | How it reached us |
|---|---|---|---|
| Sangeun report | 20 Sept | Preshow reception, desert modules, pool flicker, main show postponed | Documentation request |
| Elliot, Monday notes | 21 Sept | External-antenna range test, preshow upgrades pending, pool improvements | Documentation request |
| Hojun, Korean report | 21–22 Sept | Eight replacement desert tag-module sets | Documentation request |
| Elliot, Tuesday report | 22 Sept | Preshow and enclosed NFC work, USB batteries, main show 9 of 10 cubes | Documentation request |
| "NFC unknown" and "cannot connect to the ESP32" cases | 22 Sept | {{page:X11}} | Documentation request; reporter not named |
| Hojun, PoolCentral 4.2.2 | 23 Sept | Relay modules replaced, frame map re-measured and checked on site | Commit message and `zones/firmware/PoolCentral/RELAY_BOARD_FINDINGS.md` (commit `5996e10`) |
| Local inventory records | 23 Sept | Flash receipts, cube show reports, publication metadata | Read-only query of the bench computer's database |

Exact work times in the field reports were not independently verified.

### How this documentation was checked

| Method | Covers | Evidence level |
|---|---|---|
| Code and README reading | Every behaviour and card text quoted | Code-checked |
| Git history review | Dates and change list above | Code-checked |
| Console headless suite | Console logic with simulated boards: 247 tests OK, 1 skipped (the opt-in Chrome smoke), evening of 23 Sept | Simulation-verified |
| Screenshots | 43 captures by `console/tools/docshots.py` (headless Chrome 1440×1000 @2x): fresh temporary database with simulated boards, scenes staged by `console/docscenes.py`, checked by `console/tests/test_docscenes.py` and `test_docshots.py`; yellow outlines drawn by the page | Simulation-verified |
| Bench pass with ex-cube #138 | Radio discovery, zone query, identify, log, RX gain, lock refusal | Bench-verified |
| Show system bench checks | Cube #17 and #138 (serial logs only) | Bench-verified |
| Version 1 readback | Notion text of version 1 | — |

## Known issues / open questions

| Issue | Evidence |
|---|---|
| Field-report work times not independently verified | To confirm |
| The reporter of the two 22 Sept field cases is not named | To confirm |
| The failed cube in Elliot's 1-of-10 main-show test is not identified ({{page:X13}}) | Field-reported (Elliot, 22 Sept) |
| Test report wording: the report says 34 scenarios / 36 captures in places; `console/docs/shots/manifest.json` now lists 43 captures | Code-checked |

## Sources

- `git log --date=iso --all` (commit times +09:00), `git show 5996e10`
- `console/TEST_REPORT_2026-09-23.md`, `console/docs/shots/manifest.json`
- `zones/firmware/PoolCentral/RELAY_BOARD_FINDINGS.md` (commit `5996e10`)
- Local inventory tables `flash_runs`, `show_cubes`, `metadata` (read-only)
- The documentation requests that supplied the field reports
- Old draft `16-intervention-record.md`

<span color="red">*This document was written by Kimchi and Chips*</span>
