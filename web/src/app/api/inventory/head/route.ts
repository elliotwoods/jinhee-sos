import type { NextRequest } from "next/server";
import { datasetFrom, json, withPassword } from "@/lib/http";
import { head } from "@/lib/inventory";

export async function GET(req: NextRequest) {
  const dataset = datasetFrom(req.nextUrl.searchParams.get("dataset"));
  if (!dataset) return json({ error: "Invalid dataset" }, 400);
  return withPassword(req, "status check", dataset, async (store) => json(await head(store, dataset)));
}
