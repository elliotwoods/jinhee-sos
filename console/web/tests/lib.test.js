import test from 'node:test';
import assert from 'node:assert/strict';
import { railEntries, groupOf, deviceLabel, workstationLabel } from '../lib/rail.js';
import { order, group, badge } from '../lib/suggestions.js';
import { inventoryFilter, sortRows } from '../lib/table.js';
import { outcomeText, isSuccess, outcomeTone } from '../lib/ladder.js';
import { Ring } from '../lib/ring.js';

const devices = [
  { id: 'A', port: '/dev/cu.b', role: 'zone', details: { zone_type: 3, point_id: 2, name: 'Pool 2' }, mac: 'AA' },
  { id: 'B', port: '/dev/cu.a', role: 'zone', details: { zone_type: 1, point_id: 1, name: 'Preshow 1' }, mac: 'BB' },
  { id: 'C', port: '/dev/cu.c', role: 'workstation', details: { firmware: 'nct-pairing-1.8-zones', nfc_ok: true }, mac: 'CC' },
  { id: 'D', port: '/dev/cu.d', role: null, presumed: {}, mac: null },
];

test('rail groups and sorts zones by type then point', () => {
  const groups = railEntries(devices, { rows: [] }, { zones: [{ mac: 'ZZ', name: 'Desert 1', zone_type: 2, point_id: 1, in_range: true, db_version: 3, state: 'behind' }] }, {}, '');
  const zones = groups.find((g) => g.key === 'zones').entries.map((e) => e.label);
  assert.deepEqual(zones, ['Preshow 1', 'Pool 2', 'Desert 1']);
  assert.equal(groups[0].entries[0].id, 'computer');
  assert.equal(groupOf(devices[3]), 'unknown');
});

test('one workstation role, four families told apart by the hello', () => {
  assert.equal(groupOf(devices[2]), 'stations');
  assert.equal(groupOf({ role: 'mainshow' }), 'stations');
  assert.equal(workstationLabel({ firmware: 'workstation-1.0.0', nfc_ok: true }), 'Workstation');
  assert.equal(workstationLabel({ firmware: 'workstation-1.0.0', nfc_ok: false }), 'Workstation');
  assert.equal(workstationLabel({ firmware: 'general-radio-1.2.0', nfc_ok: false }), 'General Radio');
  assert.equal(workstationLabel({ firmware: 'mainshow-1.3.0' }), 'Mainshow controller');
  assert.equal(workstationLabel({ firmware: 'nct-pairing-1.8-zones', nfc_ok: true }), 'Pairing station');
  assert.equal(workstationLabel({ firmware: 'nct-pairing-1.8-zones', nfc_ok: false }), 'ESP-NOW dongle');
  assert.equal(workstationLabel(null), 'ESP-NOW dongle');
  assert.equal(deviceLabel(devices[2]), 'Pairing station');
  assert.equal(deviceLabel({ role: 'workstation', details: { firmware: 'nct-pairing-1.8-zones', nfc_ok: false } }), 'ESP-NOW dongle');
  assert.equal(deviceLabel({ role: 'workstation', details: { firmware: 'workstation-1.0.0', nfc_ok: false } }), 'Workstation');
  assert.equal(deviceLabel({ role: 'workstation', details: { firmware: 'general-radio-1.1.0' } }), 'General Radio');
  const groups = railEntries(devices, { rows: [] }, null, {}, 'pairing station');
  assert.deepEqual(groups.find((g) => g.key === 'stations').entries.map((e) => e.label), ['Pairing station']);
});

test('rail search matches MAC and label', () => {
  const groups = railEntries(devices, { rows: [] }, null, {}, 'pool');
  assert.deepEqual(groups.filter((g) => g.key !== 'computer').flatMap((g) => g.entries.map((e) => e.label)), ['Pool 2']);
});

test('suggestions order by severity, actionable, then newest', () => {
  const list = [
    { id: '1', severity: 'info', actions: [], fired_at: 5 }, { id: '2', severity: 'bad', actions: [], fired_at: 1 },
    { id: '3', severity: 'bad', actions: [{ id: 'a' }], fired_at: 0 }, { id: '4', severity: 'warn', actions: [], fired_at: 9 },
  ];
  assert.deepEqual(order(list).map((s) => s.id), ['3', '2', '4', '1']);
});

test('three suggestions of one rule collapse into a group', () => {
  const list = [1, 2, 3].map((n) => ({ id: `r:${n}`, rule: 'zone.db_behind', severity: 'warn', device: `d${n}`, actions: [] }));
  const g = group(list);
  assert.equal(g.length, 1);
  assert.equal(g[0].group.length, 3);
  assert.deepEqual(g[0].members, ['d1', 'd2', 'd3']);
  assert.deepEqual(badge(list, 'd2'), { count: 1, severity: 'warn' });
});

test('inventory filters follow the pairing app', () => {
  const row = { mac: 'AA', cube_id: 44, uid: 'X', role: 'auto', status: 'acknowledged', recent: false, original_number: null };
  assert.equal(inventoryFilter(row, 'All devices', ''), true);
  assert.equal(inventoryFilter(row, 'Registered (ACK)', ''), true);
  assert.equal(inventoryFilter(row, 'Unregistered', ''), false);
  assert.equal(inventoryFilter(row, 'Seen recently', ''), false);
  assert.equal(inventoryFilter({ ...row, role: 'excluded' }, 'All devices', ''), false);
  assert.equal(inventoryFilter({ ...row, role: 'excluded' }, 'All incl. excluded', ''), true);
  assert.equal(inventoryFilter(row, 'All devices', '44'), true);
  assert.equal(inventoryFilter(row, 'All devices', 'zz'), false);
  assert.deepEqual(sortRows([{ a: 2 }, { a: null }, { a: 1 }], 'a').map((r) => r.a), [1, 2, null]);
});

test('the ladder never reads delivered as success', () => {
  const ladder = { delivered: 'Delivered to the radio', verified: 'Verified' };
  assert.equal(isSuccess('delivered'), false);
  assert.equal(isSuccess('verified'), true);
  assert.match(outcomeText({ level: 'delivered' }, ladder), /not yet acknowledged/);
  assert.equal(outcomeTone({ level: 'delivered' }), 'warn');
  assert.equal(outcomeTone({ level: 'failed' }), 'bad');
});

test('ring trims in blocks', () => {
  const r = new Ring(10, 4);
  for (let i = 0; i < 12; i++) r.push(i);
  assert.equal(r.length, 8);
  assert.equal(r.dropped, 4);
  assert.deepEqual(r.last(2), [10, 11]);
});
