import type { NextRequest } from "next/server";
import { datasetFrom, json, readJson, withPassword } from "@/lib/http";
import { parseReport } from "@/lib/sightings";

/** A computer replaces its own cube/zone "last seen" report (telemetry, not inventory records). */
export async function POST(req: NextRequest) {
  const body = await readJson(req);
  const dataset = datasetFrom(typeof body?.dataset === "string" ? body.dataset : null);
  if (!body || !dataset) return json({ error: "Invalid dataset" }, 400);
  return withPassword(req, "report sightings", dataset, async (store) => {
    const computer = (req.headers.get("x-inventory-client") ?? "").split(" · ")[0].slice(0, 80) || "unnamed computer";
    const report = parseReport(body, computer);
    if (typeof report === "string") return json({ error: report }, 400);
    await store.reportSightings(dataset, report);
    return json({ cubes: Object.keys(report.cubes).length, zones: report.zones.length });
  });
}
