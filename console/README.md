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
| Pairing station | Cube panel (Register, Send saved mapping, Flash, number, role), Pairing station panel (connection, NFC health, Discover, Pair new, Retry/Skip/Stop), Inventory › Cubes (grid/table, filters, bulk Transmit original 32 / Retry unconfirmed / Flash all shown, exports) |
| Cube flasher | Cube panel › Firmware (Flash, Check boot, history); This computer › USB intake (Auto-flash cubes, off at launch) and Firmware builds |
| Zone flasher + cube monitor | Zone panel › Monitor (card, LED ring, history, actions, console) and › Firmware & database (identity form, Flash, Force, Update database over USB, Check report, RX gain); USB intake (Auto-flash zones) |
| Zone Database Manager | Zone panel (Update over the air, Identify, Request log, Reboot, RX gain), Pairing station / dongle panel (Query zones, auto-refresh, Update all, Auto-update all), Inventory › Zone database |
| Mainshow controller | Show section and the Mainshow controller panel (① ready, ② trigger, Stop → idle, clock); "Make this a Mainshow controller" on a spare board |
| Pool calibration | PoolZone panel › Calibration (override lease, control points, guided recording, tuning), › Diagnostics, › Firmware & database (firmware, database, radio id) |
| Pool light test | PoolRadioTest bridge panel; pool central telemetry on the PoolCentral panel |
| Preshow test | PreshowZone panel › Cue test |
| Range test | RangeTest panel |
| General Radio (`zones/firmware/GeneralRadio`) | General Radio panel: cube colours (one cube with the plate-style ×3 result, or every cube in range by hold), identify flash, show start, the zone relay, a leased pool lamp through the central, a leased TouchDesigner cue through the bridge (acknowledgements shown), LED test. Its Pairing tab (`radio.discover` / `radio.identify` / `radio.transmit` / `radio.stop`) and the relay buttons address this board even while a pairing station is also connected (`pairing.*` / `zones.*` take an optional `device`); without a station it is the pairing link. A `fatal` from the board (radio driver dead) shows as a banner and an advisor card until the board is power-cycled. Written onto a spare board from the Unidentified board panel or with `dongle.flash` (`firmware: general`) |
| Web sync | Top-bar Sync button; Inventory › Web sync (check, sync, upload only, download only, publish, pull, plan) |

Port pickers are gone: boards are identified when plugged in. Manual choice survives on the
Unidentified board panel (probe again, open console, make this a dongle / controller / zone).

## Show editor (#/showedit, ⌘4)

The main show as cues on a timeline. The colour band and the LED preview use `web/lib/showengine.js`,
which renders exactly what cube firmware v1.5.0 plays (the same vectors as the C++ and Python engines).
- The working copy lives in the device database (metadata `show_draft`), so `--simulate` never touches it.
  It is validated by `showfile.py` on every save.
- **Publish** sends it to the web, which allocates the next show version (`jobs/show.py`, `show_publish.py`).
- **Query / Update all / Auto update** drive `pairing_station/show_registry.py` through a General Radio
  running general-radio-1.1.0 (`sessions/general_radio.py` routes `show_sent`/`show_frame` to `showedit.py`).
- Updates hold while the show controller reports a running show.
- A timecode-capable controller (mainshow-1.3.0, general-radio-1.1.0) is sent the published show's length
  once per publication. Older controllers are left alone and keep working.
- Back end: `showedit.py` (owned by the hub, section `showedit`) and `commands_show.py` (`show.*`).
  Tests: `tests/test_show_editor.py`, `web/tests/showengine.test.js`.

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
