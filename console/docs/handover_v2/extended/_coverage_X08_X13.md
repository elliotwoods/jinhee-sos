# Coverage map: old chapters 06, 12, 13, 14, 16, 17 → X08, X09, X10, X12, X13

Korean prose (`<kr>`), screenshots (`{{shot:…}}`), purpose callouts, "What success looks like" wording and "Related guides" lists were dropped by rule. Old `{{page:NN}}` links were remapped to X/H keys.

## 06-zone-databases.md

| Old section | New location |
|---|---|
| (purpose callout) | Dropped (rule); who/when folded into X08 Summary |
| ## Why a zone board can say "unknown tag" (+ mermaid, WARNING "Published ≠ on every board") | X08 › Facts › Zone database distribution (first paragraph); the flow is part of X08's copies diagram; warning content in X08 Procedures › Update all by hand (steps 3–4) and states table |
| ## Automatic updates (on by default) (switch table, Newer/differs never overwritten, evidence) | X08 › Facts › Automatic updates (with setting keys added); evidence in X08 Known issues |
| ## Update all by hand · ### 1. Finish other work | X08 › Procedures › Update all by hand, step 1 |
| ### 2. Click Sync (cards Sync & publish / Sync again / Sync (pulls the database)) | X08 step 2 + Facts › Zone database distribution (Attention cards) |
| ### 3. Find the zone boards in range | X08 step 3; "in range" 20 s in the timings table |
| ### 4. Update the boards that are behind | X08 step 4; controls in Facts (Zone relay UI) |
| ### 5. Walk the space with Auto-update all ("another relay is walking", 30 s retry) | X08 step 5; Zone relay UI; timings table |
| ### 6. Finish (+ two WARNINGs: delivered ≠ success; USB drop stops the run, resend resumes) | X08 step 6 + both WARNINGs under the procedure; resume in timings table |
| ## Read the results (states table, red card, did-not-confirm card) | X08 › Zone states table + Attention cards list |
| ## What success looks like | Folded into X08 procedure steps and states table (Sync chip, cards, Current, Show out of range, real reader test) |
| ## Tag reading strength is not radio strength (RX gain vs Signal, Set RX gain, 48 dB preshow, Identify/Request tap log/Reboot, bench evidence) | X08 › RX gain vs signal table + bullets; per-board controls in Zone relay UI; evidence in Known issues |
| ## Replace the Workstation (+ WARNING refusals, reader optional, Code-checked) | X08 › Workstation replacement (refusal list corrected against code; contradiction noted in Known issues) |
| Engineering detail (timings table, which radio walks, relay firmware capabilities, publication rule) | X08 timings table, "Which radio walks", "Relay firmware capabilities", "What goes into a published zone database" |
| Sources | X08 › Sources |

## 12-inventory-database-sync.md

| Old section | New location |
|---|---|
| ## Where the records live (table, NVS/MAC definitions, mermaid, separate baselines) | X08 › The copies (table, diagram, bullets incl. baseline keys) |
| ## What each action moves (table, WARNING, what neither sync carries) | X08 › What each action moves + indicator line; "neither sync carries" bullet in The copies |
| ## Field guide (fields table, status pills) | X08 › Field guide |
| ### What goes into the zone database (rules, CRC) | X08 › What goes into a published zone database (extended from `zonedb.py`) |
| ## Worked example | X08 worked-example table |
| ## Sync decision rules (table, losers keep `updated_at`, server refusal, audit events, Attention card, Web sync › Check, Apply now, two WARNINGs) | X08 › Sync decision rules; WARNINGs under X08 Procedures › Correct a sync result |
| ## Web access and offline (URL, password, DANGER, offline table, "Last seen") | X08 › Web access and offline |
| Sources and evidence | X08 › Sources + Known issues (evidence rows) |

## 13-zone-boards.md

| Old section | New location |
|---|---|
| Intro (firmware / identity / database) + mermaid provisioning flow | X09 Summary; flow expressed as X09 Procedures › Provision one zone board (steps 1–6) |
| ## Board roles | X09 › Board roles (extended with kind, points, name templates, versions from code) |
| ## Identify the role before flashing (+ WARNING bootloader restarts) | X09 › Identification + WARNING |
| ## Reset plate | X09 › Reset plate; naming/antenna in Known issues and X13 |
| ## Provision a zone board · ### 1–5 (+ WARNING no backup) | X09 › Procedures › Provision one zone board + WARNING; pre-flash cards in Facts |
| ## Replace one reader board | X09 › Procedures › Replace one reader board |
| ### Several boards at once (+ WARNING) | X09 › Automatic intake (Facts) + Procedures › Several boards at once + WARNING |
| ## Database only, over USB | X09 › Database only, over USB |
| ## Cube monitor (unknown-tag card table, test buttons, Zone console) | X09 › Cube monitor + Unknown-tag cards |
| ## What success looks like | X09 › Procedures › Success checks |
| ## Avoid accidental repurposing (DANGER Force flash, WARNING protected station, WARNING matched sets) | X09 › Procedures › Repurposing hazards (same three callouts) |
| Sources and evidence | X09 › Sources + Known issues |

## 14-computer-setup-backups.md

| Old section | New location |
|---|---|
| Intro | X10 Summary |
| ## Obtain the intended release (+ WARNING agree revision) | X10 › Source and release + WARNING |
| ## Set up a Mac (steps, command block, hash rule) | X10 › Procedures › Set up a Mac (+ environment check from SETUP §2) |
| ## Set up a Windows PC (WARNING, steps, WARNING `.venv`) | X10 › Environments table + Procedures › Set up a Windows PC + WARNING; Windows evidence in Known issues |
| ## Launchers (table, console options, WARNING locks, firmware builds) | X10 › Launchers, Console options (adds `--no-open`, API-port detail), Instance locks + WARNING, Environments (firmware builds bullet) |
| ## Shared inventory versus full backup (table, DANGER) | X10 › Shared inventory versus full backup + DANGER |
| ### Make a full backup | X10 › Procedures › Make a full backup (snippet from SETUP §4 included) |
| ## Restore or move to another computer (mermaid, 7 steps, WARNING) | X10 › Procedures › Restore or move (diagram, steps, WARNING) |
| Engineering detail (baselines, reserved numbers seeded, sync never asks, hostos) | Baselines/reserved/sync rules → X08 (The copies, Sync decision rules); hostos → X10 Environments |
| Sources | X10 › Sources |

## 16-intervention-record.md

| Old section | New location |
|---|---|
| Intro (KST, commit meaning) | X12 Summary |
| ## Scope and authorship (+ NOTE on "Repair by Kimchi and Chips" scope) | X12 › Scope and authorship (NOTE turned into a bullet: callouts are WARNING/DANGER only) |
| ## Dated progression (table, no-flash statement) | X12 › Dated progression (all rows; flash row extended with MACs from the test report) |
| ## Git evidence | X12 › Git evidence (adds 8b27c87, c268f5c, 6aa287f, 2a39bd1, bf869f8, a2591e6 rows cited in the progression, plus authors) |
| ## Original Engineering Six document | X12 › Original Engineering Six document (`{{v1-14}}` kept) |
| ## Field sources | X12 › Field sources |
| ## How this documentation was checked | X12 › How this documentation was checked (test count updated) |
| Sources | X12 › Sources |

## 17-open-items-acceptance.md

| Old section | New location |
|---|---|
| Intro | X13 Summary |
| ## Open items | X13 › Open items (all rows; adds Reset plate names row and the 19 boards list) |
| ## Console hardware verification (+ proven radio boards line) | X13 › Console hardware verification (adds USB intake and receipt recovery rows from the test report) |
| ## Bench pass, 23 September (+ `{{test-report-table}}`) | X13 › Bench pass, 23 September (placeholder kept exactly, plus extra observations) |
| ## Acceptance walk | X13 › Acceptance walk checklist |
| ## Sign-off record (+ WARNING) | X13 › Procedures › Sign-off template + WARNING |
| Sources | X13 › Sources |

## Not placed / changed on purpose

- Screenshot references (06-1…06-4, C-2, C-4, C-5, C-6, 07-1…07-4): not used in X pages by rule.
- "The screenshots come from the console in simulation…" notes: dropped with the screenshots; the simulation provenance of the scripted flash is kept in X09 Known issues.
- Ch. 06's claim that the console refuses the Mainshow controller when writing a Workstation: contradicted by `console/jobs/dongle.py`; recorded as a contradiction in X08 Known issues instead of repeated as fact.

## Audit changes (23 Sept, final audit)

- X12 › Evidence table: console suite now "247 tests OK, 1 skipped (the opt-in Chrome smoke)"; the 168 capture-time figure removed here.
- X13 › Known issues: the test-report-table note rewritten to match the renderer (English-only table; "168 tests" and "34 screenshot scenarios" are the historical counts of the 23 Sept pass; current suite 247).
- Old-chapter "20 seconds" / "10 seconds" (06) are X08's 20 s `IN_RANGE` and 10 s `SET_TIMEOUT`.
