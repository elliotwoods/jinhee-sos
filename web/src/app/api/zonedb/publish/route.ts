import type { NextRequest } from "next/server";
import { datasetFrom, json, readJson, withPassword } from "@/lib/http";
import { publish, ZoneDbBusy, ZoneDbError } from "@/lib/zonedb";

export async function POST(req: NextRequest) {
  const body = await readJson(req);
  const dataset = datasetFrom(typeof body?.dataset === "string" ? body.dataset : null);
  if (!dataset) return json({ error: "Invalid dataset" }, 400);
  return withPassword(req, "zone database publish", dataset, async (store) => {
    if (!body || typeof body.records_b64 !== "string") return json({ error: "records_b64 is required" }, 400);
    const client = typeof body.client === "string" ? body.client.slice(0, 120) : "";
    try {
      const result = await publish(store, dataset, body.records_b64, Number(body.min_version ?? 0),
                                   Number(body.inventory_revision ?? 0), client);
      return json({ ...result.doc, changed: result.changed });
    } catch (error) {
      if (error instanceof ZoneDbError) return json({ error: error.message }, 400);
      if (error instanceof ZoneDbBusy) return json({ error: error.message, retryable: true }, 503);
      throw error;
    }
  });
}
