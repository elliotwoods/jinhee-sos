import type { NextRequest } from "next/server";
import { datasetFrom, json } from "@/lib/http";
import { getStore } from "@/lib/store";
import { head } from "@/lib/show";

/** Public on purpose, like the zone database head: version, hash, CRC, size and time only. */
export async function GET(req: NextRequest) {
  const dataset = datasetFrom(req.nextUrl.searchParams.get("dataset"));
  if (!dataset) return json({ error: "Invalid dataset" }, 400);
  return json(await head(getStore(), dataset));
}
