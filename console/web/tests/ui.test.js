import test from 'node:test';
import assert from 'node:assert/strict';
import { normalise, colour, ledToken, cssVar } from '../lib/theme.js';
import { signalBars } from '../lib/format.js';
import { syncTone } from '../lib/tones.js';
import { notify, dismiss, onNotify } from '../lib/notify.js';

test('theme names fall back to dark', () => {
  assert.equal(normalise('dark'), 'dark');
  assert.equal(normalise('light'), 'light');
  assert.equal(normalise('system'), 'system');
  assert.equal(normalise('blue'), 'dark');
  assert.equal(normalise(null), 'dark');
});

test('colours resolve tokens, pass device literals through, and fall back without a document', () => {
  assert.equal(cssVar('--text', 'fallback'), 'fallback');
  assert.equal(colour('--chart-1', 'x'), 'x');
  assert.equal(colour('#123456'), '#123456');
  assert.equal(colour('', 'y'), 'y');
});

test('LED ring token follows identify, then acknowledgement', () => {
  assert.equal(ledToken({ status: 'acknowledged', telemetry: { command: 'identify' } }), '--led-identify');
  assert.equal(ledToken({ status: 'acknowledged' }), '--led-white');
  assert.equal(ledToken({ status: 'pending' }), '--led-off');
  assert.equal(ledToken(null), '--led-off');
});

test('signal bars and sync tones', () => {
  assert.equal(signalBars(-60), '▂▄▆');
  assert.equal(signalBars(-75), '▂▄·');
  assert.equal(signalBars(-90), '▂··');
  assert.equal(signalBars(null, '—'), '—');
  assert.equal(syncTone('error'), 'bad');
  assert.equal(syncTone('nonsense'), 'muted');
});

test('errors stay until dismissed; other toasts expire', async () => {
  let seen = [];
  const off = onNotify((items) => { seen = items; });
  const bad = notify('broken', 'bad');
  notify('fine', 'ok', 10);
  assert.equal(seen.length, 2);
  await new Promise((r) => setTimeout(r, 30));
  assert.deepEqual(seen.map((i) => i.text), ['broken']);
  dismiss(bad);
  assert.equal(seen.length, 0);
  off();
});

test('MAC tails: two bytes unless two known devices share them', async () => {
  const { tailLength, splitMac, isMac } = await import('../lib/mac.js');
  assert.equal(isMac('AC:27:6E:82:68:54'), true);
  assert.equal(isMac('AC:27:6E:82:68'), false);
  assert.equal(tailLength(['AC:27:6E:82:68:54', '1C:DB:D4:F0:A8:30']), 2);
  assert.equal(tailLength(['AC:27:6E:82:68:54', '1C:DB:D4:F0:68:54']), 3);
  assert.equal(tailLength(['AC:27:6E:82:68:54', '1C:DB:D4:82:68:54']), 6);
  assert.deepEqual(splitMac('ac:27:6e:82:68:54', 2), ['AC:27:6E:82:', '68:54']);
  assert.deepEqual(splitMac('AC:27:6E:82:68:54', 3), ['AC:27:6E:', '82:68:54']);
  assert.deepEqual(splitMac('AC:27:6E:82:68:54', 6), ['', 'AC:27:6E:82:68:54']);
});
