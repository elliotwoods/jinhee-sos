import type { Sighting, SightingsReport, ZoneSighting } from "./store";

const MAC = /^[0-9A-F]{2}(:[0-9A-F]{2}){5}$/;
const KIND = /^[a-z_]{1,20}$/;
export const MAX_CUBES = 5000;
export const MAX_ZONES = 500;

const str = (v: unknown, max = 200) => (typeof v === "string" ? v.slice(0, max) : null);
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const iso = (v: unknown) => (typeof v === "string" && !Number.isNaN(Date.parse(v)) ? new Date(v).toISOString() : null);

/** Validate and normalize a computer's report (from pairing_station/sightings.py collect()). */
export function parseReport(body: Record<string, unknown>, computer: string): SightingsReport | string {
  const cubesIn = body.cubes, zonesIn = body.zones ?? [];
  if (!cubesIn || typeof cubesIn !== "object" || Array.isArray(cubesIn) || !Array.isArray(zonesIn)) return "cubes and zones are required";
  const entries = Object.entries(cubesIn as Record<string, unknown>);
  if (entries.length > MAX_CUBES || zonesIn.length > MAX_ZONES) return "Report too large";
  const cubes: SightingsReport["cubes"] = {};
  for (const [mac, kinds] of entries) {
    if (!MAC.test(mac) || !kinds || typeof kinds !== "object") continue;
    const out: Record<string, Sighting> = {};
    for (const [kind, s] of Object.entries(kinds as Record<string, unknown>)) {
      const at = iso((s as Sighting | null)?.at);
      if (KIND.test(kind) && at) out[kind] = { at, detail: str((s as Sighting).detail) ?? "" };
    }
    if (Object.keys(out).length) cubes[mac] = out;
  }
  const zones: ZoneSighting[] = [];
  for (const z of zonesIn as Record<string, unknown>[]) {
    if (!z || typeof z !== "object" || typeof z.mac !== "string" || !MAC.test(z.mac)) continue;
    zones.push({
      mac: z.mac, name: str(z.name, 80), zone_type: num(z.zone_type), point_id: num(z.point_id), profile: str(z.profile, 80),
      firmware: str(z.firmware, 80), db_version: num(z.db_version), tags: num(z.tags), source: str(z.source, 40),
      last_seen: iso(z.last_seen),
    });
  }
  return { computer, reported_at: new Date().toISOString(), cubes, zones };
}
