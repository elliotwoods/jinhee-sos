# Handover v2 printable PDF

Builds `console/docs/NCT_Console_Handover_v2_<version>.pdf` (plus `NCT_Console_Handover_v2.pdf`, a copy of the latest
build) from the same drafts as the Notion pages:
the handbook (`console/docs/handover_v2/handbook/H*.md`, bilingual) and the extended reference
(`console/docs/handover_v2/extended/X*.md`, English only). Page keys, titles and the dialect are defined in
`console/docs/handover_v2/STYLE_GUIDE.md` (› Two sections, › Draft dialect); this tool reads the two page tables from
there. Files whose name starts with `_` (coverage notes) are not pages and are skipped. The old `NN-*.md` chapters are
no longer printed.

## Build

```sh
cd "console/tools/handover_pdf"
npm install          # once: marked, puppeteer-core, pdf-lib
npm run build        # = node build.mjs
```

Needs Node 18+, an installed Google Chrome and network access (Google Fonts: Inter, Noto Sans KR,
JetBrains Mono; mermaid 11 from jsdelivr). Environment overrides:

| Variable | Default | Meaning |
|---|---|---|
| `CHROME_PATH` | `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` | Chrome or Chromium to print with (on Windows e.g. `C:\Program Files\Google\Chrome\Application\chrome.exe`) |
| `HANDOVER_DOCS` | `console/docs/handover_v2` | Draft folder (holds `STYLE_GUIDE.md`, `handbook/`, `extended/`); point it at a scratch copy to test |
| `HANDOVER_TMP` | `<os tmp>/nct-handover-pdf` | Scratch folder: `handover.html` (the intermediate page, open it in Chrome to debug), resized screenshots, previews |
| `HANDOVER_PDF_OUT` | versioned file + stable copy in `console/docs/` | Write exactly this one file instead (scratch/test builds). A path outside `console/docs/` also stops the version counter |
| `HANDOVER_NO_BUMP=1` | off | Do not record this build in `build_version.json` (scratch/test builds; the pages show the version the next real build would get) |
| `HANDOVER_PNG=1` | off | Embed the original 2880 px PNG screenshots instead of 1600 px JPEG copies (PDF several times larger) |

## Build version

Every build has a version: the build date in Korea time (KST, Asia/Seoul) plus a letter for that day's build count.
The first build of the day is `2026-09-23`, the second `2026-09-23B`, then `C`, `D` … `Z`, `AA`, `AB` …
The version is printed on the title page (Version block and the note under it), in the running footer of every page
that has one ("… · 23 September 2026 · build 2026-09-23B"), on the colophon, and in the PDF metadata (title, subject,
keywords).

- A real build (`npm run build` without `HANDOVER_PDF_OUT`) writes `console/docs/NCT_Console_Handover_v2_<version>.pdf`
  and copies it to `console/docs/NCT_Console_Handover_v2.pdf`, so existing links to the stable name always get the
  latest build. Older versioned files are never deleted or overwritten: if a versioned file already exists, for
  example after the counter file was deleted, the build skips to the next free letter. (`console/docs/*.pdf` is
  gitignored.)
- The counter is `build_version.json` in this folder: `{"date": "YYYY-MM-DD", "count": n, "version": "…"}`. It is
  gitignored, so each computer counts its own builds. The version is worked out before rendering, but the file is
  written only after the PDF has been written, so a failed build does not use a letter. A new KST date starts again
  at count 1.
- Test builds must not use letters: set `HANDOVER_NO_BUMP=1` and point `HANDOVER_PDF_OUT` at a scratch file, e.g.
  `HANDOVER_NO_BUMP=1 HANDOVER_PDF_OUT=/path/to/scratch/t.pdf npm run build`. `HANDOVER_PDF_OUT` outside
  `console/docs/` does not bump either. `HANDOVER_NO_BUMP=1` on its own still writes both files into `console/docs/`,
  so the next real build overwrites that versioned file.

`npm run preview -- 1 2 17` rasterises those pages to PNG in `$HANDOVER_TMP/preview` (macOS `sips`) for a quick look.

## Book structure

1. Title page, then **Contents**: the handbook entries, then one level listing the appendix pages.
2. **About this handover**: `handbook/H0-*.md` as a short opening without a chapter number. Its page-link list
   (every line starting with `{{page:…}}`, and a heading left empty by that) and its "About this handover" heading
   are dropped.
3. The handbook in Parts, each with a divider page: **I Introduction** (H1), **II Procedures** (H3, H4),
   **III Troubleshooting** (H5), **IV What we fixed** (H6) (`PARTS` in `build.mjs`). A Part takes whichever of its keys
   the STYLE_GUIDE table lists. H2 (Daily operation) was retired on 2026-09-23, so it is simply absent and gives no
   warning. If it were still in the table with a draft, it would print first in Procedures. Chapter openers show the key
   (a large "H3") and the running header reads "H3 · Cube procedures".
4. An **Appendix divider**, "Appendix — Extended reference (English) / 확장 참조(영문)", listing the X pages, then
   X01…X13 in a compact style: each starts on a new page with a small "Appendix · X06" label instead of a big number,
   9 pt body, 8.5 pt tables with tighter padding, smaller headings; running header "Appendix · X06 · Pool / forest —
   detail".
5. Colophon.

A page with no draft yet is left out with a warning, and so is a Part with no drafts; a `{{page:KEY}}` link to it prints
as plain grey text. The build reports the handbook page count (title page to the last handbook page) and the appendix
page count (divider to the last X page) separately.

## What it does

- Dialect: GFM tables; `> [!INFO|TIP|NOTE|WARNING|DANGER]` callouts; `<kr>…</kr>` (and, for older drafts, a
  Korean line or a `<br>`-separated Korean half) as muted Korean text; `## EN | KR` headings; `<details><summary>`
  as an always-open box; mermaid (theme neutral, classDefs `op`/`dev`/`data` injected in place of the draft's own);
  `{{shot:ID}}` + caption line as a figure (inline `{{shot:ID}}` → "(capture below)" and the figure after the
  paragraph, as in `handover_render.py`); `{{page:KEY}}` → an internal link "→ H3 · Cube procedures",
  "→ X06 · Pool / forest — detail", "→ Appendix · Extended reference (English)" (`XP`) or "→ About this handover"
  (`H0`/`root`); an old `{{page:NN}}` fails the build. `{{v1-root}}`/`{{v1-14}}` → "Handover v1 (Notion)";
  `{{test-report-table}}` parsed from `TEST_REPORT_TABLE` in `console/tools/handover_render.py` (one source).
  Leftover raw Notion `<table>` rows and `<span color>` are tolerated.
- The byline (`<span color="red">*This document was written by Kimchi and Chips*</span>`, first and last line of
  every draft) is stated once on the title page and dropped from the section pages, together with a draft's leading
  `# Title` line (the section opener carries the title from the STYLE_GUIDE table).
- Diagrams print at their natural size (mermaid text 9.75 pt), shrunk only to fit. The build tries, in order, the
  author's direction in the column (normal height, then a full page), the other direction (LR ↔ TD), and a landscape
  A4 page, taking the first that keeps text at 8 pt or more (otherwise the largest). A landscape page carries the
  heading it belongs to. The build prints how many were turned or put on landscape pages and the smallest text size
  (`HANDOVER_DEBUG=1` lists every diagram).
- Title page, running header (small logo + book title left, section right), running footer ("Kimchi and Chips ·
  NCT Console handover v2 · prepared for Amberin / Engineering Six · 23 September 2026 · build <version>" left, page
  number right) and a
  colophon page, all in `build.mjs`/`print.css`.
  The logo is `assets/kimchi-and-chips-logo.svg`, cropped from `assets/kimchi-and-chips-logo-source.svg` (A4 canvas)
  to the artwork, with "AND" in the logo grey `#6d6e71` to match `assets/kimchi-and-chips-logo.png`. Page headers
  and footers are CSS `@page` margin boxes on named pages, so each section has its own header; the title page,
  Part and Appendix dividers and colophon have no header.
- Contents page numbers are read back from the printed PDF's outline (every section, Part and Appendix title is an `<h1>`) and
  the book is reprinted until they are stable, so they always match.

The build fails on an unknown placeholder, an unknown callout type, a missing screenshot, an image that does not
load, or any mermaid error.
