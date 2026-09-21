// One JSON document per dataset. Production keeps it in a private Vercel Blob store and
// relies on ETag conditional writes for compare-and-swap; tests and `dev:local` use memory.
import { BlobPreconditionFailedError, get, list, put } from "@vercel/blob";

export type StoredRecord = { record: unknown; revision: number; updated_at: string; updated_from: string };
export type Change = { revision: number; mac: string; before: unknown; after: unknown; client: string; at: string };
export type InventoryDoc = { revision: number; records: Record<string, StoredRecord>; changes: Change[] };

/** Last contact from one computer/app. Stored per client so it never contends with the inventory. */
export type Presence = { client: string; action: string; at: string; ip: string };

/** The document changed between read and write; re-read and try again. */
export class StoreConflict extends Error {}

export interface Store {
  read(dataset: string): Promise<{ doc: InventoryDoc; etag: string | null }>;
  /** etag null = create only (fails if someone created it meanwhile). */
  write(dataset: string, doc: InventoryDoc, etag: string | null): Promise<void>;
  touch(dataset: string, presence: Presence): Promise<void>;
  presence(dataset: string): Promise<Presence[]>;
}

export const emptyDoc = (): InventoryDoc => ({ revision: 0, records: {}, changes: [] });
const pathFor = (dataset: string) => `inventory/${dataset}.json`;
const presencePrefix = (dataset: string) => `presence/${dataset}/`;
const slug = (client: string) => client.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 80) || "unknown";

export class BlobStore implements Store {
  async read(dataset: string) {
    const result = await get(pathFor(dataset), { access: "private", useCache: false });
    if (!result || result.statusCode !== 200) return { doc: emptyDoc(), etag: null };
    const doc = JSON.parse(await new Response(result.stream).text()) as InventoryDoc;
    // Uncached reads return a weak ETag (W/"…", same hash); conditional writes need the strong form.
    return { doc, etag: result.blob.etag.replace(/^W\//, "") };
  }

  async write(dataset: string, doc: InventoryDoc, etag: string | null) {
    try {
      await put(pathFor(dataset), JSON.stringify(doc), {
        access: "private",
        contentType: "application/json",
        addRandomSuffix: false,
        ...(etag ? { ifMatch: etag } : { allowOverwrite: false }),
      });
    } catch (error) {
      if (error instanceof BlobPreconditionFailedError) throw new StoreConflict("Inventory changed during write");
      // A create-only write fails if another push created the document first.
      if (!etag && (await this.read(dataset)).etag) throw new StoreConflict("Inventory created during write");
      throw error;
    }
  }

  async touch(dataset: string, presence: Presence) {
    await put(presencePrefix(dataset) + slug(presence.client) + ".json", JSON.stringify(presence), {
      access: "private", contentType: "application/json", addRandomSuffix: false, allowOverwrite: true,
    });
  }

  async presence(dataset: string) {
    const { blobs } = await list({ prefix: presencePrefix(dataset), limit: 200 });
    const entries = await Promise.all(blobs.map(async (b) => {
      try {
        const result = await get(b.pathname, { access: "private", useCache: false });
        return result?.statusCode === 200 ? (JSON.parse(await new Response(result.stream).text()) as Presence) : null;
      } catch {
        return null;
      }
    }));
    return entries.filter((e): e is Presence => e !== null);
  }
}

export class MemoryStore implements Store {
  private docs = new Map<string, { json: string; etag: string }>();
  private counter = 0;
  /** Test hook: runs once just before the next write, to simulate a concurrent writer. */
  beforeWrite: (() => Promise<void>) | null = null;

  async read(dataset: string) {
    const entry = this.docs.get(dataset);
    return entry ? { doc: JSON.parse(entry.json) as InventoryDoc, etag: entry.etag } : { doc: emptyDoc(), etag: null };
  }

  async write(dataset: string, doc: InventoryDoc, etag: string | null) {
    const hook = this.beforeWrite;
    this.beforeWrite = null;
    if (hook) await hook();
    if ((this.docs.get(dataset)?.etag ?? null) !== etag) throw new StoreConflict("Inventory changed during write");
    this.docs.set(dataset, { json: JSON.stringify(doc), etag: `m${++this.counter}` });
  }

  private seen = new Map<string, Presence>();

  async touch(dataset: string, presence: Presence) {
    this.seen.set(presencePrefix(dataset) + slug(presence.client), presence);
  }

  async presence(dataset: string) {
    return [...this.seen].filter(([k]) => k.startsWith(presencePrefix(dataset))).map(([, v]) => v);
  }
}

let store: Store | null = null;
export function getStore(): Store {
  if (!store) {
    store = process.env.INVENTORY_STORE === "memory" && process.env.NODE_ENV !== "production" ? new MemoryStore() : new BlobStore();
  }
  return store;
}
