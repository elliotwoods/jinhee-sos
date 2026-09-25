# NCT Console

One window for every operator tool: pairing, cube and zone flashing, the cube monitor, the Zone
Database Manager, the Mainshow controller, pool calibration and the bench tools (pool light test,
preshow cue test, range test), plus inventory, zone database and web sync in one place. The old
apps are untouched and still work; the console holds their instance locks while it runs, so the
two never share a database at the same time (each refuses to start and names the other).

```sh
./console/Launch.command            # macOS (Launch.bat on Windows)
pairing_station/.venv/bin/python console/app.py [--database PATH] [--api-port N] [--browser] [--debug] [--simulate] [--scenario default|docs|empty]
```

`--simulate` runs against fake boards (a legacy pairing station, a preshow plate holding an older database, a pool
radio, a cube, a legacy General Radio and a Workstation, `/dev/sim.workstation` = 02:AA:BB:CC:DD:F0) on a temporary copy of the database, so every panel and the suggestion cards can
be exercised without hardware. `--browser` serves the same page to the default browser (also used
automatically when the native webview is unavailable, e.g. no WebView2 runtime on Windows).

## Standalone app (`packaging/`)

Operators install the console as an app from the GitHub releases (`console-v<version>`, version from
`CONSOLE_VERSION` in `state.py`): a signed, notarized `NCT-Console-<version>.dmg` for Apple Silicon Macs and an
unsigned `NCT-Console-<version>-windows-x64.zip`. PyInstaller freezes only the interpreter and third-party
packages; `packaging/launcher.py` copies the shipped tree (Git-known sources under the tool folders, minus tests and
`console/docs`, plus each firmware build's flashable images and manifest; `packaging/stage.py`) to
`<app data>/runtime` (`~/Library/Application Support/NCT Console`, `%LOCALAPPDATA%\NCT Console`), restoring the
repository's modification times, and runs `console/app.py` from there, so paths and data work as in a checkout. An
update replaces only the files the previous version shipped; databases, the web password, flash runs and backups
stay. The launcher also stands in for Python when the console starts esptool.

The launcher sets `NCT_PACKAGED=1` (`paths.PACKAGED`): firmware is fixed per release, so automatic builds are off
and their Settings checkbox hidden, and the **Firmware builds are unavailable** card never appears. No effect in a
checkout.

Release: `packaging/build_mac.py` on the Mac (firmware current check, stage, freeze, sign, verify, tree zip,
notarize and staple app and disk image; `--resume ID` after an interruption), a GitHub release carrying the dmg and
`NCT-Console-<version>-tree.zip`, then the `windows-app` workflow, which builds the Windows app from that tree zip on
`windows-latest` (nothing is compiled there, so both apps ship identical firmware) and attaches its zip. The Windows
app has been checked in a simulated start on the runner only, not with USB boards.

## How it is built

- `hub.py` is the owner thread: SQLite, every serial session, the controllers (`pairing_station/
  controller.py`, `zone_registry.py`), jobs bookkeeping and the snapshot the page polls. It ticks
  every 100 ms like the old Tk apps' `root.after` loop. Nothing on it sleeps or reads serial.
- `scanner.py` enumerates USB off-thread; `probe.py` asks each new board what it is without
  resetting it (`?`, JSON `hello`, `STATUS`; never an arming command); `devices.py` keeps the
  per-port state (present → probing → idle → session / job / foreign / protected).
- `sessions/` hold a port per role: workstation (`sessions/workstation.py`: one session for a pairing
  station, an ESP-NOW dongle, a legacy General Radio or the Workstation firmware; `Controller` +
  `ZoneRegistry` on one transport, zone frames routed to the registry, and the radio verbs gated by the
  `roles` the board's hello reports, so a legacy station sees no new traffic), zone plate (cube monitor + console), pool radio
  (calibration, tuning, leased override), preshow plate (leased cue override), cube (passive
  monitor), Mainshow controller, pool central, pool test bridge, preshow bridge, range test.
  Leases (`HOST PING`) are driven from the tick only while the page keeps touching them.
- `jobs/` run flashes, builds and syncs on worker threads through the existing pipelines
  (`flashing_station/backend.py`, `zones/flasher/zone_flash.py`, `zones/dbmanager/dongle.py`,
  `zones/calibration/firmware.py`, `pairing_station/sync_all.py`); results are applied on the
  owner thread. A session's port is released before a job and re-probed after it.
- `advisor.py` is a pure rules engine: `evaluate(sections, now, dismissed)` turns the snapshot into
  suggestion cards with actions. Actions name commands in `commands.py`. Buttons run on one click;
  hardware commands carry a warning dot and a tooltip (what it does, ▲ hazard, needs, why unavailable)
  from `uitext.ACTIONS`, which must cover every hardware/destructive command. Destructive commands
  (broadcasts to every cube, force flash, unregister) are press-and-hold and need a confirmation token
  (`confirm` then `call`), so the hold is enforced by the backend, not the page. A card's action never runs on
  its own (the automatic updates below are settings, not cards).
- `api.py` is what the page calls (`pull`, `call`, `confirm`, `get_copy`, `get_lines`); `window.py`
  hosts it in pywebview, `httpbridge.py` in a browser. `web/` is the front end (vendored Preact +
  htm, no build step, no network).
- Front-end conventions (after the av-frameworks design system): every colour is a token in the
  theme blocks at the top of `web/styles.css` (dark, light, and "match the system"); canvases read
  them through `web/lib/theme.js`. Cards space their children, so panels carry no inline margins.
  Device panels open under a page header (`PageHead`), tabs live in the route
  (`#/devices/<id>/<tab>`), read-only facts sit in the bottom status bar, and every command
  button carries `data-doc="<command>"`. `tests/test_static.py` guards the colour and spacing rules.
- The pairing app's loopback Python API (`pairing_station/data/api.curl`, port 8765) is hosted
  unchanged with `hub`, `sessions`, `jobs`, `devices` and `store` added to its namespace.

## Where the old controls went

| Old app | Now |
|---|---|
| Pairing station | Register page (plug-in-to-register workflow, ⌘3), Cube panel (Register, Send saved mapping, Flash, number, role), Stations › Workstation panel › Pairing (connection, NFC health, Discover, Pair new, Retry/Skip/Stop; titled "Pairing station" for the legacy station), Inventory › Cubes (grid/table, filters, bulk Transmit original 32 / Retry unconfirmed / Flash all shown, exports) |
| Cube flasher | Flash page (plug-in-to-flash workflow with the published show, ⌘2, off at launch), Cube panel › Firmware (Flash, Update show over USB, Check boot, history); This computer › Firmware builds |
| Zone flasher + cube monitor | Zone panel › Monitor (card, LED ring, history, actions, console) and › Firmware & database (identity form, Flash, Force, Update database over USB, Automatic database update, Check report, RX gain); USB intake (Auto-flash zones); database-only USB updates run without Auto-flash (Settings › Automatic updates) |
| Zone Database Manager | Zone panel (Update over the air, Identify, Request log, Reboot, RX gain), Stations › Workstation panel › Zone relay (Query zones, auto-refresh, Update all, Auto-update all = Settings › Automatic updates), Inventory › Zone database |
| Mainshow controller | Show section and the Mainshow controller panel (① ready, ② trigger, Stop → idle, clock); "Make this a Mainshow controller" on a spare board |
| Pool calibration | PoolZone panel › Calibration (override lease, control points, guided recording, tuning), › Diagnostics, › Firmware & database (firmware, database, radio id) |
| Pool light test | PoolRadioTest bridge panel; pool central telemetry on the PoolCentral panel |
| Preshow test | PreshowZone panel › Cue test |
| Range test | RangeTest panel |
| General Radio (legacy general-radio-1.x boards; the sketch became `zones/firmware/Workstation`) | Workstation panel in the rail group Stations (one role, `workstation`, and one panel for a legacy pairing station, a legacy ESP-NOW dongle, a legacy General Radio or a Workstation, titled from hello: "Pairing station" / "ESP-NOW dongle" / "General Radio" / "Workstation"). Tabs Pairing, Zone relay, Cubes & show, Pool lamp, Preshow cue, Console; a tab is greyed when hello lacks the capability (legacy station: Pairing and Zone relay only; legacy General Radio: everything but the reader; Workstation: all): cube colours (one cube with the plate-style ×3 result, or every cube in range by hold), identify flash, show start, the zone relay, a leased pool lamp through the central, a leased TouchDesigner cue through the bridge (acknowledgements shown), LED test. With a reader, an **On the reader** card above the tabs shows the tag lying on it: UID, owning cube (committed `uid`, then `pending_uid`), inventory state and the last colour sent, with a history of up to 20 recent tags and their held time; **Stop** and **Open cube page** act on the cube on the reader or on the selected history row. The card itself only observes (no database write, not an `nfc_seen` scan); an idle link asks for the UID with `nfc_poll` at most once a second. On a Workstation (the `nfc` role; never a legacy pairing station) the console acts on each tag placed on the reader, whether or not the page is open: by default its owning cube does a 2 s identify flash (blue/red, then idle white), or it gets one SET_ZONE and stays in that zone (staging: tap each cube to make it mainshow-ready). One selector at the top of the card, **Signal the cube when its tag is read**, holds the setting: **Off** · **Flash 2 s** · **idle** · **preshow** · **desert** · **pool** · **mainshow** (a saved setting, not a one-shot button; the card has no on-demand flash or zone buttons: send those from **Cubes & show**). **Off** (also Settings › Behaviour) turns it off: setting `reader_flash`, on by default, saved, one for every Workstation; the action is saved in metadata `console_reader_action` (`flash` \| `zone:0`…`zone:4`); command `radio.reader_flash {on?, action?}`. It never gets in the way: nothing is sent while that radio is busy, another link works with the cube or a main show the console knows about is running, and the flash is a background Controller mode (`reader_flash`) that anything the operator starts takes over at once (`stop` first); a refused or unfinished flash just ends, the registration banner is untouched, and a USB cube plugged in meanwhile does not log "Stopped the active pairing operation". One action per placement (lift to repeat; a reconnect does not repeat it); an unknown tag sends nothing; no inventory write, not an `nfc_seen` scan, no cube firmware change or NVS write. The result shows under "Last automatic action". Its Pairing tab (`radio.discover` / `radio.identify` / `radio.transmit` / `radio.stop`) and the relay buttons address this board even while a pairing station is also connected (`pairing.*` / `zones.*` take an optional `device`); the primary pairing link is the first connected link with a reader (else the first connected), every relay-capable link walks the zones its own radio hears (one radio publishes at a time), and the show relay is the `show:1` link whose radio heard most of the cubes that are behind. A `fatal` from the board (radio driver dead) shows as a banner and an advisor card until the board is power-cycled. Written onto a spare board from the Unidentified board panel or with `dongle.flash` (`firmware: workstation`; built with `build.dongle which=workstation`). Legacy boards keep working but are no longer a flash target |
| Web sync | Top-bar Sync button; Inventory › Web sync (check, sync, upload only, download only, publish, pull, plan) |

Port pickers are gone: boards are identified when plugged in. Manual choice survives on the
Unidentified board panel (probe again, open console, make this a Workstation / Mainshow controller / cube, or open the zone form). The only dongle flash targets are the Workstation and the Mainshow controller (`dongle.flash firmware=workstation|mainshow`, `build.dongle which=workstation|mainshow`).

## Language (EN | KR)

An EN | KR switch sits at the far right of the top bar (also Settings › Appearance › "Language · 언어"). The choice
is stored per machine/browser (localStorage `nct.lang`, default English) and switching re-renders in place: no
reload, and leases and popovers are kept. Python-generated text stays English (advisor cards and their buttons, job
stages, sync status, device logs and reports, errors), and Settings says so. Protocol and hardware tokens (SET_ZONE,
NFC, ACK, MAC, UID, CRC, NVS, RX gain, versions) and product names are never translated. In Korean, buttons, tabs
and nav tooltips also show the English name ("EN: Update all out-of-date zones"), so Korean documents that quote
English button names still match the screen. `?lang=ko` (or `en`) after a route applies a language to that page
only, without changing the stored choice, like `?theme=`.

Strings: front end `t('English')` / `hint()` / `tk()` (`web/lib/i18n.js`), Korean in `web/lib/ko/*.js` keyed by
the English text (one entry per key across files); operator copy `uitext.py` → `uitext_ko.py` (same keys; `api.get_copy`
ships both). Tests: `web/tests/i18n.test.js` (every `t()` literal translated, no unused or duplicate entries,
placeholders match) and `tests/test_uitext.py` (every entry translated; rewording English fails until the Korean is
revisited and `pairing_station/.venv/bin/python console/uitext_ko.py --stamp` records it in `uitext_ko_sources.json`).
Other sessions write plain English; one session does the Korean.

## Automatic updates (Settings › Automatic updates)

Every database is kept current without a click, by default and across relaunches (settings are saved in
the device database, metadata `console_settings`; `console.settings` / Settings page):

- **Zone databases over the air** (`auto_zone_db_radio`): `hub.apply_auto_modes()` switches the
  `ZoneRegistry` walk-around on for every relay-capable Workstation link, and each one walks the out-of-date
  zones its own radio heard in the last 20 s (`walk_candidates`), so a zone only a second Workstation reaches is
  still updated. `hub.zone_walk_allowed()` lets one radio publish at a time, so two never broadcast chunks over
  each other. A walk that cannot publish logs once and backs off (30 s). Reopened sessions and newly plugged
  boards pick it up within a second. The relay panel's "auto-update all" box is this setting.
- **Zone databases over USB** (`auto_zone_db_usb`): `Intake.database_step()` gives any configured NctZone board
  on USB whose database is behind the published one a database-only update (`jobs/zone.update_db_job`,
  identity and firmware untouched), once per board and publication, independent of Auto-flash zones. The zone's
  Firmware & database tab shows the result.
- **Main show over the air** (`auto_show`): the show registry's walk-around (Show editor › Auto update),
  through the show relay whose radio heard most of the cubes that are behind (`showedit.choose_relay`); with
  nothing to send, several relays take turns querying every 10 s.
- **Firmware builds** (`auto_build`, "Build firmware when its source changes (cube, zone plates, Workstation,
  Mainshow controller), one build at a time, before anything is flashed from it") and **USB firmware upgrades**
  (`auto_firmware_usb`, "Upgrade the firmware of USB boards that are out of date: zone plates keep their
  identity, a pairing station or General Radio becomes a Workstation, cubes only while Register and Flash are
  off. Never while you are using the board; pool radios, the pool central and the preshow bridge are only
  listed"): both in `autoupgrade.py` (`AutoUpgrade.tick`, which the hub ticks every 1 s). See below.
- **Web pulls** (`auto_pull`, needs the web password): a status check that reports a newer zone database pulls
  it (each web version once per run); a newer published show is pulled every 5 min while a show relay is
  connected (silent while none is published; a new one logs "Pulled show vN"). Failures are logged once per
  distinct error.

`--simulate` writes databases to the fake zones instead of running esptool (`simulate.fake_zone_db`); the
documentation bench (`simdocs`) switches automatic updates off (firmware too) so its staged scenes stay put.
Tests: `tests/test_auto_update.py`.

### Automatic firmware (`autoupgrade.py`)

Builds (`auto_build`):
- Targets: the cube, the five zone sketches, the Workstation and the Mainshow controller. A target is out of
  date when its manifest check fails (cube, zones) or `dongle.build_state` says stale or missing (Workstation,
  Mainshow controller); the hub refreshes that check every 60 s.
- One build at a time, targets a waiting board needs first, and never while any hardware job or another
  automatic job runs (checked directly, not only through the idle flag). Builds never upload.
- A failed build is remembered by its source fingerprint and not retried until the source changes or the
  operator presses **Retry** on its row in the **Automatic updates** panel. Without arduino-cli and ESP32 core
  3.3.11 the row says "no build tools".
- The `build.stale` card stays silent while the builder has a target queued or building; it shows when the
  automatic build failed, the tools are missing, or `auto_build` is off.

USB upgrades (`auto_firmware_usb`):
- Upgraded: a zone plate whose FW differs from its sketch's `FIRMWARE_VERSION` (through the zone flasher
  pipeline, keeping the profile, point, name, params and RX gain from its own `?` report; needs a configured
  board and a published zone database); a legacy pairing station or General Radio, an old Workstation (all to
  the current Workstation firmware) and an old Mainshow controller; a cube whose `?` FW differs from
  `core.VERSION` (the Flash-page pipeline, firmware plus the published show).
- Listed only, never flashed: pool radios (a matched set with the pool central), the pool central and the
  preshow bridge (no flash pipeline), unconfigured zones.
- Never touched: the protected station 3C:0F:02:AD:83:24; every flasher refusal still applies.
- Held back while: the console is busy (pairing, a zone publication, any hardware job, Register not idle, an
  armed Flash intake); for a cube, while Register or the Flash page is on; for 20 s after the board was
  identified ("Starts in N s"); for 60 s after the operator sent that board a command; while it is relaying or
  sending the show; for a Workstation or Mainshow controller, while the show runs.
- One automatic job at a time. Each board is tried once per plug-in and target version; after a failure use
  **Retry** or replug. **Skip** holds until a replug; **Pause** lasts until relaunch.

The **Automatic updates** panel (`web/components/AutoUpdates.js`, top of the right sidebar above Attention)
shows "✓ Everything up to date" when idle, otherwise one row per build or USB board (port, current → target,
state pill, reason, progress, **Skip** / **Retry**), **Pause** / **Resume**, the over-the-air zone database and
main show counts, and a short history. Automatic jobs appear in Jobs only when they fail. Simulation-verified
only: no automatic firmware flash has run on hardware yet.

## Register cubes (#/register, ⌘3)

`regflow.py` + `web/panels/RegisterSection.js`. With "Register cubes as they are plugged in" on (setting
`auto_register`, off by default), plugging in a cube runs: USB identification (pinned) → a number if it has none
(`suggested_number()`: lowest free above 32, never 2/22/39/43; the page and a toast say NEW NUMBER so it goes on
the label; "Label says" overrides it before the scan) → `Controller.repair` on the pairing station (the cube
flashes; scan its tag; every registration rule stays in the controller) → one Sync once the tag is lifted
(inventory both ways, then the zone database publish). The registration reaches zones only once the published database is on them: automatic zone updates (on by default) do that for zones in range of any relay and zones plugged in over USB, or use Update all.
A failure never retries by itself (Retry / Start again). Plugging in another cube mid-flow interrupts the
first, which keeps its retryable saved mapping. A simulated console refuses every non-loopback web server
(`jobs/sync.client`), so `--simulate` can never sync with the real web inventory.

## Flash cubes (#/flash, ⌘2)

`flashflow.py` (`FlashFlow`) + `web/panels/FlashSection.js`; steps usb → firmware → show, USB only (no radio).
"Flash cubes as they are plugged in" is off at every launch (`flash.enable`); switching it on arms the cube side of
`Intake` (`core.Scheduler`), so cubes already plugged in and every cube plugged in afterwards are each taken once per
plug-in. Each gets `flash_job` with the published show from the local `ShowStore` cache and `session_start` (the Tk
"earlier attempt needs attention" rule); the backend's show stage writes the show into NVS when it is missing, older
or damaged (see [flashing_station/README.md](../flashing_station/README.md#show-stage-nct-console-only)). A failure
waits for Retry (`flash.retry`, which rewrites the firmware like the Tk Manual Retry). `cube.flash_firmware` now also
brings the show up to date, and `cube.update_show` (Cube panel › Firmware › "Update show over USB") writes only the
show. The Automatic intake card's "Auto-flash cubes" is now a link to this page (`usb.auto_cubes` remains an alias).
With Register and Flash both on, registration waits ("Waiting for the Flash page to finish this cube") until the
flash is done. Register and Flash each start with a full-width ON/OFF switch bar (`ActivateSwitch`,
`components/basics.js`; accent when on, dashed when off).

`probe.py` parses the cube's `SHOW:` line into `device.details.show` (Cube panel › Firmware › "Main show"). In
`--simulate`, `FakeCube` prints the SHOW line (firmware ≥ v1.5.0) and `simulate.fake_cube_flash` mimics
`Flasher.execute`.

Audio cues (the Tk flasher's sounds) play for USB cube flashing: the Flash page, Cube panel › Flash cube firmware
and Check boot. A rising two-note start; a tick at each stage and every 4 s while writing; a rising four-note chord
on success (firmware already current with the show written counts as success); a single tick when nothing was
written; a falling three-note tone for anything else, including boot not confirmed; one note when a new USB port
appears while the Flash page is on. Switch: Settings › Behaviour › "Audio cues for USB cube flashing" (Test sound).
Never in a simulation. Auto-flash waits until the console has finished probing a new port.

## Show editor (#/showedit, ⌘6)

The main show as cues on a timeline. Every cube gets the same show; **Preview cubes** renders several cube
numbers at once, because fanned cues (cube firmware v1.6.0+) offset each cube by its number and random cues differ
per cube. The colour band and the LED preview use `web/lib/showengine.js`, which renders exactly what the cube
firmware plays (the same vectors as the C++ and Python engines).

Layout, top to bottom:
- **Header**: "↺ Revert to vN" ("Revert to default" while nothing is published; undoable), **Publish**, **Pull**.
- **Transport** (timeline card, left): Stop, previous cue, Play/Pause, next cue; the timecode (m:ss.mmm) with the
  total length and the current cue; speed 0.25× / 0.5× / 1× / 2×, Loop (off / selected cue / whole show), a
  "go to m:ss" field; then Add cue at playhead, Delete cue, Undo, Redo, Fit and the key hints.
- **Reference video** (timeline card, right): drag a video file in or Choose file…. It plays from an object URL
  (never uploaded) in step with the timeline, with Offset (ms, remembered per file name), Mute, Larger, Replace…
  and ✕. While it plays smoothly the video is the master clock; beyond 80 ms of drift it is sought to the show
  clock (`web/lib/showvideo.js`). Kept while switching pages, not across a restart.
- **Cube box**: the Preview cubes field (e.g. `1-8, 17`), One / 1-8 / 1-24, and **Send to real cubes #…**
  (`show.live`, hardware; "■ Stop sending" while on, the box glows with "● Live on #…"). While on, the page
  sends the colour of each previewed cube number every 60 ms; `showedit.live()` broadcasts SHOW_LIVE frames
  (`showfile.live`, lease 0.6 s) through the relay, drops calls closer than 40 ms, holds during a show update or
  a running show, and swallows the relay's replies (fire-and-forget). Needs a Workstation or general-radio-1.2.0 and cubes on
  v1.7.0-USB.1; a cube playing a real show ignores it. Off when toggled or when leaving the page.
- **Overview strip**: the whole show; drag its window's edges to zoom, drag inside to scroll, double-click to
  fit. Ctrl/⌘ + wheel or pinch zooms around the pointer.
- **Timeline**: ruler and colour band (always 16 cube rows: the previewed cubes first, then the following
  numbers), then the cue lane. Click or drag the ruler/band to scrub; click a block to select it, drag it to move
  it (length kept, clamped between its neighbours), drag its left edge to move only its start (10 ms steps),
  double-click to add a cue. The view follows the playhead while playing.
- **Cue** inspector (type, start, colours, parameters, **Fanning**: none / sequential step × group / scatter
  spread, with the per-cube offsets listed) and **Preview** (one LED ring per previewed cube at the playhead;
  Working copy: hold "Revert to published", hold "Start from the default", Export JSON, Import JSON…).
- **Cubes**: Query cubes, "Update all to vN", "Update selected (n)" with tick boxes, Auto update on/off, Stop
  sending, Send length to controller, and a table (#, MAC, firmware, show version + source, state, staging,
  signal, seen).

Keys (not while typing): Space play/pause, ←/→ ±100 ms (⇧ ±1 s), Home/End, Delete removes the selected cue,
⌘Z / Ctrl+Z undo, ⇧⌘Z / Ctrl+Y redo. Every edit goes through undo and the autosave; changing a cue's type and
back restores its earlier settings.

Behind it:
- The working copy lives in the device database (metadata `show_draft`), so `--simulate` never touches it.
  It is validated by `showfile.py` on every save.
- **Publish** sends it to the web, which allocates the next show version (`jobs/show.py`, `show_publish.py`).
- **Query / Update all / Auto update** drive `pairing_station/show_registry.py` through any link reporting
  `show:1` (a Workstation or general-radio-1.1.0+; `sessions/workstation.py` routes `show_sent`/`show_frame` to `showedit.py`). Auto
  update is the saved Settings › Automatic updates › main show switch. Updates hold while the show controller
  reports a running show.
- A timecode-capable controller (mainshow-1.3.0, a Workstation or general-radio-1.1.0+) is sent the published show's length
  once per publication (or with Send length to controller). Older controllers are left alone and keep working.
- Back end: `showedit.py` (owned by the hub, section `showedit`) and `commands_show.py` (`show.*`).
  Tests: `tests/test_show_editor.py`, `web/tests/showengine.test.js`, `web/tests/showtimeline.test.js`.
  Screenshots: `docscenes.py` 11-5 and 11-6.

## Tests

```sh
pairing_station/.venv/bin/python -m unittest discover -s console/tests -p 'test_*.py'
node --test 'console/web/tests/*.test.js'   # optional, pure front-end helpers
```

The suite is headless: simulated boards (`simulate.py`), a temporary database, no network.
A green suite proves the logic, not the hardware: follow the hardware checks in the plan before
relying on a new flash path.

## Handover screenshots

The operations handover (Notion, "Operations & Technical Handover v2 — NCT Console") is illustrated
with captures of the simulated console. `--scenario docs` (`simdocs.py`) adds a scriptable bench:
a station whose scans and registrations can be held at each step, a plate and a pool radio that
answer `CAL`/`TUNE`/`HOST`, a blank zone board, two cubes and a Mainshow controller. `docscenes.py`
stages each documented step (34 scenarios, EN/KR titles, route, highlighted controls) and
`tests/test_docscenes.py` proves every one of them settles. To recapture:

```sh
pairing_station/.venv/bin/python console/tools/docshots.py --list
pairing_station/.venv/bin/python console/tools/docshots.py --out console/docs/shots   # needs Chrome
```

Each chapter starts a fresh `app.py --simulate --scenario docs --browser --no-open --api-port 8766`
on an empty temporary database, drives it through the loopback API and captures headless Chrome at
1440×1000 @2x. The page reads a documentation query in the hash
(`#/devices/<id>/<tab>?hl=<data-doc tokens>&open=<tokens>&dock=1&still=1`) and outlines the named
controls in yellow; `manifest.json` records the route and titles of every capture. Nothing in this
path touches hardware or the real database.
