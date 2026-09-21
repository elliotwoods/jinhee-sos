import type { NextRequest } from "next/server";
import { datasetFrom, json } from "@/lib/http";
import { getStore } from "@/lib/store";
import { head } from "@/lib/zonedb";

/**
 * Public on purpose: only the version, count, hash and time, so every app can warn "pull the
 * new zone database" without the (never stored) password. Records stay behind the password.
 */
export async function GET(req: NextRequest) {
  const dataset = datasetFrom(req.nextUrl.searchParams.get("dataset"));
  if (!dataset) return json({ error: "Invalid dataset" }, 400);
  return json(await head(getStore(), dataset));
}
