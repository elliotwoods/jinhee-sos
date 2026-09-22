import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { t, hint, normalise, applyLang, localCopy } from '../lib/i18n.js';
import KO from '../lib/ko.js';

const WEB = join(dirname(fileURLToPath(import.meta.url)), '..');

function sources(dir = WEB, out = []) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (['vendor', 'tests', 'ko'].includes(name)) continue;
    if (statSync(path).isDirectory()) sources(path, out);
    else if (name.endsWith('.js') && name !== 'ko.js' && name !== 'i18n.js') out.push(path);
  }
  return out;
}

// Every literal passed to t()/hint(), in '…', "…" or `…` (without ${} inside) quotes.
function literals() {
  const found = new Map();
  const re = /\b(?:t|hint)\(\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"|`((?:[^`\\$]|\\.)*)`)/g;
  for (const path of sources()) {
    for (const m of readFileSync(path, 'utf-8').matchAll(re)) {
      const raw = m[1] ?? m[2] ?? m[3];
      const text = raw.replace(/\\(['"`\\])/g, '$1');
      if (!found.has(text)) found.set(text, path.slice(WEB.length + 1));
    }
  }
  return found;
}

test('language names fall back to English', () => {
  assert.equal(normalise('ko'), 'ko');
  assert.equal(normalise('en'), 'en');
  assert.equal(normalise('fr'), 'en');
  assert.equal(normalise(null), 'en');
});

test('t() falls back to English, fills placeholders, and hint() names the English label in Korean', () => {
  applyLang('en', { persist: false });
  assert.equal(t('Hold: {label}', { label: 'Sync' }), 'Hold: Sync');
  assert.equal(t('not in the dictionary {n}', { n: 3 }), 'not in the dictionary 3');
  assert.equal(hint('Needs:'), 'Needs:');
  applyLang('ko', { persist: false });
  assert.equal(t('Hold: {label}', { label: 'Sync' }), KO['Hold: {label}'].replace('{label}', 'Sync'));
  assert.equal(t('not in the dictionary'), 'not in the dictionary');
  assert.equal(hint('Needs:'), `${KO['Needs:']} · EN: Needs:`);
  applyLang('en', { persist: false });
});

test('uitext copy takes the Korean fields only in Korean', () => {
  const copy = { panels: { a: { title: 'A', what: 'w', check: 'c' } }, status: { s: { label: 'L', tone: 'ok', tip: 't' } }, actions: {},
    ladder: { sent: 'Sent' }, glossary: {}, ko: { panels: { a: { title: '에이' } }, status: { s: { label: '엘' } }, actions: {}, ladder: { sent: '보냄' } } };
  applyLang('en', { persist: false });
  assert.equal(localCopy(copy), copy);
  applyLang('ko', { persist: false });
  const ko = localCopy(copy);
  assert.equal(ko.panels.a.title, '에이');
  assert.equal(ko.panels.a.what, 'w');
  assert.equal(ko.status.s.tone, 'ok');
  assert.equal(ko.status.s.label, '엘');
  assert.equal(ko.ladder.sent, '보냄');
  assert.equal(copy.panels.a.title, 'A');
  applyLang('en', { persist: false });
});

test('every t()/hint() literal has a Korean entry, and every entry is used', () => {
  const used = literals();
  assert.ok(used.size > 0);
  const missing = [...used].filter(([text]) => !Object.prototype.hasOwnProperty.call(KO, text)).map(([text, file]) => `${file}: ${text}`);
  assert.deepEqual(missing, [], 'literals without a ko.js entry');
  const unused = Object.keys(KO).filter((k) => !used.has(k));
  assert.deepEqual(unused, [], 'ko.js entries no t()/hint() uses');
});

test('Korean entries keep their placeholders and are not empty', () => {
  for (const [en, ko] of Object.entries(KO)) {
    assert.ok(ko && ko.trim(), en);
    const names = (s) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort().join(',');
    assert.equal(names(ko), names(en), `placeholders differ: ${en}`);
  }
});
