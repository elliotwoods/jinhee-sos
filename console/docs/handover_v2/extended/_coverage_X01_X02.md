# Coverage: old chapters 00, 01, 02, 15 → X01, X02

Every `##` section (and toggle) of the four source drafts, and where its content went. Korean prose (`<kr>`) was dropped;
Korean names kept in X01's 한국어 column.

## 00-root.md

| Source section | Destination |
|---|---|
| (preamble) Kimchi and Chips → Amberin / Engineering Six | X02 › Facts › Handover identity |
| About this handover | X02 › Handover identity (v2, console 0.1.0, commit c955d9f, start 17 Sept 2026, v1 unchanged and fallback); intro prose → handbook H0 |
| Who reads what | handbook H0 (intro prose; reading paths refer to the superseded chapter numbers) |
| Chapter map | handbook H0 (superseded chapter map; replaced by the H/X structure in STYLE_GUIDE) |
| What changed from version 1 | X02 › What changed from v1 (full table) |
| The console at a glance | Screenshots C-1, C-3 → handbook H1 (no screenshots in X). Dismiss options → X01 › Console › Attention panel. Language facts (EN/KR switch, Settings › Appearance, per-computer choice, English cards/logs, "EN: …" labels) → X01 › Console › EN / KR switch and X02 › Console architecture (language bullet) |
| Where things stand | X02 › Current state (field-reported zones, six v1.7.0 cubes, show v6, rest on v1.4.1-USB.2, open-items list → X13) |
| Evidence levels | X01 › Evidence levels; X02 › Evidence methodology (incl. simulated-screenshot note) |
| Scope | X02 › Scope |
| Korean machine-draft WARNING | handbook H0 (applies to the Korean text only; X pages are English) |
| Chapters (page list) | Not carried (navigation only; replaced by H/X page list) |

## 01-how-it-works.md

| Source section | Destination |
|---|---|
| Purpose callout / intro | handbook H1 (intro prose) |
| What the visitor carries | X02 › Visitor journey and cube states (two paths: tag vs radio; zone database turns tag into number); intro prose → handbook H1 |
| The visitor journey (diagram + 7 steps) | X02 › Visitor journey and cube states (table with SET_ZONE values, colours, counts); diagram → handbook H1 |
| Pool wording WARNING | X02 › Visitor journey (approved wording) and Known issues (label treatment, To confirm) |
| The system map (diagram + 3 paragraphs) | X02 › System map (detailed mermaid + bullets) |
| Which board is which (table) | X02 › Boards and versions + How the console presents each role |
| Unidentified board / Make this board a… | X02 › How the console presents each role |
| Not-every-ESP32 WARNING | X02 › How the console presents each role (WARNING kept) |
| Inherited charging / TouchDesigner note | X02 › Visitor journey (last bullet) |
| Engineering detail toggle: Radio | X02 › Protocols on channel 2 |
| Engineering detail: Cube colours | X02 › Visitor journey (table) and Protocols (show start ×5, timecode) |
| Engineering detail: Pool | X02 › Protocols (OR arbitration, matched set) |
| Engineering detail: Which Workstation does which job | X02 › Which Workstation does which job |
| Engineering detail: Identification without reset | X02 › How the console presents each role; Evidence methodology |
| Engineering detail: Evidence line | X02 › Boards table and Evidence methodology |
| Sources toggle | X02 › Sources (incl. Engineering Six PDF pages) and Scope |
| Related guides | Not carried (navigation) |

## 02-glossary.md

| Source section | Destination |
|---|---|
| Purpose callout / intro prose | X01 › Summary |
| People & places | X01 › People & places |
| Objects & boards | X01 › Objects & boards |
| Data | X01 › Data |
| Console | X01 › Console |
| Result status (diagram + prose) | X01 › Result status (diagram + table) |
| Evidence levels | X01 › Evidence levels |
| Old name → canonical name | X01 › Old name → canonical name |
| Engineering terms | X01 › Engineering terms (plus I²C and manifest from 15's intro) |
| Sources toggle | X01 › Sources |
| Related guides | Not carried (navigation) |

## 15-engineering-reference.md

| Source section | Destination |
|---|---|
| Intro (ESP-NOW, NVS, manifest, I²C definitions) | X01 › Engineering terms |
| Version inventory (table) | X02 › Boards and versions |
| Zone DB v38 WARNING (simulated publish) | X02 › Current state, Procedures 5, Known issues (guard location corrected to `client()` in `console/jobs/sync.py`) |
| Console architecture (diagram + module table + language) | X02 › Console architecture |
| Protocol boundaries (table, host ↔ Workstation, show format, Wi-Fi callback WARNING) | X02 › Protocols on channel 2 (frame type codes added from headers) |
| Zone storage and integrity | X02 › Zone storage and integrity (otadata and coredump rows added from partitions.csv) |
| Pool output mapping (+ WARNING + evidence) | X02 › Pool output mapping (4.2.2 table verified against `origin/main`; superseded 4.2.0 row and inverse map added) |
| Release discrepancy (DANGER) | X02 › Known issues (DANGER kept); Procedures 2 |
| Build and validation commands (+ CI, hardware scripts) | X02 › Build targets; Build and validation commands |
| Local automation interface | X02 › Local automation API |
| Wiring reference | X02 › Wiring |
| Sources toggle | X02 › Sources |
| Related guides | Not carried (navigation) |

## Unplaced

None. Items deliberately not carried: navigation lists (Chapters, Related guides), the superseded chapter map and
reading paths (handbook H0), the two screenshots (handbook H1) and the Korean machine-draft warning (handbook H0).

## Audit changes (23 Sept, final audit)

- X01 › Engineering terms › **SHOW_LIVE**: "~20 Hz" corrected to "about every 60 ms (~16 Hz); 600 ms lease" (code value, as X03/X07).
- X02 › Protocols on channel 2 › Main show link: same `SHOW_LIVE` correction.
- X02 › Tests table: console suite "168 tests OK" → "247 tests OK, 1 skipped" (168 kept only as the historical count in X13).
- X02 › Boards table › Reset plate: "two boards in the design" → the 23 Sept registry's two boards named "Reset 1" (v31, v32), matching X09/X13.
- X01, X02: title line moved above the byline (style guide order; the renderer drops a leading H1).
- No old-chapter fact was missing from X01/X02 (see `_coverage_SUMMARY.md`).
