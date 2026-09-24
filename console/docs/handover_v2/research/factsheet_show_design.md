# Show design — operator fact sheet (NCT Console)

This fact sheet comes from reading the code, with no edits made. Evidence levels:
- **code:** read in the source only.
- **test:** simulation or unit tests.
- **bench:** real hardware. The evidence is the serial output or console records; nobody watched the LEDs.

Paths are relative to the repo.

## 1. Starting a session

- **Where it is.** Top bar tab **Show editor**, shortcut ⌘6 / Ctrl+6, route `#/showedit` (code: `console/web/components/TopBar.js:32`, `console/web/app.js:67`).
  - Page title: **Show editor**.
  - Subtitle: "The main show the cubes play (cube firmware v1.5.0+). Edit, publish a version, then update the cubes over the radio." (`ShowEditor.js:841`)
- **Hardware needed.**
  - None for editing, previewing or publishing. Publishing needs the web password.
  - Updating cubes, Query and Auto update need a show relay on USB: a Workstation, or a General Radio on general-radio-1.1.0 or later that announces `show` in its hello (code: `showedit.py:103-106`, `commands_show.py:47`).
  - Without a relay the Cubes card shows the banner **No show relay connected**: "Updating cube shows needs a Workstation (or General Radio general-radio-1.1.0+). Publishing to the web works without one." (`ShowEditor.js:413`)
  - Live mirroring needs a Workstation or general-radio-1.2.0 or later (`ShowEditor.js:567,587,590`; `showedit.py:30`).
  - Bench status: relay #138 runs general-radio-1.2.0. workstation-1.0.0 is built but not yet on any board (bench: TEST_REPORT "Workstation firmware merge").
- **Working copy and published show.**
  - The working copy lives on this computer only, in metadata `show_draft` in `devices.sqlite3` (code: `showedit.py:3-5,26,74-80`).
  - Edits autosave 1.2 s after the last change (`ShowEditor.js:655-665`).
  - On first load the working copy comes from the saved draft if there is one. Otherwise it comes from the published show (web cache), and failing that from the compiled-in default `shows/mainshow.json` (`showedit.py:61-72`).
- **Header chips** (`ShowEditor.js:822-825`):
  - Save state: **unsaved edits** (warning) or **saved on this computer** (ok).
  - Publish state: **same as published v{N}** (ok), **differs from published v{N}**, or **not published yet**.
  - A note line: "{n} cues · length · started from {origin} · image {bytes} B {crc}". It adds "(the compiled-in default)" when the CRC matches the default.
- **Header buttons** (`ShowEditor.js:836-839`):
  - **↺ Revert to v{N}**, or **↺ Revert to default** when nothing is published.
    - Takes one click, and Undo brings the edits back.
    - Disabled when the working copy already equals the published show and has no edits.
    - Toasts: "Reverted to published v{N} (Undo brings your edits back)", "Already the same as the last version".
  - **Publish**.
  - **Pull** ("Fetch the published show from the web").
- **Working copy card** (`ShowEditor.js:892-899`):
  - **Revert to published**: hold to confirm. "Discards this computer's edits."
  - **Start from the default**: hold to confirm. "The compiled-in v1.4.1 show. Discards this computer's edits."
  - **Export JSON**: downloads `mainshow.json`.
  - **Import JSON…**: opens a paste box, then **Replace the working copy**.
- **Validation.**
  - An invalid show gets the red banner **The cubes would refuse this show**, with the reason from `showfile.validate`, and Publish is disabled (`ShowEditor.js:842,838`).
  - Limits: 1–128 cues; length from 1 ms to 1 h; levels 0–100; at most 3 colours per cue (`pairing_station/showfile.py:20-23,90-93`).

## 2. Editing model

- **Cues.** A show is a list of cues, each with a start time and a type.
  - The first cue is always at 0:00 and cannot be deleted: "The first cue cannot be removed (the show starts with it)".
  - Each cue lasts until the next one starts. The last cue lasts until the show's **Length** (`ShowEditor.js:358,779`).
- **Cue types** (`showengine.js:5-13`, help text `ShowEditor.js:30-38`):
  - `off`: LEDs off.
  - `solid`: one steady colour.
  - `fade`: fades from **From** to **To** over the **Fade time**, then holds To.
  - `blink`: shows the **On** colour for the **On time** of every **Period**, then the **Off** colour.
  - `pulse`: goes from **From** up to **To** over the **Up time** and back over the **Down time**, then holds From.
  - `cycle`: crossfades through 1–3 colours in a loop, one step per **Step time**. Colours are added and removed with **+ colour / − colour**.
  - `random`: a random walk of brightness. Settings: **Level min**, **Level max**, **Shortest step**, **Longest step**, **Start level**. Every cube moves differently.
- **Colours.**
  - Colours are R/G/B levels 0–100. The cube caps its LEDs at 100, so 100 is full brightness.
  - There is also a colour picker (`ShowEditor.js:339-345`).
  - Changing a cue's type remembers its previous settings under the other type for the rest of the session.
- **Fanning** (cube v1.6.0+; `ShowEditor.js:383-401`, `showengine.js:16-26`).
  - Available on fade, blink, pulse and cycle only. It shifts the cue for each cube by its registered number.
  - **Fan** options:
    - **none: every cube together**.
    - **sequential: step × position in a group**. Settings: **Step** (ms per cube) and **Group of** (cubes, then it repeats). Offset = ((number−1) mod group) × step.
    - **scatter: fixed random spread**. Setting: **Spread** (ms). Each cube gets a fixed offset between 0 and the spread.
  - A cube with no number gets no offset.
  - On-screen warning: "Needs cube firmware v1.6.0; an older cube refuses the whole show and keeps its current one."
- **Timeline** (`ShowEditor.js:271-336,882`; showtimeline.js `SNAP_MS=10`, `RATES=[0.25,0.5,1,2]`).
  - Overview strip:
    - Drag the window's edges to zoom and the window itself to scroll.
    - Double-click to fit.
    - Ctrl/⌘ + wheel over the timeline also zooms.
  - The ruler and the colour band (16 rows, previewed cubes first): click or drag either to scrub.
  - Cue lane:
    - Click a block to select it and drag it to move it.
    - Dragging a block's left edge moves only its start, in 10 ms steps.
    - Double-click to add a cue there.
- **Transport** (`ShowEditor.js:846-871`).
  - Icon buttons:
    - "Stop and return to 0:00 (Home)".
    - "Previous cue start (again within 0.25 s: the one before)".
    - "Play (Space)" / "Pause (Space)".
    - "Next cue start".
  - Speed buttons: **0.25× / 0.5× / 1× / 2×**.
  - **Loop**: "off: stop at the end", "the selected cue", or "the whole show".
  - A go-to field ("go to m:ss", Enter). A bad entry gives the toast "Time is m:ss.mmm".
  - Add a cue at the playhead (it copies the cue it splits). Delete the selected cue (Delete).
  - Undo (⌘Z / Ctrl+Z) and Redo (⇧⌘Z / Ctrl+Y) go up to 100 steps. Fit shows the whole show.
- **Keys** (ignored while typing in a field; `ShowEditor.js:745-768`):
  - Space: play or pause.
  - ← / →: ±0.1 s. With ⇧: ±1 s.
  - Home / End: start or end of the show.
  - Delete / Backspace: remove the selected cue.
- **Preview.**
  - The **Preview** card ("at the playhead") shows one LED ring per previewed cube number.
  - It is cube-exact: the C++, Python and JS renderers are cross-checked by shared vectors (code/test: `showengine.js:1-3`).
  - The **Preview cubes** field (e.g. `1-8, 12`) has quick buttons **One / 1-8 / 1-24** and is remembered.
  - **＋ Plugged-in** adds cubes as they are plugged in over USB. They need an inventory number (test only).
- **Show length.** Set in **Show › Length** (m:ss.mmm). Note: "At the end the cube turns off and leaves mainshow-ready, as before." (`ShowEditor.js:885-886`)
- **Reference video** (`ShowEditor.js:497-548`).
  - Add one by dragging a video onto the player, or with **Choose file…**. It plays in step with the timeline and is never uploaded.
  - **Offset** (ms, remembered per file name), **Mute**, **Larger**, **Replace…**, ✕.

## 3. Live preview on real cubes

- **Button:** **Send to real cubes {numbers}** (primary). While it runs the page shows "● Live on {numbers}" and **■ Stop sending** (code: `ShowEditor.js:580-583`).
- **What it sends:** `SHOW_LIVE` (0x55) as a broadcast every 60 ms (about 16 Hz), with a 600 ms lease and at most 48 cubes per frame (`ShowEditor.js:551`, `showfile.py:41`).
- **Which cubes follow:** cubes on v1.7.0-USB.1 or later that are registered, are not playing, and have a previewed number. They follow the playhead during play, scrub and pause.
- **Stopping:**
  - After you stop, each cube restores its previous state 0.6 s after the last colour it received.
  - Other numbers ignore the frames, and so does a cube that is playing the real show.
  - SET_ZONE, REGISTER, SHOW_START or a timecode join ends live mode at once.
  - Live mode never changes the stored zone (X07).
- **Mirroring pauses** with a warning (`showedit.py:221-225`):
  - "A show update is being sent; mirroring resumes when it finishes".
  - "A show is running on the controller; mirroring resumes when it ends".
- **Errors:**
  - "The radio refused live colours ({error})".
  - "{firmware} cannot relay live colours: flash the Workstation firmware (or general-radio-1.2.0+)."
  - Toast: "Mirroring stopped: {error}".
- **Firmware floor:**
  - v1.5.0: show as data, and joining from timecode.
  - v1.6.0: fanning.
  - v1.7.0: live preview.
  - A cube on v1.4.1-USB.2 drops every show frame and plays the built-in show. It still starts on MSG_SHOW_START.
- **Bench, #17 on v1.7.0-USB.1** (TEST_REPORT:160-162):
  - Live mode was entered and the lease ended it.
  - Frames for other numbers were ignored, and the radio refused a unicast live frame.
  - A running show ignored the live frames.
  - Mirroring worked through the real console's `show.live`.

## 4. Publishing

- **What Publish does** (code: `show_publish.py:30-48`, `jobs/show.py:38-58`):
  - It saves the working copy, then runs the `show.publish` job.
  - The web allocates the next version number, which only ever goes up. The console sends the highest version any cube has reported (`show_cubes`) so that the web numbers above it.
  - It does not touch the cubes. Tooltip: "Publish this show on the web as the next version (cubes are not touched)".
  - Success line: "Show v{N} published". Identical content keeps its version: "Unchanged: show v{N} is already published".
- **Without the web password:** "Enter the web inventory password first (Sync › sign in)". Versions are never numbered locally.
- **Offline:** once pulled, the published show is cached in the device DB, so updating cubes works offline.
- **Pull:**
  - Results: "Pulled show v{N}", "Show v{N} is already here", or "No show published on the web yet" (`jobs/show.py:18-30`).
  - An automatic pull runs when auto-pull and auto-show are on, the password is known, and a relay is connected (`hub.py:504-511`).

## 5. Updating cubes

**Over the air: the Cubes card** (`ShowEditor.js:405-445`, `commands_show.py`, `show_registry.py`)
- **Buttons:**
  - **Query cubes**: broadcasts SHOW_QUERY. Every v1.5.0+ cube in range answers within 2 s.
  - **Update all to v{N}**: broadcasts until every cube heard in the last 15 min confirms. Cubes that come into range during the send join it.
  - **Auto update on** / **Auto update off**: walk-around mode.
  - **Update selected ({n})**: tick cubes first. The header checkbox ticks every "behind" cube. Other older cubes in range also take the show.
  - A per-row **Update** button, on "behind" rows only; it never forces.
  - **Stop sending**, shown only while sending.
  - **Send length to controller**.
- **Summary lines:**
  - **Published**: "v{N} · crc · {n} bytes · publisher".
  - **Cubes**: counts per state.
  - **Auto update**: on/off, "(saved; Settings › Automatic updates)".
- **Table columns:** #, MAC, Firmware, Show (e.g. "v6 nvs"; v0 = compiled-in), State, Staging ("v{N} x/y · waits for show end"), Signal, Seen.
- **State values:**
  - `current`: has the published version and CRC.
  - `updating`: receiving it.
  - `pending`: received; commits when its show ends.
  - `behind`: holds an older version.
  - `ahead`: holds a newer version than the published one.
  - `unpublished`: nothing is published yet.
- **Progress line:** "{done}/{total} confirmed · cycle {c} · {s} s".
- **Rules:**
  - A cube accepts only a higher version. FORCE (rollback) is unicast only, and the console UI does not offer it.
  - A cube never commits a new show while its show runs.
  - The console holds all sends while the Mainshow controller reports a running show: banner **A show is running**, and "Show v{N}: waiting, a show is running".
  - Timeouts: 180 s for Update all, 45 s for one cube or a walk-around run. A walk-around cube that timed out is retried after 30 s.
  - A disconnected radio stops the send: "Show update paused: radio disconnected".
- **auto_show setting:**
  - It is in **Settings › Automatic updates**: "Main show over the air: cubes in range on an older show are updated (a Workstation or General Radio; never mid-show)".
  - It is on by default and saved (`hub.py:134`, `sections.js:52`). It also enables the automatic web pull.
  - The button's hazard warning reads "Keeps transmitting while on; switch it off when you are done."

**Over USB: the Flash page** (⌘2)
- Every plugged-in cube gets the firmware and the published show. The switch is off at every launch.
- Result lines (`FlashSection.js:37-41`):
  - "Show v{N} was already on the cube".
  - "Show v{N} written to NVS, read back, and reported by the cube".
  - "The cube holds show v{N}, newer than the published one; kept".
  - "Firmware too old to hold a show; the built-in show is kept".
  - "No published show on this computer; the built-in show is kept".

**Over USB: the cube panel**
- **Update show over USB** (`CubePanel.js:124-126`, `uitext.py:142-144`):
  - It rewrites NVS, keeps every other value, reads the show back, restarts the cube and checks that the cube reports it. The firmware is untouched.
  - It needs v1.5.0+ and a published show. The previous contents are kept in the run folder.
- The panel's **Main show** row reads "v{N} from NVS (crc …)", "the built-in show (compiled into the firmware)", or "not reported (…before v1.5.0…)".

**How to confirm**
- The row reads `current`, or the timeline says "Show v{N} confirmed on {n} cube(s)".
- This comes from the cube's own SHOW_STATUS reply. It is not a visual LED check.

## 6. Mainshow controller: length and test trigger

- **Send length to controller** (code: `showedit.py:162-200`):
  - Sends `show_config` (length, version, CRC) to a mainshow-1.3.0+ controller or a Workstation. The length bounds the show clock (SHOW_TIMECODE).
  - It is also sent automatically after a publish and whenever such a controller connects.
  - Errors: "No Mainshow controller or Workstation connected"; "{firmware} has no show timecode; it still starts the show, but reflash it to send timecode".
- **The installed controller:** #134 runs mainshow-1.2.0, which has no show clock and no late join. Its default length is 298 000 ms (≈4:58).
- **Test trigger: Show control (⌘5)** (`ShowSection.js:55-62`):
  - **Cube #**, then **① Mainshow ready**: SET_ZONE 4, and the cube turns neon.
  - **② Trigger mainshow**: a fresh showId sent ×5, to one cube.
  - **② Trigger all ready cubes**: hold to confirm. "Broadcast, no acknowledgment; cannot be undone."
  - **Stop → idle**: SET_ZONE 0.
  - **Show clock** shows the expected position only; the cubes report nothing about the show.
- **Evidence:**
  - Test only for the console path (fake controller).
  - Bench: #17 on v1.5.0 started with the old SET_ZONE 4 + SHOW_START.
  - Bench: #138 temporarily on mainshow-1.3.0. A cube that missed the start joined from timecode at T = 3132 ms (TEST_REPORT:156-164).

## 7. Success and common errors

**What success looks like**
- The chips read **saved on this computer** and **same as published v{N}**.
- Every cube in range reads `current` in the Cubes card.
- The Automatic updates sidebar reads "Main show v{N}: {x} current · 0 behind".
- A cube played by eye plays the change.

**Bench record, 23 Sep**
- Show v6 was published at 04:52 KST.
- By 04:59 six v1.7.0-USB.1 cubes reported v6 over the air: #17, #33, #39, #52, #58, #95.
- Earlier USB runs on those six (04:39 and 04:47–49) wrote v5 with read-back.
- The rest of the fleet is on v1.4.1-USB.2.
- Nobody has watched v6 play in the room.

**Errors an operator may see** (code)
- "The cubes would refuse this show" (validation), and "Fix the show before publishing".
- "Enter the web inventory password first (Sync › sign in)".
- "No show published yet; publish one from the Show editor".
- "Cached show is inconsistent; pull it again from the web".
- "Connect a Workstation (or General Radio general-radio-1.1.0 or later) to update cube shows", and the same wording "…to query cube shows".
- "Tick the cubes to update first".
- "Show v{N} timed out; not confirmed: {macs}", or "…no cubes answered".
- Per-cube reasons in the State tooltip (`showfile.py:43-44`): "update: out of memory", "update: CRC mismatch", "update: invalid show", "update: NVS write failed", "update: timed out", "update: bad announce".
- "Show command rejected by the radio: …".
- Editing toasts: "A cue already starts there; move the playhead", "The first cue already starts at 0:00", "No earlier version to revert to", "Drop a video file (mp4, mov, webm…)".
- Flash page: "Firmware too old to hold a show; the built-in show is kept".

## Inconsistencies for the docs owner

- The tooltip label for `show.live` in `uitext.py:195`, and the `showedit.py` docstring, say "Mirror on real cubes". The visible button says **Send to real cubes {numbers}**.
- The publish log at `jobs/show.py:57` says "Cubes take it from Update all (a General Radio)". It should also mention the Workstation.
- H4 §F says Auto update is on by default. This is consistent: `hub.py:134` sets auto_show=True, and the same setting also enables the automatic show pull.
- The live-preview relay floor is general-radio-**1.2.0**. The update and query floor is general-radio-**1.1.0**. Keep the two distinct.
