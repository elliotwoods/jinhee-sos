import type { NextRequest } from "next/server";
import { datasetFrom, json, readJson, withPassword } from "@/lib/http";
import { claim, FIRST_NUMBER, NumberError, NumbersBusy } from "@/lib/numbers";

/** POST {dataset, mac, exclude?: number[], min?: number, client?} -> {number, existing}: the next free cube number. */
export async function POST(req: NextRequest) {
  const body = await readJson(req);
  const dataset = datasetFrom(typeof body?.dataset === "string" ? body.dataset : null);
  if (!dataset) return json({ error: "Invalid dataset" }, 400);
  return withPassword(req, "number claim", dataset, async (store) => {
    if (!body || typeof body.mac !== "string") return json({ error: "mac is required" }, 400);
    const exclude = Array.isArray(body.exclude) ? body.exclude.filter((n): n is number => typeof n === "number").slice(0, 10000) : [];
    const client = typeof body.client === "string" ? body.client.slice(0, 120) : "";
    try {
      return json(await claim(store, dataset, body.mac, exclude, client, Number(body.min ?? FIRST_NUMBER)));
    } catch (error) {
      if (error instanceof NumberError) return json({ error: error.message }, 400);
      if (error instanceof NumbersBusy) return json({ error: error.message, retryable: true }, 503);
      throw error;
    }
  });
}
