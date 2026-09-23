# Coverage summary: old chapters 00–17 → handbook + extended reference

Final audit, 23 Sept 2026. The detailed section-by-section maps are in the four `_coverage_*.md` files beside this one.
Result: **every specific fact in the old drafts `00..17-*.md` exists in an X page or, for operator prose, in a
handbook H page.** The old drafts can be deleted.

## Old chapters → destinations

| Old chapter | Facts went to | Operator prose went to | Detailed map |
|---|---|---|---|
| 00-root | X02 (handover identity, what changed from v1, current state, scope, evidence methodology), X01 (evidence levels, EN/KR) | H0 | `_coverage_X01_X02.md` |
| 01-how-it-works | X02 (visitor journey, system map, boards, protocols, which Workstation does which job) | H1 | `_coverage_X01_X02.md` |
| 02-glossary | X01 (all tables, with the Korean name column) | — | `_coverage_X01_X02.md` |
| 03-daily-operation | X11 (controls, checklist, cards), X03 | H2 | `_coverage_X03_X11.md` |
| 04-register-cubes | X03 (registration), X11 (cards) | H3 | `_coverage_X03_X11.md` |
| 05-cube-firmware-show | X03 (firmware, versions, flash page, show), X07 (show editor) | H3 | `_coverage_X03_X11.md` |
| 06-zone-databases | X08 (distribution, timings, RX gain, relay), X11 (cards) | H4 | `_coverage_X08_X13.md` |
| 07-preshow-touchdesigner | X04 | H4, H5 | `_coverage_X04_X07.md` |
| 08-desert | X05 | H4, H5 | `_coverage_X04_X07.md` |
| 09-pool-forest | X06 | H4, H5 | `_coverage_X04_X07.md` |
| 10-mainshow-media-interface | X07 | H2, H4, H5 | `_coverage_X04_X07.md` |
| 11-troubleshooting | X11 (catalogue, cards, indicators, reader status codes) | H5 | `_coverage_X03_X11.md` |
| 12-inventory-database-sync | X08 | — | `_coverage_X08_X13.md` |
| 13-zone-boards | X09 | H4 | `_coverage_X08_X13.md` |
| 14-computer-setup-backups | X10 | — | `_coverage_X08_X13.md` |
| 15-engineering-reference | X02 (architecture, protocols, tests, builds), X01 (terms), X06/X10 (PoolCentral flash speed) | — | `_coverage_X01_X02.md` |
| 16-intervention-record | X12 | H6 | `_coverage_X08_X13.md` |
| 17-open-items-acceptance | X13 | — | `_coverage_X08_X13.md` |

## How it was checked

English text only (`<kr>` blocks, Korean runs, `{{shot:}}` and `{{page:}}` placeholders stripped), compared with
`extended/X*.md` plus `handbook/H*.md`, case- and whitespace-insensitive, bold/backtick markers ignored.

| Pass | Tokens / units checked | Not found verbatim | Genuinely missing after review |
|---|---|---|---|
| 1. Backticked strings, bold labels, versions (`v1.x`, `name-x.y.z`), MACs, numbers with units, dates, commit hashes, file paths, `#N` cube numbers | 1,836 | 92 | 0 |
| 2. Pass 1 plus double-quoted messages/card texts, `0x` hex values, clock times, number + word | 2,364 | 300 (208 new beyond pass 1) | 0 |
| 3. Every numeral in the old drafts against every numeral in the new pages | all | 4 (`0.7`, `0.12`, `350`, `3.1`) | 0 (unit variants, below) |
| 4. Every word of 6+ letters | all | ~150 ordinary prose words | 0 |
| 5. Paragraph/table-row overlap (418 fact-bearing paragraphs and rows) | 418 | 9 below 75 % word overlap | 0 (each read by hand) |

**Facts added to X pages: 0.** Every unmatched token resolved to a fact already present in different wording or units:
`0.7 s` = `TAG_LEAVE_TIMEOUT` 700 ms (X04, X05); `350 ms` = 0.35 s ping (X04); `0.12 s / 0.4 s` = 120/400 ms repeats
(X05); `3.1 s` join = T = 3132 ms (X07); `20 seconds` / `10 seconds` = 20 s `IN_RANGE` / 10 s `SET_TIMEOUT` (X08);
`preshow.*` = the four expanded advisor ids (X04); `PoolCentral/README.md` = `README.md` in X06 Sources;
`PRESHOW,1,ON` = `PRESHOW,<n>,ON|OFF` (X04); `USB 115200` = 115200 baud (X04, X07); card texts ("…: failed",
"Two preshow plates are flashed as point …", "Pool radio … runs firmware without tuning support", etc.) in X03/X04/X06/X11.

## Tokens deliberately dropped (with reason)

| Tokens | Reason |
|---|---|
| Screenshot captions and ids (e.g. `↑3 ↓2` caption in 06, shot ids 03-1…11-6) | Screenshots belong to the handbook only; the Sync ↑/↓ chip itself is in X08 |
| Korean bold and prose (e.g. **태그 리더가 있는**, **두 가지 "flash".**, **쇼 상태(9월 23일).**) | Extended reference is English only; Korean names kept in X01's 한국어 column |
| Paragraph-lead bold labels (**Cube colours.**, **Why it happens.**, **Fix.**, **Open Show editor.**, **Record the old board.** …) | Formatting only; the content under each label was checked and is present |
| Chapter-map mermaid labels and navigation (00 chapter map, "Related guides", "chapters 12–16", "Engineering detail" toggles) | Superseded chapter structure; replaced by the H/X page list |
| Station/card wording the X pages deliberately corrected (see each page's Known issues), e.g. `SHOW_LIVE` "about 20 times a second" (old 05) | Corrected to the code value, about every 60 ms (~16 Hz), 600 ms lease |
| "168 tests OK" as the current console suite (old 15) | Superseded: 247 tests OK, 1 skipped; 168 kept only as the historical count in X13's test-report note |

## Consistency and template fixes made in this audit

- `SHOW_LIVE` rate now identical in X01, X02, X03, X07: about every 60 ms (~16 Hz), 600 ms lease. No "20 Hz" left
  outside X03's correction note.
- Console test count 247 (1 skipped) in X02 and X12; 168 only in X13 as the historical count.
- X07 sequence diagram cut to 4 participants with short labels; dropped details moved to a "Diagram key" paragraph.
- X02 Reset plate row aligned with X09/X13 (two boards named "Reset 1", v31/v32).
- X03 `<error>` → `‹error›`; X11 **NEOCORE #n** → **#N** (station title as in X03 and the code).
- X01, X02, X03, X11: title line moved above the byline, like the other X pages (the renderer drops a leading H1).
- Checked on all 13 pages: title, byline first and last, Summary / Facts / Procedures / Known issues / Sources in
  order (X01 has no Procedures or Known issues, X12 no Procedures: empty, allowed), no `<kr>`, no `{{shot:}}`,
  callouts only WARNING/DANGER, page links only `{{page:H*/X*/XP}}`. The renderer placeholders `{{v1-root}}` (X02),
  `{{v1-14}}` (X12) and `{{test-report-table}}` (X13) are kept: they are v1-page mentions and the English-only test
  table, supported by `console/tools/handover_render.py`.
- `python3 console/tools/handover_render.py --all --outdir <scratch> --allow-missing-pages` exits 0.
