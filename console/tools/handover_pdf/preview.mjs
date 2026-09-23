#!/usr/bin/env node
// Rasterises pages of the built PDF to PNG for a visual check (macOS: uses sips).
//   node preview.mjs 1 2 17 [--pdf path] [--out dir]
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join, dirname, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { PDFDocument } from 'pdf-lib';

const HERE = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const opt = (name, dflt) => { const i = args.indexOf(name); return i >= 0 ? args.splice(i, 2)[1] : dflt; };
const pdfPath = resolve(opt('--pdf', join(HERE, '..', '..', 'docs', 'NCT_Console_Handover_v2.pdf')));
const outDir = resolve(opt('--out', join(process.env.HANDOVER_TMP || join(tmpdir(), 'nct-handover-pdf'), 'preview')));
mkdirSync(outDir, { recursive: true });
const src = await PDFDocument.load(readFileSync(pdfPath));
for (const n of args.map(Number)) {
  const one = await PDFDocument.create();
  const [p] = await one.copyPages(src, [n - 1]);
  one.addPage(p);
  const pdf = join(outDir, `page-${n}.pdf`);
  const png = join(outDir, `page-${n}.png`);
  writeFileSync(pdf, await one.save());
  execFileSync('sips', ['-s', 'format', 'png', '-Z', '1400', pdf, '--out', png], { stdio: 'ignore' });
  console.log(png);
}
