// The truth ladder. Only 'acknowledged' and 'verified' may read as success.
export const LEVELS = ['sent', 'delivered', 'acknowledged', 'verified', 'failed'];
export function isSuccess(level) { return level === 'verified' || level === 'acknowledged'; }
export function outcomeText(outcome, ladder) {
  if (!outcome) return '';
  const level = outcome.level || 'failed';
  const label = (ladder && ladder[level]) || level;
  const next = level === 'delivered' ? ' — not yet acknowledged by the device' : level === 'sent' ? ' — no delivery confirmation' : '';
  return `${label}${next}${outcome.text ? ': ' + outcome.text : ''}`;
}
export function outcomeTone(outcome) {
  if (!outcome) return 'muted';
  if (outcome.level === 'failed') return 'bad';
  return isSuccess(outcome.level) ? 'ok' : 'warn';
}
