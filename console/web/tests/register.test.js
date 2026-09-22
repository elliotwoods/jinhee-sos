import test from 'node:test';
import assert from 'node:assert/strict';
import { stepStates } from '../lib/register.js';

const steps = ['usb', 'number', 'nfc', 'sync'];

test('no cube: every step is still to do', () => {
  assert.deepEqual(stepStates({ steps, step: 'idle' }), { usb: 'todo', number: 'todo', nfc: 'todo', sync: 'todo' });
});

test('scanning: USB and number done, NFC current or waiting', () => {
  assert.deepEqual(stepStates({ steps, mac: 'x', step: 'nfc' }), { usb: 'done', number: 'done', nfc: 'current', sync: 'todo' });
  assert.equal(stepStates({ steps, mac: 'x', step: 'nfc', wait: 'Connect the pairing station' }).nfc, 'waiting');
});

test('a failure marks the step it happened in', () => {
  assert.deepEqual(stepStates({ steps, mac: 'x', step: 'failed', failed_step: 'sync' }), { usb: 'done', number: 'done', nfc: 'done', sync: 'failed' });
  assert.equal(stepStates({ steps, mac: 'x', step: 'failed', failed_step: 'nfc' }).nfc, 'failed');
});

test('done: every step done', () => {
  assert.deepEqual(stepStates({ steps, mac: 'x', step: 'done' }), { usb: 'done', number: 'done', nfc: 'done', sync: 'done' });
});
