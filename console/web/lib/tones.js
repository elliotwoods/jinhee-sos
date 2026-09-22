export const TONES = ['ok', 'warn', 'bad', 'info', 'muted'];
export const GLYPHS = { ok: '●', warn: '▲', bad: '✕', info: '◐', muted: '○' };
export function glyph(tone) { return GLYPHS[tone] || GLYPHS.muted; }
export function toneOf(status) {
  return ({ acknowledged: 'ok', unconfirmed: 'warn', pending: 'info', not_transmitted: 'info', awaiting_tag: 'info',
    needs_number: 'bad', discovered: 'muted', current: 'ok', behind: 'warn', ahead: 'bad', updating: 'info',
    unpublished: 'bad', done: 'ok', failed: 'bad', running: 'info', cancelled: 'warn', queued: 'muted',
    delivered: 'info', verified: 'ok', sent: 'muted' })[status] || 'muted';
}
export function severityRank(s) { return { bad: 0, warn: 1, info: 2 }[s] ?? 3; }
// The sync status tone reported by the backend → a UI tone.
export function syncTone(tone) { return ({ ok: 'ok', pending: 'warn', error: 'bad', muted: 'muted', busy: 'info' })[tone] || 'muted'; }
