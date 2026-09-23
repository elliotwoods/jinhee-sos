#!/usr/bin/env python
"""Render a Handover v2 draft into final Notion markdown.

    python console/tools/handover_render.py KEY [--uploads console/docs/handover_v2/uploads.json] [--out FILE]
    python console/tools/handover_render.py --all --outdir DIR [--allow-missing-pages]

KEY picks the draft (STYLE_GUIDE.md › Two sections): H0 or root → handbook/H0-*.md (the root page), H1…H6 →
handbook/H1-*.md…, X01…X13 → extended/X01-*.md…; an old two-digit NN → NN-*.md (the superseded chapters).
--all renders every handbook/*.md and extended/*.md draft (files starting with "_" are skipped).

Placeholders: {{shot:ID}} → `![EN caption / KR caption](<markdown_source>)` from uploads.json (id → markdown_source,
written by the publishing step after each notion-create-file-upload); the caption line that follows the placeholder
in the draft is consumed into the image caption (plain text: **, backticks and <kr> tags are stripped), and a shot
directly under a numbered step becomes that step's tab-indented child so Notion keeps the numbering.
{{page:KEY}} (H0…H6, XP, X01…X13, root; an old NN resolves through PAGES.json legacy_NN) → <mention-page url="…">
from PAGES.json; a page whose PAGES.json id is still TO_CREATE fails unless --allow-missing-pages (then its title in
bold).
{{v1-root}}, {{v1-14}} → mentions of the v1 pages; {{test-report-table}} → the acceptance table below.
Unresolved placeholders make the script exit 1 so a page is never published with a raw token.

Draft dialect (STYLE_GUIDE.md) → Notion-flavored markdown (notion://docs/enhanced-markdown-spec):
  GFM pipe table                     → <table header-row="true"> with tab-indented <tr>/<td> rows
  > [!INFO|TIP|NOTE|WARNING|DANGER]  → <callout icon="…" color="…_bg"> with tab-indented children
  <kr>…</kr>                         → <span color="gray">…</span>
  <details><summary>T</summary>…     → <details>/<summary>T</summary> with tab-indented children
  ```mermaid                         → passed through untouched (code block, language mermaid)
Nothing inside a fenced code block is transformed.
"""
import argparse
import json
import re
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
DOCS = HERE.parent / 'docs' / 'handover_v2'
V1_14 = 'https://app.notion.com/p/3e35e8c80bde8198b785f8910d56729f'
MISSING = 'TO_CREATE'
# Plain text for a page that does not exist in Notion yet (rendered bold with --allow-missing-pages);
# titles from STYLE_GUIDE.md › Two sections
PAGE_TITLES = {
    'root': 'Operations & Technical Handover v2 — NCT Console',
    'H1': 'Introduction',
    'H2': 'Daily operation',
    'H3': 'Cube procedures',
    'H4': 'Zone procedures',
    'H5': 'Troubleshooting',
    'H6': 'What Kimchi and Chips fixed',
    'XP': 'Extended reference (English)',
    'X01': 'Glossary & names',
    'X02': 'System, boards & protocols',
    'X03': 'Cubes: registration, firmware & main show — detail',
    'X04': 'Preshow & TouchDesigner — detail',
    'X05': 'Desert — detail',
    'X06': 'Pool / forest — detail',
    'X07': 'Main show & media interface — detail',
    'X08': 'Inventory, database & sync',
    'X09': 'Zone boards: set-up & replacement',
    'X10': 'Computer set-up, backups & recovery',
    'X11': 'Console controls, Attention cards & troubleshooting catalogue',
    'X12': 'Intervention record & sources',
    'X13': 'Open items & acceptance',
    '02': 'Glossary & names',
}
PAGE_KEY = re.compile(r'\{\{page:(H\d|XP|X\d\d|\d\d|root)\}\}')
CALLOUTS = {
    'INFO': ('ℹ️', 'blue_bg'),
    'TIP': ('💡', 'green_bg'),
    'NOTE': ('📝', 'gray_bg'),
    'WARNING': ('⚠️', 'yellow_bg'),
    'DANGER': ('🛑', 'red_bg'),
}

# {{test-report-table}}: English only (it is used on the English-only page X13). The 168 tests and 34 scenarios are the
# historical counts of that pass; the line above the table says so.
TEST_REPORT_TABLE = """Dongle pass of 23 September 2026 (historical counts; the console suite now runs 247 tests; 43 captures)

| Check (`console/TEST_REPORT_2026-09-23.md`) | Result | Evidence level |
|---|---|---|
| Dongle identified without reset (General Radio general-radio-1.1.0, AC:27:6E:82:68:54) | done: session opened, `connected=true` | Bench-verified |
| Discover cubes over the radio | 113 cubes answered; all in the inventory | Bench-verified (radio reply only) |
| Query zones | 27 zones in range (−61…−96 dBm), all *current* at v37; 19 out-of-range records *behind* | Bench-verified |
| Identify one zone (Preshow 4) + request its log | delivered; log frame with 8 entries = acknowledged; blink not observed | Bench-verified (acknowledged, not visually verified) |
| Set RX gain (48 dB = stored value) | zone replied `set_result=1 (ok)`; nothing changed | Bench-verified (acknowledged) |
| Old pairing app refused while the console runs | refused: "This database is already open in another pairing window." | Bench-verified (one direction) |
| Advisor readability on the real inventory | 9 cards; `apps.legacy_open` false positive fixed | Bench-verified |
| Zone database update over the air | **not performed** (needs an explicit go: it changes an installation board) | To confirm |
| Cube flash, database over USB, calibration, cue test, show trigger, USB intake, receipts recovery through the console | simulation only (`console/tests`, 168 tests green) | Simulation-verified |
| 34 screenshot scenarios stage and settle | `tests/test_docscenes.py` green; captures reviewed | Simulation-verified |"""


def manifest_captions():
    try:
        manifest = json.loads((HERE.parent / 'docs' / 'shots' / 'manifest.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return {s['id']: f"{s['en']} / {s['kr']}" for s in manifest.get('shots', [])}


def inline_shots(text, uploads):
    """A {{shot:ID}} inside a sentence becomes "(capture below)" / "(아래 캡처)" and the image follows the paragraph."""
    captions = manifest_captions()
    paragraphs = text.split('\n\n')
    out = []
    for paragraph in paragraphs:
        ids = re.findall(r'\{\{shot:([A-Za-z0-9-]+)\}\}', paragraph)
        if not ids:
            out.append(paragraph)
            continue
        seen = []
        for sid in ids:
            if sid not in seen:
                seen.append(sid)

        def swap(m):
            line_start = paragraph.rfind('\n', 0, m.start()) + 1
            korean = re.search(r'[\uac00-\ud7a3]', paragraph[line_start:m.start()]) is not None
            return '(아래 캡처)' if korean else '(capture below)'

        paragraph = re.sub(r'\{\{shot:[A-Za-z0-9-]+\}\}', swap, paragraph)
        paragraph = re.sub(r'\(\s*\(capture below\)(?:\s*,\s*\(capture below\))*\s*\)', '(captures below)', paragraph)
        paragraph = re.sub(r'\(\s*\(아래 캡처\)(?:\s*,\s*\(아래 캡처\))*\s*\)', '(아래 캡처)', paragraph)
        images = []
        for sid in seen:
            source = uploads.get(sid)
            if not source:
                raise SystemExit(f'no upload for shot {sid}')
            images.append(f'![{captions.get(sid, sid)}]({source})')
        out.append(paragraph + '\n\n' + '\n\n'.join(images))
    return '\n\n'.join(out)


FENCE_OPEN = re.compile(r'^(\s*)(`{3,}|~{3,})(.*)$')
TOKEN = '\x00FENCE{}\x00'
TOKEN_RE = re.compile(r'^(.*)\x00FENCE(\d+)\x00$')


def protect_fences(text):
    """Swap every fenced code block for a one-line token so no transformation can touch its contents."""
    lines = text.split('\n')
    out, fences = [], []
    i = 0
    while i < len(lines):
        m = FENCE_OPEN.match(lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue
        indent, fence = m.group(1), m.group(2)
        close = re.compile(r'^\s*' + re.escape(fence[0]) + '{' + str(len(fence)) + r',}\s*$')
        block = [lines[i]]
        i += 1
        while i < len(lines) and not close.match(lines[i]):
            block.append(lines[i])
            i += 1
        if i >= len(lines):
            raise SystemExit(f'unterminated code fence: {block[0].strip()}')
        block.append(lines[i])
        i += 1
        opener = FENCE_OPEN.match(block[0])
        if opener.group(3).strip().lower() == 'mermaid':
            block[0] = opener.group(1) + opener.group(2) + 'mermaid'
        # strip the fence's own indentation; the token keeps it so containers can add theirs
        block = [line[len(indent):] if line.startswith(indent) else line.lstrip() for line in block]
        out.append(indent + TOKEN.format(len(fences)))
        fences.append(block)
    return '\n'.join(out), fences


def restore_fences(text, fences):
    out = []
    for line in text.split('\n'):
        m = TOKEN_RE.match(line)
        if not m:
            out.append(line)
            continue
        prefix = m.group(1)
        out.extend(prefix + fence_line if fence_line else prefix.rstrip(' ') for fence_line in fences[int(m.group(2))])
    return '\n'.join(out)


CODE_SPAN = re.compile(r'(`+)(.+?)\1')


def outside_code(line, fn):
    """Apply fn to the parts of a line that are not inline code spans."""
    parts, last = [], 0
    for m in CODE_SPAN.finditer(line):
        parts.append(fn(line[last:m.start()]))
        parts.append(m.group(0))
        last = m.end()
    parts.append(fn(line[last:]))
    return ''.join(parts)


def inline(line):
    """<kr>…</kr> → grey span (spec: Inline colors, <span color="Color">Rich text</span>)."""
    def kr(segment):
        return segment.replace('<kr>', '<span color="gray">').replace('</kr>', '</span>')
    return outside_code(line, kr)


TABLE_SEPARATOR = re.compile(r'^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$')


def split_row(line):
    """Split a GFM table row on unescaped pipes; an escaped pipe stays escaped (spec: escape |) except inside code spans."""
    row = line.strip()
    if row.startswith('|'):
        row = row[1:]
    if row.endswith('|') and not row.endswith('\\|'):
        row = row[:-1]
    cells, current, i, code = [], '', 0, ''
    while i < len(row):
        ch = row[i]
        if ch == '\\' and i + 1 < len(row) and row[i + 1] == '|':
            current += '|' if code else '\\|'
            i += 2
            continue
        if ch == '`':
            run = len(row[i:]) - len(row[i:].lstrip('`'))
            ticks = row[i:i + run]
            if not code:
                code = ticks
            elif ticks == code:
                code = ''
            current += ticks
            i += run
            continue
        if ch == '|' and not code:
            cells.append(current.strip())
            current = ''
        else:
            current += ch
        i += 1
    cells.append(current.strip())
    return cells


def escape_cell(cell):
    """A cell starting with "+ ", "- " or "* " (also right after a leading code span) becomes a bullet list in Notion,
    and so does "`Code` + text" or "**Bold** + text". Backslash escapes do not survive Notion's import (checked on the
    live pages), so a " + " right after closing bold, italic or code becomes " and "; any other " + " (e.g. inside a
    bold button label) is left alone."""
    cell = re.sub(r'([`*]) \+ ', r'\1 and ', cell)
    return re.sub(r'^((?:`+[^`]+`+\s+)?)([-+*]) ', r'\1\\\2 ', cell)


def render_table(lines):
    """GFM pipe table → spec "Table": <table header-row="true"> / <tr> / <td>, children tab-indented."""
    header = split_row(lines[0])
    width = len(header)
    rows = [header] + [split_row(line) for line in lines[2:]]
    out = ['<table header-row="true">']
    for row in rows:
        row = (row + [''] * width)[:width]
        out.append('\t<tr>')
        out.extend(f'\t\t<td>{inline(escape_cell(cell))}</td>' for cell in row)
        out.append('\t</tr>')
    out.append('</table>')
    return out


CALLOUT_OPEN = re.compile(r'^\s*>\s*\[!([A-Za-z]+)\]\s*(.*)$')
DETAILS_OPEN = re.compile(r'^\s*<details>\s*(?:<summary>(.*?)</summary>)?\s*$')
SUMMARY = re.compile(r'^\s*<summary>(.*?)</summary>\s*$')
DETAILS_CLOSE = re.compile(r'^\s*</details>\s*$')


def indent_children(lines):
    """Container children: one tab deeper (spec: toggles/callouts need indented children); blank lines dropped."""
    return ['\t' + line for line in lines if line.strip()]


def convert(lines):
    """Block-level dialect → Notion markdown. Fences are already tokens, so their contents are never seen here."""
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if TOKEN_RE.match(line):
            out.append(line)
            i += 1
            continue
        m = CALLOUT_OPEN.match(line)
        if m:
            kind = m.group(1).upper()
            if kind not in CALLOUTS:
                raise SystemExit(f'unknown callout kind [!{m.group(1)}] (use {", ".join(CALLOUTS)})')
            body = [m.group(2)] if m.group(2).strip() else []
            i += 1
            while i < len(lines) and lines[i].lstrip().startswith('>'):
                body.append(re.sub(r'^\s*> ?', '', lines[i]))
                i += 1
            icon, color = CALLOUTS[kind]
            out.append(f'<callout icon="{icon}" color="{color}">')
            out.extend(indent_children(convert(body)))
            out.append('</callout>')
            continue
        m = DETAILS_OPEN.match(line)
        if m:
            summary = m.group(1)
            start = line.strip()
            i += 1
            if summary is None:
                while i < len(lines) and not lines[i].strip():
                    i += 1
                s = SUMMARY.match(lines[i]) if i < len(lines) else None
                if not s:
                    raise SystemExit(f'<details> without <summary>: {start}')
                summary = s.group(1)
                i += 1
            depth, body = 1, []
            while i < len(lines):
                if DETAILS_OPEN.match(lines[i]):
                    depth += 1
                elif DETAILS_CLOSE.match(lines[i]):
                    depth -= 1
                    if depth == 0:
                        break
                body.append(lines[i])
                i += 1
            if depth:
                raise SystemExit(f'unterminated <details>: {summary}')
            i += 1
            out.append('<details>')
            out.append(f'<summary>{inline(summary.strip())}</summary>')
            out.extend(indent_children(convert(textwrap.dedent('\n'.join(body)).split('\n'))))
            out.append('</details>')
            continue
        if line.lstrip().startswith('|') and i + 1 < len(lines) and TABLE_SEPARATOR.match(lines[i + 1]) \
                and '|' in lines[i + 1]:
            table = [line, lines[i + 1]]
            i += 2
            while i < len(lines) and lines[i].lstrip().startswith('|'):
                table.append(lines[i])
                i += 1
            out.extend(render_table(table))
            continue
        out.append(inline(line))
        i += 1
    return out


def check_balanced(text):
    """Every <kr> must close on its own line (a grey span cannot cross a Notion block)."""
    for line in text.split('\n'):
        if TOKEN_RE.match(line):
            continue
        tags = []
        outside_code(line, lambda s: tags.extend(re.findall(r'</?kr>', s)) or s)
        if tags != ['<kr>', '</kr>'] * (len(tags) // 2):
            raise SystemExit(f'unbalanced <kr> tags: {line.strip()[:80]}')


def draft_path(key, docs=DOCS):
    """H0/root → handbook/H0-*.md, H1… → handbook/H1-*.md, X01… → extended/X01-*.md, NN → NN-*.md (old chapters)."""
    key = 'H0' if key == 'root' else key
    if re.fullmatch(r'H\d', key):
        folder = docs / 'handbook'
    elif re.fullmatch(r'X\d\d', key):
        folder = docs / 'extended'
    elif re.fullmatch(r'\d\d', key):
        folder = docs
    else:
        raise SystemExit(f'unknown page key {key} (use H0…H6, X01…X13 or an old NN)')
    files = sorted(p for p in folder.glob(f'{key}-*.md') if not p.name.startswith('_'))
    if not files:
        raise SystemExit(f'no draft for {key}')
    return files[0]


def render(key, uploads, pages, allow_missing=False, docs=DOCS):
    return render_text(draft_path(key, docs).read_text(encoding='utf-8'), uploads, pages, allow_missing)


def page_entry(key, pages):
    """PAGES.json entry for a {{page:KEY}}: H0/00/root → root; an old NN → legacy_NN[NN] when present."""
    if key in ('H0', '00', 'root'):
        return pages.get('root')
    if re.fullmatch(r'\d\d', key) and key in pages.get('legacy_NN', {}):
        return pages['legacy_NN'][key]
    return pages.get(key)


def render_text(text, uploads, pages, allow_missing=False):
    text, fences = protect_fences(text)
    lines = text.split('\n')
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.fullmatch(r'\s*\{\{shot:([A-Za-z0-9-]+)\}\}\s*', line)
        if m:
            sid = m.group(1)
            caption = ''
            if i + 1 < len(lines) and lines[i + 1].strip() and not lines[i + 1].startswith(('#', '{{', '!')) \
                    and not TOKEN_RE.match(lines[i + 1]):
                caption = lines[i + 1].strip()
                i += 1
            source = uploads.get(sid)
            if not source:
                raise SystemExit(f'no upload for shot {sid}')
            # image alt text is plain: Notion would show ** and ` literally
            caption = re.sub(r'</?kr>', '', caption).replace('**', '').replace('`', '')
            image = f'![{caption}]({source})'
            previous = next((o for o in reversed(out) if o.strip()), '')
            if re.match(r'\d+\. ', previous):
                # a shot between numbered steps becomes the step's child, or Notion restarts the numbering at 1
                while out and not out[-1].strip():
                    out.pop()
                out.append('\t' + image)
                i += 1
                while i < len(lines) and not lines[i].strip():
                    i += 1
                continue
            out.append(image)
            i += 1
            continue
        out.append(line)
        i += 1
    text = '\n'.join(out)
    text = inline_shots(text, uploads)

    def page(m):
        key = m.group(1)
        entry = page_entry(key, pages)
        if not entry:
            raise SystemExit(f'no page for {{page:{key}}}')
        if entry.get('id') == MISSING or entry.get('url') == MISSING:
            if not allow_missing:
                raise SystemExit(f'page {key} is not created yet (PAGES.json id {MISSING}); '
                                 f'create it first or pass --allow-missing-pages')
            return f'**{PAGE_TITLES.get(key, "Chapter " + key)}**'
        return f'<mention-page url="{entry["url"]}"/>'

    text = PAGE_KEY.sub(page, text)
    text = text.replace('{{v1-root}}', f'<mention-page url="{pages["v1_root"]["url"]}"/>')
    text = text.replace('{{v1-14}}', f'<mention-page url="{V1_14}"/>')
    text = text.replace('{{test-report-table}}', TEST_REPORT_TABLE)
    left = re.findall(r'\{\{[^}]*\}\}', text)
    if left:
        raise SystemExit(f'unresolved placeholders: {sorted(set(left))}')
    check_balanced(text)
    text = '\n'.join(convert(text.split('\n')))
    # Notion pages get their title from properties: drop a leading H1 if the draft carries one
    if text.lstrip().startswith('# '):
        text = text.lstrip().split('\n', 1)[1]
    return restore_fences(text, fences)


def chapters(docs=DOCS):
    """Every handbook and extended draft, handbook first; files starting with "_" are notes, not pages."""
    return [p for folder in ('handbook', 'extended')
            for p in sorted((docs / folder).glob('*.md')) if not p.name.startswith('_')]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('number', nargs='?', metavar='KEY', help='H0 (= root) … H6, X01 … X13, or an old NN')
    parser.add_argument('--uploads', type=Path, default=DOCS / 'uploads.json')
    parser.add_argument('--pages', type=Path, default=DOCS / 'PAGES.json')
    parser.add_argument('--docs', type=Path, default=DOCS, help=argparse.SUPPRESS)
    parser.add_argument('--out', type=Path, default=None)
    parser.add_argument('--all', action='store_true',
                        help='render every handbook/*.md and extended/*.md draft (needs --outdir)')
    parser.add_argument('--outdir', type=Path, default=None)
    parser.add_argument('--allow-missing-pages', action='store_true',
                        help='render {{page:KEY}} of a not-yet-created page (PAGES.json TO_CREATE) as bold text')
    args = parser.parse_args(argv)
    if args.all == bool(args.number):
        parser.error('give a page key or --all')
    if args.all and not args.outdir:
        parser.error('--all needs --outdir')
    uploads = json.loads(args.uploads.read_text(encoding='utf-8')) if args.uploads.exists() else {}
    pages = json.loads(args.pages.read_text(encoding='utf-8'))
    if args.all:
        args.outdir.mkdir(parents=True, exist_ok=True)
        failed = []
        drafts = chapters(args.docs)
        if not drafts:
            print(f'no handbook/extended drafts under {args.docs}', file=sys.stderr)
            return 1
        for path in drafts:
            try:
                text = render_text(path.read_text(encoding='utf-8'), uploads, pages, args.allow_missing_pages)
            except SystemExit as exc:
                failed.append(path.name)
                print(f'{path.name}: {exc}', file=sys.stderr)
                continue
            target = args.outdir / path.name
            target.write_text(text, encoding='utf-8', newline='\n')
            print(f'{target} ({len(text)} chars)')
        if failed:
            print(f'failed: {", ".join(failed)}', file=sys.stderr)
            return 1
        return 0
    text = render(args.number, uploads, pages, args.allow_missing_pages, args.docs)
    if args.out:
        args.out.write_text(text, encoding='utf-8', newline='\n')
        print(f'{args.out} ({len(text)} chars)')
    else:
        sys.stdout.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
