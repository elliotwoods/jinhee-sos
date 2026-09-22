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

`--simulate` runs against fake boards (a station, a preshow plate holding an older database, a pool
radio and a cube) on a temporary copy of the database, so every panel and the suggestion cards can
be exercised without hardware. `--browser` serves the same page to the default browser (also used
automatically when the native webview is unavailable, e.g. no WebView2 runtime on Windows).

## How it is built

- `hub.py` is the owner thread: SQLite, every serial session, the controllers (`pairing_station/
  controller.py`, `zone_registry.py`), jobs bookkeeping and the snapshot the page polls. It ticks
  every 100 ms like the old Tk apps' `root.after` loop. Nothing on it sleeps or reads serial.
- `scanner.py` enumerates USB off-thread; `probe.py` asks each new board what it is without
  resetting it (`?`, JSON `hello`, `STATUS`; never an arming command); `devices.py` keeps the
  per-port state (present → probing → idle → session / job / foreign / protected).
- `sessions/` hold a port per role: pairing station or dongle (`Controller` + `ZoneRegistry` on one
  transport, zone frames routed to the registry), zone plate (cube monitor + console), pool radio
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
  (`confirm` then `call`), so the hold is enforced by the backend, not the page. Nothing ever runs on its own.
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
| Pairing station | Register page (plug-in-to-register workflow, ⌘2), Cube panel (Register, Send saved mapping, Flash, number, role), Pairing station panel (connection, NFC health, Discover, Pair new, Retry/Skip/Stop), Inventory › Cubes (grid/table, filters, bulk Transmit original 32 / Retry unconfirmed / Flash all shown, exports) |
| Cube flasher | Cube panel › Firmware (Flash, Check boot, history); This computer › USB intake (Auto-flash cubes, off at launch) and Firmware builds |
| Zone flasher + cube monitor | Zone panel › Monitor (card, LED ring, history, actions, console) and › Firmware & database (identity form, Flash, Force, Update database over USB, Automatic database update, Check report, RX gain); USB intake (Auto-flash zones); database-only USB updates run without Auto-flash (Settings › Automatic updates) |
| Zone Database Manager | Zone panel (Update over the air, Identify, Request log, Reboot, RX gain), Pairing station / dongle panel (Query zones, auto-refresh, Update all, Auto-update all = Settings › Automatic updates), Inventory › Zone database |
| Mainshow controller | Show section and the Mainshow controller panel (① ready, ② trigger, Stop → idle, clock); "Make this a Mainshow controller" on a spare board |
| Pool calibration | PoolZone panel › Calibration (override lease, control points, guided recording, tuning), › Diagnostics, › Firmware & database (firmware, database, radio id) |
| Pool light test | PoolRadioTest bridge panel; pool central telemetry on the PoolCentral panel |
| Preshow test | PreshowZone panel › Cue test |
| Range test | RangeTest panel |
| General Radio (`zones/firmware/GeneralRadio`) | General Radio panel: cube colours (one cube with the plate-style ×3 result, or every cube in range by hold), identify flash, show start, the zone relay, a leased pool lamp through the central, a leased TouchDesigner cue through the bridge (acknowledgements shown), LED test. Its Pairing tab (`radio.discover` / `radio.identify` / `radio.transmit` / `radio.stop`) and the relay buttons address this board even while a pairing station is also connected (`pairing.*` / `zones.*` take an optional `device`); without a station it is the pairing link. A `fatal` from the board (radio driver dead) shows as a banner and an advisor card until the board is power-cycled. Written onto a spare board from the Unidentified board panel or with `dongle.flash` (`firmware: general`) |
| Web sync | Top-bar Sync button; Inventory › Web sync (check, sync, upload only, download only, publish, pull, plan) |

Port pickers are gone: boards are identified when plugged in. Manual choice survives on the
Unidentified board panel (probe again, open console, make this a dongle / controller / zone).

## Automatic updates (Settings › Automatic updates)

Every database is kept current without a click, by default and across relaunches (settings are saved in
the device database, metadata `console_settings`; `console.settings` / Settings page):

- **Zone databases over the air** (`auto_zone_db_radio`): `hub.apply_auto_modes()` switches the
  `ZoneRegistry` walk-around on for the preferred relay only (`station_session()`: a pairing station, else a
  General Radio) and off on every other relay, so two radios never broadcast chunks over each other. Reopened
  sessions and newly plugged dongles pick it up within a second. The relay panel's "auto-update all" box is
  this setting.
- **Zone databases over USB** (`auto_zone_db_usb`): `Intake.database_step()` gives any configured NctZone board
  on USB whose database is behind the published one a database-only update (`jobs/zone.update_db_job`,
  identity and firmware untouched), once per board and publication, independent of Auto-flash zones. The zone's
  Firmware & database tab shows the result.
- **Main show over the air** (`auto_show`): the show registry's walk-around (Show editor › Auto update).
- **Web pulls** (`auto_pull`, needs the web password): a status check that reports a newer zone database pulls
  it (each web version once per run); a newer published show is pulled every 5 min while a show relay is
  connected (silent while none is published; a new one logs "Pulled show vN"). Failures are logged once per
  distinct error.

`--simulate` writes databases to the fake zones instead of running esptool (`simulate.fake_zone_db`); the
documentation bench (`simdocs`) switches automatic updates off so its staged scenes stay put.
Tests: `tests/test_auto_update.py`.

## Register cubes (#/register, ⌘2)

`regflow.py` + `web/panels/RegisterSection.js`. With "Register cubes as they are plugged in" on (setting
`auto_register`, off by default), plugging in a cube runs: USB identification (pinned) → a number if it has none
(`suggested_number()`: lowest free above 32, never 2/22/39/43; the page and a toast say NEW NUMBER so it goes on
the label; "Label says" overrides it before the scan) → `Controller.repair` on the pairing station (the cube
flashes; scan its tag; every registration rule stays in the controller) → one Sync once the tag is lifted
(inventory both ways, then the zone database publish). The registration reaches zones only once the published database is on them: automatic zone updates (on by default) do that for zones in range of the relay and zones plugged in over USB, or use Update all.
A failure never retries by itself (Retry / Start again). Plugging in another cube mid-flow interrupts the
first, which keeps its retryable saved mapping. A simulated console refuses every non-loopback web server
(`jobs/sync.client`), so `--simulate` can never sync with the real web inventory.

## Show editor (#/showedit, ⌘5)

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
  a running show, and swallows the relay's replies (fire-and-forget). Needs general-radio-1.2.0 and cubes on
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
- **Query / Update all / Auto update** drive `pairing_station/show_registry.py` through a General Radio
  (general-radio-1.1.0+; `sessions/general_radio.py` routes `show_sent`/`show_frame` to `showedit.py`). Auto
  update is the saved Settings › Automatic updates › main show switch. Updates hold while the show controller
  reports a running show.
- A timecode-capable controller (mainshow-1.3.0, general-radio-1.1.0+) is sent the published show's length
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
