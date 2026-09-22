import test from 'node:test';
import assert from 'node:assert/strict';
import { parseDoc, docSelector, applyHighlights, useDocOpen } from '../lib/doc.js';
import { state } from '../store.js';

test('parseDoc reads every field and tolerates a leading ?', () => {
  const doc = parseDoc('?hl=rail,attention.card:tag.known_zone_behind,css:.rail-item&open=pairing.register&dock=1&theme=light&still=1&explainers=1&search=%2344');
  assert.deepEqual(doc.hl, ['rail', 'attention.card:tag.known_zone_behind', 'css:.rail-item']);
  assert.deepEqual(doc.open, ['pairing.register']);
  assert.equal(doc.dock, true);
  assert.equal(doc.theme, 'light');
  assert.equal(doc.still, true);
  assert.equal(doc.explainers, true);
  assert.equal(doc.search, '#44');
  assert.equal(doc.cube, null);
  assert.equal(parseDoc('cube=44').cube, 44);
  assert.equal(parseDoc('cube=x').cube, null);
});

test('parseDoc defaults: empty query, unknown theme, dock=0', () => {
  assert.deepEqual(parseDoc(''), { hl: [], open: [], dock: false, theme: null, still: false, explainers: false, search: '', cube: null });
  assert.deepEqual(parseDoc(undefined).hl, []);
  const doc = parseDoc('theme=blue&dock=0&hl=,,relay.table,');
  assert.equal(doc.theme, null);
  assert.equal(doc.dock, false);
  assert.deepEqual(doc.hl, ['relay.table']);
});

test('docSelector: exact, prefix and raw css tokens', () => {
  assert.equal(docSelector('rail'), '[data-doc="rail"]');
  assert.equal(docSelector('relay.zone:14:63:93:C0:EC:14'), '[data-doc="relay.zone:14:63:93:C0:EC:14"]');
  assert.equal(docSelector('attention.action*'), '[data-doc^="attention.action"]');
  assert.equal(docSelector('css:tr.selected > td'), 'tr.selected > td');
  assert.equal(docSelector('a"b'), '[data-doc="a\\"b"]');
  assert.equal(docSelector(''), null);
});

test('useDocOpen reads the open tokens parsed at boot', () => {
  const before = state.ui.doc;
  state.ui.doc = { ...parseDoc('open=attention.menu,sync.signin'), active: true };
  assert.equal(useDocOpen('attention.menu'), true);
  assert.equal(useDocOpen('sync.signin'), true);
  assert.equal(useDocOpen('pairing.register'), false);
  state.ui.doc = before;
  assert.equal(useDocOpen('attention.menu'), false);
});

test('applyHighlights outlines matches, drops stale ones and scrolls the first once', () => {
  const made = [];
  const el = (doc, cls = []) => {
    const classes = new Set(cls);
    const e = { dataset: { doc }, scrolled: 0, classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c), contains: (c) => classes.has(c) }, scrollIntoView() { this.scrolled += 1; } };
    made.push(e);
    return e;
  };
  const a = el('rail'), b = el('rail:usb1'), stale = el('other', ['doc-hl']);
  const root = {
    querySelectorAll(selector) {
      if (selector === '.doc-hl') return made.filter((e) => e.classList.contains('doc-hl'));
      const m = selector.match(/^\[data-doc(\^?)="(.*)"\]$/);
      if (!m) throw new Error('bad selector ' + selector);
      return made.filter((e) => (m[1] ? e.dataset.doc.startsWith(m[2]) : e.dataset.doc === m[2]));
    },
  };
  assert.equal(applyHighlights({ hl: ['rail', 'rail:*'] }, root), 2);
  assert.equal(a.classList.contains('doc-hl'), true);
  assert.equal(b.classList.contains('doc-hl'), true);
  assert.equal(stale.classList.contains('doc-hl'), false);
  assert.equal(a.scrolled + b.scrolled, 1);
  applyHighlights({ hl: ['rail'] }, root);
  assert.equal(b.classList.contains('doc-hl'), false);
  assert.equal(a.scrolled + b.scrolled, 1, 'scrolls only once per page');
  assert.equal(applyHighlights({ hl: [] }, root), 0);
  assert.equal(applyHighlights({ hl: ['css:bad['] }, { querySelectorAll() { throw new Error('bad'); } }), 0);
});
