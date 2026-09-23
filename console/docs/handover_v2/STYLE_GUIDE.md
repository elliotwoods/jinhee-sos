# Handover v2 style guide

This is the single source for how the handover v2 drafts are written. Both outputs come from the same drafts:
the Notion pages (via `console/tools/handover_render.py`) and the printable PDF (via `console/tools/handover_pdf/`).


## Two sections (from 2026-09-23 evening; supersedes the "Chapter map" below)

The handover has two parts. Human readers found the 18-chapter version too long.

**Handbook** (`handbook/H*.md`) is bilingual EN/KR, with screenshots, and about **40 printed A4 pages** in total. It is
for people: introduction, procedures, troubleshooting, and what Kimchi and Chips fixed. Nothing else goes in it.

| Key | File | Title (EN · KR) | Budget |
|---|---|---|---|
| H0 | handbook/H0-root.md | Operations & Technical Handover v2 — NCT Console · 운영·기술 인수인계 v2 | 2 pp |
| H1 | handbook/H1-introduction.md | Introduction · 소개 | 5 pp |
| H2 | handbook/H2-daily-operation.md | Daily operation · 일일 운영 | 4 pp |
| H3 | handbook/H3-cube-procedures.md | Cube procedures · 큐브 작업 | 10 pp |
| H4 | handbook/H4-zone-procedures.md | Zone procedures · 존 작업 | 10 pp |
| H5 | handbook/H5-troubleshooting.md | Troubleshooting · 문제 해결 | 7 pp |
| H6 | handbook/H6-what-we-fixed.md | What Kimchi and Chips fixed · 김치앤칩스 개선 내역 | 4 pp |

Handbook length rules:
- One idea per paragraph, and one short paragraph per step.
- At most one screenshot per step, and only where it shows something the text can't.
- No "Engineering detail" toggles and no Sources toggles. End a section with one line such as
  `More detail: {{page:X06}}` / `<kr>자세한 내용: {{page:X06}}</kr>`.
- Tables only where they replace more text than they add.
- Keep the purpose callout, the steps and the "What success looks like" table. Keep evidence levels short, for example
  "(Bench-verified)".

**Extended reference** (`extended/X*.md`) is **English only** and dense. It is for engineers and AI agents, and it holds
every fact that is not in the handbook. **Nothing from the old chapters may be lost**: a fact cut from the handbook
must land in an X page.

| Key | File | Title |
|---|---|---|
| XP | (Notion parent page only) | Extended reference (English) · 확장 참조(영문) |
| X01 | extended/X01-glossary.md | Glossary & names (keeps a Korean name column) |
| X02 | extended/X02-system-protocols.md | System, boards & protocols |
| X03 | extended/X03-cubes.md | Cubes: registration, firmware & main show — detail |
| X04 | extended/X04-preshow.md | Preshow & TouchDesigner — detail |
| X05 | extended/X05-desert.md | Desert — detail |
| X06 | extended/X06-pool-forest.md | Pool / forest — detail |
| X07 | extended/X07-mainshow.md | Main show & media interface — detail |
| X08 | extended/X08-inventory-sync.md | Inventory, database & sync |
| X09 | extended/X09-zone-boards.md | Zone boards: set-up & replacement |
| X10 | extended/X10-computer-setup.md | Computer set-up, backups & recovery |
| X11 | extended/X11-console-cards.md | Console controls, Attention cards & troubleshooting catalogue |
| X12 | extended/X12-intervention-record.md | Intervention record & sources |
| X13 | extended/X13-open-items.md | Open items & acceptance |

Extended page template (fixed order; leave a section out if it is empty):
1. `# Title` line, then the byline.
2. **Summary**: 2–4 sentences.
3. **Facts**: tables and `key: value` lists (versions, pins, ids, timings, file paths, message and card texts,
   button labels, defaults).
4. **Procedures**: terse numbered steps, no screenshots.
5. **Known issues / open questions**, each with an evidence level.
6. **Sources**: file paths, commits and reports, as a plain list (no toggle).

Extended pages have no `<kr>`, no screenshots, and no purpose callouts. Callouts are only for real hazards (WARNING/DANGER).
Mermaid diagrams are only for structure (architecture, state machines, signal paths). Use precise names, exact
strings and units. Exact console labels stay in bold.

Links: use `{{page:H1}}`…`{{page:H6}}`, `{{page:X01}}`…`{{page:X13}}` and `{{page:XP}}`. The old `{{page:NN}}` keys are gone.
Diagrams in the handbook must print at 8 pt or more: at most about 8 nodes, labels of 4 words or fewer per language.

## Audience and voice

- Readers: floor operators (Korean first language, not engineers), the cube desk, the receiving engineers
  (Engineering Six) and project management (Amberin). Chapters 03–11 are for operators: write for someone who has
  never seen the code.
- Short sentences. Active voice. Imperative for steps ("Plug in the cube.").
  One idea per paragraph.
- Say what the operator sees and does first, and why second. Put engineering detail in chapters 12–15, or in a
  collapsed "Engineering detail" toggle at the end of an operator chapter.
- Keep evidence honest. Every hardware claim carries its evidence level (see the table below). Never upgrade
  "simulation-verified" to "works". Don't invent facts: check a claim against the code or README before you write it,
  and drop it if you can't confirm it.

### Evidence levels (use these exact words)

| Level | Meaning |
|---|---|
| **Code-checked** | Implemented in the repository; nobody has run it on hardware for this document |
| **Simulation-verified** | Exercised by the console's automated tests or simulated boards |
| **Bench-verified** | Exercised on a real board at the bench (name the board) |
| **Field-reported** | Reported working on site by a named person (Elliot, Hojun, Sangeun) |
| **To confirm** | Still needs checking on site, or a client decision |

(Old words: "code-inspected" → Code-checked; "dongle-verified" → Bench-verified.)

## Canonical names

Use the **canonical name** every time. Mention an old name once, in brackets, where the reader might meet it on a
label or in the old apps. The Glossary (chapter 02) holds this full table, with Korean.

| Canonical (EN) | Korean | Not / old names | Plain meaning |
|---|---|---|---|
| **NCT Console** (or "the console") | NCT 콘솔 | the app, pairing app, GUI | The one operator program on the Mac |
| **Cube** | 큐브 | device, LED cube, Neocore | The glowing object a visitor carries |
| **Cube number** | 큐브 번호 | ID, cube_id, label number | The number on the cube's label |
| **Tag** | 태그 | NFC UID, card, sticker | The NFC tag inside a cube that zone boards read |
| **Workstation** | 워크스테이션 | General Radio, dongle, pairing station, station, relay | The small radio board plugged into the Mac by USB. It talks to cubes and zone boards over the air and has the tag reader for registration. The installed *pairing station* and the bench *General Radio* are older kinds of Workstation and still work |
| **Zone board** | 존 보드 | plate, reader, reader board, zone | A tag reader board in a zone (Preshow, Desert, Pool, Reset). "Zone" alone means the area of the exhibition |
| **Zone database** | 존 데이터베이스 | zone DB, zdb, mapping | The tag → cube-number list stored on every zone board |
| **Inventory** | 인벤토리 | devices database, SQLite, records | The console's list of every cube (number, tag, role) |
| **Web inventory** | 웹 인벤토리 | Vercel, web copy, blob | The shared online copy that keeps several Macs in step |
| **Sync** | 동기화 | web sync, push/pull | Exchanging the inventory and published zone databases with the web inventory |
| **Main show** | 메인쇼 | mainshow, show image | The finale animation every cube plays together |
| **Mainshow controller** | 메인쇼 컨트롤러 | M5 show starter, show trigger | The board that starts the main show on every cube |
| **Show clock** | 쇼 타임코드 | SHOW_TIMECODE | The once-a-second signal that lets a late cube join a running show |
| **Pool central controller** | 풀 중앙 컨트롤러 | PoolCentral, central | Drives the pool/forest frame lights from the six pool radios |
| **Pool radio** | 풀 라디오 | pool slider, pool zone board | The six boards that read the pool sliders |
| **Preshow bridge** | 프리쇼 브리지 | media bridge, PreshowBridge | Passes preshow events to TouchDesigner over USB |
| **Firmware** | 펌웨어 | build, binary, sketch | The program running on a board |
| **Attention panel** / **suggestion card** | Attention 패널 / 제안 카드 | advisor | The right-hand list of things the console thinks you should know |
| **Result status** | 결과 상태 | truth ladder | Sent → Delivered → Acknowledged → Verified / Failed |
| **Hold to confirm** | 길게 눌러 확인 | press-and-hold, confirmation token | Destructive buttons must be held down |
| **Temporary control** | 임시 제어 | lease, override | The console borrows a board's output for a short time; it hands it back automatically |

Result status in one line: *Sent* = the console sent it; *Delivered* = the radio says it arrived (not proof that
anything happened); *Acknowledged* = the board answered; *Verified* = read back and checked. Only Verified and
Acknowledged count as success.

Engineering words (ESP-NOW, NVS, channel 2, chunk, manifest, MAC, PN532, PCA9685, lease, relay, SET_ZONE, packet
types) may appear in chapters 12–16. In operator chapters (03–11), give each one a one-line explanation the first time
it appears and link the Glossary (`{{page:02}}`), or move it into the "Engineering detail" toggle.

Console controls, button labels, page names and protocol tokens stay **in English, in bold**, in both languages, so
they match the screen: **Register**, **Update all**, Settings › Automatic updates.

## Chapter map (superseded, kept for the old drafts NN-*.md)

| # | File | Title (EN · KR) | Part |
|---|---|---|---|
| 00 | 00-root.md | Operations & Technical Handover v2 — NCT Console · 운영·기술 인수인계 v2 | — |
| 01 | 01-how-it-works.md | How the installation works · 전시 시스템 구성 | Understand |
| 02 | 02-glossary.md | Glossary & names · 용어·명칭 | Understand |
| 03 | 03-daily-operation.md | Daily operation & first response · 일일 운영·초기 대응 | Operate |
| 04 | 04-register-cubes.md | Register cubes · 큐브 등록 | Cube desk |
| 05 | 05-cube-firmware-show.md | Update cube firmware & the main show · 큐브 펌웨어·메인쇼 업데이트 | Cube desk |
| 06 | 06-zone-databases.md | Keep zone databases current · 존 데이터베이스 최신 유지 | Cube desk |
| 07 | 07-preshow-touchdesigner.md | Preshow & TouchDesigner · 프리쇼·터치디자이너 | Zones |
| 08 | 08-desert.md | Desert · 사막존 | Zones |
| 09 | 09-pool-forest.md | Pool / forest · 풀존·숲존 | Zones |
| 10 | 10-mainshow-media-interface.md | Main show & media interface · 메인쇼·미디어 연결 | Zones |
| 11 | 11-troubleshooting.md | Troubleshooting · 문제 해결 | Operate |
| 12 | 12-inventory-database-sync.md | Inventory, database & sync · 인벤토리·데이터베이스·동기화 | Engineering |
| 13 | 13-zone-boards.md | Zone boards: set-up & replacement · 존 보드 설정·교체 | Engineering |
| 14 | 14-computer-setup-backups.md | Computer set-up, backups & recovery · PC 설치·백업·복구 | Engineering |
| 15 | 15-engineering-reference.md | Engineering reference & release checks · 기술 참조·릴리스 점검 | Engineering |
| 16 | 16-intervention-record.md | Intervention record & sources · 개선 이력·출처 | Project |
| 17 | 17-open-items-acceptance.md | Open items & acceptance · 남은 항목·인수 검수 | Project |

Old → new numbers: 02→03, 03→04, 04→05, 05→12, 06→06, 07→13, 08→07, 09→08, 10→09, 11→10, 12→14, 13→15, 14→16,
15→17, 16→11. The `{{page:NN}}` placeholders have already been remapped. **Prose references ("see chapter 15",
"15장") have not**: fix them while you rewrite.

## Page template

Every chapter from 03 to 11, 13 and 14 follows this shape (skip the parts that don't apply):

1. **Purpose callout**, first thing on the page:
   ```
   > [!INFO] **Who:** cube desk · **When:** a new cube arrives · **You need:** the console, the Workstation, the cube's USB cable
   > **누가:** 큐브 담당 · **언제:** 새 큐브가 들어왔을 때 · **준비물:** 콘솔, 워크스테이션, 큐브 USB 케이블
   ```
2. An **At a glance** diagram (mermaid) where a flow or a path exists.
3. **Steps**: `###` numbered headings or a numbered list, one action each, with `{{shot:ID}}` directly under the step
   it illustrates.
4. **What success looks like**: a table with the columns *You see* | *It means* | *If not* (the last one links to
   Troubleshooting).
5. **Warnings** as `> [!WARNING]` callouts, never buried in a paragraph.
6. An **Engineering detail** toggle (optional).
7. A **Sources** toggle (file paths, commits), then **Related guides** (`{{page:NN}}` list).

Chapters 12, 15 and 16 are reference pages: tables first, prose second.

## Bilingual layout

- Each English paragraph is followed immediately by its Korean paragraph, **on its own line, wrapped in
  `<kr>…</kr>`**. The renderer turns it into grey text in Notion and a muted style in the PDF. Don't use `<br>` pairs any more.
  ```
  Plug the cube in. The console identifies it without restarting it.
  <kr>큐브를 꽂습니다. 콘솔은 큐브를 재시작하지 않고 식별합니다.</kr>
  ```
- Headings: `## English | 한국어`.
- Tables: bilingual header cells (`You see · 화면`) and bilingual cells where short (`Verified · 검증됨`). For long
  cells, write two rows or keep EN only and add a Korean sentence under the table.
- List items: the EN text, then ` <kr>…</kr>` on the same item.
- Callouts: the EN line, then the KR line, inside the same callout.
- Mermaid labels: `"English<br/>한국어"`.
- Korean is still machine-drafted. Keep the note on the root page that a native speaker must review it.

## Draft dialect (what the renderer and the PDF builder understand)

| Construct | Write | Notion output | PDF output |
|---|---|---|---|
| Table | GFM pipe table | `<table>` block | styled table |
| Callout | `> [!INFO]`, `> [!TIP]`, `> [!WARNING]`, `> [!DANGER]` + following `>` lines | `<callout>` with icon/colour | coloured box |
| Korean | `<kr>…</kr>` | `<span color="gray">…</span>` | `.kr` muted text |
| Diagram | ```` ```mermaid ```` fenced block | mermaid code block (Notion renders it) | rendered SVG |
| Toggle | `<details><summary>Title</summary>` … `</details>` (blank lines inside) | toggle block | expanded box with title |
| Screenshot | `{{shot:ID}}` + caption line under it | image + caption | figure + caption |
| Page link | `{{page:NN}}` | page mention | "→ Chapter NN · Title" |
| Keyboard/control | `**Update all**` | bold | bold |

Mermaid rules: `flowchart LR` or `TD`, or `sequenceDiagram`. At most about 12 nodes. Quote every label. No `%%{init}` or
HTML beyond `<br/>`. Use classDefs only for these colours: `op` (operator action), `dev` (board), `data` (database).
The PDF builder defines them identically.

Do not use raw Notion XML (`<callout>`, `<table>`, `<columns>`) or `<span color>` in drafts. Write the dialect, so the
PDF stays in step with Notion.

## Screenshots

Keep every existing `{{shot:ID}}` (ids in `../shots/manifest.json`). Nothing is being recaptured in this pass. You may
move a shot or rewrite its caption line (EN / KR).

## Byline (the one exception)

The first and last line of every chapter is exactly this line, on its own, not in a blockquote:

```
<span color="red">*This document was written by Kimchi and Chips*</span>
```

The renderer passes it through to Notion unchanged. The PDF builder shows it once, on the cover, and drops it from the
chapter pages.

## Current facts (23 September 2026, from the device database and TEST_REPORT)

- Cube firmware: six cubes (#17, #33, #39, #52, #58, #95) run **v1.7.0-USB.1**. The rest of the fleet runs
  **v1.4.1-USB.2**. #17 got its show over USB at 04:39 KST. The other five were flashed on the Flash page at 04:47–04:49
  KST (firmware verified, boot confirmed, registration kept, show v5 written and read back). Evidence: Bench-verified,
  as recorded by the console (USB read-back; LEDs not recorded).
- Main show **v6** was published from the console at 04:52 KST. All six v1.7.0 cubes reported v6 by 04:59, over the air.
  Do not write "no show is published" or "the next show must be above v4". Say "the next publish is numbered by the web".
- The USB intake race ("USB port is owned by another Neocore application") has since been fixed.
- Pool central controller **4.2.2** (commit 5996e10, Hojun, field-reported): relay modules replaced, frame map
  re-measured (outputs 1–24).
- The Workstation firmware has been built but is not yet on any board. #134 (Mainshow controller) is still on
  mainshow-1.2.0.
