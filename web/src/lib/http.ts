import { timingSafeEqual } from "node:crypto";
import { after, NextResponse, type NextRequest } from "next/server";
import { DATASET_PATTERN } from "./inventory";
import { getStore, type Store } from "./store";

export const DEFAULT_DATASET = "jinhee-sos";

/**
 * One shared password for every computer, set only as the INVENTORY_PASSWORD environment
 * variable (never in source). Unset means every request is refused.
 */
export function password(): string {
  return process.env.INVENTORY_PASSWORD ?? "";
}

export function passwordMatches(presented: string | null | undefined): boolean {
  const expected = password();
  if (!presented || !expected) return false;
  const a = Buffer.from(presented), b = Buffer.from(expected);
  return a.length === b.length && timingSafeEqual(a, b);
}

export function json(body: unknown, status = 200) {
  return NextResponse.json(body, { status, headers: { "Cache-Control": "no-store" } });
}

export function datasetFrom(value: string | null | undefined): string | null {
  const dataset = value || DEFAULT_DATASET;
  return DATASET_PATTERN.test(dataset) ? dataset : null;
}

/** Session cookie for the web page: a hash of the password, so changing the password logs everyone out. */
export const SESSION_COOKIE = "nct_inventory_session";

export async function sessionValue(secret = password()): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`nct-inventory:${secret}`));
  return Buffer.from(digest).toString("hex");
}

/**
 * `Authorization: Bearer <password>` guard for the desktop API. Successful calls record
 * "last seen" for the calling computer (X-Inventory-Client) after the response is sent.
 */
export async function withPassword(
  req: NextRequest,
  action: string,
  dataset: string,
  handler: (store: Store) => Promise<Response>,
): Promise<Response> {
  const presented = req.headers.get("authorization")?.match(/^Bearer\s+(.+)$/i)?.[1];
  if (!passwordMatches(presented)) return json({ error: "Wrong inventory password" }, 401);
  const store = getStore();
  const client = (req.headers.get("x-inventory-client") ?? "").slice(0, 120) || "unnamed client";
  const ip = (req.headers.get("x-forwarded-for") ?? "").split(",")[0].trim();
  after(() => store.touch(dataset, { client, action, at: new Date().toISOString(), ip }).catch(() => {}));
  return handler(store);
}

export async function readJson(req: NextRequest): Promise<Record<string, unknown> | null> {
  try {
    const body = await req.json();
    return body && typeof body === "object" && !Array.isArray(body) ? body : null;
  } catch {
    return null;
  }
}
