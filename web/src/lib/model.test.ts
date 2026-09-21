import { describe, expect, it } from "vitest";
import { applyFilters, DEFAULT_FILTERS, fromQuery, matchesSearch, toCsv, toQuery } from "./filter";
import { buildModel } from "./model";
import { parseReport } from "./sightings";
import type { InventoryDoc, SightingsReport } from "./store";

const rec = (mac: string, n: number | null, uid: string | null, status = "acknowledged", updated = "2026-09-20T00:00:00+00:00") =>
  ({ mac, cube_id: n, uid, pending_uid: null, source: "paired", status, updated_at: updated, detail: "", role: "auto" });

const doc: InventoryDoc = {
  revision: 3,
  records: {
    "AC:27:6E:00:00:01": { record: rec("AC:27:6E:00:00:01", 12, "04:AA:BB:CC"), revision: 1, updated_at: "2026-09-20T00:00:00Z", updated_from: "bench · CLI" },
    "AC:27:6E:00:00:02": { record: rec("AC:27:6E:00:00:02", 3, null, "needs_number"), revision: 2, updated_at: "2026-09-20T00:00:00Z", updated_from: "laptop · Web Sync" },
    "3C:0F:02:AD:83:24": { record: { mac: "3C:0F:02:AD:83:24", role: "excluded" }, revision: 1, updated_at: "2026-09-20T00:00:00Z", updated_from: "bench · CLI" },
  },
  changes: [
    { revision: 3, mac: "AC:27:6E:00:00:01", before: rec("AC:27:6E:00:00:01", 11, "04:AA:BB:CC"), after: rec("AC:27:6E:00:00:01", 12, "04:AA:BB:CC"), client: "bench · CLI", at: "2026-09-21T10:00:00Z" },
  ],
};
const reports: SightingsReport[] = [
  { computer: "bench", reported_at: "2026-09-21T11:00:00Z", zones: [], cubes: {
    "AC:27:6E:00:00:01": { radio: { at: "2026-09-21T10:30:00.000Z", detail: "discovery reply" }, nfc: { at: "2026-09-20T09:00:00.000Z", detail: "04:AA:BB:CC" } } } },
  { computer: "laptop", reported_at: "2026-09-21T11:05:00Z", cubes: {
    "AC:27:6E:00:00:01": { radio: { at: "2026-09-21T10:50:00.000Z", detail: "discovery reply" } } },
    zones: [{ mac: "14:63:93:C0:EC:14", name: "Preshow 4", zone_type: 1, point_id: 4, profile: null, firmware: "preshow-2.2.0", db_version: 7, tags: 5, source: "radio", last_seen: "2026-09-21T10:00:00.000Z" }] },
];
const now = Date.parse("2026-09-21T11:10:00Z");

describe("buildModel", () => {
  const model = buildModel("d", doc, [{ client: "bench · Pairing app", action: "status check", at: "2026-09-21T11:08:00Z", ip: "" }], reports);
  const cube = model.cubes.find((c) => c.number === 12)!;

  it("takes the latest sighting per kind across computers", () => {
    expect(cube.lastSeen).toMatchObject({ kind: "radio", computer: "laptop", at: "2026-09-21T10:50:00.000Z" });
    expect(cube.seen.map((s) => s.kind)).toEqual(["radio", "nfc"]);
    expect(cube.history[0].summary).toBe("#: 11 → 12");
  });

  it("merges computers from presence and reports, and zone boards", () => {
    expect(model.computers.map((c) => c.name)).toEqual(["bench", "laptop"]);
    expect(model.computers[0]).toMatchObject({ reportedCubes: 1, apps: [{ action: "status check" }] });
    expect(model.zones[0]).toMatchObject({ name: "Preshow 4", type: "preshow", reporter: "laptop" });
  });

  it("searches, filters and sorts", () => {
    const f = DEFAULT_FILTERS;
    expect(matchesSearch(cube, "#12")).toBe(true);
    expect(matchesSearch(cube, "ac276e000001")).toBe(true);
    expect(matchesSearch(cube, "04:aa")).toBe(true);
    expect(matchesSearch(cube, "laptop")).toBe(true);
    expect(matchesSearch(cube, "13")).toBe(false);
    expect(applyFilters(model.cubes, f, now).map((c) => c.number)).toEqual([3, 12, null]);
    expect(applyFilters(model.cubes, { ...f, seen: "1h" }, now).map((c) => c.number)).toEqual([12]);
    expect(applyFilters(model.cubes, { ...f, seen: "never" }, now)).toHaveLength(2);
    expect(applyFilters(model.cubes, { ...f, status: "needs_number" }, now).map((c) => c.number)).toEqual([3]);
    expect(applyFilters(model.cubes, { ...f, role: "excluded" }, now)).toHaveLength(1);
    expect(applyFilters(model.cubes, { ...f, tagged: "yes" }, now).map((c) => c.number)).toEqual([12]);
    expect(applyFilters(model.cubes, { ...f, sort: "lastSeen" }, now)[0].number).toBe(12);
    expect(applyFilters(model.cubes, { ...f, desc: true }, now)[0].number).toBe(null);
  });

  it("round-trips filters through the URL and exports CSV", () => {
    const f = { ...DEFAULT_FILTERS, q: "#12", seen: "24h" as const, desc: true };
    const q = toQuery(f, { tab: "zones" });
    expect(q).toContain("tab=zones");
    expect(fromQuery(Object.fromEntries(new URLSearchParams(q)))).toEqual(f);
    expect(toQuery(DEFAULT_FILTERS)).toBe("");
    const csv = toCsv([cube]);
    expect(csv.split("\n")[1]).toContain("12,AC:27:6E:00:00:01,04:AA:BB:CC");
  });
});

describe("parseReport", () => {
  it("keeps valid sightings and zones, drops junk", () => {
    const report = parseReport({
      cubes: {
        "AC:27:6E:00:00:01": { radio: { at: "2026-09-21T10:00:00+00:00", detail: "x" }, "BAD KIND": { at: "2026-09-21T10:00:00Z" }, nfc: { at: "nope" } },
        "not-a-mac": { radio: { at: "2026-09-21T10:00:00Z" } },
      },
      zones: [{ mac: "14:63:93:C0:EC:14", name: "Preshow 4", zone_type: 1, last_seen: "2026-09-21T17:16:54+09:00" }, { mac: "x" }],
    }, "bench");
    expect(typeof report).toBe("object");
    if (typeof report === "string") return;
    expect(Object.keys(report.cubes)).toEqual(["AC:27:6E:00:00:01"]);
    expect(Object.keys(report.cubes["AC:27:6E:00:00:01"])).toEqual(["radio"]);
    expect(report.zones).toHaveLength(1);
    expect(report.zones[0].last_seen).toBe("2026-09-21T08:16:54.000Z");
    expect(parseReport({ cubes: [] }, "b")).toBe("cubes and zones are required");
  });
});
