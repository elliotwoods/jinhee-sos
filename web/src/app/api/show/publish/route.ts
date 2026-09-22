import type { NextRequest } from "next/server";
import { datasetFrom, json, readJson, withPassword } from "@/lib/http";
import { publish, ShowBusy, ShowError } from "@/lib/show";

export async function POST(req: NextRequest) {
  const body = await readJson(req);
  const dataset = datasetFrom(typeof body?.dataset === "string" ? body.dataset : null);
  if (!dataset) return json({ error: "Invalid dataset" }, 400);
  return withPassword(req, "show publish", dataset, async (store) => {
    if (!body || typeof body.image_b64 !== "string") return json({ error: "image_b64 is required" }, 400);
    const client = typeof body.client === "string" ? body.client.slice(0, 120) : "";
    try {
      const result = await publish(store, dataset, body.source, body.image_b64, Number(body.min_version ?? 0), client);
      return json({ ...result.doc, changed: result.changed });
    } catch (error) {
      if (error instanceof ShowError) return json({ error: error.message }, 400);
      if (error instanceof ShowBusy) return json({ error: error.message, retryable: true }, 503);
      throw error;
    }
  });
}
