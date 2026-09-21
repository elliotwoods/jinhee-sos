import type { NextRequest } from "next/server";
import { datasetFrom, json, withPassword } from "@/lib/http";
import { current } from "@/lib/zonedb";

export async function GET(req: NextRequest) {
  const dataset = datasetFrom(req.nextUrl.searchParams.get("dataset"));
  if (!dataset) return json({ error: "Invalid dataset" }, 400);
  return withPassword(req, "zone database pull", dataset, async (store) => json(await current(store, dataset)));
}
