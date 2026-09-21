import type { NextRequest } from "next/server";
import { datasetFrom, json, withPassword } from "@/lib/http";
import { pull } from "@/lib/inventory";

export async function GET(req: NextRequest) {
  const dataset = datasetFrom(req.nextUrl.searchParams.get("dataset"));
  if (!dataset) return json({ error: "Invalid dataset" }, 400);
  return withPassword(req, "check / pull", dataset, async (store) => json(await pull(store, dataset)));
}
