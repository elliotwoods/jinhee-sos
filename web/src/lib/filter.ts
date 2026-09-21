// Pure search / filter / sort for the cube list (shared by the UI and its tests).
import type { Cube } from "./model";

export type SeenWindow = "any" | "1h" | "24h" | "7d" | "older" | "never";
export type SortKey = "number" | "lastSeen" | "changed" | "status" | "mac";
export type Filters = {
  q: string; status: string; role: string; seen: SeenWindow; numbered: "any" | "yes" | "no";
  tagged: "any" | "yes" | "no"; sort: SortKey; desc: boolean;
};
export const DEFAULT_FILTERS: Filters = { q: "", status: "", role: "", seen: "any", numbered: "any", tagged: "any", sort: "number", desc: false };

const HOUR = 3600e3;
const WINDOWS: Record<string, number> = { "1h": HOUR, "24h": 24 * HOUR, "7d": 7 * 24 * HOUR };
const hex = (s: string) => s.replace(/[^0-9a-f]/gi, "").toLowerCase();

/** Free text: number ("#12" or "12"), MAC or NFC with/without separators, detail, computer. */
export function matchesSearch(c: Cube, query: string): boolean {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return terms.every((term) => {
    const n = term.replace(/^#/, "");
    if (/^\d+$/.test(n) && c.number != null && String(c.number) === n) return true;
    const h = hex(term);
    if (h.length >= 2 && [c.mac, c.uid ?? "", c.pendingUid ?? ""].some((v) => hex(v).includes(h))) return true;
    const text = [c.detail, c.status, c.role, c.source, c.uploadedBy, c.lastSeen?.computer, c.lastSeen?.detail]
      .filter(Boolean).join(" ").toLowerCase();
    return text.includes(term);
  });
}

export function seenWithin(c: Cube, window: SeenWindow, now: number): boolean {
  if (window === "any") return true;
  if (window === "never") return !c.lastSeen;
  if (!c.lastSeen) return false;
  const age = now - Date.parse(c.lastSeen.at);
  return window === "older" ? age > 7 * 24 * HOUR : age <= WINDOWS[window];
}

export function applyFilters(cubes: Cube[], f: Filters, now: number): Cube[] {
  const out = cubes.filter((c) =>
    matchesSearch(c, f.q) &&
    (!f.status || (f.status === "pending_any" ? c.status === "pending" || c.status === "unconfirmed" || !!c.pendingUid : c.status === f.status)) &&
    (!f.role || c.role === f.role) &&
    seenWithin(c, f.seen, now) &&
    (f.numbered === "any" || (f.numbered === "yes") === (c.number != null)) &&
    (f.tagged === "any" || (f.tagged === "yes") === (c.uid != null)));
  const key = (c: Cube): number | string => {
    switch (f.sort) {
      case "lastSeen": return c.lastSeen ? Date.parse(c.lastSeen.at) : -Infinity;
      case "changed": return c.updatedAt ? Date.parse(c.updatedAt) : -Infinity;
      case "status": return c.status ?? "~";
      case "mac": return c.mac;
      default: return c.number ?? Infinity;
    }
  };
  const byRecent = f.sort === "lastSeen" || f.sort === "changed";
  return out.sort((a, b) => {
    const ka = key(a), kb = key(b);
    let order = ka < kb ? -1 : ka > kb ? 1 : a.mac.localeCompare(b.mac);
    if (byRecent) order = -order; // most recent first by default
    return f.desc ? -order : order;
  });
}

/** Filters <-> URL query, omitting defaults so links stay short. */
export function toQuery(f: Filters, extra: Record<string, string> = {}): string {
  const params = new URLSearchParams(extra);
  for (const [k, v] of Object.entries(f)) {
    if (v !== DEFAULT_FILTERS[k as keyof Filters]) params.set(k, String(v));
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

export function fromQuery(params: Record<string, string | undefined>): Filters {
  const f = { ...DEFAULT_FILTERS };
  for (const k of Object.keys(f) as (keyof Filters)[]) {
    const v = params[k];
    if (v === undefined) continue;
    (f as Record<string, unknown>)[k] = k === "desc" ? v === "true" : v;
  }
  return f;
}

export function toCsv(cubes: Cube[]): string {
  const cols = ["number", "mac", "uid", "pending_uid", "status", "role", "last_seen", "last_seen_via", "last_seen_by", "last_changed", "detail"];
  const esc = (v: unknown) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const rows = cubes.map((c) => [c.number, c.mac, c.uid, c.pendingUid, c.status, c.role, c.lastSeen?.at, c.lastSeen?.kind,
    c.lastSeen?.computer, c.updatedAt, c.detail].map(esc).join(","));
  return [cols.join(","), ...rows].join("\n") + "\n";
}
