export function sortRows(rows, key, dir = 1) {
  if (!key) return rows;
  return [...rows].sort((a, b) => {
    const x = a[key], y = b[key];
    if (x == null && y == null) return 0;
    if (x == null) return 1;
    if (y == null) return -1;
    if (typeof x === 'number' && typeof y === 'number') return (x - y) * dir;
    return String(x).localeCompare(String(y), undefined, { numeric: true }) * dir;
  });
}
export function filterRows(rows, query, keys) {
  if (!query) return rows;
  const q = query.toLowerCase();
  return rows.filter((r) => keys.some((k) => String(r[k] ?? '').toLowerCase().includes(q)));
}
// The pairing app's seven inventory filters (dashboard.matches).
export const FILTERS = ['All devices', 'Seen recently', 'Has original number and connected', 'Registered (ACK)',
  'Unregistered', 'Needs attention', 'All incl. excluded'];
export function inventoryFilter(row, choice, query) {
  if (choice !== 'All incl. excluded' && row.role === 'excluded') return false;
  if (choice === 'Seen recently' && !row.recent) return false;
  if (choice === 'Has original number and connected' && (row.original_number == null || !row.recent)) return false;
  if (choice === 'Registered (ACK)' && row.status !== 'acknowledged') return false;
  if (choice === 'Unregistered' && (row.uid || row.pending_uid)) return false;
  if (choice === 'Needs attention' && !['unconfirmed', 'pending', 'not_transmitted'].includes(row.status)) return false;
  const hay = ['mac', 'cube_id', 'original_number', 'uid', 'pending_uid'].map((k) => row[k] ?? '').join(' ').toLowerCase();
  return hay.includes((query || '').toLowerCase());
}
