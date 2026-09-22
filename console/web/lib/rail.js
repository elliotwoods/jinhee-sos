// Grouping, sorting and search for the device rail. Pure apart from the interface language of its labels.
import { t, tk } from './i18n.js';

export const GROUPS = [
  ['computer', tk('This computer')], ['stations', tk('Stations')], ['zones', tk('Zones')], ['cubes', tk('Cubes (live)')],
  ['bench', tk('Bench')], ['unknown', tk('Unidentified USB')],
];
const ZONE_ORDER = { 1: 0, 2: 1, 3: 2, 4: 3, 5: 4 };

export function groupOf(device) {
  const role = device.role || (device.presumed && device.presumed.role);
  if (role === 'workstation' || role === 'mainshow') return 'stations';
  if (role === 'zone') return 'zones';
  if (role === 'cube') return 'cubes';
  if (['poolcentral', 'preshowbridge', 'pooltest', 'rangetest'].includes(role)) return 'bench';
  return 'unknown';
}

export function matches(text, query) {
  if (!query) return true;
  return String(text || '').toLowerCase().includes(query.toLowerCase());
}

// The family of a role-'workstation' board from its hello, mirroring Python dongle.label: the Workstation
// firmware, a legacy General Radio, the Mainshow controller, else a legacy pairing station or a bare dongle.
export function workstationLabel(details) {
  const d = details || {};
  const fw = String(d.firmware || '');
  if (fw.startsWith('workstation-')) return 'Workstation';
  if (fw.startsWith('general-radio-')) return 'General Radio';
  if (fw.startsWith('mainshow-')) return 'Mainshow controller';
  return d.nfc_ok ? t('Pairing station') : t('ESP-NOW dongle');
}

export function deviceLabel(device) {
  const d = device.details || {};
  if (device.role === 'zone') return d.name || t('Unconfigured zone');
  if (device.role === 'cube') {
    const row = device.presumed && device.presumed.row;
    return row && row.cube_id != null ? t('Cube #{n}', { n: row.cube_id }) : t('Cube (no number)');
  }
  if (device.role === 'workstation') return workstationLabel(d);
  return device.role_label || t('USB device');
}

export function railEntries(devices, inventory, registry, station, query) {
  const entries = [];
  for (const device of devices || []) {
    const label = deviceLabel(device);
    const hay = [label, device.mac, device.port, device.firmware, device.role_label].join(' ');
    if (!matches(hay, query)) continue;
    entries.push({ id: device.id, group: groupOf(device), label, device, sort: sortKey(device) });
  }
  // Zones in radio range but not on USB, from the registry.
  const onUsb = new Set(entries.map((e) => e.device.mac).filter(Boolean));
  for (const z of ((registry && registry.zones) || [])) {
    if (onUsb.has(z.mac) || !z.in_range) continue;
    const label = z.name || z.mac;
    if (!matches([label, z.mac, z.firmware].join(' '), query)) continue;
    entries.push({ id: `zone:${z.mac}`, group: 'zones', label, zone: z, sort: [1, ZONE_ORDER[z.zone_type] ?? 9, z.point_id || 0, label] });
  }
  // Live cubes: recently discovered over the radio or pinned, not on USB.
  const rows = (inventory && inventory.rows) || [];
  for (const row of rows) {
    if (onUsb.has(row.mac) || row.role === 'excluded') continue;
    if (!(row.recent || row.pinned)) continue;
    const label = row.cube_id != null ? t('Cube #{n}', { n: row.cube_id }) : t('Cube {mac}', { mac: row.mac });
    if (!matches([label, row.mac, row.uid].join(' '), query)) continue;
    entries.push({ id: `cube:${row.mac}`, group: 'cubes', label, row, sort: [1, row.cube_id ?? 1e9, row.mac] });
  }
  entries.sort((a, b) => compare(a.sort, b.sort));
  const groups = GROUPS.map(([key, title]) => ({ key, title: t(title), entries: entries.filter((e) => e.group === key) }));
  groups[0].entries.unshift({ id: 'computer', group: 'computer', label: t('USB intake & builds'), sort: [0] });
  return groups.filter((g) => g.entries.length);
}

function sortKey(device) {
  const d = device.details || {};
  if (device.role === 'zone') return [0, ZONE_ORDER[d.zone_type] ?? 9, d.point_id || 0, d.name || ''];
  return [0, device.role || 'zz', device.port];
}

function compare(a, b) {
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const x = a[i], y = b[i];
    if (x === y) continue;
    if (x === undefined) return -1;
    if (y === undefined) return 1;
    if (typeof x === 'number' && typeof y === 'number') return x - y;
    return String(x) < String(y) ? -1 : 1;
  }
  return 0;
}
