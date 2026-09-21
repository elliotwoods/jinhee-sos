// Server-side merge of the inventory document, computer presence and every computer's
// sightings report into one serializable model for the client UI.
import type { InventoryDoc, Presence, SightingsReport } from "./store";

export const KIND_LABELS: Record<string, string> = {
  radio: "radio discovery",
  radio_ack: "radio ack",
  nfc: "NFC scan",
  usb: "USB identify",
  usb_flash: "USB flash",
  zone_tap: "zone tap",
};
export const ZONE_TYPES: Record<number, string> = { 1: "preshow", 2: "desert", 3: "pool", 4: "mainshow" };
export const STATUSES = ["acknowledged", "not_transmitted", "awaiting_tag", "needs_number", "pending", "unconfirmed"] as const;

export type SeenEntry = { kind: string; at: string; detail: string; computer: string };
export type HistoryEntry = { revision: number; at: string; client: string; summary: string };
export type Cube = {
  mac: string; number: number | null; uid: string | null; pendingUid: string | null; status: string | null;
  role: string; source: string | null; detail: string; updatedAt: string | null; revision: number;
  uploadedBy: string; uploadedAt: string | null; seen: SeenEntry[]; lastSeen: SeenEntry | null; history: HistoryEntry[];
};
export type Computer = {
  name: string; lastAt: string; apps: Presence[]; reportedAt: string | null; reportedCubes: number;
};
export type Zone = {
  mac: string; name: string; type: string; point: number | null; profile: string | null; firmware: string | null;
  dbVersion: number | null; tags: number | null; lastSeen: string | null; reporter: string;
};
export type Model = {
  dataset: string; revision: number; lastChange: string | null; generatedAt: string;
  cubes: Cube[]; computers: Computer[]; zones: Zone[]; changes: (HistoryEntry & { mac: string })[];
};

type RecordShape = {
  mac: string; role: string; cube_id?: number | null; uid?: string | null; pending_uid?: string | null;
  status?: string; source?: string; detail?: string; updated_at?: string;
};

const FIELDS = ["cube_id", "uid", "pending_uid", "status", "role"] as const;

export function summarizeChange(before: unknown, after: unknown): string {
  const b = before as RecordShape | null, a = after as RecordShape;
  if (!b) return "added";
  const parts = FIELDS.filter((f) => b[f] !== a[f]).map((f) => `${f === "cube_id" ? "#" : f}: ${b[f] ?? "—"} → ${a[f] ?? "—"}`);
  return parts.join(", ") || "detail / timestamp";
}

const host = (client: string) => client.split(" · ")[0] || client;

export function buildModel(dataset: string, doc: InventoryDoc, presence: Presence[], reports: SightingsReport[]): Model {
  const seenByMac = new Map<string, Map<string, SeenEntry>>();
  for (const report of reports) {
    for (const [mac, kinds] of Object.entries(report.cubes)) {
      const perKind = seenByMac.get(mac) ?? new Map<string, SeenEntry>();
      for (const [kind, s] of Object.entries(kinds)) {
        const current = perKind.get(kind);
        if (!current || s.at > current.at) perKind.set(kind, { kind, at: s.at, detail: s.detail, computer: report.computer });
      }
      seenByMac.set(mac, perKind);
    }
  }
  const historyByMac = new Map<string, HistoryEntry[]>();
  const changes = doc.changes.map((c) => {
    const entry = { revision: c.revision, at: c.at, client: c.client, summary: summarizeChange(c.before, c.after) };
    historyByMac.set(c.mac, [...(historyByMac.get(c.mac) ?? []), entry]);
    return { ...entry, mac: c.mac };
  });
  const cubes: Cube[] = Object.entries(doc.records).map(([mac, stored]) => {
    const r = stored.record as RecordShape;
    const seen = [...(seenByMac.get(mac)?.values() ?? [])].sort((a, b) => b.at.localeCompare(a.at));
    return {
      mac, number: "cube_id" in r ? (r.cube_id ?? null) : null, uid: r.uid ?? null, pendingUid: r.pending_uid ?? null,
      status: r.status ?? null, role: r.role, source: r.source ?? null, detail: r.detail ?? "", updatedAt: r.updated_at ?? null,
      revision: stored.revision, uploadedBy: host(stored.updated_from), uploadedAt: stored.updated_at ?? null,
      seen, lastSeen: seen[0] ?? null, history: historyByMac.get(mac) ?? [],
    };
  });
  const computers = new Map<string, Computer>();
  for (const p of presence) {
    const name = host(p.client);
    const c = computers.get(name) ?? { name, lastAt: p.at, apps: [], reportedAt: null, reportedCubes: 0 };
    c.apps.push(p);
    if (p.at > c.lastAt) c.lastAt = p.at;
    computers.set(name, c);
  }
  for (const report of reports) {
    const c = computers.get(report.computer) ?? { name: report.computer, lastAt: report.reported_at, apps: [], reportedAt: null, reportedCubes: 0 };
    c.reportedAt = report.reported_at;
    c.reportedCubes = Object.keys(report.cubes).length;
    computers.set(report.computer, c);
  }
  const zones = new Map<string, Zone>();
  for (const report of reports) {
    for (const z of report.zones) {
      const current = zones.get(z.mac);
      if (current && (current.lastSeen ?? "") >= (z.last_seen ?? "")) continue;
      zones.set(z.mac, {
        mac: z.mac, name: z.name || z.mac, type: z.zone_type != null ? (ZONE_TYPES[z.zone_type] ?? String(z.zone_type)) : "unconfigured",
        point: z.point_id, profile: z.profile, firmware: z.firmware, dbVersion: z.db_version, tags: z.tags,
        lastSeen: z.last_seen, reporter: report.computer,
      });
    }
  }
  for (const c of computers.values()) c.apps.sort((a, b) => b.at.localeCompare(a.at));
  return {
    dataset, revision: doc.revision, lastChange: doc.changes[0]?.at ?? null, generatedAt: new Date().toISOString(),
    cubes, computers: [...computers.values()].sort((a, b) => b.lastAt.localeCompare(a.lastAt)),
    zones: [...zones.values()].sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true })),
    changes,
  };
}
