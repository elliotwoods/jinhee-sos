# Documentation inbox

This file queues facts that other sessions send to the documentation owner. Each item is written into the handbook
(`handbook/`) or the extended reference (`extended/`), then marked **applied** here.

## 2026-09-23 · from jinhee-sos-cf · new-computer setup (code reading plus one user report)

1. **The console falls back to a browser without any error message.** `console/app.py:69` opens a browser when
   `--browser` is passed, or when `native_available()` is False. That happens when `import webview` fails, or on Windows
   when `hostos.webview2_available()` (`pairing_station/hostos.py:130`) finds no WebView2 runtime.
   - Usual cause: running `console/app.py` with the system Python instead of `pairing_station/.venv`.
   - Fix: always launch through `console/Launch.command` or `Launch.bat`, after running `Setup.command` or `Setup.bat`.
     `scripts/setup.py` installs `console/requirements.txt`, which includes `pywebview==6.2.1`.
   - Diagnose: `pairing_station/.venv/bin/python -c "import webview"`.
   - Evidence: code, plus a user report of the console opening in a browser on a new computer.
   - Goes to: X10, and an H5 section on the console opening in a browser.
2. **"SSL: certificate verify failed" during setup on another computer.** The step is unknown: pip or
   `scripts/sync_inventory.py`.
   - Likely cause: python.org's macOS Python has no certificates until `/Applications/Python 3.x/Install Certificates.command`
     has been run. Otherwise, a proxy or antivirus intercepting TLS.
   - Evidence: user report only; cause not confirmed.
   - Goes to: X10 (Known issues).
3. **`scripts/setup.py` needs Python 3.11 or newer with Tk.** It exits with an install hint if Tk is missing. The web
   inventory also needs `pairing_station/data/web_password`, which is not in git.
   - Evidence: code.
   - Goes to: X10.

**Applied to extended:** X10 (2026-09-23): Environments (Python ≥3.11 + Tk check, requirements, `web_password`), new
"Browser fallback" fact, procedures "The console opens in a browser…" and "SSL: certificate verify failed…", two Known
issues rows. Verified: `console/app.py::native_available`, `hostos.webview2_available`, `scripts/setup.py`, both launchers.
**Handbook part pending:** H5 needs a short section "The console opens in a web browser" (launch only through
`console/Launch.command` / `Launch.bat` after Setup; if it persists, run Setup again; Windows: install WebView2; the
browser page still works). SSL error and Python version stay X10 only.
**Applied to handbook** (2026-09-23): H5 new §10 "The console opens in a web browser" (launcher, Setup again, Edge WebView2 on Windows, browser page still works; More detail X10) and a symptom-index row.

## 2026-09-23 · from auto-database-sync · automatic updates (unit tests and simulation only)

There are four saved settings, all on by default. They live in the device database metadata `console_settings` and are
set from Settings › Automatic updates. `auto_zone_db_radio`, `auto_zone_db_usb` and `auto_show` behave as X08
describes: the walk-around runs on a single relay; a board that is ahead is left alone; the USB update runs once per
board per publication.

- `auto_pull` checks every 5 minutes for a newer show while a show relay is connected.
- `auto_pull` logs only a new pull or each distinct error once. "No show published" is silent.
- The docs bench (`simdocs`, and so `docshots`) turns all four off, so screenshots show them unticked. The real defaults
  are on.
- Tests: `console/tests/test_auto_update.py`.
- Evidence: Simulation-verified.
- Goes to: check X08 and X11 for these three details and add any that are missing.

**Applied to extended:** X08, X11 (2026-09-23): show pull every 300 s only with `auto_show` also on; logging (new pull or
each distinct error once, "No show published…" silent); docs bench turns all five switches off; older saved settings
load missing keys as on. Verified in `console/hub.py`, `console/jobs/show.py`, `console/simdocs.py`. No handbook change.

## 2026-09-23 · from guided-cube-flash-page · Flash page, NVS show, audio (commit c955d9f unless noted)

Most of this is already in X03 and H3. Verify these points:

- **Top bar:** order and shortcuts are Devices, Flash ⌘2, Register ⌘3, Inventory ⌘4, Show ⌘5, Show editor ⌘6, Bench ⌘7
  (`components/TopBar.js`; the reorder is uncommitted). The handbook and X pages must use these shortcuts.
- **Show over USB (NVS):**
  - The console reads NVS at 0x9000, length 0x5000, and replaces only the `show` namespace.
  - It then reads the write back byte for byte, and after a reset the cube must answer `SHOW: v=N crc=… src=nvs`.
  - Result "newer" means the cube keeps its newer show. Firmware before v1.5.0 gives "unsupported".
  - Run folder files: nvs-show-before/-.bin/-after.bin.
  - New columns in `flash_runs`: `show_result`, `show_version`.
- **nvs.py:** byte-identical to esp-idf-nvs-partition-gen 0.3.0. All 342 local backups round-trip. The official
  generator drops `sta.pswd`.
- **Cube panel › Firmware:** a "Main show" row and **Update show over USB** (`cube.update_show`).
- **USB intake race fix:** `intake.next_settled_cube`, `hub.apply_probe_results`. Unit tests pass; not re-tested on
  hardware.
- **Audio cues:** each cue and the setting Settings › Behaviour › "Audio cues for USB cube flashing" (on by default,
  **Test sound**). Silent in simulation. Not heard on real speakers.
- **Show v5 hardware test:**
  - Entrance neon [18,20,1]→[20,20,1], crc 1213966328: the first real web publish.
  - It went over the radio through general-radio-1.2.0 to #17, then NVS was read back and matched the published image
    byte for byte.
  - #17 was restored to v4, then the USB write was done: the cube reported v5 from NVS. LED appearance was not verified.
  - general-radio-1.2.0 ignored a `{"cmd":"hello"}` without an id sent right after the no-reset open.
  - Conflict to check: X07 says v5 changed the first cue "Neon hold (entrance)", not the SET_ZONE 4 colour. Both can be
    true; make them consistent.
- **Docs they already edited** (now mine to own and check): flashing_station/README.md, console/README.md, the root
  README and AGENTS.md rows.

**Applied to extended:** X03, X07, X11 (2026-09-23).
- Top bar: verified (`TopBar.js` `SECTIONS`, key handler in `app.js`; now committed). ⌘1 is Devices. X03/X07/X11 already
  used these keys; X11 now also says where they live. New finding: Settings › Keyboard still says "⌘1–⌘4 sections"
  (X11 Known issues; a code fix, not a doc fix).
- NVS/nvs.py: X03 (0.3.0 byte-identity, 342 backups, `sta.pswd`, `flash_runs.show_result`/`show_version`). The rest was
  already in X03.
- Intake race fix: X03 evidence changed from Code-checked to Simulation-verified (unit tests), not re-tested on hardware.
- Audio cues: already in X03 (not heard on hardware).
- Show v5: resolved in X07 once. Checked against the device database (`metadata.show_source`, `show_crc`) and
  `showfile.pack`: v5 = default show with only the first cue "Neon hold (entrance)" changed (18,20,1) → (20,20,1), CRC
  1213966328 (recomputed, matches). The `SET_ZONE 4` ready colour is firmware (`MAINSHOW_R/G/B` = 18,20,1) and was never
  changed. v6 is byte-identical to the compiled-in default (CRC 3716106196), i.e. v6 reverted v5's change. The radio
  test and the hello-without-id quirk are in X07 Known issues (Bench-verified from serial/NVS read-back; LEDs not verified).
**Handbook part pending:** none required. (The handbook already uses ⌘2/⌘3/⌘6 correctly.)

## 2026-09-23 · from nct-console-language-selector · EN/KR switch (evidence: simulator, headless Chrome, unit tests)

- The EN | KR switch sits at the far top right of the top bar, and is also in Settings › Appearance › "Language · 언어".
  The choice is stored in localStorage `nct.lang` (per browser) and defaults to English. Switching needs no reload.
- `?lang=ko` or `?lang=en` after the route applies that language to one page only (for Korean docshots).
- In Korean, tooltips also give the English name ("EN: <label>").
- These stay in English: text generated in Python (cards, job stages, sync status, logs, errors), protocol tokens and
  product names.
- Developer rules: `t()`/`hint()`/`tk()`, `web/lib/ko/*.js`, `uitext_ko.py --stamp`, `i18n.test.js`, `test_uitext.py`.
  One session does all Korean translation.
- Goes to: H1 (the switch), X11 (settings), X02 (developer rules).

**Applied to extended:** X02, X11 (2026-09-23): X02 corrected "the choice is per computer" → per browser (`nct.lang`),
added `?lang=`, the one-translator rule; X11 has the switch, the Appearance row and evidence. Verified in
`console/web/lib/i18n.js`, `TopBar.js`, `sections.js`.
**Handbook part pending:** H1 line "Each computer remembers its choice" / "선택은 컴퓨터마다 저장됩니다" should say the console
window remembers it (a browser fallback window keeps its own choice). Optional wording fix.
**Applied to handbook** (2026-09-23): H1 Language paragraph now says the console remembers the choice on this computer and a console opened in a web browser keeps its own (EN + KR).

## 2026-09-23 · from merge-station-radio-firmware · Workstation merge (c955d9f; simulation and compile only, no hardware)

These facts are already in the drafts. Verify that X02, X08 and X11 carry the detail:

- **Firmware:** workstation-1.0.0 ("NCT WORKSTATION"). Its USB protocol is the union of the General Radio verbs and the
  pairing station's reader verbs: `nfc_recover`, `nfc_poll` {enabled, once, trace}, `nfc_status`.
- **Reader events:** `tag`, `tag_state`, `nfc_error`, `nfc_init`, `nfc_bus`, `nfc_i2c`.
- **hello additions:** `nfc_ok`, `nfc_polling`, `nfc_firmware`, `nfc_i2c_status`, `tag_present`; roles cube, zone, pool,
  preshow, nfc.
- **"?" report:** gains an "NFC: ok=… fw=…" line.
- **Reader polling:** only while a host sends `nfc_poll enabled:true`. The 80 ms read never slows a bare dongle or a
  show relay.
- **nfc_i2c trace:** reports failures only unless `trace:1` is set. Always-on tracing was about 9 kB/s and starved the
  relays.
- **Hosts:** capability helpers in `zones/dbmanager/dongle.py` (`has_reader`, `relay_capable`, `rx_gain_capable`,
  `show_capable`, `show_relay`, `label`, `family`, `radio_roles`).
- **RX gain over the air:** needs nct-pairing-1.8-zones, general-radio-1.x or workstation. nct-pairing-1.6/1.7 relay
  but cannot set gain.
- **CLI:** `zones/tools/workstation.py`; `general_radio.py` is an alias.
- **Console:** one role, "workstation", with one panel. Its title comes from hello: Pairing station / ESP-NOW dongle /
  General Radio / Workstation.
- **Panel tabs:** Pairing, Zone relay, Cubes & show, Pool lamp, Preshow cue, Console. A tab is greyed out when the board
  lacks the capability.
- **Links:** the primary pairing link is the first link with a reader. The auto-walk uses that link if it relays,
  otherwise the first relay. The show relay is any link reporting show:1.
- **Unidentified board menu:** offers Workstation and Mainshow controller only.
- **Simulation:** adds `/dev/sim.workstation` 02:AA:BB:CC:DD:F0.
- **Metadata:** the key stays `general_radios`.
- **Evidence:** real compile 1,031,248 B (78% of the partition); Python suites green. Nothing has been flashed; the bench
  dongle AC:27:6E:82:68:54 still runs general-radio-1.2.0.
- **Repo docs outside the handover that still say "General Radio" or "Flash dongle"** (a later README sweep):
  - AGENTS.md rows (General radio, Zone Database Manager, Show editor);
  - README.md ~75-78;
  - zones/README.md ~206-213, 230-235, 287-305;
  - zones/mainshow/README.md;
  - pairing_station/README.md:31,82;
  - flashing_station/README.md:27,42;
  - zones/firmware/MainshowController/README.md:36-42;
  - TEST_REPORT;
  - docscenes.py scenario titles ~787/~799.
- The test-report table rows that name general-radio-1.1.0 are historical: that pass did run on general-radio-1.1.0.

**Applied to extended:** X02 (2026-09-23): new Workstation detail table (verbs, events, hello, `?` line, polling,
trace, host helpers, RX gain, title, tabs, links, CLI, metadata key, simulation, evidence). X08 already had the walk
rule and relay capabilities. Verified in `zones/dbmanager/dongle.py`, `zones/firmware/Workstation/README.md`,
`Pn532Wire.h`, `WorkstationPanel.js`, `console/simulate.py`.
**Rejected:** "Unidentified board menu offers Workstation and Mainshow controller only". `console/web/panels/others.js`
offers three hold buttons (Workstation, Mainshow controller, Neocore cube); X02 keeps three.
README sweep items are outside the handover; not applied here. No handbook change.

## 2026-09-23 · from updatable-show-timecode · show system (d43eaa4)

Its "no show published / next > v4" line is STALE: v6 is published (see Current facts). The rest is already in X03 and
X07. Verify that X07 carries the following:

- **Editor layout after the rework:**
  - Header: "↺ Revert to vN" / "Revert to default", Publish, Pull.
  - Transport as icons; a big timecode; speed 0.25–2× plus Loop; a go-to field.
  - "Reference video" drop zone (offset, mute, size; never uploaded).
- **Cube box:** "Preview cubes", One / 1-8 / 1-24, "＋ Plugged-in" (uncommitted; unit test and simulation only), and
  "Send to real cubes #…".
- **Timeline:**
  - Overview strip (drag the edges to zoom, drag inside to scroll, double-click to fit, ⌘+wheel; no zoom slider).
  - Colour band of 16 rows.
  - Cue lane gestures.
- **Keys:** Space, ←/→ (⇧ = 1 s), Home/End, ⌘Z, ⇧⌘Z / Ctrl+Y.
- **Cubes card:** Query, Update all, Update selected, Auto update, Send length to controller.
- **Firmware behaviour:** a timecode snap when a cube drifts by more than 100 ms. Fanning formula: sequential offset =
  ((n-1) mod groups) × step; scatter is fixed pseudo-random, 0 to the spread.
- **Live mode:** SET_ZONE, SHOW_START or a timecode join ends it.
- console/README.md's Show editor UI description is out of date after the layout rework (README sweep).

**Applied to extended:** X07 (2026-09-23): header (chips, **↺ Revert to vN** / **Revert to default**, **Publish**,
**Pull**), transport (icons, readout, 0.25–2×, **Loop** options, go-to field), timeline (overview strip gestures,
Ctrl/⌘ + wheel, no zoom slider, 16-row colour band), **＋ Plugged-in** (unit test and simulation only), Cubes card button
order, live mode ends on `SET_ZONE`/`REGISTER`/`SHOW_START`/timecode join. Fanning formula and 100 ms snap were already
there. Verified in `ShowEditor.js`, `showtimeline.js`, `neocore_usb.ino`. The stale "no show / next > v4" line was not
added (v6 is published). **Plugged-in** is committed in c955d9f, not uncommitted.
**Handbook part pending:** none required by this item (H4 show-editor steps already match the chips).

## 2026-09-23 · from auto-sync-console-inventory · automatic inventory sync (uncommitted; Simulation-verified only)

This affects the **handbook**: operators no longer need to press **Sync**. Update H2, H3 (registration step 4), H4 and
H5 (sync problems), then X08 and X11.

- **The setting:** `auto_sync` is on by default. It appears as Settings › Automatic updates › "Sync the inventory with
  the web by itself…" and is stored in metadata `console_settings`. Older saved settings without the key load as on.
- **When it syncs:**
  - 5 s after the last local change to devices or roles (checked every 2 s);
  - when the 60 s web status check finds changes up or down, or mappings to publish;
  - when downloads that were deferred while the console was busy can apply because it is now idle.
- **What a sync does:** a full sync, the same as the button (`sync_all.sync`): upload, download, then publish the zone
  database if the mappings changed. Merge and wire format are unchanged. Automatic syncs are at least 15 s apart.
- **Failures:**
  - Offline or error: back off 60 s, doubling up to 10 min.
  - Sync lock held by another app: retry after 15 s.
  - Interrupted after the upload: retry once, straight away.
  - Password rejected: the password is forgotten and automatic sync stops until the operator signs in again.
  - Zone publish error: treated as a failure for back-off.
- **Top-bar chip:** "✓ Synced" / "⟳ Sync in 5 s" / "Sync · retry in 2 min" / "Sync · offline" / "⟳ Sync · sign in".
  Clicking it syncs at once.
- **Inventory › Web sync:** a new "Automatic" row.
- **Jobs list:** automatic syncs that succeed are hidden; failures show.
- **Attention cards:** `sync.publish_pending` and `sync.waiting` are hidden while automatic sync is on and has no
  errors. Other sync cards say "It retries by itself; Sync now to try at once."
- **Unchanged:**
  - `auto_pull` still covers pulling the web zone database.
  - The password is still entered once per computer.
  - --simulate never syncs automatically; simdocs has `auto_sync` off.
  - The old Tk apps still sync by hand.
- **Side effect** (also true of a manual Sync): each sync sets metadata `auto_number=0` (`web_sync.py:228`). A new USB
  cube on a synced computer then gets **needs_number** rather than an automatic number. Check how this interacts with
  the Register page's number allocation.
- **Files:**
  - `console/hub.py`: `auto_sync`, `watch_local_changes`, `auto_sync_finished`;
  - `console/jobs/sync.py`: `needs_sync`, `sync_job auto=`;
  - `console/state.py`: `describe_auto`;
  - `console/advisor.py`;
  - `sections.js`, `InventorySection.js`, `Attention.js`.
- **Tests:** `console/tests/test_auto_update.py` AutoSyncTests.

**Applied to extended:** X08 (new "Automatic inventory sync" section, switch row, Known issues), X11 (setting row, Sync
chip states, cards, §12, Known issues), X10 (backup table), X03 (number allocation) (2026-09-23). Evidence kept:
Simulation-verified, uncommitted. Verified in `console/hub.py`, `console/jobs/sync.py`, `console/state.py`,
`console/advisor.py`, `sections.js`, `InventorySection.js`, `Attention.js`. Precision: only the **Web sync problem** card
uses "It retries by itself; Sync now to try at once."
auto_number check (`database.reserve`, `regflow.step_number`, `controller.choose`; live DB holds `auto_number=0`):
- The Register page still assigns a number: `step_number` calls `suggested_number()` for a row without one and shows
  **NEW NUMBER: write #N on the cube's label**. The allocation is local to the computer; two computers numbering at once
  before syncing can clash, and the merge then drops one to **Needs number**.
- A new cube seen by USB identification or radio discovery with the Register page off gets **Needs number** (card
  "‹MAC› has no number", **Assign #N**).
- **Pair new cubes (auto)** skips cubes without a number, so on any synced computer it no longer numbers brand-new
  cubes (Code-checked). X03 corrected.
**Handbook part pending:**
- H2 lines 30, 71, 89: replace "press **Sync**" with "check the Sync chip shows **✓ Synced** (it syncs by itself; click
  it to sync now)".
- H3 line 75 (manual path step 7): same; lines 35/40 (Register step 4/5) can stay (the flow syncs), but "press **Sync**
  again" → "click the Sync chip".
- H3: note that a cube plugged in with the Register page off, or found by **Pair new cubes (auto)**, gets no number:
  use the Register page, or assign the label number first.
- H4 line 31: "Click **Sync**" → "Check the Sync chip shows **✓ Synced**".
- H5 lines 24/34/38 and §9 (192–203): Sync chip states (**Sync · retry in …**, **Sync · offline**, **⟳ Sync · sign in**),
  it retries by itself, successful automatic syncs are not in Jobs.
**Applied to handbook** (2026-09-23): H2 (start checklist, quick-check table, end checklist), H3 (Register step 5, manual step 7, new two-sentence note that only the Register page numbers a new cube, else **Needs number**), H4 procedure A step 1 (chip **✓ Synced**, **⟳ Sync · sign in** for the password), H5 (index row, §1 text and step 2, §9 symptom, chip-state paragraph with sign-in after a rejected password, password card row). Evidence kept: Simulation-verified.

## 2026-09-23 · from auto-sync-console-inventory · web-allocated cube numbers (NOT YET SHIPPED: simulation and tests only, not deployed or committed)

HOLD: apply only when the sender confirms the change is deployed and committed. The handbook and the X pages currently
describe the old behaviour, which is still live (a new cube shows Needs number after a sync, and numbers are chosen
locally).

- The user chose that the web hands out numbers.
- **Web endpoint:** `POST /api/inventory/claim {dataset, mac, exclude[], min=33, client}` returns `{number, existing}`.
  - It gives the lowest free number ≥33 that no other MAC holds or has claimed and that is not in `exclude`.
  - The same MAC always gets the same number back.
  - Claims are kept in a separate blob, `numbers/<dataset>.json`, written with compare-and-swap. The inventory document
    is never written.
  - Code: `web/src/lib/numbers.ts`, `web/src/app/api/inventory/claim/route.ts`.
- **When the console claims** (only with a stored web password, and never in --simulate):
  - for new unnumbered cubes (`needs_number`, not excluded) found by USB, radio discovery or pairing. It checks every
    2 s, renames the cube to the claimed number (status `awaiting_tag`), and automatic sync uploads it;
  - in the Register page's Number step, which shows "Getting a new number from the web…".
- **exclude** = every number in the local database plus the reserved numbers 2, 22, 39 and 43.
- **When the web is unreachable or old (404):** new cubes stay at Needs number (the console never guesses locally) and it
  retries every 60 s. Registration shows "The web could not hand out a number (…); retrying. Or assign one by hand."
  Renaming by hand still works.
- **No web password:** the computer numbers locally as before. The old Tk apps never claim.
- **After it ships:** two computers can no longer pick the same number. **Pair new cubes (auto)** picks cubes up once
  they have a number.
- **Code:**
  - `console/hub.py`: `web_numbering`, `claim_numbers`, `numbers_claimed`;
  - `console/jobs/sync.py`: `claim_job`;
  - `console/regflow.py`: `step_number`;
  - `pairing_station/web_client.py`: `claim_number`;
  - `pairing_station/database.py`: `NEW_UNNUMBERED`.
- **Goes to:** H3 (numbering note and the Register Number step), H5 (Needs number), X03 (number rules), X08 (web
  endpoint and blob), X11 (messages).

## 2026-09-23 · from auto-firmware-usb-updates · automatic builds and USB firmware upgrades (COMMITTED in 6b26cdf; Simulation-verified only, no hardware flash yet)

APPLY to the handbook (H1 console at a glance: the new panel; H2 daily: what the panel means, leave it on; H3: cubes
are upgraded automatically only while Register and Flash are off; H4: zone boards upgrade over USB, and zone databases
are walked by every relay; H5: failed / "by hand" / "no build tools" rows) and to the X pages (X02 architecture; X03
cubes; X08 zone databases over the air; X09 zone boards; X11 settings, panel, cards).

- `console/autoupgrade.py`; the hub ticks it every 1 s.
- **New settings,** both ON by default (metadata `console_settings`):
  - `auto_build`: "Build firmware when its source changes (cube, zone plates, Workstation, Mainshow controller), one build
    at a time, before anything is flashed from it".
  - `auto_firmware_usb`: "Upgrade the firmware of USB boards that are out of date: zone plates keep their identity, a
    pairing station or General Radio becomes a Workstation, cubes only while Register and Flash are off. Never while you
    are using the board; pool radios, the pool central and the preshow bridge are only listed".
- **Builds:**
  - Targets: the cube, the 5 zone sketches, the Workstation and the Mainshow controller.
  - A target is out of date when its manifest check fails, or when the dongle build is stale or missing.
  - One build at a time, starting with the targets a waiting board needs.
  - A failed build is not retried until its source changes (keyed by source fingerprint).
  - Builds need arduino-cli and core 3.3.11; without them the panel shows "no build tools".
- **USB upgrades:**
  - **Zone plate** (not a pool radio): upgraded when its FW differs from the sketch's `FIRMWARE_VERSION`. It goes
    through the zone flasher pipeline and keeps the profile, point, name, params and RX gain from its own `?` report.
    Needs the board configured and a published zone database.
  - **Pairing station** (nct-pairing-*) or **General Radio** (general-radio-*): becomes workstation-1.0.0. An old
    workstation-* or an old Mainshow controller is upgraded too.
  - **Cube:** when its `?` FW differs from core.VERSION (v1.7.0-USB.1). Uses the Flash-page pipeline (firmware plus the
    published show), and only while Register and the Flash page are off.
  - **Listed only, never flashed:**
    - pool radios ("Pool radios and the pool central are a matched set: upgrade them together by hand");
    - PoolCentral and PreshowBridge (no flash pipeline);
    - unconfigured zones.
  - **Never touched:** the protected station 3C:0F:02:AD:83:24. Every existing flasher refusal still applies.
- **What holds an upgrade back:**
  - the console is busy (pairing mode, a zone publication, any hardware job, a session arming);
  - Register is not idle, or Flash intake is armed;
  - the board was identified less than 20 s ago ("Starts in N s");
  - the operator named that board in a command in the last 60 s ("Waiting: in use…");
  - the relay is publishing or sending the show;
  - the show is running (for Workstation and Mainshow).
- **Retries:** one automatic job at a time. Each board is tried once per plug-in and target version; after a failure,
  use Retry or replug. Skip holds until a replug. Pause is runtime only.
- **Panel "Automatic updates"** (`web/components/AutoUpdates.js`, at the top of the right sidebar above Attention):
  - "✓ Everything up to date" when idle.
  - Otherwise one row per build or USB board: port, current → target, a state pill, the reason, progress, and
    **Skip** / **Retry**.
  - State pills: queued, building, upgrading, waiting, checking, needs build, skipped, paused, off, failed, by hand,
    no build tools.
  - Header: **Pause** / **Resume**.
  - Over-the-air lines:
    - "Zone databases v{n}: X current · Y behind · Z updating";
    - "Main show v{n}: …";
    - "{n} more behind, out of range: updated when a radio next hears them";
    - "{n} heard over the air in the last day with older firmware: plug in over USB to upgrade".
  - "Recent (n)" history. Automatic jobs appear in Jobs only when they fail.
- **Zone databases over the air:**
  - Every relay-capable Workstation link now walks the zones its own radio heard in the last 20 s, one radio at a time
    (`hub.zone_walk_allowed`).
  - New settings text: "Zone databases over the air: every zone relay walks the zone database to the out-of-date zones
    its radio hears, one radio at a time".
  - A walk that cannot publish (an inconsistent cache) logs once and backs off.
- **Main show over the air:** the console uses the relay that heard the out-of-date cubes. With nothing to send, relays
  take turns querying every 10 s.
- **Advisor:**
  - `build.stale` is silent while the auto-builder handles a target. It still shows when the build failed, the tools
    are missing, or `auto_build` is off.
  - `dongle.old` and `cube.fw_different` say the board "will be upgraded automatically" when `auto_firmware_usb` is on.
  - New card `zone.fw_behind` (info): zone firmware heard over the air is older than the build. Pool radios get the
    matched-set wording.
- **Build speed** (`hostos.arduino_build_args`):
  - Builds now use the venv's esptool 5.3.1; images are byte-identical.
  - A no-change zone rebuild went from 35 s to 4.5 s; a cold build from about 70 s to about 32 s.
  - PoolZone's build ID now goes through a generated `pool_build_opt.h`.
  - Side effect: the pool calibration app shows "Update available" for the pool radios until they are reflashed (the
    user is deciding whether to keep that).
- **Fixed:** the Workstation and Mainshow Build buttons in This computer › Firmware builds sent the wrong argument.
- **Evidence:** simulation and unit tests only. The first real Workstation flash (bench General Radio
  AC:27:6E:82:68:54) is still pending.

**Applied to extended** (2026-09-23): X02 (Which Workstation does which job, Console architecture `autoupgrade.py` row, Build and validation commands: build speed, `pool_build_opt.h`, Build-button fix, auto builds; Known issues: pool calibration "Update available" To confirm, automatic upgrades Simulation-verified; Sources), X03 (Flash page note, new "Automatic cube upgrade" section, Known issues, Sources), X08 (Zone relay UI label, "Which radio walks" rewritten with back-off and show relay choice, Automatic updates table, Known issues, Sources), X09 (new "Automatic firmware upgrade over USB" section, Known issues, Sources), X11 (Settings rows `auto_zone_db_radio`, `auto_build`, `auto_firmware_usb`, new "Automatic updates panel" section, `build.stale`/`dongle.old`/`cube.fw_different` rows, new `zone.fw_behind` rows, Known issues, Sources). Checked against the code: `zones/flasher/zone_build.py` (not `zones/tools/`); the walk back-off is 30 s (`WALK_BACKOFF`).
**Applied to handbook** (2026-09-23): H1 console at a glance (two paragraphs: the **Automatic updates** panel above Attention, **✓ Everything up to date**, rows with state pills, **Pause**/**Resume**, **Skip**/**Retry**); H2 (start checklist reads the panel, Automatic updates paragraph extended to builds and USB upgrades, pool radios / pool central / preshow bridge only listed **by hand**, WARNING: do not unplug a board showing **upgrading**); H3 C ("Automatic upgrade" paragraph: only while Register and Flash are off, **Starts in N s**, **Skip**); H4 A (every Workstation walks the zones its radio hears, one radio at a time; USB zone boards get firmware upgrades keeping identity, pool radios by hand); H5 new §11 "The Automatic updates panel" (pill table: waiting, needs build, failed, by hand, no build tools, paused/off) and a symptom-index row. Evidence kept: Simulation-verified.

## 2026-09-23 · from jinhee-sos-20 · Windows handoff merge (f498c6a; simulation and unit tests on the Mac; Windows suites ran, no hardware checks of these features)

1. **console/README.md ~l.108 "Firmware builds (auto_build)"** describes `hub.auto_build_step()` and a `build.stale`
   card retry. That code was dropped in the merge. Now:
   - automatic builds live in `console/autoupgrade.py` (`AutoUpgrade.tick`), with `auto_build` and `auto_firmware_usb`
     both on by default;
   - a failed build is remembered by source fingerprint and retried only after a source change or the operator's
     **Retry** in its panel;
   - one build at a time, and never while any hardware job runs (now checked directly).
   - Goes to: README fix; X02/X11 check.
2. **docs/SETUP.md §6**, the paragraph after `build_all_firmware.py --stale`, now reads:
   - the pairing station, Workstation and Mainshow controller use `dongle.build_state`;
   - other targets compare compiled sources (.ino/.h/.hpp/.c/.cpp/.S, ignoring build/ and the output folder) against
     the four images (`<sketch>.ino.bin`, `.bootloader.bin`, `.partitions.bin`, `.merged.bin`);
   - fix the label: the checkbox reads "Build firmware when its source changes (cube, zone plates, Workstation, Mainshow
     controller), one build at a time, before anything is flashed from it", and it has a partner, `auto_firmware_usb`.
   - Goes to: SETUP fix; X10.
3. **Setup** (`scripts/setup.py`, commit 9261547):
   - installs arduino-cli (winget on Windows, Homebrew on Mac), the ESP32 core and pinned libraries, then runs
     `build_all_firmware.py --stale`; `--no-firmware` skips all of this;
   - `hostos.arduino_cli()` also finds `%ProgramFiles%\Arduino CLI`;
   - not hardware-tested end to end;
   - the Setup.bat comment understates what it does (the sender will change it on request).
   - Goes to: SETUP, X10, H? (no).
4. **Workstation reader view** (`console/sessions/workstation.py`, `WorkstationPanel.js`):
   - an **On the reader** card shows the tag on the reader: UID, owning cube (committed uid, then pending_uid), inventory
     and last colour sent;
   - a history of up to 20 recent tags with held time;
   - buttons **Flash 2 s**, **SET_ZONE**, **Stop**, **Open cube page**, acting on the cube on the reader or on the
     selected history row;
   - observation only: no database writes and no `nfc_seen`;
   - when idle the console sends `nfc_poll` at most once a second; colour sends now carry the MAC;
   - evidence: simulation, plus hardware on the Windows bench only.
   - Goes to: X11 (Workstation panel), X03 (not a scan), H5 maybe (identify a cube by its tag).
5. **docshots.py** forces UTF-8 stdout (it crashed on a cp949 Windows console). Goes to: X10 or X02 build tools.
6. **Simulator MACs in the real web inventory** (rev 20, from the 2026-09-22 leak): A4:CF:12:34:56:78/79/9A,
   34:85:18:00:00:12 and 02:AA:BB:CC:DD:01/EE.
   - Web pulls spread them to computers, and `scripts/sync_inventory.py` (run by setup.py) exports them to
     `inventory/devices`.
   - No console simulation path writes to Git (guard: `console/tests/test_sim_isolation.py`).
   - Not cleaned up; the user decides.
   - Goes to: X13 open item, X08 known issue.

## 2026-09-23 · user feedback on the PDF, batch 1 (relayed by jinhee-sos-1c)

**Applied** (2026-09-23):
- H0: removed "Who reads what" and the evidence-level table (now a one-line pointer to X01, which already had the
  table). Screenshot sentence no longer says "simulated". Korean machine-draft WARNING removed.
- H1: removed the purpose callout.
- PDF: dropped the machine-draft note from the title page and "simulated" from the colophon.
- STYLE_GUIDE updated to match.

Pending: whether to remove the purpose callouts on H2–H6 (jinhee-sos-1c is asking the user).
Also pending from the README fix: SETUP §7 target table is stale (Pool central path/output, missing Workstation,
Mainshow controller, Preshow bridge and Range test rows, pairing-only build example); `build_all_firmware.py` comment
names `general_radio.py`.

## 2026-09-23 · user feedback batch 2 · Applied

- Handbook "Mac" wording: the console runs on a Mac or a Windows PC. H0, H1, H2, H4, H5 now say "the console computer" /
  "this computer" / "a Mac or Windows PC" (KR 콘솔 컴퓨터 / 컴퓨터 / Mac 또는 Windows PC). Launcher lines keep
  `Launch.command` (Mac) / `Launch.bat` (Windows). The Windows-untested caveat stays in X10 only (X10 already says
  "never used with hardware"). STYLE_GUIDE canonical rows (NCT Console, Workstation, Web inventory) updated.
- H1 "The system map" is now "The wireless and communication map": every edge labelled NFC / ESP-NOW / USB (serial) /
  internet / wired; 10 nodes (media system node = TouchDesigner + media server cue); legend table EN+KR; the
  paragraph names ESP-NOW on channel 2. PDF: map prints at 9.8 pt, H1 is 6 pages.
- H1 "Not every board is a cube" WARNING moved to X02 (merged with the existing warning under "How the console presents
  each role", plus a Code-checked refusal table and the Role selector). H1 now has a short "What the console refuses
  to flash" table (cube / zone + **Force flash** / Workstation and controller firmware) and the **Role** selector line.
- Code finding for the owner of X07: `console/jobs/dongle.py` clears the Mainshow-controller check when writing
  Workstation firmware, and mainshow firmware is allowed on a controller, so the console never refuses a recorded
  controller. X07 line "The dongle flasher refuses to turn a recorded controller back into a Workstation" is true only
  of the old Zone Database Manager (`zones/dbmanager`), not the console. Not changed here.

## 2026-09-23 · user feedback batch 3 · Applied

- **"Who" removed everywhere.** Purpose callouts (Who / When / You need) deleted from H4, H5, H6 (H0/H1 had none; H3
  is the other session's). Role framing removed: H1 journey node "Cube desk" → "Receive cube"; H4 C step 5 and H5
  (swap test, §3 check 5, §4, §7, §8, §11 rows, DANGER callout) no longer send things to "the cube desk", "the duty
  technician" or "(engineer)"; H6 "Still open" lost its Owner column. X01 "Cube desk" glossary row deleted; X02, X05,
  X07, X08, X11, X12 reworded; X10 backup table lost its Who column; X13 "Owner / decision" → "Decision / contact" with
  role entries (Cube desk, Operator, Engineering team) removed; sign-off field "Receiving operator" → "Received by
  (organisation, name)". Named people stay only as evidence sources. STYLE_GUIDE: page template has no purpose
  callout; audience section without roles.
- **H2 removed.** Its First response table is merged into H5's index ("Symptom index and first response": Symptom ·
  First check · Section, bilingual rows kept) plus the "firmware-difference card is information only" line. The rest
  (daily routine) is dropped; its technical items already live in X11. `handbook/H2-daily-operation.md` deleted.
  `{{page:H2}}` fixed in H0 (list), H1 (→ H4), X07 (→ H3/H4/H5), X11 (→ H4/H5). PAGES.json: `H2` → `H2_archived` with
  the note "archived stub; content moved to H5/H3/H4" (the Notion page becomes a stub). STYLE_GUIDE handbook table
  has no H2 (H4 12 pp, H5 8 pp). Not my files, for their owners: `console/tools/handover_render.py` still has
  `'H2': 'Daily operation'` in its title map, and `handover_pdf/build.mjs` still lists `H2` in the Procedures part
  keys (both harmless: a scratch PDF built fine, H4 = 11 pp, H5 = 8 pp, handbook 51 pp incl. dividers).
- **H4 opens with "What the console does by itself | 콘솔이 스스로 하는 일"** (from the automatic fact sheet): four
  groups (always automatic · automatic unless you switch it off · only when you switch it on · never automatic), a
  table per group, the **Automatic updates** panel and pills, and the "plugging a board in is enough to flash it"
  WARNING moved from H2. Firmware wording is neutral: "flashes it … if its firmware differs from this computer's
  build". "Never goes backwards" is stated only for zone databases and shows. Zone database walks carry on during a
  running show. H4 §F replaced by a one-line pointer to H3; its success-table row removed. H4 A "click Sync on its red
  card" rewritten (pulled automatically; the card's **Sync** or the chip does it at once). H1's two Automatic-updates
  paragraphs shrunk to one pointer.
- **Correction to the fact sheet:** **Pause** in the Automatic updates panel stops only firmware builds and USB firmware
  upgrades (`console/autoupgrade.py`: `self.paused` gates `start_build` and the upgrade plan; log "Automatic firmware
  updates paused"). Zone database walks, show updates and sync ignore it. H4 says so.
- **Web-allocated cube numbers** (the HOLD entry above) are committed in 6b26cdf (`hub.claim_numbers`,
  `regflow.step_number`, `web_client.claim_number`, `web/src/app/api/inventory/claim/route.ts` exists). X08 has a new
  "Cube numbers from the web" table and Known-issue row (Code-checked; deployment of the endpoint **To confirm**); X03
  Number allocation rows and **Pair new cubes (auto)** row updated. **For the H3 owner:** H3 A step 2 ("A new cube
  gets the lowest free number above 32") and the note "Only the Register page gives a new cube a number … **Needs
  number**" must match: with the web password the number comes from the web ("Getting a new number from the web…";
  on failure the cube stays **Needs number** and retries every 60 s), and a brand-new cube seen elsewhere is numbered
  from the web within seconds; the local lowest-free-above-32 rule applies only without a web password.
- **X07:** "The dongle flasher refuses to turn a recorded controller back into a Workstation" corrected: true only of
  the old Zone Database Manager; the console allows it (closes the batch 2 finding).
- **X11:** the two Tier 0 rows ("Another app is open on this database: ‹apps›", "‹port› is owned by another
  application") moved into the Tier 0 table; `auto_sync` noted as committed in 6b26cdf (also in X08).
- Validation: `handover_render.py --all --allow-missing-pages` with fake uploads exits 0.

## 2026-09-23 · from workstation-auto-flash-tag · "Flash the cube when its tag is read" (NOT committed yet; Simulation-verified, unit tests only)

> **Superseded 2026-09-24** (enable-default-tag-flash, below): the switch is now **Signal the cube when its tag is read**, ON by default and saved (`reader_flash`); "off every time the console starts / off at every launch", "Last automatic flash", the "not flashed: …" results, the "Not flashed: …" log lines, `radio.reader_flash {device, on}` and step 5 "turn the switch OFF" no longer apply.

The user wants this written up as a common procedure: H3, new section after B, "Check that a cube is registered, using
the Workstation reader". Also update X03 (the cube tools table and the "Two kinds of flash" warning: this switch only
blinks the LEDs), X11 and the Workstation row in console/README.md.

**Where and what**
- Where: Workstation panel › **On the reader** card, a big ON/OFF switch at its top. The card appears only on a board
  with a reader.
- When ON, each tag placed on the reader makes its owning cube flash blue/red for 2 s over this board's radio, the same
  as **Flash 2 s**.
- Owner: the device with this committed tag, otherwise the one with this pending tag.
- Default off. It is off at every console start and whenever the link reopens; the setting is not saved.
- It sends only while the board is idle. It never writes the database and does not count as an `nfc_seen` scan.
- One flash per placement: lift the tag and place it again to repeat.

**Exact strings**
- Switch: **Flash the cube when its tag is read**
- ON detail: "Each tag placed on the reader makes its cube flash blue/red for 2 s over this radio: the cube is registered
  and reachable. Nothing is sent while the board is busy."
- OFF detail: "Off: a tag on the reader is only shown here. It is off every time the console starts."
- Status line "Last automatic flash": "#<n> · <result> · <time>". Results: flashed / flashed (pending tag) / not
  flashed: unknown tag / not flashed: the board was busy / not flashed: excluded device.
- Log lines:
  - "Flashing cube #44 for 2 s: its tag <uid> is on the reader"
  - "Not flashed: no device in the inventory owns tag <uid>"
  - "Flash on tag read turned ON/OFF"
- Command `radio.reader_flash {device, on}` (hardware; one click with a warning tooltip).

**Procedure**
1. Open the Workstation panel. The **On the reader** card must show NFC ready.
2. Turn the switch ON.
3. Place a cube's tag on the reader. The card shows the cube's number and the cube flashes.
4. Do the cubes one by one, lifting each tag before placing the next.
5. Turn the switch OFF when done.

**What each result means**
- The cube flashes: it is registered and the radio reaches it.
- "Unknown tag" or "not flashed: unknown tag": no cube owns this tag; register it.
- A number is shown but nothing flashes: the cube is off, out of range, or has the wrong MAC. Check the Signal column,
  or use Send saved mapping.
- flashed (pending tag): the registration was never acknowledged; send the saved mapping again.
- not flashed: the board was busy: stop the other operation, then place the tag again.

**Sources**
- `console/sessions/workstation.py` (`set_reader_flash`, `_auto_flash`)
- `console/commands.py` (`radio.reader_flash`)
- `console/uitext.py`
- `console/web/panels/WorkstationPanel.js` (`ReaderCube`)
- `console/tests/test_workstation.py::test_flash_on_tag_read`

**Applied** (2026-09-24): H3, X03, X11, console/README.md

**Applied** (2026-09-24): H3 (B3), X03, X11, console/README.md.

## 2026-09-24 · Post-6b26cdf code audit · Applied

Commits reviewed: `9261547`/`f498c6a`, `6ad3f6e`, `c353997`, `5bc1b07`, `63d82dc`, `83f8252`, `2739586`, plus the
working-tree change to `console/autoupgrade.py` (finished and tested per its author; uncommitted when written).

- **Forced Workstation / Mainshow controller write** (`c353997`, Korean `83f8252`): Unidentified board panel ›
  **Override inventory protection…** (KR 인벤토리 보호 무시…) opens **Override inventory protection?** with the refusal
  text, a **Firmware** choice and a hold **Force write** (KR 강제 쓰기); it also opens by itself when a **Make this board
  a…** hold is refused. Command `dongle.flash_force` (destructive) skips `dongle.refusal`; log "Override: ‹reason›";
  first-time backup kept. Disabled on non-candidate ports (the protected station). Code-checked only (no test, no
  hardware). Applied: H1 refusal table (Override column was "None"), X02 refusal table + Unidentified rows, X08
  Workstation replacement ("No override" removed), X09 Repurposing hazards, X11 hold/USB identification/§9.
- **Git inventory retired** (`5bc1b07`, `63d82dc`): `inventory/devices/*.json`, `scripts/sync_inventory.py`,
  `inventory_sync.sync()`, `git_inventory_baseline_v1` and `console/tests/test_sim_isolation.py` removed; `/inventory/`
  gitignored; setup now runs `scripts/web_sync.py sync` only when the web password is stored. Applied: X08 (two copies,
  table, diagram, baselines, actions table, merge wording, sources), X03 `auto_number` row, X10 (setup steps, backup
  table, SSL step, known issues). Item 6 of the Windows-handoff entry above (sync_inventory export, sim-isolation test)
  is superseded.
- **`63d82dc` other changes:** hold buttons show a padlock and a fill (0.7 s), the visible "Hold:" prefix is gone
  (Workstation "(hold)" labels too); a board written as a Workstation/controller, or first reporting Workstation roles,
  has its zone row removed (`ZoneStore.forget`, event `zone_forgotten`). Applied: H1 hold paragraph, X11, X02, X08, X09.
  Screenshots showing hold buttons still show the old "Hold: …" label: recapture with `console/tools/docshots.py`.
- **Windows handoff setup** (`9261547`/`f498c6a`): setup installs the Arduino toolchain and runs
  `build_all_firmware.py --stale` (`--no-firmware` skips). Applied: X10 setup facts. Reader view was already in X11/H3.
- **Only upgrade, never downgrade** (`console/autoupgrade.py`, Simulation-verified: `test_versions_are_ordered`,
  `test_newer_boards_are_listed_never_downgraded`, `test_newer_workstation_and_unordered_plate_are_left_alone`):
  newer boards and unorderable versions are listed as `report` (**by hand**) with "Newer than this computer's build
  (‹version›); not downgraded" / "Cannot tell whether ‹running› is older than ‹version›; not flashed automatically
  (flash it by hand if it should change)". Applied: H3 (cube auto-upgrade line), H4 (table row, new paragraph, WARNING,
  Never automatic), H5 **by hand** row, X02, X03, X09, X11 (rule paragraph, table, heard-over-the-air line, evidence).
  Update the evidence lines with the commit id once it is committed.
- Revision pointers: X02 handover identity, X10, X12 Git evidence table, X13 release package now name `6471a94`.
- `c353997` also carried handover-draft edits: they were the docs session's own batch 1/2 work (no Who callouts, H2
  still present then and archived later in `c42fbf7`); no conflict with the current structure.
- Not docs owner's files, stale after these commits: README.md "Share the inventory through Git" (l.35–52);
  AGENTS.md Inventory invariants (l.123–124) and hygiene (l.296–297); docs/SETUP.md §2b checklist (l.127–128), §4
  "Shared Git inventory" (l.173–200) and the web-inventory paragraph naming `git_inventory_baseline_v1` (l.207–212);
  web/README.md l.4; web/package.json description; rangetest/README.md l.99; console/README.md USB upgrades (l.142–146,
  "differs" → older-only) and the Unidentified board line (l.74, no override mentioned).

## 2026-09-24 · from enable-default-tag-flash · Workstation tag-read action on by default, with an action picker · Applied

Uncommitted working-tree change. Evidence: Simulation-verified (`console/tests/test_workstation.py::test_tag_read_*` (4),
`pairing_station/tests/test_station.py::test_background_flash_gives_way_to_every_operation`, a simulated console run).
No hardware test. Supersedes the 2026-09-23 workstation-auto-flash-tag entry ("off at every launch").

- Every Workstation (`nfc` role) acts on each tag placed on its reader, whether or not its page is open; the legacy
  pairing station never does (manual **Flash 2 s** only). Default action: 2 s identify flash (blue/red, then idle
  white). Picker **On each tag**: **Flash 2 s** · **idle** · **preshow** · **desert** · **pool** · **mainshow** (one
  SET_ZONE N; the zone stays). No cube firmware change, no NVS, no inventory write, not an `nfc_seen` scan.
- Never in the way: nothing sent while that radio is busy, another link works with the cube, or a main show the console
  knows about is running; the flash is Controller mode `reader_flash` ("Reader check: flashing cube #‹n› · ‹mac›") that
  any operator action takes over at once (`stop` first); refused/unfinished flash just ends; registration banner
  untouched; a USB cube identified meanwhile no longer logs "Stopped the active pairing operation…". One action per
  placement; a reconnect does not repeat it; a tag laid down while busy is read back and acted on once free.
- Strings: switch **Signal the cube when its tag is read**; row **On each tag**; row "Last automatic action"; results
  flashed / flashed (pending tag) / zone N sent / nothing sent: unknown tag / nothing sent: the radio was busy / nothing
  sent: excluded device / nothing sent: a main show is running. Settings › Behaviour checkbox "Workstation reader:
  signal the cube whose tag is read (a 2 s flash, or the zone chosen on the Workstation page), whether or not the page
  is open; never while the radio is busy or a main show is running". Setting `reader_flash` (default true,
  `console_settings`); metadata `console_reader_action` (`flash` | `zone:0`…`zone:4`); command
  `radio.reader_flash {on?, action?}`. Log lines listed in X11.
- Applied: H3 B3 rewritten as "Check a cube on the Workstation reader" (on by default, 5 steps, results table, staging
  variant, running-show WARNING) and its success-table row; H4 "What the console does by itself" group 2 row + intro
  (switch in Settings › Behaviour); H5 symptom-index row; X02 Workstation detail row + role-change note; X03 tools row,
  "Two kinds of flash" warning, USB-plug-in row; X11 settings row, section "Workstation panel › On the reader: tag-read
  action", close-out line, sources; X13 two hardware checks for the next bench session; `console/README.md` Workstation
  row.
- Code note (not a docs change): the `sessions/workstation.py` docstring says "a cube plugged in takes over at once";
  `hub.identified()` actually leaves a running tag-read flash alone (it finishes its 2 s or the next operation takes it
  over). The docs describe the code.

## 2026-09-25 · from jinhee-sos-04 · Workstation tag-read action is one selector, not a switch plus buttons · Applied

Commit `926ac6f`. Evidence: Simulation-verified (console JS 42/42, console Python 301 OK, simulated console screenshots
of the Off, Flash 2 s and pool states). No hardware test.

- The **On the reader** card's ON/OFF switch and **On each tag** picker became one selector, **Signal the cube when its
  tag is read**: **Off** · **Flash 2 s** · **idle** · **preshow** · **desert** · **pool** · **mainshow**. It is a
  saved setting that applies to every tag read from then on, not an on-demand action. Same settings and command as
  before (`reader_flash`, `console_reader_action`, `radio.reader_flash {on?, action?}`); **Off** keeps the chosen action.
- The card's one-shot **Flash 2 s**, **Clear (idle white)** and zone buttons, and the note "Actions apply to the cube on
  the reader, or to a selected history row", are removed. **Stop** and **Open cube page** stay. Manual flash: Pairing
  tab; manual SET_ZONE: **Cubes & show**.
- Applied: `console/README.md` Workstation row; H3 B3 (intro, staging, turning it off); H5 symptom row; X03 tools row;
  X11 close-out line, tag-read section (controls, rest of the card, `zone:N`, evidence); X13 bench check.
