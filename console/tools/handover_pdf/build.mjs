#!/usr/bin/env node
// Builds console/docs/NCT_Console_Handover_v2.pdf from the handover v2 drafts.
//
//   cd console/tools/handover_pdf && npm install && npm run build
//
// Book = the handbook, then the extended reference as an appendix (STYLE_GUIDE.md › Two sections):
//   title page, contents, "About this handover" (handbook/H0-*.md, its page-link list dropped),
//   Parts Introduction (H1) · Procedures (H2–H4) · Troubleshooting (H5) · What we fixed (H6),
//   then an Appendix divider and extended/X01…X13-*.md in a compact English-only style, then the colophon.
// Page keys and titles are parsed from the two STYLE_GUIDE tables; a page with no draft yet is left out with a
// warning. The draft dialect (STYLE_GUIDE.md › Draft dialect) is converted to HTML, rendered in the installed Chrome
// (CHROME_PATH overrides) and printed A4. Contents page numbers are read back from the printed PDF's outline and the
// book is reprinted until they are stable. Unknown placeholders, missing screenshots and mermaid errors fail the build.
// Intermediate HTML goes to HANDOVER_TMP (default: <os tmp>/nct-handover-pdf), never into the repository.
// HANDOVER_DOCS points the build at another copy of console/docs/handover_v2 (tests with scratch drafts).

import { readFileSync, writeFileSync, existsSync, mkdirSync, statSync, readdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { tmpdir } from 'node:os';
import { Marked } from 'marked';
import puppeteer from 'puppeteer-core';
import { PDFDocument, PDFName, PDFDict, PDFArray, PDFRef } from 'pdf-lib';

const HERE = dirname(fileURLToPath(import.meta.url));
const CONSOLE = resolve(HERE, '..', '..');
const DOCS = process.env.HANDOVER_DOCS ? resolve(process.env.HANDOVER_DOCS) : join(CONSOLE, 'docs', 'handover_v2');
const SHOTS = join(CONSOLE, 'docs', 'shots');
const RENDER_PY = join(CONSOLE, 'tools', 'handover_render.py');
const OUT = process.env.HANDOVER_PDF_OUT || join(CONSOLE, 'docs', 'NCT_Console_Handover_v2.pdf');
const TMP = process.env.HANDOVER_TMP || join(tmpdir(), 'nct-handover-pdf');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const KEEP_PNG = process.env.HANDOVER_PNG === '1';
const LOGO = join(HERE, 'assets', 'kimchi-and-chips-logo.svg');
const MERMAID_URL = 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js';
const FONTS_URL = 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Noto+Sans+KR:wght@400;500;700&family=JetBrains+Mono:wght@400;600&display=block';

const BOOK = {
  title: 'Operations & Technical Handover v2',
  subtitle: 'NCT Console',
  titleKr: '운영·기술 인수인계 v2 — NCT 콘솔',
  parties: 'Kimchi and Chips → Amberin / Engineering Six',
  partiesKr: '김치앤칩스 → 앰버린 / 엔지니어링식스',
  running: 'NCT Console · Handover v2',
  footer: 'Kimchi and Chips · NCT Console handover v2 · prepared for Amberin / Engineering Six',
};
// Handbook Parts (the handbook order); H0 opens the book as "About this handover", outside the Parts.
const PARTS = [
  { name: 'Introduction', kr: '소개', keys: ['H1'] },
  { name: 'Procedures', kr: '작업 절차', keys: ['H2', 'H3', 'H4'] },
  { name: 'Troubleshooting', kr: '문제 해결', keys: ['H5'] },
  { name: 'What we fixed', kr: '개선 내역', keys: ['H6'] },
];
const ABOUT = { en: 'About this handover', kr: '이 인수인계 문서에 대하여' };
const APPENDIX = { en: 'Appendix — Extended reference (English)', kr: '확장 참조(영문)', short: 'Appendix · Extended reference (English)' };
const PAGE_KEY = /\{\{page:([A-Za-z0-9]+)\}\}/g;
const ROMAN = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X'];
const CALLOUTS = { INFO: 'Info', TIP: 'Tip', NOTE: 'Note', WARNING: 'Warning', DANGER: 'Danger' };
// Mermaid classes shared with the Notion drafts (STYLE_GUIDE.md › Mermaid rules).
const CLASSDEFS = [
  'classDef op fill:#e6eef6,stroke:#1d5c8f,stroke-width:1.5px,color:#10263a',
  'classDef dev fill:#f2f2ef,stroke:#5f6368,stroke-width:1.2px,color:#202124',
  'classDef data fill:#fbf1dc,stroke:#a8781e,stroke-width:1.2px,color:#3d2b06',
];

const fail = (msg) => { console.error(`build failed: ${msg}`); process.exit(1); };
const warned = new Set();
const warn = (msg) => { if (!warned.has(msg)) { warned.add(msg); console.warn(`warning: ${msg}`); } };
const read = (p) => readFileSync(p, { encoding: 'utf-8' }).replace(/\r\n/g, '\n');
const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const HANGUL = /[가-힣ㄱ-ㆎ]/g;
const hasHangul = (s) => /[가-힣]/.test(s);
function koreanHeavy(s) {
  const plain = s.replace(/`[^`]*`/g, '').replace(/<[^>]+>/g, '').replace(/\*\*[A-Za-z][^*]*\*\*/g, '');
  const k = (plain.match(HANGUL) || []).length;
  const l = (plain.match(/[A-Za-z]/g) || []).length;
  return k >= 4 && k / (k + l) > 0.3;
}

// ---------------------------------------------------------------------------------------------- sources

// STYLE_GUIDE.md › Two sections: the handbook table (| H1 | handbook/H1-….md | EN · KR | budget |) and the
// extended table (| X01 | extended/X01-….md | Title |; XP is the Notion parent page, no draft).
function pageMap() {
  const text = read(join(DOCS, 'STYLE_GUIDE.md'));
  const start = text.indexOf('## Two sections');
  if (start < 0) fail('no "## Two sections" section in STYLE_GUIDE.md');
  const next = text.indexOf('\n## ', start + 3);
  const rows = [];
  for (const line of text.slice(start, next < 0 ? undefined : next).split('\n')) {
    const cells = line.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
    const key = cells[0];
    if (!/^(H\d|X\d\d|XP)$/.test(key || '') || cells.length < 3) continue;
    let title = cells[2];
    if (/^X\d\d$/.test(key)) title = title.replace(/\s*\([^)]*\)\s*$/, '');   // "(keeps a Korean name column)"
    const cut = title.indexOf(' · ');
    rows.push({
      key, file: /\.md$/.test(cells[1]) ? cells[1] : null, section: key.startsWith('H') ? 'handbook' : 'extended',
      en: cut < 0 ? title : title.slice(0, cut), kr: cut < 0 ? '' : title.slice(cut + 3),
    });
  }
  if (!rows.some((r) => r.key.startsWith('H'))) fail('no handbook table (H0…H6) found in STYLE_GUIDE.md › Two sections');
  return rows;
}

// "→ H3 · Cube procedures", "→ X06 · Pool / forest — detail", "→ Appendix · Extended reference (English)"
function pageLabel(key, titles) {
  if (key === 'H0') return ABOUT.en;
  if (key === 'XP') return APPENDIX.short;
  return `${key} · ${titles[key].en}`;
}
const pageAnchor = (key) => (key === 'XP' ? 'appendix' : `sec-${key}`);

// H0 in print: the opening needs no list of the pages (the contents follows the title page). Drops every line that
// starts with a page link and then any heading left with nothing under it.
function dropPageList(text) {
  const lines = text.split('\n').filter((l) => !/^\s*(?:[-*+]\s+|\d+\.\s+)?\{\{page:[A-Za-z0-9]+\}\}/.test(l));
  const out = [];
  const empty = (l) => !l.trim() || /^\s*<span color="\w+">.*<\/span>\s*$/.test(l);   // blank or the byline
  for (let i = 0; i < lines.length; i++) {
    if (/^#{1,6}\s/.test(lines[i])) {
      let j = i + 1;
      while (j < lines.length && !/^#{1,6}\s/.test(lines[j]) && empty(lines[j])) j++;
      if (j >= lines.length || /^#{1,6}\s/.test(lines[j])) continue;
    }
    out.push(lines[i]);
  }
  return out.join('\n');
}

function testReportTable() {
  const m = read(RENDER_PY).match(/TEST_REPORT_TABLE\s*=\s*"""([\s\S]*?)"""/);
  if (!m) fail(`TEST_REPORT_TABLE not found in ${RENDER_PY}`);
  return m[1];
}

function shotManifest() {
  const manifest = JSON.parse(read(join(SHOTS, 'manifest.json')));
  return Object.fromEntries((manifest.shots || []).map((s) => [s.id, s]));
}

// Screenshots are 2880 px wide PNGs (29 MB together). Unless HANDOVER_PNG=1 they are re-encoded once in Chrome as
// 1600 px JPEG (230 dpi at 174 mm) into the scratch cache, which keeps the PDF small.
async function prepareShots(browser, ids) {
  const out = {};
  const cache = join(TMP, 'shots');
  mkdirSync(cache, { recursive: true });
  let page = null;
  for (const id of ids) {
    const src = join(SHOTS, `${id}.png`);
    if (!existsSync(src)) fail(`screenshot ${src} does not exist ({{shot:${id}}})`);
    if (KEEP_PNG) { out[id] = pathToFileURL(src).href; continue; }
    const dst = join(cache, `${id}-1600q85.jpg`);
    if (!existsSync(dst) || statSync(dst).mtimeMs < statSync(src).mtimeMs) {
      page ||= await browser.newPage();
      await page.goto(pathToFileURL(join(TMP, 'blank.html')).href);
      const data = await page.evaluate(async (url) => {
        const img = new Image();
        img.src = url;
        await img.decode();
        const scale = Math.min(1, 1600 / img.naturalWidth);
        const c = document.createElement('canvas');
        c.width = Math.round(img.naturalWidth * scale);
        c.height = Math.round(img.naturalHeight * scale);
        const g = c.getContext('2d');
        g.fillStyle = '#fff';
        g.fillRect(0, 0, c.width, c.height);
        g.imageSmoothingQuality = 'high';
        g.drawImage(img, 0, 0, c.width, c.height);
        return c.toDataURL("image/jpeg", 0.85).split(',')[1];
      }, pathToFileURL(src).href);
      writeFileSync(dst, Buffer.from(data, 'base64'));
    }
    out[id] = pathToFileURL(dst).href;
  }
  if (page) await page.close();
  return out;
}

// ---------------------------------------------------------------------------------------------- dialect

function makeMarked() {
  const marked = new Marked({ gfm: true, breaks: false });
  marked.use({
    renderer: {
      heading({ tokens, depth }) {
        const html = this.parser.parseInline(tokens);
        const cut = html.lastIndexOf(' | ');
        if (cut >= 0 && hasHangul(html.slice(cut))) {
          return `<h${depth}><span class="h-en">${html.slice(0, cut)}</span> <span class="h-kr">${html.slice(cut + 3)}</span></h${depth}>\n`;
        }
        return `<h${depth}>${html}</h${depth}>\n`;
      },
      code({ text, lang }) {
        if ((lang || '').trim() === 'mermaid') return `<div class="diagram"><pre class="mermaid-src">${esc(mermaidSource(text))}</pre></div>\n`;
        return `<pre class="code"><code>${esc(text)}</code></pre>\n`;
      },
      blockquote({ tokens }) {
        const html = this.parser.parse(tokens);
        const m = html.match(/^<p>\[!([A-Z]+)\][ \t]*\n?/);
        if (!m) return `<blockquote>${html}</blockquote>\n`;
        const kind = m[1];
        if (!CALLOUTS[kind]) throw new Error(`unknown callout [!${kind}]`);
        const body = html.slice(m[0].length).replace(/^<p>\s*<\/p>\n?/, '').replace(/^<p><\/p>/, '');
        return `<div class="callout callout-${kind.toLowerCase()}"><div class="callout-label">${CALLOUTS[kind]}</div><div class="callout-body"><p>${body}</div></div>\n`;
      },
      table(token) {
        // default rendering, wrapped so zebra/header styles and break rules apply
        let head = '<tr>' + token.header.map((c) => `<th${c.align ? ` style="text-align:${c.align}"` : ''}>${this.parser.parseInline(c.tokens)}</th>`).join('') + '</tr>';
        const body = token.rows.map((r) => '<tr>' + r.map((c) => `<td${c.align ? ` style="text-align:${c.align}"` : ''}>${this.parser.parseInline(c.tokens)}</td>`).join('') + '</tr>').join('\n');
        return `<table class="md"><thead>${head}</thead><tbody>${body}</tbody></table>\n`;
      },
    },
  });
  return marked;
}

function mermaidSource(text) {
  const lines = text.replace(/\s+$/, '').split('\n').filter((l) => !/^\s*classDef\s+(op|dev|data)\b/.test(l));
  const first = lines.findIndex((l) => l.trim() && !l.trim().startsWith('%%'));
  if (first >= 0 && /^\s*(flowchart|graph)\b/.test(lines[first])) lines.splice(first + 1, 0, ...CLASSDEFS.map((c) => '  ' + c));
  return lines.join('\n');
}

function splitCaption(line) {
  let idx = -1;
  for (let i = line.indexOf(' / '); i >= 0; i = line.indexOf(' / ', i + 1)) {
    if (hasHangul(line.slice(i + 3)) && !koreanHeavy(line.slice(0, i))) { idx = i; break; }
  }
  return idx < 0 ? [line, ''] : [line.slice(0, idx), line.slice(idx + 3)];
}

function figure(marked, id, caption, shots, manifest) {
  let [en, kr] = caption ? splitCaption(caption) : [manifest[id]?.en || id, manifest[id]?.kr || ''];
  if (caption && !kr && manifest[id]?.kr && !hasHangul(caption)) kr = '';
  return `<figure class="shot" id="shot-${esc(id)}"><img src="${shots[id]}" alt="${esc(en.replace(/[*`]/g, ''))}"><figcaption>`
    + `<span class="fig-id">${esc(id)}</span><span class="fig-en">${marked.parseInline(en.trim())}</span>`
    + (kr ? `<span class="fig-kr">${marked.parseInline(kr.trim())}</span>` : '')
    + '</figcaption></figure>';
}

// CommonMark will not close **bold** when a Korean particle follows it directly (**Register (scan a tag)**를):
// on lines with Hangul, bold outside code spans is converted to <strong> before marked sees it.
function cjkBold(line) {
  const code = [];
  const masked = line.replace(/`[^`]*`/g, (m) => `\u0000${code.push(m) - 1}\u0000`);
  return masked.replace(/\*\*([^*\n]+?)\*\*/g, '<strong>$1</strong>').replace(/\u0000(\d+)\u0000/g, (_, i) => code[+i]);
}

function koreanLine(line) {
  // One source line. Leaves tables, raw HTML rows and headings alone.
  const m = line.match(/^(\s*(?:>\s?)*)(\s*(?:[-*+]|\d+\.)\s+)?(.*)$/);
  let [, quote, marker = '', rest] = m;
  const callout = rest.match(/^\[![A-Z]+\]\s*/);
  if (callout) { marker += callout[0]; rest = rest.slice(callout[0].length); }
  if (!rest.trim() || /^(\||<\/?(tr|td|th|table|div|figure|span class="kr")|#)/.test(rest.trim())) return line;
  let body = rest.replace(/<kr>/g, '<span class="kr">').replace(/<\/kr>/g, '</span>');
  if (/<br\s*\/?>/i.test(body)) {
    const parts = body.split(/<br\s*\/?>/i);
    body = parts[0];
    for (const p of parts.slice(1)) body += koreanHeavy(p) && !p.includes('class="kr"') ? `<span class="kr">${p.trim()}</span>` : `<br>${p}`;
  } else if (!body.includes('class="kr"') && koreanHeavy(body)) {
    body = `<span class="kr">${body}</span>`;
  }
  return quote + marker + body;
}

function convertDraft(num, text, ctx) {
  const { marked, shots, manifest, titles, present, report } = ctx;
  const byline = /^\s*>?\s*<span color="\w+">\s*\*?(.*?)\*?\s*<\/span>\s*$/;
  if (num === 'H0') text = dropPageList(text);
  const lines = text.split('\n');
  // the byline (first and last line) is shown once, on the title page; the "# Title" line is the section opener
  for (;;) {
    while (lines.length && (!lines[0].trim() || byline.test(lines[0]))) lines.shift();
    if (lines[0]?.startsWith('# ')) { lines.shift(); continue; }
    break;
  }
  // H0: its "## About this handover" heading repeats the opener's own title
  if (num === 'H0') {
    const dup = lines.findIndex((l) => /^##\s+About this handover\b/i.test(l));
    if (dup >= 0) lines.splice(dup, 1);
  }
  const out = [];
  let fence = false;
  for (let i = 0; i < lines.length; i++) {
    let line = lines[i];
    if (/^\s*```/.test(line)) { fence = !fence; out.push(line); continue; }
    if (fence) { out.push(line); continue; }
    // byline (STYLE_GUIDE.md › Byline): dropped from the section pages
    if (byline.test(line)) continue;
    line = line.replace(/<span color="(\w+)">/g, '<span class="c-$1">');
    // standalone screenshot + caption line
    const shot = line.match(/^\s*\{\{shot:([A-Za-z0-9-]+)\}\}\s*$/);
    if (shot) {
      let caption = '';
      const next = lines[i + 1];
      if (next !== undefined && next.trim() && !/^(#|\{\{|!|\||>|<)/.test(next.trim())) { caption = next.trim(); i++; }
      if (!shots[shot[1]]) fail(`${num}: unknown screenshot ${shot[1]}`);
      out.push('', figure(marked, shot[1], caption, shots, manifest), '');
      continue;
    }
    // toggles → always-expanded boxes
    if (/<\/?details>|<summary>/.test(line)) {
      line = line.replace(/<details>\s*/g, '\n<div class="details">\n')
        .replace(/<summary>(.*?)<\/summary>/g, (_, t) => `<div class="details-title">${marked.parseInline(koreanTitle(t))}</div>\n\n`)
        .replace(/\s*<\/details>/g, '\n\n</div>\n');
      out.push(line);
      continue;
    }
    // a line holding only page links becomes a list item
    if (/^\s*(\{\{page:[A-Za-z0-9]+\}\}\s*)+$/.test(line)) {
      if (out.length && out[out.length - 1].trim() && !/^\s*- /.test(out[out.length - 1])) out.push('');
      out.push(`- ${line.trim()}`);
      if (lines[i + 1]?.trim() && !/^\s*\{\{page:[A-Za-z0-9]+\}\}\s*$/.test(lines[i + 1])) out.push('');
      continue;
    }
    if (/^\s*\{\{test-report-table\}\}\s*$/.test(line)) { out.push('', report, ''); continue; }
    out.push(koreanLine(hasHangul(line) ? cjkBold(line) : line));
  }
  let md = out.join('\n');

  // raw Notion tables: first row becomes the header, cells get inline markdown
  md = md.replace(/<table([^>]*)>([\s\S]*?)<\/table>/g, (_, attrs, inner) => {
    let first = /header-row="true"/.test(attrs);
    const rows = inner.match(/<tr>[\s\S]*?<\/tr>/g) || [];
    const html = rows.map((r) => {
      const cells = [...r.matchAll(/<td>([\s\S]*?)<\/td>/g)].map((c) => c[1]);
      const tag = first ? 'th' : 'td';
      const row = '<tr>' + cells.map((c) => `<${tag}>${marked.parseInline(c)}</${tag}>`).join('') + '</tr>';
      if (first) { first = false; return `<thead>${row}</thead><tbody>`; }
      return row;
    }).join('');
    return `<table class="md">${html}${html.includes('<tbody>') ? '</tbody>' : ''}</table>`;
  });

  // screenshots referenced inside a sentence: "(capture below)" and the figure after the paragraph
  md = md.split('\n\n').map((para) => {
    const ids = [...new Set([...para.matchAll(/\{\{shot:([A-Za-z0-9-]+)\}\}/g)].map((m) => m[1]))];
    if (!ids.length) return para;
    para = para.replace(/\{\{shot:[A-Za-z0-9-]+\}\}/g, (m, off) => {
      const start = para.lastIndexOf('\n', off) + 1;
      return hasHangul(para.slice(start, off)) ? '(아래 캡처)' : '(capture below)';
    });
    para = para.replace(/\(\s*\(capture below\)(?:\s*,\s*\(capture below\))*\s*\)/g, '(captures below)')
      .replace(/\(\s*\(아래 캡처\)(?:\s*,\s*\(아래 캡처\))*\s*\)/g, '(아래 캡처)');
    for (const id of ids) if (!shots[id]) fail(`${num}: unknown screenshot ${id}`);
    return para + '\n\n' + ids.map((id) => figure(marked, id, '', shots, manifest)).join('\n\n');
  }).join('\n\n');

  md = md.replace(PAGE_KEY, (_, raw) => {
    const n = raw === 'root' ? 'H0' : raw;
    if (/^\d\d$/.test(n)) fail(`${num}: {{page:${n}}} is an old chapter key; use H0…H6, XP or X01…X13 (STYLE_GUIDE.md › Two sections)`);
    if (!titles[n]) fail(`${num}: {{page:${n}}} names no page in STYLE_GUIDE.md › Two sections`);
    const label = `→ ${esc(pageLabel(n, titles))}`;
    if (!present.has(n)) { warn(`${num}: {{page:${n}}} links to a page with no draft yet`); return `<span class="xref missing">${label}</span>`; }
    return `<a class="xref" href="#${pageAnchor(n)}">${label}</a>`;
  });
  md = md.replace(/\{\{v1-root\}\}|\{\{v1-14\}\}/g, '<em class="xref-v1">Handover v1 (Notion)</em>');
  const left = md.match(/\{\{[^}]*\}\}/g);
  if (left) fail(`${num}: unknown placeholders ${[...new Set(left)].join(', ')}`);
  try {
    return marked.parse(md);
  } catch (e) {
    fail(`${num}: ${e.message}`);
  }
}

function commitLine(chapters, index) {
  // the root draft states the baseline commit; INDEX.json is the fallback
  const root = chapters.find((c) => c.num === 'H0');
  const m = root && read(root.path).match(/commit ([0-9a-f]{7,40})( plus uncommitted)?/);
  if (m) return `commit ${m[1]}${m[2] ? ' + working-copy changes' : ''}`;
  return index.baseline_commit ? `commit ${index.baseline_commit}` : '';
}

function koreanTitle(t) {
  const cut = t.lastIndexOf(' | ');
  return cut >= 0 && hasHangul(t.slice(cut)) ? `${t.slice(0, cut)} <span class="h-kr">${t.slice(cut + 3)}</span>` : t;
}

// ---------------------------------------------------------------------------------------------- book

function buildHtml(ctx, pagesIn, pages = {}) {
  const pg = (id) => (pages[id] ? String(pages[id]) : '000');
  const about = pagesIn.find((c) => c.num === 'H0');
  const handbook = pagesIn.filter((c) => c.section === 'handbook' && c.num !== 'H0');
  const extended = pagesIn.filter((c) => c.section === 'extended');
  const parts = [];
  for (const [i, part] of PARTS.entries()) {
    const chapters = part.keys.map((k) => handbook.find((c) => c.num === k)).filter(Boolean);
    if (!chapters.length) { warn(`Part "${part.name}" has no drafts yet; left out`); continue; }
    const info = { ...part, roman: ROMAN[i], id: `part-${i + 1}`, chapters };
    for (const ch of chapters) ch.partInfo = info;
    parts.push(info);
  }
  for (const ch of handbook) if (!ch.partInfo) warn(`${ch.num} is in no Part (build.mjs PARTS); left out`);

  const sections = [];
  const logo = pathToFileURL(LOGO).href;
  const cover = `<section class="sec cover" id="cover" data-page="cover">
    <img class="cover-logo" src="${logo}" alt="Kimchi and Chips">
    <div class="cover-main">
      <div class="cover-kicker">Operations &amp; technical handover <span>운영·기술 인수인계</span></div>
      <div class="cover-title">Operations &amp; Technical Handover&nbsp;v2</div>
      <div class="cover-sub">NCT Console</div>
      <div class="cover-kr">${esc(BOOK.titleKr)}</div>
    </div>
    <div class="cover-foot">
      <div class="cover-grid">
        <div><div class="cl">Prepared by</div><div class="cv">Kimchi and Chips</div><div class="ck">김치앤칩스</div></div>
        <div><div class="cl">Prepared for</div><div class="cv">Amberin / Engineering Six</div><div class="ck">앰버린 / 엔지니어링식스</div></div>
        <div><div class="cl">Baseline</div><div class="cv">${esc(ctx.baselineDate)}</div><div class="ck">문서 기준일 2026년 9월 23일</div></div>
        <div><div class="cl">Version</div><div class="cv">Version 2 · NCT Console ${esc(ctx.consoleVersion)}</div><div class="ck">${esc(ctx.commitLine)}</div></div>
      </div>
      <div class="cover-note"><span>This document was written by Kimchi and Chips. Printed ${esc(ctx.built)} from the handover v2 drafts: the handbook, then the extended reference (English) as an appendix.</span></div>
    </div>
  </section>`;
  sections.push({ id: 'cover', html: cover });

  // ---- contents: the handbook, then one level for the appendix pages
  const tocRows = [];
  const tocChapter = (ch) => `<li class="toc-ch"><a href="#sec-${ch.num}"><span class="toc-num">${ch.num}</span><span class="toc-title">${esc(ch.en)}<span class="toc-kr">${esc(ch.kr)}</span></span><span class="toc-dots"></span><span class="toc-pg">${pg(`sec-${ch.num}`)}</span></a></li>`;
  if (about) tocRows.push(`<li class="toc-ch toc-about"><a href="#sec-H0"><span class="toc-num"></span><span class="toc-title">${esc(ABOUT.en)}<span class="toc-kr">${esc(ABOUT.kr)}</span></span><span class="toc-dots"></span><span class="toc-pg">${pg('sec-H0')}</span></a></li>`);
  for (const p of parts) {
    tocRows.push(`<li class="toc-part"><a href="#${p.id}"><span class="toc-num">${p.roman}</span><span class="toc-title">${esc(p.name)}<span class="toc-kr">${esc(p.kr)}</span></span><span class="toc-dots"></span><span class="toc-pg">${pg(p.id)}</span></a></li>`);
    for (const ch of p.chapters) tocRows.push(tocChapter(ch));
  }
  if (extended.length) {
    tocRows.push(`<li class="toc-part toc-appendix"><a href="#appendix"><span class="toc-num">A</span><span class="toc-title">${esc(APPENDIX.en)}<span class="toc-kr">${esc(APPENDIX.kr)}</span></span><span class="toc-dots"></span><span class="toc-pg">${pg('appendix')}</span></a></li>`);
    for (const x of extended) tocRows.push(`<li class="toc-x"><a href="#sec-${x.num}"><span class="toc-num">${x.num}</span><span class="toc-title">${esc(x.en)}</span><span class="toc-dots"></span><span class="toc-pg">${pg(`sec-${x.num}`)}</span></a></li>`);
  }
  sections.push({ id: 'toc', title: 'Contents 목차', html: `<section class="sec toc" id="toc" data-page="toc"><h1 class="toc-head">Contents <span class="h-kr">목차</span></h1><ol class="toc-list">${tocRows.join('\n')}</ol></section>` });

  // ---- handbook
  if (about) {
    sections.push({ id: 'sec-H0', title: ABOUT.en, html: `<section class="sec opening" id="sec-H0" data-page="chH0">
      <header class="opener opener-about"><div class="opener-part">Handbook <span>핸드북</span></div>
      <h1 class="opener-title">${esc(ABOUT.en)}</h1><div class="opener-kr">${esc(ABOUT.kr)}</div></header>
      <div class="body">${about.html}</div></section>` });
  }
  const chapterSection = (ch) => `<section class="sec chapter" id="sec-${ch.num}" data-page="ch${ch.num}">
      <header class="opener"><div class="opener-part">Part ${ch.partInfo.roman} · ${esc(ch.partInfo.name)} <span>${esc(ch.partInfo.kr)}</span></div><div class="opener-num">${ch.num}</div>
      <h1 class="opener-title">${esc(ch.en)}</h1><div class="opener-kr">${esc(ch.kr)}</div></header>
      <div class="body">${ch.html}</div></section>`;
  for (const p of parts) {
    const list = p.chapters.map((c) => `<li><span class="pl-num">${c.num}</span><span class="pl-title">${esc(c.en)}<span>${esc(c.kr)}</span></span><span class="pl-pg">${pg(`sec-${c.num}`)}</span></li>`).join('');
    sections.push({ id: p.id, title: p.name, html: `<section class="sec part" id="${p.id}" data-page="part"><div class="part-inner"><div class="part-roman">Part ${p.roman}</div><h1 class="part-name">${esc(p.name)}</h1><div class="part-kr">${esc(p.kr)}</div><ol class="part-list">${list}</ol></div></section>` });
    for (const ch of p.chapters) sections.push({ id: `sec-${ch.num}`, title: ch.en, html: chapterSection(ch) });
  }

  // ---- appendix: extended reference, compact, English only
  if (extended.length) {
    const list = extended.map((x) => `<li><span class="pl-num">${x.num}</span><span class="pl-title">${esc(x.en)}</span><span class="pl-pg">${pg(`sec-${x.num}`)}</span></li>`).join('');
    sections.push({ id: 'appendix', title: APPENDIX.en, html: `<section class="sec part appendix" id="appendix" data-page="part"><div class="part-inner"><div class="part-roman">Appendix</div><h1 class="part-name">${esc(APPENDIX.en)}</h1><div class="part-kr">${esc(APPENDIX.kr)}</div>
      <p class="appendix-note">English only. For engineers and AI agents: every fact that is not in the handbook, as terse reference pages.<span>영문 전용. 기술자와 AI 에이전트를 위한 참조로, 핸드북에 없는 모든 사실을 담습니다.</span></p>
      <ol class="part-list">${list}</ol></div></section>` });
    for (const x of extended) {
      sections.push({ id: `sec-${x.num}`, title: x.en, html: `<section class="sec xpage" id="sec-${x.num}" data-page="ch${x.num}">
      <header class="xopener"><div class="xopener-label">Appendix · ${x.num}</div><h1 class="xopener-title">${esc(x.en)}</h1></header>
      <div class="body compact">${x.html}</div></section>` });
    }
  }

  sections.push({ id: 'colophon', html: `<section class="sec colophon" id="colophon" data-page="back"><div class="colo-inner">
    <img class="colo-logo" src="${logo}" alt="Kimchi and Chips">
    <p><strong>Operations &amp; Technical Handover v2 — NCT Console.</strong> Prepared by Kimchi and Chips for Amberin / Engineering Six.
    Documentation baseline ${esc(ctx.baselineDate)}; NCT Console ${esc(ctx.consoleVersion)}, ${esc(ctx.commitLine)}.</p>
    <p class="colo-kr">운영·기술 인수인계 v2 — NCT 콘솔. 김치앤칩스가 앰버린 / 엔지니어링식스를 위해 작성했습니다.</p>
    <p class="colo-small">Printed edition of the Notion handover v2 pages, built ${esc(ctx.built)} by <code>console/tools/handover_pdf</code> from
    <code>console/docs/handover_v2/handbook</code> and <code>extended</code>. Screenshots are console captures with example data (<code>console/docs/shots</code>). Set in Inter, Noto Sans KR and JetBrains Mono.</p>
  </div></section>` });

  const cssString = (t) => '"' + t.replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
  const running = (c) => (c.num === 'H0' ? ABOUT.en : c.section === 'extended' ? `Appendix · ${c.num} · ${c.en}` : `${c.num} · ${c.en}`);
  const pageRules = pagesIn.map((c) => {
    const head = cssString(running(c));
    return `#sec-${c.num} { page: ch${c.num}; }\n#sec-${c.num} .diagram.wide { page: ch${c.num}w; }\n`
      + `@page ch${c.num} { @top-right { content: ${head}; } }\n`
      + `@page ch${c.num}w { size: A4 landscape; @top-right { content: ${head}; } }`;
  }).join('\n');
  const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>${esc(BOOK.title)} — ${esc(BOOK.subtitle)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="${FONTS_URL}">
<link rel="stylesheet" href="${pathToFileURL(join(HERE, 'print.css')).href}">
<style>
@page {
  @top-left { content: ${cssString(BOOK.running)}; background-image: url("${logo}"); }
  @bottom-left { content: ${cssString(BOOK.footer + ' · ' + ctx.baselineDate)}; }
  @bottom-right { content: counter(page); }
}
@page toc { @top-right { content: "Contents"; } }
${pageRules}
@page cover { @top-left { content: none; background: none; border: 0; } @top-center { content: none; border: 0; } @top-right { content: none; border: 0; } @bottom-left { content: none; } @bottom-right { content: none; } }
@page back { @top-left { content: none; background: none; border: 0; } @top-center { content: none; border: 0; } @top-right { content: none; border: 0; } @bottom-left { content: none; } @bottom-right { content: none; } }
@page part { @top-left { content: none; background: none; border: 0; } @top-center { content: none; border: 0; } @top-right { content: none; border: 0; } }
</style>
<script src="${MERMAID_URL}"></script>
</head><body>
${sections.map((s) => s.html).join('\n')}
<script>
window.__render = (async () => {
  const fonts = ['400 12px Inter', '600 12px Inter', '700 12px Inter', '800 12px Inter', '400 12px "Noto Sans KR"', '500 12px "Noto Sans KR"', '700 12px "Noto Sans KR"', '400 12px "JetBrains Mono"'];
  await Promise.all(fonts.map((f) => document.fonts.load(f, 'Aa한국어')));
  await document.fonts.ready;
  const errors = [];
  if (!window.mermaid) return { count: 0, errors: ['mermaid did not load from ${MERMAID_URL}'] };
  mermaid.initialize({ startOnLoad: false, theme: 'neutral', securityLevel: 'loose',
    fontFamily: 'Inter, "Noto Sans KR", sans-serif',
    themeVariables: { fontFamily: 'Inter, "Noto Sans KR", sans-serif', fontSize: '13px' },
    flowchart: { htmlLabels: true, useMaxWidth: true, padding: 8, nodeSpacing: 28, rankSpacing: 36, wrappingWidth: 120 },
    sequence: { useMaxWidth: true, wrap: true, width: 120, actorMargin: 28, boxMargin: 6, messageMargin: 28, noteMargin: 8, actorFontSize: 13, messageFontSize: 12.5, noteFontSize: 12.5 } });
  const nodes = [...document.querySelectorAll('pre.mermaid-src')];
  for (const [i, el] of nodes.entries()) {
    const chapter = (el.closest('section')?.id || '?').replace(/^sec-/, '');
    try {
      // Mermaid text is 13 px (9.75 pt) at scale 1; nothing may print below MIN_SCALE (8 pt). Each diagram is tried
      // in its own direction and the other one (LR <-> TD), in the portrait column and on a landscape page; the
      // portrait column wins whenever it keeps the text at 8 pt or more.
      const MIN_SCALE = 0.82;
      const src = el.textContent;
      const box = el.parentElement.getBoundingClientRect();
      const MM = 96 / 25.4;
      const areas = { compact: [box.width - 26, 150 * MM], tall: [box.width - 26, 234 * MM], landscape: [(297 - 34) * MM - 26, (210 - 39 - 14) * MM] };
      const size = (svg) => { const m = svg.match(/viewBox="[-\\d.]+ [-\\d.]+ ([\\d.]+) ([\\d.]+)"/); return m ? [+m[1], +m[2]] : null; };
      const scaleIn = (svg, area) => { const wh = size(svg); return wh ? Math.min(1, area[0] / wh[0], area[1] / wh[1]) : 1; };
      const variants = [{ svg: (await mermaid.render('mmd' + i, src)).svg, flipped: false }];
      const dir = /^(\\s*(?:flowchart|graph))\\s+(LR|RL|TD|TB|BT)\\b/m;
      const m = src.match(dir);
      if (m) {
        const other = /LR|RL/.test(m[2]) ? 'TD' : 'LR';
        variants.push({ svg: (await mermaid.render('mmd' + i + 'b', src.replace(dir, '$1 ' + other))).svg, flipped: true });
      }
      // Preference order (the first that keeps 8 pt wins, otherwise the largest): the author's direction in the column,
      // then the other direction at a normal height, then the author's direction on a landscape page. Prose such as
      // "read left to right" refers to the author's direction, so turning a diagram is a late resort.
      const [own, alt] = variants;
      const order = [[own, 'compact'], [own, 'tall'], [alt, 'compact'], [own, 'landscape'], [alt, 'tall'], [alt, 'landscape']];
      const options = order.filter(([v]) => v).map(([v, where]) => ({ ...v, where, scale: scaleIn(v.svg, areas[where]) }));
      let pick = options.find((o) => o.scale >= MIN_SCALE) || options.slice().sort((x, y) => y.scale - x.scale)[0];
      const wide = pick.where === 'landscape';
      if (pick.flipped) window.__flipped = (window.__flipped || 0) + 1;
      const svg = pick.svg;
      const div = document.createElement('div');
      div.className = 'mermaid-svg';
      div.innerHTML = svg;
      const g = div.querySelector('svg');
      const vb = g && g.viewBox && g.viewBox.baseVal;
      if (vb && vb.width) {
        g.removeAttribute('height');
        g.style.maxWidth = 'none';
        g.style.width = (vb.width * pick.scale) + 'px';
        g.style.height = 'auto';
      }
      window.__minScale = Math.min(window.__minScale || 1, pick.scale);
      (window.__diag ||= []).push(chapter + (' ' + pick.where) + (pick.flipped ? ' flipped' : '') + ' ' + (9.75 * pick.scale).toFixed(1) + 'pt');
      if (wide) {
        // own landscape page: carry the heading it belongs to, so the page makes sense on its own
        const holder = el.parentElement;
        holder.classList.add('wide');
        let h = holder.previousElementSibling;
        while (h && !/^H[2-4]$/.test(h.tagName)) h = h.previousElementSibling;
        if (h) {
          const t = document.createElement('div'); t.className = 'diagram-title'; t.innerHTML = h.innerHTML; holder.prepend(t);
          // a heading directly above the diagram moves onto the landscape page instead of being left orphaned
          if (h === holder.previousElementSibling) h.style.display = 'none';
        }
        window.__wide = (window.__wide || 0) + 1;
      }
      el.replaceWith(div);
    } catch (e) {
      errors.push(chapter + ': ' + (e && e.message ? e.message : String(e)).split('\\n').slice(0, 3).join(' '));
    }
    document.querySelectorAll('#dmmd' + i + ', #mmd' + i + ', #dmmd' + i + 'b, #mmd' + i + 'b').forEach((n) => { if (!n.closest('.mermaid-svg')) n.remove(); });
  }
  // tables: keep short tokens (versions, ids, short code) on one line
  const TOKEN = /[A-Za-z0-9][\\w.#:/+-]*[-.][\\w.#:/+-]*[A-Za-z0-9]/g;
  const HAS_TOKEN = new RegExp(TOKEN.source);
  for (const cell of document.querySelectorAll('table.md td, table.md th')) {
    for (const code of cell.querySelectorAll('code')) if (code.textContent.length <= 26) code.classList.add('nw');
    const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
    const texts = [];
    for (let n = walker.nextNode(); n; n = walker.nextNode()) if (!n.parentElement.closest('code') && HAS_TOKEN.test(n.data)) texts.push(n);
    for (const n of texts) {
      TOKEN.lastIndex = 0;
      const html = n.data.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c])
        .replace(TOKEN, (t) => (t.length <= 20 ? '<span class="nw">' + t + '</span>' : t));
      const span = document.createElement('span');
      span.innerHTML = html;
      n.replaceWith(...span.childNodes);
    }
  }
  // long callouts may split across pages instead of leaving a gap
  for (const c of document.querySelectorAll('.callout')) if (c.getBoundingClientRect().height > 75 * 96 / 25.4) c.classList.add('may-break');
  await Promise.all([...document.images].map((img) => img.complete ? null : new Promise((r) => { img.onload = img.onerror = r; })));
  const broken = [...document.images].filter((img) => !img.naturalWidth).map((img) => img.src);
  for (const b of broken) errors.push('image failed to load: ' + b);
  await document.fonts.ready;
  return { count: nodes.length, flipped: window.__flipped || 0, wide: window.__wide || 0, diag: window.__diag || [], minScale: window.__minScale || 1, errors };
})();
</script>
</body></html>`;
  return { html, sections, parts };
}

// ---------------------------------------------------------------------------------------------- pdf

async function printPdf(page) {
  return page.pdf({ format: 'A4', printBackground: true, preferCSSPageSize: true, displayHeaderFooter: false, outline: true, tagged: true, timeout: 0 });
}

async function countPages(buf) {
  return (await PDFDocument.load(buf, { updateMetadata: false })).getPageCount();
}

// Walks the PDF outline (Chrome builds it from h1…h6) and returns { title → 1-based page } for top-level entries.
async function outlinePages(buf) {
  const doc = await PDFDocument.load(buf, { updateMetadata: false });
  const pageIndex = new Map(doc.getPages().map((p, i) => [p.ref.toString(), i + 1]));
  const ctx = doc.context;
  const lookup = (o) => (o instanceof PDFRef ? ctx.lookup(o) : o);
  const outlines = lookup(doc.catalog.get(PDFName.of('Outlines')));
  const found = [];
  if (!(outlines instanceof PDFDict)) return found;
  const names = new Map();
  const namesDict = lookup(doc.catalog.get(PDFName.of('Names')));
  const destsTree = namesDict instanceof PDFDict ? lookup(namesDict.get(PDFName.of('Dests'))) : null;
  const walkNames = (node) => {
    if (!(node instanceof PDFDict)) return;
    const arr = lookup(node.get(PDFName.of('Names')));
    if (arr instanceof PDFArray) for (let i = 0; i + 1 < arr.size(); i += 2) names.set(lookup(arr.get(i)).decodeText?.() ?? String(arr.get(i)), lookup(arr.get(i + 1)));
    const kids = lookup(node.get(PDFName.of('Kids')));
    if (kids instanceof PDFArray) for (let i = 0; i < kids.size(); i++) walkNames(lookup(kids.get(i)));
  };
  walkNames(destsTree);
  const destPage = (item) => {
    let dest = lookup(item.get(PDFName.of('Dest')));
    const action = lookup(item.get(PDFName.of('A')));
    if (!dest && action instanceof PDFDict) dest = lookup(action.get(PDFName.of('D')));
    if (dest && !(dest instanceof PDFArray)) dest = names.get(dest.decodeText?.() ?? String(dest));
    if (dest instanceof PDFDict) dest = lookup(dest.get(PDFName.of('D')));
    return dest instanceof PDFArray ? pageIndex.get(dest.get(0).toString()) : undefined;
  };
  const walk = (item, depth) => {
    while (item instanceof PDFDict) {
      const title = lookup(item.get(PDFName.of('Title')));
      found.push({ title: title?.decodeText?.() ?? '', page: destPage(item), depth });
      const first = lookup(item.get(PDFName.of('First')));
      if (first) walk(first, depth + 1);
      item = lookup(item.get(PDFName.of('Next')));
    }
  };
  walk(lookup(outlines.get(PDFName.of('First'))), 0);
  return found;
}

async function main() {
  if (!existsSync(CHROME)) fail(`Chrome not found at ${CHROME}; set CHROME_PATH`);
  mkdirSync(TMP, { recursive: true });
  writeFileSync(join(TMP, 'blank.html'), '<!doctype html><title>blank</title>', { encoding: 'utf-8' });
  const map = pageMap();
  const titles = Object.fromEntries(map.map((r) => [r.key, r]));
  titles.H0 ||= { key: 'H0', en: ABOUT.en, kr: ABOUT.kr };
  titles.XP ||= { key: 'XP', en: APPENDIX.en, kr: APPENDIX.kr };
  const present = new Set();
  const chapters = [];   // every page with a draft, in book order (handbook H0…H6, then extended X01…X13)
  const listing = (folder) => (existsSync(join(DOCS, folder)) ? readdirSync(join(DOCS, folder)).filter((f) => f.endsWith('.md') && !f.startsWith('_')) : []);
  for (const section of ['handbook', 'extended']) {
    const files = listing(section);
    for (const row of map.filter((r) => r.section === section && r.file)) {
      const name = row.file.split('/').pop();
      const file = files.includes(name) ? name : files.find((f) => f.startsWith(`${row.key}-`));
      if (!file) { warn(`${row.key} (${row.file}) has no draft yet; left out`); continue; }
      present.add(row.key);
      chapters.push({ ...row, num: row.key, path: join(DOCS, section, file) });
    }
    for (const f of files) if (!chapters.some((c) => c.path === join(DOCS, section, f))) warn(`${section}/${f} is not in the STYLE_GUIDE › Two sections tables; left out`);
  }
  if (!chapters.length) fail(`no handbook/extended drafts under ${DOCS}`);
  if (chapters.some((c) => c.section === 'extended')) present.add('XP');

  let index = {};
  try { index = JSON.parse(read(join(DOCS, 'INDEX.json'))); } catch { /* optional */ }
  const manifest = shotManifest();
  const allText = chapters.map((c) => read(c.path)).join('\n');
  const shotIds = [...new Set([...allText.matchAll(/\{\{shot:([A-Za-z0-9-]+)\}\}/g)].map((m) => m[1]))];

  const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ['--allow-file-access-from-files', '--font-render-hinting=none'] });
  try {
    const shots = await prepareShots(browser, shotIds);
    const ctx = {
      marked: makeMarked(), shots, manifest, titles, present, report: testReportTable(),
      baselineDate: '23 September 2026',
      commitLine: commitLine(chapters, index),
      consoleVersion: index.console_version || '',
      built: new Date().toISOString().slice(0, 10),
    };
    for (const ch of chapters) ch.html = convertDraft(ch.num, read(ch.path), ctx);

    const page = await browser.newPage();
    // lay out at the printed column width (A4 minus the @page side margins) so measured diagram sizes hold in print
    await page.setViewport({ width: Math.round((210 - 34) / 25.4 * 96), height: 1100 });
    await page.emulateMediaType('print');
    page.on('pageerror', (e) => warn(`page error: ${e.message}`));
    const load = async (pages, quiet = false) => {
      const { html, sections } = buildHtml(ctx, chapters, pages);
      const file = join(TMP, 'handover.html');
      writeFileSync(file, html, { encoding: 'utf-8' });
      await page.goto(pathToFileURL(file).href, { waitUntil: 'networkidle0', timeout: 120000 });
      const result = await page.evaluate(() => window.__render);
      if (result.errors.length) fail(`rendering errors:\n  ${result.errors.join('\n  ')}`);
      if (!quiet) console.log(`  diagrams: ${result.flipped} printed in the other direction, ${result.wide} on landscape pages; smallest text ${(9.75 * result.minScale).toFixed(1)} pt`);
      if (!quiet && process.env.HANDOVER_DEBUG) console.log('   ' + result.diag.join('\n   '));
      return { sections, diagrams: result.count, file };
    };

    // Section start pages come from the printed PDF itself: Chrome's outline links every <h1> (contents, part and
    // chapter titles) to the page it landed on. Print, read the pages, fill the contents, print again until stable.
    const squash = (s) => s.replace(/\s+/g, '');
    const locate = async (pdf, sections) => {
      const outline = (await outlinePages(pdf)).filter((o) => o.depth === 0);
      const starts = { cover: 1 };
      let k = 0;
      for (const s of sections) {
        if (!s.title) continue;
        while (k < outline.length && squash(outline[k].title) !== squash(s.title)) k++;
        if (k >= outline.length || outline[k].page === undefined) fail(`section ${s.id} ("${s.title}") not found in the PDF outline`);
        starts[s.id] = outline[k++].page;
      }
      return starts;
    };
    let starts = {};
    let pdf, sections, diagrams, file;
    for (let round = 1; ; round++) {
      ({ sections, diagrams, file } = await load(starts, round > 1));
      pdf = await printPdf(page);
      const found = await locate(pdf, sections);
      if (sections.every((s) => found[s.id] === starts[s.id])) break;
      if (round >= 4) fail('contents page numbers did not settle after 4 prints');
      starts = found;
    }
    const total = await countPages(pdf);
    starts.colophon = total;
    sections.forEach((s, i) => { s.pages = (i + 1 < sections.length ? starts[sections[i + 1].id] : total + 1) - starts[s.id]; });
    writeFileSync(OUT, pdf);
    const hb = chapters.filter((c) => c.section === 'handbook').length;
    const handbookPages = (starts.appendix || total) - 1;   // title page … last handbook page (colophon excluded)
    const appendixPages = starts.appendix ? total - starts.appendix : 0;   // divider … last X page
    console.log(`wrote ${OUT}`);
    console.log(`  ${total} pages, ${hb} handbook + ${chapters.length - hb} extended pages, ${diagrams} diagrams, ${shotIds.length} screenshots; contents page numbers match the PDF outline`);
    console.log(`  handbook: ${handbookPages} pages (title page, contents and Part dividers included); appendix: ${appendixPages} pages (divider included); colophon: 1`);
    console.log(`  intermediate HTML: ${file}`);
    for (const s of sections) console.log(`  ${String(starts[s.id]).padStart(4)}  ${s.id} (${s.pages} p)`);
  } finally {
    await browser.close();
  }
}

main().catch((e) => fail(e.stack || e.message));
