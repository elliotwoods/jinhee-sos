// MAC display: the trailing bytes identify a device among ours, so they are shown large and the
// rest small. Two bytes are unique across the inventory today; if two known devices ever share them
// the tail widens to three (then all six) so the emphasised part always identifies one device.
import { section, state } from '../store.js';

const MAC = /^[0-9A-F]{2}(:[0-9A-F]{2}){5}$/i;
let cache = { key: null, tail: 2 };

export function isMac(text) { return typeof text === 'string' && MAC.test(text); }

export function tailLength(macs) {
  const list = [...new Set((macs || []).filter(isMac).map((m) => m.toUpperCase()))];
  for (const n of [2, 3]) {
    const seen = new Set();
    let clash = false;
    for (const m of list) { const t = m.slice(-(3 * n - 1)); if (seen.has(t)) { clash = true; break; } seen.add(t); }
    if (!clash) return n;
  }
  return 6;
}

// Tail length for everything this computer knows about (inventory, zones, USB), memoised per version.
export function knownTail() {
  const v = state.versions || {};
  const key = `${v.inventory}|${v.registry}|${v.devices}`;
  if (cache.key === key) return cache.tail;
  const inv = section('inventory') || {};
  const macs = [...(inv.rows || []).map((r) => r.mac), ...(inv.zones || []).map((z) => z.mac),
    ...((section('registry') || {}).zones || []).map((z) => z.mac), ...(section('devices') || []).map((d) => d.mac)];
  cache = { key, tail: tailLength(macs) };
  return cache.tail;
}

// ['AC:27:6E:82:', '68:54'] for a 2-byte tail.
export function splitMac(mac, tail = 2) {
  const m = String(mac).toUpperCase();
  const at = tail >= 6 ? 0 : m.length - (3 * tail - 1);
  return [m.slice(0, at), m.slice(at)];
}
