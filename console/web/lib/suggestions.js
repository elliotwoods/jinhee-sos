// Ordering, grouping and scoping of advisor suggestions. Pure.
import { severityRank } from './tones.js';

export function order(list, selectedDevice) {
  return [...(list || [])].sort((a, b) => {
    const s = severityRank(a.severity) - severityRank(b.severity);
    if (s) return s;
    const act = (b.actions?.length ? 1 : 0) - (a.actions?.length ? 1 : 0);
    if (act) return act;
    const sel = (b.device === selectedDevice ? 1 : 0) - (a.device === selectedDevice ? 1 : 0);
    if (sel) return sel;
    return (b.fired_at || 0) - (a.fired_at || 0);
  });
}

export function group(list) {
  // ≥3 suggestions sharing one rule collapse into one card carrying the members.
  const byRule = new Map();
  for (const s of list) { if (!byRule.has(s.rule)) byRule.set(s.rule, []); byRule.get(s.rule).push(s); }
  const out = [];
  const seen = new Set();
  for (const s of list) {
    if (seen.has(s.id)) continue;
    const members = byRule.get(s.rule);
    if (members.length >= 3 && members.every((m) => !m.actions?.length || m.actions.length === members[0].actions.length)) {
      members.forEach((m) => seen.add(m.id));
      out.push({ ...s, id: `group:${s.rule}`, group: members, title: `${members.length} × ${s.rule.replace(/[._]/g, ' ')}`, members: members.map((m) => m.device || m.title) });
    } else { seen.add(s.id); out.push(s); }
  }
  return out;
}

export function forDevice(list, deviceId, mac) {
  return (list || []).filter((s) => s.device === deviceId || (mac && s.scope && s.scope.endsWith(mac)));
}

export function badge(list, deviceId, mac) {
  const mine = forDevice(list, deviceId, mac);
  if (!mine.length) return null;
  const worst = mine.reduce((w, s) => (severityRank(s.severity) < severityRank(w) ? s.severity : w), 'info');
  return { count: mine.length, severity: worst };
}
