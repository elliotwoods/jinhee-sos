# Zone boards: set-up & replacement

<span color="red">*This document was written by Kimchi and Chips*</span>

## Summary

A zone board is a tag reader board in a zone (Preshow, Desert, Pool, Mainshow entrance, Reset). Its firmware decides the zone, its identity (kind, point, name in the `zcfg` partition) says where it stands, and its zone database (`zdb` slots) says which tags are which cubes. The console identifies a board on USB without a reset, provisions it in one job (firmware + identity + published database, read back and verified after reboot) and can update the database alone. Not every ESP32 is a zone board: check the role before writing anything. Operator steps: {{page:H4}}.

## Facts

### Board roles

| Role | Firmware (version in tree) | Profile label in the form | Kind (`zone_type`) · points · name template | Zone flasher target | Notes |
|---|---|---|---|---|---|
| Preshow plate | `PreshowZone` (preshow-3.4.0) | Preshow plate (media points 1-4) | 1 · 1–4 · `Preshow {point}` | Yes | Points 1–4 = TouchDesigner cues ({{page:X04}}) |
| Preshow exit / safety plate | `TagPlateZone` (tagplate-2.4.0) | Preshow exit / safety plate | 1 · 1–8 · `Preshow Exit {point}` | Yes | Cube → Preshow colour |
| Mainshow entrance plate | `TagPlateZone` | Mainshow entrance plate | 4 · 1–8 · `Mainshow {point}` | Yes | Not the Mainshow controller firmware |
| Desert board | `DesertZone` (desert-2.4.0) | Desert plate (light panel) | 2 · 1–8 · `Desert {point}` | Yes | Drives its local lamp (MOSFET GPIO1) ({{page:X05}}) |
| Pool radio | `PoolZone` (pool-3.2.0) | Pool radio (slider) | 3 · 1–6 · `Pool Radio {point}` | Yes | Radio ID = point 1–6; calibration kept; form params "Slider mm at member 1" (default 383.0) and "at member 23" (43.0) ({{page:X06}}) |
| Reset plate | `ResetZone` (reset-1.0.0) | Reset plate (cube → idle) | 5 · 1–8 · `Reset {point}` | Yes | See Reset plate below |
| Pool central controller | `PoolCentral` | — | — | **No** | Matched set with the six pool radios; flash the central first |
| Preshow bridge | `PreshowBridge` (preshowbridge-1.0.0) | — | — | **No** | See the order note under Known issues |
| Mainshow controller | `MainshowController` (mainshow-1.3.0 in tree; #134 runs 1.2.0) | — | — | **No** | {{page:X07}} |
| Workstation | `Workstation` (workstation-1.0.0) | — | — | **No** | Role `excluded`; {{page:X08}} |
| Cube | Neocore cube firmware | — | — | **No** | {{page:X03}} |

- Zone flasher targets are only the six NctZone profiles (`zones/flasher/zone_build.py::PROFILES`). For the other roles the console opens their own panel and never proposes zone firmware.
- All NctZone boards: ESP32-C3 SuperMini, PN532 on SDA 4 / SCL 3. Exception: replacement preshow plates on ex-cube XIAO ESP32-C3 with the reader on D4/D5 = GPIO6/7 (preshow-3.4.0 tries 4/3, then 6/7; `NFC:` report line ends `pins=<sda>/<scl>`).
- RX gain choices: 18, 23, 33, 38, 43, 48 dB; firmware default 48.
- Name field: at most 15 characters.

### Identification

- Current firmware answers `?` with a report; the console identifies it **without a reset**: rail shows name, kind, point, firmware, database version; the Zone panel opens.
- No answer → **Unidentified board**, with **Probe again (no reset)**, **Read zone report** (opens the port and sends `?`), **Identify via bootloader** (ROM bootloader read of firmware and identity, then reboot).
- A USB serial number that matches an ESP32 identifies the chip only, never the role.

> [!WARNING] **Identify via bootloader** restarts the board. Maintenance only; never on a board serving visitors.

### Reset plate

- Tapping a cube returns it to **idle** (dim white 3,3,3): the plate sends `MSG_SET_ZONE` 0. It also stops a running main show on that cube and clears main-show eligibility. Use: park cubes collected from visitors (saves battery).
- Idle is the lowest state reachable from outside; nothing switches a cube fully off. A dark cube tapped rises to idle white.
- The plate's kind is `ZONE_RESET` (5) in `zcfg`, the registry and the web page; the value sent to the cube is 0 (`cubeZoneFor()` in `NctZoneProtocol.h`). 5 must never be sent to a cube.
- No local hardware on the plate.
- Registry on 2026-09-23: two boards run it, both named "Reset 1" (database v31 and v32), both ESP32-C3 SuperMini with reader and no external antenna. One of them is the ex-Preshow 3 SuperMini (first Reset board, commit `7191c5d`).

### Automatic intake (several boards)

**This computer › Automatic intake**:

| Control | Behaviour |
|---|---|
| **Auto-flash zones** | Flashes zone boards as they are plugged in. Identified zones updated in place, keeping identity and gain. Cubes and stations skipped. Off at every launch. Stopping lets the write in progress finish |
| Zone (legacy sketches) / Next point / Name | Identity given to older sketches without one |
| advance the point after each legacy flash | Increments the point |
| include unidentified boards (bootloader read only) | Writes unknown boards with the selected profile |
| database-only update for zones that are behind | Database only, no firmware |

### Database only, over USB

- **Update database over USB** (**Firmware & database** tab): writes only the published database into the board's `zdb` slot via esptool; firmware and identity untouched; the board reboots and reports the new version. Offered when the board's database is older than the publication; a current board is skipped (boards accept only a higher version).
- With Settings › Automatic updates › **Zone databases over USB** on (default) the console does this itself for a configured zone board that is behind, once per board and publication, without Auto-flash zones. Result on the tab's **Automatic database update** row.

### Cube monitor (Zone panel › **Monitor**)

- Shows tag UID, cube number and MAC, lookup result, radio delivery, reader health (**NFC scanning**, degraded, not responding). LED ring = colour the board commanded (confirm the real light by eye). **History** = recent taps.
- **Flash 5 s**, **Clear (idle white)**, Set zone 1–4, **Stop flashing**: real commands to the cube on this plate. Zone buttons are one-click hardware buttons with a warning tooltip. A real tap takes priority over test flashing.
- **Zone console**: raw serial lines; accepts `?`, `db`, `log`.

### Unknown-tag cards

| Attention card | Cause | Action |
|---|---|---|
| "Unknown tag on … is cube #… — the plate's database is behind" | Board holds an older database | **Update database over USB** / **Update database over the air** |
| "Unknown tag on … is cube #… — not yet in the published database" | Mapping only on this Mac | **Sync & publish**, then update the board |
| "Unknown tag on … is a pending registration for cube #…" | Cube never acknowledged the tag | **Send the saved mapping to cube #…** or **Retry the paused registration** |
| "Unknown tag on … belongs to a device without a number" | No number, so not published | **Assign a number**, then Sync |
| "Unknown tag on … is not in this computer's inventory" (info) | Registered elsewhere, or never | **Sync first (another computer may know it)**, then **Start registration at the pairing station** |

The "behind" card fires only from the plate's own `?` report; a stale report or a running Auto-update all masks it (`console/advisor.py` `tag.*`).

### Pre-flash cards

- "Local cube mappings differ from the published zone database" → **Sync & publish**.
- "… firmware: Firmware source changed since the last build" (`build.stale`) → **Rebuild** under **This computer › Firmware builds**.

## Procedures

### Provision one zone board

1. Keep **Auto-flash zones** off. **Sync**; clear the two pre-flash cards.
2. Plug in; confirm the role (Identify via bootloader only if it does not answer `?`). Another role → stop and use its own panel.
3. **Firmware & database** tab: profile, point, name, **RX gain** (prefilled from an existing identity). Use the real position (Preshow 1–4, Pool radio 1–6).
4. **Flash firmware + identity + database**. Job stages: build check, write, identity + published database, read-back, reboot, report check.
5. Require **Verified** (report after reboot matches the write).
6. **Monitor**: tap a registered cube; check role, point, reader health, database version, real tag read; then watch the real cube colour and downstream effect (lamp, frame light, media cue).

> [!WARNING] A normal zone flash does **not** back up the old firmware. Make an explicit technical backup first if the old image matters ({{page:X10}}).

### Replace one reader board

1. Record the old board: location, role, point, name, MAC, RX gain, database version (Zone panel header + **Firmware & database**). Pool radio: also radio ID and calibration (**Calibration** tab). Photograph the wiring.
2. Sync and check the build (as above).
3. Plug in the replacement; fill the form with the old values.
4. Flash; require **Verified**.
5. Test on **Monitor** with a real cube; watch the real effect.
6. Retire the old board from that role; update the board list.

### Several boards at once

1. Remove every other ESP32 from the bench.
2. Arm **Auto-flash zones**; set the legacy form and options.
3. Plug boards one after another; read **Last results**.
4. Switch it off when finished.

> [!WARNING] Remove every other ESP32 before arming **Auto-flash zones**. Looking like an ESP32 on USB is not proof of role.

### Success checks

| You see | Means | If not |
|---|---|---|
| Rail shows name, kind, point without reset | Current firmware, identity readable | **Identify via bootloader** (restarts it) |
| Job ends **Verified** | Report after reboot matches the write | Read the failed stage; {{page:X11}} |
| Database state **Current** | Board knows every published cube | **Update database over USB** |
| Monitor tap shows `#n`, reader **NFC scanning** | Reader and lookup work | Unknown-tag card; {{page:X11}} |
| Real cube colour and downstream effect | Whole zone works | {{page:X04}}, {{page:X05}}, {{page:X06}} |

### Repurposing hazards

> [!DANGER] **Force flash (overwrite)** is not a normal fix for a refused board. It is hold-to-confirm and flashes a board the inventory lists as a cube or an excluded device (reader, station, dongle). A cube loses its LED firmware and, after the write, its number, tag and pending tag are released. The published zone database may still hold the old mapping until you publish and update the zones again.

> [!WARNING] The installed pairing station (3C:0F:02:AD:83:24) and non-ESP32 USB devices are always refused, even with Force flash.

> [!WARNING] Pool central controller + six pool radios are a matched set: flash them together, central first (it still accepts the legacy 15-byte packet while radios are updated one by one). Preshow plates and bridge: both must be current for acknowledged cues.

## Known issues / open questions

| Issue | Evidence |
|---|---|
| Two Reset boards share the name "Reset 1" and hold v31/v32: give distinct names, bring both to the current database | Bench-verified (registry read, General Radio, 23 Sept, read only); name fix To confirm |
| Reset boards' antenna detail (no external antenna) | To confirm |
| Reset plate tap-to-idle not yet witnessed with a real cube in this documentation | To confirm |
| **Contradiction on preshow order:** `zones/README.md` says "Flash the bridge first"; `AGENTS.md` says plates and bridge update in either order (bridge accepts the old 2-byte packet; preshow-3.2.0+ plates send it until they hear a beacon). Both are compatible for current firmware; bridge-first is the conservative order | Code-checked |
| No zone board was flashed or updated over USB through the console while this handover was written | Procedures Code-checked; Monitor, unknown-tag cards and scripted flash Simulation-verified (`console/docscenes.py`, no esptool) |
| Pool radio IDs reported 1, 2, 3, 3, 4, 4 (duplicates): see {{page:X06}}, {{page:X13}} | Field-reported (`RELAY_BOARD_FINDINGS.md`) |

## Sources

- `zones/flasher/zone_detect.py`, `zone_flash.py` (`execute`, `update_database`), `zone_build.py` (`PROFILES`, `FIRMWARE_PREFIX`), `zone_monitor.py`
- `zones/tools/zonedb.py` (`RX_GAINS`, `ZONE_TYPES`), `zones/README.md` (zone firmwares, Reset, matched sets), `zones/firmware/*/*.ino` (`FIRMWARE_VERSION`)
- `console/sessions/zone_console.py`, `console/jobs/zone.py`, `console/intake.py`, `console/advisor.py` (`tag.*`, `build.stale`, `zone.*`), `console/uitext.py` (`zone.flash`, `zone.flash_force`, `zone.detect`), `console/web/panels/ZonePanel.js`, `others.js`
- `console/TEST_REPORT_2026-09-23.md` (zone registry census)
- Old draft `13-zone-boards.md`

<span color="red">*This document was written by Kimchi and Chips*</span>
