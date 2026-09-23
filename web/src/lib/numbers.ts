import { backoff } from "./inventory";
import { type Store, StoreConflict } from "./store";

/** Numbers below this are the original installation's; new cubes start here (as suggested_number() does). */
export const FIRST_NUMBER = 33;
export const MAX_NUMBER = 0xffffffff;
const WRITE_ATTEMPTS = 5;

export class NumberError extends Error {}
export class NumbersBusy extends Error {}

/**
 * Hand out the next free cube number to one MAC, so two computers numbering new cubes at the same time
 * never pick the same one. Free means: not held by another MAC's inventory record, not claimed earlier by
 * another MAC, and not in `exclude` (the caller's local numbers and reserved numbers, which the web may not
 * have yet). Idempotent: a MAC that already has a number in the inventory, or an earlier claim, gets that
 * number back. Claims live in their own document (compare-and-swap); the inventory is never written here,
 * the claiming computer uploads the record through the normal sync.
 */
export async function claim(store: Store, dataset: string, mac: string, exclude: number[], client: string,
                            min = FIRST_NUMBER): Promise<{ number: number; existing: boolean }> {
  if (!/^[0-9A-F]{2}(:[0-9A-F]{2}){5}$/.test(mac)) throw new NumberError("mac must be AA:BB:CC:DD:EE:FF (upper case)");
  if (!Number.isInteger(min) || min < 1) throw new NumberError("min must be a positive integer");
  for (let attempt = 0; ; attempt++) {
    const [{ doc: inventory }, { doc, etag }] = await Promise.all([store.read(dataset), store.readNumbers(dataset)]);
    const own = inventory.records[mac]?.record as { cube_id?: unknown } | undefined;
    if (own && typeof own.cube_id === "number") return { number: own.cube_id, existing: true };
    for (const [number, c] of Object.entries(doc.claims)) {
      if (c.mac === mac) return { number: Number(number), existing: true };
    }
    const taken = new Set<number>(exclude.filter((n) => Number.isInteger(n)));
    for (const [other, r] of Object.entries(inventory.records)) {
      const n = (r.record as { cube_id?: unknown } | null)?.cube_id;
      if (other !== mac && typeof n === "number") taken.add(n);
    }
    for (const number of Object.keys(doc.claims)) taken.add(Number(number));
    let number = min;
    while (taken.has(number)) number++;
    if (number > MAX_NUMBER) throw new NumberError("No free cube numbers remain");
    doc.claims[String(number)] = { mac, client, at: new Date().toISOString() };
    try {
      await store.writeNumbers(dataset, doc, etag);
      return { number, existing: false };
    } catch (error) {
      if (!(error instanceof StoreConflict)) throw error;
      if (attempt + 1 >= WRITE_ATTEMPTS) throw new NumbersBusy("Other computers are claiming numbers; try again");
      await backoff(attempt);
    }
  }
}
