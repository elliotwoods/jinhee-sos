# Coverage: old chapters 07–10 → X04–X07

Every `##` / `###` section (and `<details>` toggle) of the four source drafts, and where its content now lives. Korean prose was dropped (English-only pages). Screenshot placeholders and purpose callouts were not carried: they belong to the handbook (H2–H5). Old numeric page links were remapped to H and X keys.

## 07-preshow-touchdesigner.md → X04-preshow.md

| Source section | Destination |
|---|---|
| Purpose callout (Who / When / You need) | Not carried (handbook framing); the tools needed appear in X04 Procedures |
| At a glance (diagram, points 1–4, one point per board, registered cube only, 0.7 s OFF, point-clash card) | X04 Facts › Signal path; Behaviour; Timings (`TAG_LEAVE_TIMEOUT`) |
| Current status (Elliot 22 Sep: new antenna boards, robust signalling, TD settings, gain, reader position; LiPo vs USB battery; acceptance; Sunday one-point note) | X04 Known issues (repair history, battery, media routing, Sunday note) |
| Find the failing stage (6-stage table; links to troubleshooting §2/§4/§6; gain vs database; ack ≠ butterfly) | X04 Facts › Failing-stage table; Radio link › Rules (ack meaning) |
| Test a cue without a cube (warning) | X04 Facts › Cue test and temporary control (WARNING) |
| ### 1. Take temporary control | X04 Procedures › Cue test step 2 |
| ### 2. Raise a cue and read the answer | X04 Procedures › Cue test step 3–4; Cue test table (*acknowledged yes*) |
| ### 3. Hand control back (1.5 s self-release; Workstation **Preshow cue**; bridge **TEST n ON / n OFF**) | X04 Cue test table; Procedures step 5 |
| Connect the Preshow bridge to TouchDesigner (not a cube/zone board; steps 1–4; line table; change-only; unchanged format; port ownership WARNING; TD project not in repo) | X04 Facts › Firmware and boards; TouchDesigner contract; Procedures › Connect the bridge |
| What success looks like | X04 Failing-stage table (Healthy / If not columns) |
| Engineering detail › Radio link (beacon 500 ms, unicast, ack by bootId+seq incl. duplicates, 120 ms / 3 s retries, 1 s re-assert, swap needs no reflash; legacy 2-byte packet, preshow-3.2.0+, modes; Cue override 1.5 s lease renewed every 350 ms; bridge `TEST`/`STATUS`, `cue_drops`, `point_clashes`, `emitted_mask`, `desired_mask`) | X04 Radio link; Modes; Bridge serial console and STATUS fields; Cue test table |
| Sources and evidence | X04 Sources; evidence levels in Known issues |
| Related guides | Inline links ({{page:H4}}, {{page:H5}}, {{page:X09}}, {{page:X13}}, …) |

## 08-desert.md → X05-desert.md

| Source section | Destination |
|---|---|
| Purpose callout | Not carried (handbook framing) |
| At a glance (one board per position, panel by wire, cube by radio, check separately) | X05 Summary; Signal path |
| Normal behaviour (table) | X05 Behaviour |
| Current status (Hojun: gain, timing fix, eight sets; Jisung/Jimin carpentry; seven vs eight counts) | X05 Known issues |
| Two separate checks (Zone panel, Monitor, Attention) | X05 Procedures (intro steps) |
| ### Check A: the tag and the local light | X05 Procedures › Check A |
| ### Check B: the cube's colour (and Hojun's "mostly cube" guidance) | X05 Procedures › Check B; Known issues |
| Why the colour is sent more than once (one-message mailbox, 0.12/0.4 s, 3 s, cancel on move, Workstation **Set … →**) | X05 Timings; Colour repeat rationale |
| What success looks like (incl. RX gain pill) | X05 Procedures; Maintenance boundaries (RX gain card) |
| Maintenance boundaries (WARNING list) | X05 Procedures › Maintenance boundaries (WARNING) |
| Engineering detail (desert-2.4.0, GPIO1 MOSFET, TAG_STATE 1/0, 700 ms, 120/400/600 ms, 3 s) | X05 Behaviour; Timings; GPIO and wiring; Firmware |
| Sources and evidence (incl. Engineering Six PDF pp. 15–18, Sangeun 20 Sep) | X05 Sources; Known issues (evidence) |
| Related guides | Inline links |

## 09-pool-forest.md → X06-pool-forest.md

| Source section | Destination |
|---|---|
| Purpose callout | Not carried (handbook framing) |
| At a glance (six radios, central, PCA9685 ×2, relays, 23 frames) | X06 Summary; Signal path; Pool central controller |
| Normal behaviour (table; unknown tag starts the interaction) | X06 Behaviour |
| Current status (K&C repairs; relay replacement, COM–NO, terminals, mounting; all relays off with no cube; Hojun 23 Sep 4.2.2, 1–23 verified; relay power to check; physical-limit WARNING, PVC tape proposal) | X06 Known issues (repair history, relay power, physical limit); Relay-board findings |
| Calibrate a slider (23 ticks, control points, draft) + save WARNING | X06 Calibration internals; Procedures › Calibrate step 1 |
| ### 1. Open the Calibration tab | X06 Procedures › Calibrate step 2; Temporary-control table |
| ### 2. Set the two ends first | X06 Procedures step 3 |
| ### 3. Add points in between (10–1000 mm, ≥1 mm) | X06 Calibration internals; Procedures step 4 |
| ### 4. Send, then save (no frame while draft; saved=true; Reload saved; draft WARNING) | X06 Calibration internals; Procedures steps 5–6 + WARNING |
| ### 5. Check it | X06 Procedures step 7 |
| Guided recording (Stride 4, Hold 5, proposal, three apply options, Abort, `console/data/recordings/`, pool-2.8.0 card) | X06 Guided recording; Procedures › Guided recording |
| Temporary control of the lights (four WARNING tools, status bar) | X06 Temporary-control tools and hazards |
| Firmware and radio number (**Flash pool firmware**, **Update database over USB**, **Assign radio id**, matched set, clash cards) | X06 Procedures › Radio id and firmware; Matched-set rule; Pool radios (id clash) |
| Pool central controller diagnostics (table; Verified ≠ lit) | X06 Central diagnostics |
| What success looks like | X06 Procedures step 7; Central diagnostics; Temporary-control table (status bar) |
| Engineering detail (pool-3.2.0, VL53L4CD, One Euro, 500 ms beacon, heartbeats; OR, lease 600–2000/800, 400 ms hold, MAC slots, 15-byte legacy; I²C pins, 0x40/0x41, active low, `POOL_OUTPUT_FOR_MEMBER`, read-back, boot window; 40 MHz To confirm) | X06 Pool radios; Pool radio → central link; Pool central controller (all sub-parts); Known issues |
| Sources and evidence | X06 Sources; Known issues (evidence) |
| Related guides | Inline links |

## 10-mainshow-media-interface.md → X07-mainshow.md

| Source section | Destination |
|---|---|
| Purpose callout | Not carried (handbook framing) |
| At a glance (sequence diagram; show clock WARNING: #134 on 1.2.0, six cubes on v1.7.0) | X07 Sequence; Mainshow controller; Known issues |
| Current status (M5 wrong command; Elliot: 5 V adapted, one of ten failed; bench show clock on #138/#17, 3.1 s join; #138 back to radio; #134 update optional) | X07 Cube side (Old number); Mainshow controller (bench check); Known issues; Procedures › Replace step 6 |
| Normal show flow (4 steps, ≈4:58, start aligns only, no timecode following, no report back) | X07 Sequence; Cube side (End, Sync model, Feedback) |
| Test the show on one cube | X07 Procedures › One-cube maintenance test |
| ### 1. Open the Show section (controller or Workstation fallback, **Cube #**) | X07 Console Show section; Procedures step 1–2 |
| ### 2. Make the cube ready | X07 Console Show section (**① Mainshow ready**); Procedures step 3 |
| ### 3. Start the show on that cube | X07 Console Show section (**② Trigger mainshow**); Procedures step 4 |
| ### 4. Watch, then stop (+ two WARNINGs: trigger all, Stop → idle) | X07 Console Show section; Procedures steps 5–6 |
| The Workstation as a show host | X07 Workstation as show host |
| Change the show animation (steps 1–5, v1.5.0+, USB route, show-state INFO v6) | X07 Show editor table; Procedures › Change the show; show state paragraph |
| Electrical and trigger contract (table, D1/GPIO explanation, DANGER 5 V, BOOT WARNING) | X07 Electrical and trigger contract; Trigger timing; DANGER; WARNING |
| Read indicators, and when the show does not start (pointer to troubleshooting §7) | X07 Indicators (full table taken from troubleshooting §7 and the controller README); symptom checks remain in {{page:H5}} / {{page:X11}} |
| Replace or update the controller | X07 Procedures › Replace or update the controller |
| What success looks like | X07 Console Show section; Procedures; Indicators |
| Engineering detail › Start command and show clock (7 vs 8, SET_ZONE 4/0, showId ×5 30 ms; SHOW_TIMECODE, 100 ms drift, 298 s, `show_config`, `show_stop`, backwards compatible, Workstation/GR 1.1.0+ timecode; XIAO, GPIO10 LEDs, no heartbeat, USB JSON 115200) | X07 Cube side; Mainshow controller; USB protocol; Workstation as show host |
| Engineering detail › Show editor in detail (timeline, keys, cue types, fanning, identical preview, reference video, Revert; live ≈60 ms; versions web-allocated; Query/Update selected) | X07 Show editor table |
| Sources and evidence | X07 Sources; Known issues (evidence) |
| Related guides | Inline links |

## Could not place / corrected

- Nothing was left unplaced.
- Corrected against code (noted in the pages): pool calibration does not interpolate on the radio (X06 Known issues); cue types include `off` (X07); the entrance neon change in show v5 is a cue in the show document, not the `SET_ZONE 4` colour (X07); desert colour RGB (20,12,0) is called "yellow" in the old chapter and "amber" in the Workstation README (X05).
- New contradictions recorded as **To confirm**: which board is the installed Pool central controller (`48:F6:EE:15:8E:E0` in the README vs `D4:05:92:E7:D0:C4` in the relay findings) (X06); desert registry names vs point ids (X05); relay `JD-VCC` voltage after the module swap (X06).

## Audit changes (23 Sept, final audit)

- X07 › Sequence: the mermaid diagram (6 participants, long labels, printed below 8 pt) reduced to 4 participants with labels of 4 words or fewer. The details it dropped (media server 5 V cue, signal interface, GPIO3 (D1) to GND, `MSG_SHOW_START` (8) with fresh showId ×5 at 30 ms, play ≈4:58 then leave ready, timecode (showId, t) from mainshow-1.3.0, late join needs cube v1.5.0+) are in a "Diagram key" paragraph under it.
- Old-chapter timings written in other units in X04/X05/X07 were confirmed equivalent: 0.7 s = `TAG_LEAVE_TIMEOUT` 700 ms (X04, X05); 350 ms = 0.35 s ping (X04); 0.12 s / 0.4 s = 120 / 400 ms repeats (X05); 3.1 s join = T = 3132 ms (X07).
