export function hhmmss(t) {
  if (!t) return '—';
  const d = typeof t === 'number' ? new Date(t * 1000) : new Date(t);
  if (isNaN(d)) return String(t);
  return d.toTimeString().slice(0, 8);
}
export function ago(seconds) {
  if (seconds == null) return '—';
  if (seconds < 60) return `${Math.round(seconds)} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
}
export function crc(v) { return v == null ? '—' : Number(v).toString(16).toUpperCase().padStart(8, '0'); }
export function cube(row) { return row && row.cube_id != null ? `#${row.cube_id}` : 'no number'; }
export function mmss(seconds) { const s = Math.max(0, Math.floor(seconds || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; }
export function short(text, n = 80) { text = String(text ?? ''); return text.length > n ? text.slice(0, n - 1) + '…' : text; }
export function plural(n, word) { return `${n} ${word}${n === 1 ? '' : 's'}`; }
// Three-step signal strength from an ESP-NOW RSSI (dBm).
export function signalBars(rssi, missing = '') { return rssi == null ? missing : rssi >= -67 ? '▂▄▆' : rssi >= -80 ? '▂▄·' : '▂··'; }
