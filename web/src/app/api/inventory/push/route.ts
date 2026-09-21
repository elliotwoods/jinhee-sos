import type { NextRequest } from "next/server";
import { datasetFrom, json, readJson, withPassword } from "@/lib/http";
import { push } from "@/lib/inventory";

export async function POST(req: NextRequest) {
  const body = await readJson(req);
  const dataset = datasetFrom(typeof body?.dataset === "string" ? body.dataset : null);
  if (!dataset) return json({ error: "Invalid dataset" }, 400);
  return withPassword(req, "upload", dataset, async (store) => {
    const records = body?.records;
    const bases = body?.base_revisions;
    if (!body || !records || typeof records !== "object" || Array.isArray(records) || !bases || typeof bases !== "object") {
      return json({ error: "dataset, records and base_revisions are required" }, 400);
    }
    const client = typeof body.client === "string" ? body.client.slice(0, 120) : "";
    const result = await push(store, dataset, records as Record<string, unknown>, bases as Record<string, unknown>, client);
    return json(result.body, result.status);
  });
}
