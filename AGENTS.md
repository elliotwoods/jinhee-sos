# Coding-agent guide

Read this file first. For a new workstation, follow [docs/SETUP.md](docs/SETUP.md).
Commands below run from the repository root. Paths contain spaces on the original
machine: quote paths and use subprocess argument arrays when writing tooling.

## What this repository controls

This is a physical art installation, with Python/Tk operator apps and several
ESP32 firmware families. Distinguish the roles before touching hardware:

| Component | Maintained code | Responsibility |
|---|---|---|
| Neocore LED cube | `flashing_station/firmware/neocore_usb/` | LED behavior, ESP-NOW registration, saved ID/NFC mapping, USB identity. From v1.5.0 the main show is data: compiled-in `DefaultShow.h` (generated from `shows/mainshow.json`) or a newer published show received over ESP-NOW and kept in NVS namespace `show`; joins a running show from `SHOW_TIMECODE` |
| NFC pairing station | `pairing_station/firmware/pairing_station/` | PN532 scanning, selected-cube identification, registration relay, zone database distribution |
| NCT Console | `console/` | All of the tools below in one pywebview window: owner-thread hub, USB identification without resets, per-role sessions, jobs, advisor suggestion cards, vendored Preact front end. Holds every old app's instance lock while running |
| Pairing GUI | `pairing_station/app.py` | Inventory, number assignment, NFC registration, USB pinning, zone controls |
| Cube USB flasher | `flashing_station/app.py` | Identity checks, builds/uploads, NVS preservation, flash receipts |
| Zone firmwares | `zones/firmware/{PreshowZone,TagPlateZone,DesertZone,PoolZone,ResetZone}/` | NFC-driven show zones; PoolZone also has slider calibration; ResetZone returns a cube to idle (`SET_ZONE 0`) at the end of the show |
| Shared zone library | `zones/firmware/libraries/NctZone/src/` | Wire protocol, flash database, update transport, tag-plate behavior |
| Main show library | `zones/firmware/libraries/NctShow/src/`, `pairing_station/showfile.py`, `console/web/lib/showengine.js`, `shows/mainshow.json` | Show image format and renderer (C++, Python and JS kept identical, cross-checked by vectors), show update/timecode frames (`NctShowProtocol.h`). Header-only and separate from NctZone on purpose: zone manifests hash `NctZone/src` |
| Pool central controller | `zones/firmware/PoolCentral/` | Receives `PoolState` from the six pool radios, OR arbitration with per-radio leases, verified PCA9685 output. Not a zone board |
| Mainshow controller | `zones/firmware/MainshowController/`, `zones/mainshow/app.py` | Makes a cube mainshow-ready (`SET_ZONE 4`) and triggers the main show (`MSG_SHOW_START` = 8, fresh showId ×5) from the app, its BOOT button or a trigger input; from mainshow-1.3.0 also broadcasts `SHOW_TIMECODE` once a second while the show runs (length from `show_config`). Replaces the M5 Core2 show starter. Not a zone board |
| General radio | `zones/firmware/GeneralRadio/`, `zones/tools/general_radio.py` | One dongle for every ESP-NOW host function: the pairing-station relay protocol (cube discover/identify/register, zone frame relay) plus the Mainshow verbs (`set_zone` to one cube or spelled-out `broadcast`, `show_start`), one emulated pool radio (`pool`: one lamp at a time through PoolCentral) and an emulated preshow plate (`preshow`: a TouchDesigner cue through the bridge). Leased outputs; no reader. From general-radio-1.1.0 also the main-show relay (`show_send`/`show_frame`, used by the console Show editor) and the show timecode. Python client + bench CLI + `flash`. Not a zone board, not the Mainshow controller |
| Preshow media bridge | `zones/firmware/PreshowBridge/` | Receives `PreshowEvent` from the four preshow plates, acknowledges each one, writes `PRESHOW,<n>,ON|OFF` to the TouchDesigner Serial DAT. Not a zone board |
| Zone flasher | `zones/flasher/app.py` | Zone identification, configuration, firmware/database provisioning; automatic database-only updates over USB (esptool writes the `zdb` slots; identity and firmware untouched) |
| Show editor | `console/web/panels/ShowEditor.js`, `console/showedit.py`, `pairing_station/show_registry.py`, `show_publish.py`, `web/src/lib/show.ts` | Edit the main show as cues with a cube-exact preview, publish web-allocated show versions, update cubes over a General Radio (update all / auto walk-around), send the show length to the controller |
| Zone Database Manager | `zones/dbmanager/app.py` | Wireless zone discovery/version view, targeted, update-all and auto-update-all database updates over an ESP-NOW dongle (pairing-station firmware), dongle flashing, web publish/pull |
| Web inventory | `web/` (Next.js on Vercel), `inventory_web/app.py`, `scripts/web_sync.py` | Shared web copy of device records (one private Vercel Blob document, shared password), desktop sync app |
| Pool calibration | `zones/calibration/app.py` | Slider calibration, diagnostics, explicit output override, firmware update |
| Pool light diagnostics | `poolzone_test/` | USB bridge emulating all six pool radios on the current protocol, light-test GUI. The central test firmware moved to `zones/firmware/PoolCentral/` |
| ESP-NOW range test | `rangetest/` | Dual-role TX/RX link survey firmware, RSSI capture, survey GUI |
| Original registration utility | `registration_console/` | Screenless replay of original mappings; not the modern GUI station |
| Historical references | `live files/`, root `ForKimchi.ino`, `m5core2_controlloer.ino` | Existing installation behavior and protocol compatibility |

Do not assume every ESP32 is a cube. Readers, the media bridge, the pairing station,
the pool central controller and the Mainshow controller are separate roles. The TouchDesigner/media-server bridge
is maintained at `zones/firmware/PreshowBridge/`; `live files/Preshow_MediaServer_SerialDAT`
is the archived original it replaces. `m5core2_controlloer` was the old registration
console. Do not flash those boards with cube firmware.

## First actions in a coding task

1. Inspect the relevant source, README, tests, and current changes. Other tasks may
   be editing another component; preserve their work.
2. If working on a live app, read its status before changing anything. Determine
   whether registration, flashing, calibration, or a zone operation is active.
3. Identify the authoritative data and protocol involved. Do not infer ownership
   from USB port order or an old `/dev/cu.usbmodem...` path.
4. Implement and test with temporary databases/fake transports where possible.
5. Reload/restart an idle app and verify the actual controls/status after changes.
   Report separately what unit tests, firmware compilation, and hardware checks proved.

A successful compile is not a hardware test. A version response is not proof of
NFC scanning. Radio delivery is not an application acknowledgment. Registration
ACK is not independent verification of NVS persistence or visible LED behavior.

## Python architecture and threading

All apps use the shared `pairing_station/.venv`. The NCT Console (`console/`) reuses the pure
modules below unchanged; its `hub.py` owner thread plays the role of the Tk thread (SQLite, sessions,
controllers), `api.py`/`commands.py` are its only entry points, destructive commands need a
confirmation token (the UI's hold; hardware buttons run on one click with a warning tooltip), and `console/simulate.py` provides fake boards for headless tests (`console/tests`). Use its Python, not an unrelated
system interpreter. Python 3.14 with Tk is the tested Mac configuration.

**Host portability:** macOS is bench-tested; Windows is supported but nobody here can run it. Never
write `fcntl`, `/tmp`, `os.getuid`, `os.fchmod`, `/dev/cu.*` assumptions, `.venv/bin`, Arduino paths,
`'Menlo'` or `start_new_session` directly: use `pairing_station/hostos.py`, and give any new branch a
case in `pairing_station/tests/test_hostos.py` (it drives the Windows code through a fake `msvcrt`).
Always pass `encoding='utf-8'` to text I/O, plus `newline='\n'` for files committed to git (sources
and manifests are hashed as raw bytes; `.gitattributes` pins LF). A new app needs both `Launch.command`
and `Launch.bat`. `.github/workflows/tests.yml` runs the suites on `windows-latest`.

- `pairing_station/database.py`: SQLite schema, migrations, number reservations,
  NFC ownership, audit events, CSV/header export. Reuse these methods for writes.
- `controller.py`: pairing/flash state machine, current request IDs, ACK filtering,
  stop/preview handoff, pending registrations, feedback. Hardware-independent tests
  supply a fake transport and clock.
- `dashboard.py`: inventory projection, filtering, cards, button availability,
  selection lock, status/details. Keep presentation separate from registration logic.
- `transport.py`: serial worker with inbox/outbox and a no-reset open sequence.
- `usb_identify.py`: optional USB identification and reported-version checks; no upload.
- `port_lock.py`: advisory serial ownership shared with flashers, plus pyserial exclusivity.
- `http_api.py`: loopback control running Python on the Tk/SQLite owner thread.
- `inventory_sync.py`: public per-MAC JSON synchronization, validation, the conflict-free merge;
  also the shared three-way `merge`/`apply`/`validate` used by the web sync.
- `web_client.py`, `web_sync.py`, `web_status.py`: stdlib client for `web/`, web
  three-way sync (own baseline), and the background read-only status line the apps
  show. Status must never block, raise into, or write from a host app.
- `sightings.py`: per-cube "last seen" evidence for the web page (`sightings` table:
  latest per MAC and kind, plus `events`/`flash_runs`/`zones`). Hooks in the controller
  (radio discovery, throttled), `app.py` (USB identify) and `zone_registry.py` (zone tap
  logs) are best effort and must never affect pairing. Uploaded by Web Sync only;
  sightings are not inventory records and never enter the three-way merge.
- `sync_all.py`, `sync_widget.py`: the universal Sync (inventory both ways plus zone database publish/pull) and its Tk widget, used by every app on the device database. Apps holding an instance lock pass `held` and `can_apply`. The web password is stored in `data/web_password` (0600, gitignored) via `web_client`; never put it in git.
- `zone_registry.py`: zone discovery, classification and database distribution (used by the Zone
  Database Manager); `zone_publish.py`: web-allocated zone database versions. Zone database versions
  are universal and only increase: never allocate one locally. `web/src/lib/zonedb.ts` mirrors
  `zonedb.py` record validation; change them together.

Do not access Tk widgets or the SQLite connection from a worker thread. Workers
report through queues; the Tk poll callback consumes events. Do not block that
callback with long sleeps, subprocesses, or serial reads: heartbeat loss can stop
hardware operations. Use a worker for I/O and `root.after` for short scheduled work.

Preserve request-ID matching, fresh-tag gating, matching MAC/ID ACK checks, and
stop-before-switch behavior. A late reply must not register the newly selected cube.
USB identification must not reset the pairing station or silently switch an active
registration to a different MAC. USB pins remain after unplugging; explicit Unlock
or a newly identified cube replaces the pin. Filter/search must not hide that pin.

## Inventory invariants

`pairing_station/data/devices.sqlite3` is the local authoritative database. CSV is
an export, not an editable import. `inventory/devices/*.json` is the shared Git
inventory; see setup instructions for synchronization and the merge rules.
The web inventory (`web/`) stores the same records; `web/src/lib/records.ts` mirrors
`inventory_sync.validate`. Change record fields or validation in both together, or a
computer could be unable to apply what the server accepted.

- MAC identifies a physical device. Number and NFC ownership are mutable.
- `cube_id` may be NULL. Do not assume every discovered device has a number.
- `original_32.json` is historical reference, not authority to overwrite new pairings.
  Display its original number separately; it does not reserve a cleared current number.
- Default number suggestions use the lowest free ID above 32. The prompt preselects
  it and explains that Enter accepts. Manual label entry may use a lower number.
- `reserved_numbers` permanently excludes **2, 22, 39, 43** from automatic allocation,
  even without known MAC/NFC data. Explicit manual assignment remains allowed.
- Manual-number mode is stored in `metadata.auto_number`. Do not repopulate cleared
  IDs on discovery. Setup/inventory sync enables manual mode.
- `uid` is the committed tag; `pending_uid` is a proposed/retryable assignment.
  Do not report a pending or radio-delivered registration as acknowledged.
- An interactive NFC scan may take ownership of another device's committed or
  reserved tag. Transfer atomically, audit both devices, preserve unrelated tags,
  and leave a retryable pending mapping if the new device does not acknowledge.
  This does not erase the old cube's firmware remotely.
- Bulk saved-mapping transmission must not steal NFC ownership. In the sync merge a record
  whose `pending_uid` equals its `uid` has not changed its identity.
- Sync never asks for a decision and must stay that way: `inventory_sync.merge_records` is pure,
  always resolves, and gives the same answer on every computer (newest `updated_at` wins a
  device's number/tags whole; role merges separately, excluded > led > auto; absence or a
  role-only record never deletes; `reconcile` leaves a number or tag claimed twice with the
  newest claim and keeps the loser's own `updated_at`, never `now()`). Decisions are audited
  (`sync_resolved`, `sync_applied`) and the operator is told what a local device lost. Keep
  `tests/test_sync_convergence.py` passing (NCT_SYNC_SEEDS=300 for a longer run) when touching
  database writers, the merge, `web_sync.run` or the fake server.
- `inventory_sync.apply` writes only the planned MACs and refuses (`LocalChanged`) if SQLite
  changed since the plan; never reintroduce a blanket rewrite or `INSERT OR REPLACE` on devices.
- A previous pending mapping must not disable Register. Fresh registration retains
  it until a new scan is accepted. A disconnected station or genuinely active
  operation can disable Register; display the reason.
- `nfc_seen` events record local interactive scans. Discovery, USB identification,
  imported mappings, and bulk transmission are not NFC scans.

Keep reservations, UNIQUE constraints, transactions, event history, and atomic CSV
replacement intact. Cross-app writes exist: the cube flasher subclasses Database.
Database schema/allocator changes can therefore affect more than the pairing app.
Do not reset live data just to make a test pass. Back up before bulk data migrations.

## Hardware and protocol invariants

- Modern cubes, pairing station, and zones use ESP-NOW channel **2**. Check legacy
  sources individually; archived settings may differ.
- Five protocols share channel 2 and are **not** interchangeable: the cube `Packet`
  (legacy **24-byte** C struct ABI, alignment/padding and field offsets intentional,
  never to be packed without migrating both ends), zone management
  (`NctZoneProtocol.h`), the pool light link (`NctPoolProtocol.h`), the preshow
  media link (`NctPreshowProtocol.h`) and the main show link (`NctShow/src/NctShowProtocol.h`,
  types 0x50-0x54: show image announce/chunk/query/status and `SHOW_TIMECODE`). The preshow media bridge additionally claims
  every **2-byte** frame, which is the pre-2026 packet it still accepts.
- Main show: `MSG_SHOW_START` is unchanged and remains the only thing a cube needs; a controller
  without timecode (mainshow-1.2.0, general-radio-1.0.0) works exactly as before, and cubes before
  v1.5.0 drop every show frame (they only accept 24-byte frames). Show versions are web-allocated
  and only increase (a cube accepts only a higher version; FORCE is unicast-only); never allocate one
  locally. A cube never commits a new show while its show runs. `show_cubes` in the device database
  records what each cube reported (the next publish is numbered above it). Changing the show
  format means changing `NctShowEngine.h`, `showfile.py`, `showengine.js` and `web/src/lib/show.ts`
  together; `python pairing_station/showfile.py --header` regenerates `DefaultShow.h` and the JS
  vectors, and the firmware tests fail if either is stale. Changing `shows/mainshow.json` changes the
  compiled-in default (a cube firmware release), not the published show.
- Pool, preshow and show frames carry the `NZ` header but are deliberately **absent** from
  `NctZoneProtocol.h::frameType()`: `ZoneLink::receive()` queues everything that
  function accepts and `ZoneLink::handle()` drops what it does not know, so routing
  them there would swallow them. They reach the sketch through `TagPlate::onFrame`,
  which runs on the Wi-Fi task and may only hand the frame over.
- The pool radios and the pool central are a **matched set**; reflash them together.
- The preshow plates and the preshow bridge update in **either order**: the bridge accepts the
  old 2-byte packet, and a `preshow-3.2.0` or later plate also sends it until it has heard a beacon
  (then never again). A plate's `?` report says `MEDIA: mode=legacy` or `mode=modern`.
- `zones/preshow_test/` drives a plate's leased `HOST *` override to raise TouchDesigner cues
  by hand, for a plate with no reader attached.
  The central still accepts the legacy 15-byte packet so a partial rollout does not go
  dark, but that shim is insurance, not a supported configuration.
- Pairing station: ESP32-C3, PN532 I²C **SDA=4, SCL=3**; installed red PN532 board is
  powered from station **5V/GND**. Station and reader power-cycle together.
- Known original station MAC: **3C:0F:02:AD:83:24**. Keep flasher protections and
  excluded roles; record a replacement station's identity when moving hardware.
- Native ESP32 USB can expose a MAC in its serial descriptor. That identifies the
  chip, not proof of LED firmware. Firmware checking requires a matching `Cube MAC:`,
  `FW:` and ready response. Compare against the current local build manifest.
- A matching reported version is not a binary hash verification. Missing response
  means unverified, not current. Show a warning for differing/unverified versions.
- For PN532 failures, inspect real read/response evidence. Initialization success
  alone previously misled troubleshooting. The reference Arduino Wire sequence
  succeeded; see `pairing_station/I2C_DEBUG.md` before reviving abandoned changes.
- Preserve NVS and zone partitions. Use the existing flasher pipelines for uploads,
  backups, verification, receipts and reboot checks. Never substitute a full-chip
  erase or write a cube binary to whatever USB port appears first.

Hardware actions should stay within the user's requested operation and identified
target. Builds and unit tests do not upload. Light/show tests affect physical output;
run those deliberately and leave overrides/automatic flash intake disarmed afterward.

## Live app API for agents

Prefer the local API to fragile screen clicking. The app writes an owner-only curl
configuration at `pairing_station/data/api.curl` and normally listens on
`127.0.0.1:8765`. Use the actual launch port if customized. Do not print its token.

```sh
curl -sS --config pairing_station/data/api.curl http://127.0.0.1:8765/status
curl -sS --config pairing_station/data/api.curl \
  http://127.0.0.1:8765/execute -H 'Content-Type: application/json' \
  --data-binary '{"code":"(controller.connected, controller.reader_ok, controller.mode, controller.phase)"}'
```

Bindings include `app`, `controller`, `db`, `root`, and `zones`. Imports must be
explicit in this namespace. Results include stdout, stderr, the last expression,
and exceptions. A 202 response means poll `/jobs/<id>`; do not repeat a mutation
because it did not finish within the HTTP wait window. Python executes on the GUI
thread: schedule work rather than sleeping in `/execute`.

Read `app.recent_logs` for useful history; verbose `recent_events` is a bounded ring
and may be replaced quickly by I²C/discovery traffic. Check both `connected` and
`reader_ok`, not just a cached hello. The app can re-handshake when a logical
connection is lost while the USB handle remains open; this must not replay the
interrupted operation automatically.

Prefer an idle restart for class/widget changes. Hot reloading a class does not
replace callbacks already bound to old methods or create new instance fields/widgets.
If a live reload is necessary, explicitly initialize additions and rebind callbacks,
then verify the visible control's actual state. Avoid reopening a second app on the
same database: the instance/serial locks are intentional.

## Tests and builds

Use [docs/SETUP.md](docs/SETUP.md) for exact commands. Test at the layer changed:

- Python behavior: the relevant `unittest discover` suite.
- UI behavior: real Tk tests with an isolated DB and fake radio; require a desktop.
- Protocol/firmware behavior: host C++ simulator plus a real Arduino build.
- Hardware behavior: existing hardware scripts only after reading their effects.

There is no guarantee that a historically recorded test count is current. Run and
report the current suite. A GUI abort in a sandbox/headless process is different
from a test assertion failure; use a desktop-capable execution environment.

`python scripts/build_all_firmware.py --dry-run` lists fourteen maintained firmware
and diagnostic targets. Without `--dry-run`, it builds them, reuses existing cube/
zone manifest builders, reports failures, and exits nonzero if any fail. No uploads.
`live files` sketches are historical and are not all part of this build command.

Build manifests and hashes must agree with binaries and source. Update relevant
version strings/build recipes together when releasing changed firmware. Do not
hand-edit hashes to bypass stale-build checks. Only verified cube artifacts are
intentionally distributable through the repository's build-directory exceptions.

## Handoff and hygiene

Document changes, tests, and any unverified physical behavior. Keep the root README
as the operator entry point and component READMEs for subsystem detail. Older
append-only troubleshooting notes may describe superseded behavior; inspect current
code/tests before relying on them. Update conflicting instructions when relevant.

Never commit API tokens, private SQLite/WAL files, flash backups, Wi-Fi credentials,
virtualenvs, temporary logs, or generated private documents. MAC/NFC records in
`inventory/` are intentionally shared; don't publish additional private artifacts.
Do not commit/push or synchronize other people's inventory changes merely as a
side effect of editing code unless that is part of the requested task.
