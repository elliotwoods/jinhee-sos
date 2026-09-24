# What the NCT Console does by itself: fact sheet

Read-only research against HEAD 63d82dc. Paths are relative to console/ unless stated otherwise.

**Evidence levels:** code / test / sim / bench.

**Hardware evidence exists only for:** USB identification, the Flash page, and show v6 reaching 6 cubes over the air (bench, database record). auto_sync, the zone walk, the web pull, auto_build and auto_firmware_usb are sim/test only; TEST_REPORT l.169-181 says the automatic updates were not run against real zones.

## Settings
- **Where:** Settings › Automatic updates card (web/panels/sections.js:49-57). Note on the card: "Saved on this computer; on by default."
- **Defaults** (hub.py:133-135):
  - On: auto_zone_db_radio, auto_zone_db_usb, auto_show, auto_pull, auto_sync, auto_build, auto_firmware_usb, and under Behaviour: auto_sessions, preview_flash.
  - Off: auto_register.
- **Storage:** saved in metadata console_settings. A key missing from the saved settings loads as on.
- **Off at every launch (not saved):**
  - Flash › "Flash cubes as they are plugged in".
  - This computer › Auto-flash zones.
  - The Automatic updates panel's Pause.
- **Screenshots:** the docs bench (simdocs.py:369) turns the switches off, so screenshots show them unticked.

## 1. Web inventory sync (auto_sync)
- **UI text:** "Sync the inventory with the web by itself: local changes upload a few seconds later, web changes download, new cube mappings publish (needs the web password)"
- **Triggers:**
  - The devices/roles tables are hashed every 2 s. A sync runs 5 s after the last change.
  - A 60 s web status check.
  - Syncs deferred while the console was busy run once it is idle.
- **What runs:** the same full sync as the button: upload, download, and a zone DB publish if the mappings changed.
- **Limits:**
  - At least 15 s between syncs; never two at once.
  - Needs the password.
  - Never runs under --simulate.
- **Failures:**
  - Offline: backs off 60 s, doubling up to 10 min.
  - Lock held elsewhere: retries after 15 s.
  - Interrupted after the upload: retries once.
  - Password rejected: the password is forgotten and auto sync stops until someone signs in.
- **What the operator sees:**
  - A top-bar chip: ✓ Synced / ⟳ Sync in 5 s / Sync · retry in 2 min / Sync · offline / ⟳ Sync · sign in. Clicking it syncs now.
  - Inventory › Web sync shows an "Automatic" row.
  - Successful automatic syncs are hidden from Jobs.
  - The sync.publish_pending and sync.waiting cards are hidden while auto sync is healthy.
- **Related: web-allocated cube numbers** (hub.py:462-501, regflow.py:231-238).
  - Every 2 s, a brand-new unnumbered cube that is not excluded gets the next free number from the web. The web skips numbers used locally and the reserved 2/22/39/43.
  - This needs the password. A failure retries every 60 s, and the cube shows **Needs number** meanwhile.
- **Evidence:** test_auto_update.py l.157-205 and 227-255. Sim only.

## 2. Zone databases over the air (auto_zone_db_radio)
- **UI text:** "Zone databases over the air: every zone relay walks the zone database to the out-of-date zones its radio hears, one radio at a time". The same switch appears in the Workstation panel's Zone relay section as "auto-update all (walk the space)".
- **How it runs:**
  - Every 1 s it enables the walk on each relay-capable Workstation, with a 3 s query refresh.
  - A zone is a candidate when it is behind the published version, in range, and was heard by this radio within 20 s.
  - One broadcast run gives up after 45 s. Zones that did not confirm are retried after 30 s.
- **Limits:**
  - Only one radio publishes at a time.
  - A zone that is ahead ("Newer / differs") is never overwritten, and boards accept only a higher version.
  - During pairing it slows down (0.3 s between frames).
  - **It is NOT held while a show runs** (only the show updater is).
  - If publishing is impossible, it logs "Auto update all could not start: …" once and waits 30 s.
- **What the operator sees:**
  - The panel reads "Zone databases v{n}: X current · Y behind · Z updating", plus "{n} more behind, out of range: updated when a radio next hears them".
  - When the setting is off: "Over-the-air zone updates are off (Settings › Automatic updates)".
- **Evidence:** test_auto_update.py:42-83. Sim only; the bench step 8 update was not performed.

## 3. Zone databases over USB (auto_zone_db_usb)
- **UI text:** "Zone databases over USB: database-only update for any configured zone board plugged in that is behind"
- **How it runs:** a configured, identified NctZone board that is behind gets a database-only update; firmware and identity are untouched. It is tried once per publication (version + CRC), and a replug retries.
- **Limits:** works without the intake armed; never runs during a hardware job.
- **What the operator sees:** the log line "Automatic zone database update over USB on {port}: vA → vB".
- **Evidence:** test_auto_update.py:90-110. Sim only.

## 4. Main show over the air (auto_show)
- **UI text:** "Main show over the air: cubes in range on an older show are updated (a Workstation or General Radio; never mid-show)". The Show editor shows it as "Auto update".
- **How it runs:**
  - Walks cubes that are behind and in range, with the same 45 s give-up and 30 s wait.
  - Uses the relay that heard the most behind cubes. When there is nothing to send, relays take 10 s turns querying.
  - Needs a Workstation or general-radio ≥1.1.0, and cubes on v1.5.0+.
- **Limits:**
  - Cubes accept only a higher version, and a cube that is ahead is left alone.
  - It holds while a show runs.
  - Caveat: the console only knows a show is running when it was started through a Mainshow controller or Workstation connected to this console. That includes BOOT-button and trigger-input starts reported over USB. The cube's own never-commit-mid-show rule is the backstop.
- **Also automatic:** after a publish, and when a show_config-capable controller connects, the controller is sent the show length, version and CRC.
- **What the operator sees:** "Main show v{n}: X current · Y behind", and "Auto update: sending show vN to k cube(s)".
- **Evidence:** test_auto_update.py:83. Bench: v6 reached 6 cubes.

## 5. Web pulls (auto_pull)
- **UI text:** "Pull a newer zone database and show from the web (needs the web password)"
- **Zone DB:** pulled when the 60 s status check sees a newer version. Each web version is tried once per run.
- **Show:** checked every 300 s, only while a show relay is connected and auto_show is on.
- **Logging:** each new result or distinct error is logged once.
- **Evidence:** test only.

## 6. Automatic firmware builds (auto_build)
- **UI text:** "Build firmware when its source changes (cube, zone plates, Workstation, Mainshow controller), one build at a time, before anything is flashed from it"
- **How it runs:**
  - Never uploads.
  - The build state refreshes every 60 s. One build at a time, and a build that a waiting board needs goes first.
  - No build starts during a hardware job or while paused.
- **Failures:**
  - A failed build is not retried until its source changes, or until **Retry**.
  - Missing tools show **no build tools**: "Install Arduino IDE or arduino-cli with ESP32 core 3.3.11 to build firmware".
- **Attention card:** build.stale appears only on a failure, missing tools, or the setting off.
- **Evidence:** test_autoupgrade.py:144-229. Sim only.

## 7. Automatic firmware upgrades of plugged-in boards (auto_firmware_usb)
- **UI text:** "Upgrade the firmware of USB boards that are out of date: zone plates keep their identity, a pairing station or General Radio becomes a Workstation, cubes only while Register and Flash are off. Never while you are using the board; pool radios, the pool central and the preshow bridge are only listed"
- **What it upgrades:**
  - **Zone plates:** keep their profile, point, name, params and RX gain from their own report. Needs a configured board and a published DB.
  - **Legacy pairing station or General Radio:** becomes workstation-1.0.0. An older Workstation or Mainshow controller is also upgraded.
  - **Cubes:** only with a verified FW: report and not excluded, through the Flash pipeline (firmware + published show).
- **Listed only ("by hand"):** pool radios (matched set), the pool central, the preshow bridge, unconfigured zones.
- **Never:** the protected station 3C:0F:02:AD:83:24.
- **Held back when:**
  - The console is busy or a hardware job is running.
  - (Cubes) Register is on, or Flash is armed.
  - The board was identified less than 20 s ago ("Starts in N s").
  - The operator sent the board a command in the last 60 s.
  - The board is relaying or sending the show.
  - (Workstation / Mainshow) a show is running.
- **Retries:** one automatic job at a time, one try per plug-in and target version. **Skip** holds until a replug; **Retry** clears a failure.
- ⚠ **Finding:** firmware can be DOWNGRADED. It flashes when the version *differs* from this computer's source, not only when older (autoupgrade.py:181,225; dongle.current uses equality, zones/dbmanager/dongle.py:144-146). "Never downgrades" is true for databases and shows, not for firmware.
- ⚠ **Finding:** any unprotected nct-pairing-* board (e.g. a replacement station) is converted to a Workstation automatically.
- **Evidence:** test_autoupgrade.py:65-139. Sim only; no hardware flash.

## 8. The Automatic updates panel
- **Where:** top of the right sidebar, above Attention.
- **Header:** Pause/Resume, and a summary: Paused, Working or Off.
- **When nothing is pending:** "✓ Everything up to date", plus anything still needing a person: boards out of range, and "{n} heard over the air in the last day with older firmware: plug in over USB to upgrade".
- **Otherwise:** a row per build or board, with a pill: queued, building, upgrading, waiting, checking, needs build, skipped, paused, off, failed, by hand, no build tools.
- **Row buttons:** Skip and Retry.
- **History:** "Recent (n)" lists the last 8 jobs. Automatic jobs appear in Jobs only when they fail.

## 9. Register page intake (auto_register)
- **Switch:** Register › "Register cubes as they are plugged in". Off by default; saved once on.
- **Per cube:** USB identify and pin → a number (from the web, or the lowest free above 32 without a password) → NFC scan on the station → one Sync.
- **Limits:** never retries a registration by itself (Retry or Restart does).
- **Evidence:** sim only.

## 10. Flash page auto flash
- **Switch:** Flash › "Flash cubes as they are plugged in". Off at every launch.
- **Per cube:**
  - Each new candidate port is taken once, after probing.
  - Firmware: NVS is backed up and verified. Skipped when this MAC already completed this build.
  - Show: written to NVS only if the cube's show is older, missing or damaged. A newer show is kept.
- **Limits:** USB only; boards that are not cubes are skipped. A failure waits for Retry or the next cube.
- **Evidence:** bench, 5 cubes and #17.

## 11. USB identification on plug-in (always on)
- **How it probes:** one new free port at a time, with no reset: listen → ? → hello → STATUS. It never arms or moves anything. The protected station and ports held by other apps are skipped; a held port is retried every 5 s.
- **For a cube it:**
  - pins the cube;
  - stops a pairing operation if a different cube is pinned;
  - checks the firmware;
  - reserves or creates the inventory row, which auto-syncs;
  - records a sighting;
  - starts the Register flow if Register is on.
- **auto_sessions** (Settings › Behaviour › "Open a live session automatically for every identified board", default on): opens a live session for each board.
- **preview_flash** (default on): flashes the selected cube for 1 s via the station.
- **Evidence:** bench.

## 12. Advisor suggestion cards
- They never act: "Nothing here ever runs one". Every action is an operator button; destructive ones need hold-to-confirm.
- Dismissals are saved every 30 s.
- While automatic work is on, the wording changes:
  - dongle.old and cube.fw_different say "will be upgraded automatically".
  - zone.fw_behind asks you to plug the board in over USB.
  - Sync cards say "It retries by itself; Sync now to try at once."

## Doc discrepancies
1. X08 and the INBOX entry "web-allocated cube numbers" (HOLD / NOT YET SHIPPED) still describe local numbering. The code is committed (6b26cdf; hub.claim_numbers, regflow.py:231) and web/src/app/api/inventory/claim/route.ts exists. Deployment is unverified.
2. The docs never mention that the firmware auto-upgrade can downgrade, or that zone DB walks continue during a running show.
3. H4 l.25 says to "click Sync on its red card". It is still valid as a manual fix, but sync is now automatic.

## Suggested plain-language grouping
- **Always automatic:**
  - recognising USB boards and pinning cubes;
  - live sessions;
  - Attention cards (suggestions only);
  - telling the show controller the show length.
- **Automatic unless switched off (on by default, remembered):**
  - web inventory sync, and new cube numbers from the web;
  - zone databases by radio and by USB;
  - the main show by radio;
  - pulling the newest database and show;
  - building firmware;
  - upgrading plugged-in boards' firmware.
  - For a temporary stop, use Pause in the Automatic updates panel.
- **Only when switched on:**
  - Register intake (remembered once on);
  - Flash auto flash and Auto-flash zones (off at every launch).
- **Never automatic:**
  - pool radio, pool central and preshow bridge firmware;
  - the protected pairing station;
  - overwriting a board that is ahead;
  - starting a show;
  - unconfigured zones;
  - retrying a failed registration.
