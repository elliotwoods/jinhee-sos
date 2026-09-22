// One JSON document per dataset. Production keeps it in a private Vercel Blob store and
// relies on ETag conditional writes for compare-and-swap; tests and `dev:local` use memory.
import { BlobPreconditionFailedError, get, list, put } from "@vercel/blob";

export type StoredRecord = { record: unknown; revision: number; updated_at: string; updated_from: string };
export type Change = { revision: number; mac: string; before: unknown; after: unknown; client: string; at: string };
export type InventoryDoc = { revision: number; records: Record<string, StoredRecord>; changes: Change[] };

/** The zone database image the zones run, with its universal version (see zonedb.ts). */
export type ZoneDbDoc = {
  version: number; hash: string; count: number; crc: number; records_b64: string;
  published_at: string | null; published_by: string; inventory_revision: number;
};

/** The main show the cubes play, with its universal version (see show.ts). `source` is the editor JSON. */
export type ShowDoc = {
  version: number; hash: string; crc: number; length: number; image_b64: string; source: unknown;
  published_at: string | null; published_by: string;
};

/** Last contact from one computer/app. Stored per client so it never contends with the inventory. */
export type Presence = { client: string; action: string; at: string; ip: string };

/** One computer's evidence of when each cube (and zone board) was last physically seen. */
export type Sighting = { at: string; detail: string };
export type ZoneSighting = {
  mac: string; name: string | null; zone_type: number | null; point_id: number | null; profile: string | null;
  firmware: string | null; db_version: number | null; tags: number | null; source: string | null; last_seen: string | null;
};
export type SightingsReport = {
  computer: string; reported_at: string; cubes: Record<string, Record<string, Sighting>>; zones: ZoneSighting[];
};

/** The document changed between read and write; re-read and try again. */
export class StoreConflict extends Error {}

export interface Store {
  read(dataset: string): Promise<{ doc: InventoryDoc; etag: string | null }>;
  /** etag null = create only (fails if someone created it meanwhile). */
  write(dataset: string, doc: InventoryDoc, etag: string | null): Promise<void>;
  readZoneDb(dataset: string): Promise<{ doc: ZoneDbDoc; etag: string | null }>;
  /** Same compare-and-swap contract as write(). */
  writeZoneDb(dataset: string, doc: ZoneDbDoc, etag: string | null): Promise<void>;
  readShow(dataset: string): Promise<{ doc: ShowDoc; etag: string | null }>;
  /** Same compare-and-swap contract as write(). */
  writeShow(dataset: string, doc: ShowDoc, etag: string | null): Promise<void>;
  touch(dataset: string, presence: Presence): Promise<void>;
  presence(dataset: string): Promise<Presence[]>;
  /** Replace one computer's sightings report (one blob per computer: no contention). */
  reportSightings(dataset: string, report: SightingsReport): Promise<void>;
  sightings(dataset: string): Promise<SightingsReport[]>;
}

export const emptyDoc = (): InventoryDoc => ({ revision: 0, records: {}, changes: [] });
export const emptyZoneDb = (): ZoneDbDoc => ({
  version: 0, hash: "", count: 0, crc: 0, records_b64: "", published_at: null, published_by: "", inventory_revision: 0,
});
export const emptyShow = (): ShowDoc => ({
  version: 0, hash: "", crc: 0, length: 0, image_b64: "", source: null, published_at: null, published_by: "",
});
const pathFor = (dataset: string) => `inventory/${dataset}.json`;
const showPath = (dataset: string) => `show/${dataset}.json`;
const zoneDbPath = (dataset: string) => `zonedb/${dataset}.json`;
const presencePrefix = (dataset: string) => `presence/${dataset}/`;
const sightingsPrefix = (dataset: string) => `sightings/${dataset}/`;
const slug = (client: string) => client.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 80) || "unknown";

export class BlobStore implements Store {
  private async readPath<T>(path: string, empty: () => T) {
    const result = await get(path, { access: "private", useCache: false });
    if (!result || result.statusCode !== 200) return { doc: empty(), etag: null };
    const doc = JSON.parse(await new Response(result.stream).text()) as T;
    // Uncached reads return a weak ETag (W/"…", same hash); conditional writes need the strong form.
    return { doc, etag: result.blob.etag.replace(/^W\//, "") };
  }

  private async writePath(path: string, doc: unknown, etag: string | null) {
    try {
      await put(path, JSON.stringify(doc), {
        access: "private",
        contentType: "application/json",
        addRandomSuffix: false,
        ...(etag ? { ifMatch: etag } : { allowOverwrite: false }),
      });
    } catch (error) {
      if (error instanceof BlobPreconditionFailedError) throw new StoreConflict("Document changed during write");
      // A create-only write fails if another writer created the document first.
      if (!etag && (await this.readPath(path, () => null)).etag) throw new StoreConflict("Document created during write");
      throw error;
    }
  }

  read(dataset: string) {
    return this.readPath(pathFor(dataset), emptyDoc);
  }

  write(dataset: string, doc: InventoryDoc, etag: string | null) {
    return this.writePath(pathFor(dataset), doc, etag);
  }

  readZoneDb(dataset: string) {
    return this.readPath(zoneDbPath(dataset), emptyZoneDb);
  }

  writeZoneDb(dataset: string, doc: ZoneDbDoc, etag: string | null) {
    return this.writePath(zoneDbPath(dataset), doc, etag);
  }

  async readShow(dataset: string) {
    return this.readPath(showPath(dataset), emptyShow);
  }

  writeShow(dataset: string, doc: ShowDoc, etag: string | null) {
    return this.writePath(showPath(dataset), doc, etag);
  }

  async touch(dataset: string, presence: Presence) {
    await put(presencePrefix(dataset) + slug(presence.client) + ".json", JSON.stringify(presence), {
      access: "private", contentType: "application/json", addRandomSuffix: false, allowOverwrite: true,
    });
  }

  private async readAll<T>(prefix: string): Promise<T[]> {
    const { blobs } = await list({ prefix, limit: 200 });
    const entries = await Promise.all(blobs.map(async (b) => {
      try {
        const result = await get(b.pathname, { access: "private", useCache: false });
        return result?.statusCode === 200 ? (JSON.parse(await new Response(result.stream).text()) as T) : null;
      } catch {
        return null;
      }
    }));
    return entries.filter((e): e is Awaited<T> => e !== null) as T[];
  }

  presence(dataset: string) {
    return this.readAll<Presence>(presencePrefix(dataset));
  }

  async reportSightings(dataset: string, report: SightingsReport) {
    await put(sightingsPrefix(dataset) + slug(report.computer) + ".json", JSON.stringify(report), {
      access: "private", contentType: "application/json", addRandomSuffix: false, allowOverwrite: true,
    });
  }

  sightings(dataset: string) {
    return this.readAll<SightingsReport>(sightingsPrefix(dataset));
  }
}

export class MemoryStore implements Store {
  private docs = new Map<string, { json: string; etag: string }>();
  private counter = 0;
  /** Test hook: runs once just before the next write, to simulate a concurrent writer. */
  beforeWrite: (() => Promise<void>) | null = null;

  private readPath<T>(key: string, empty: () => T) {
    const entry = this.docs.get(key);
    return entry ? { doc: JSON.parse(entry.json) as T, etag: entry.etag } : { doc: empty(), etag: null };
  }

  private async writePath(key: string, doc: unknown, etag: string | null) {
    const hook = this.beforeWrite;
    this.beforeWrite = null;
    if (hook) await hook();
    if ((this.docs.get(key)?.etag ?? null) !== etag) throw new StoreConflict("Document changed during write");
    this.docs.set(key, { json: JSON.stringify(doc), etag: `m${++this.counter}` });
  }

  async read(dataset: string) {
    return this.readPath(pathFor(dataset), emptyDoc);
  }

  write(dataset: string, doc: InventoryDoc, etag: string | null) {
    return this.writePath(pathFor(dataset), doc, etag);
  }

  async readZoneDb(dataset: string) {
    return this.readPath(zoneDbPath(dataset), emptyZoneDb);
  }

  writeZoneDb(dataset: string, doc: ZoneDbDoc, etag: string | null) {
    return this.writePath(zoneDbPath(dataset), doc, etag);
  }

  async readShow(dataset: string) {
    return this.readPath(showPath(dataset), emptyShow);
  }

  writeShow(dataset: string, doc: ShowDoc, etag: string | null) {
    return this.writePath(showPath(dataset), doc, etag);
  }

  private seen = new Map<string, Presence>();

  async touch(dataset: string, presence: Presence) {
    this.seen.set(presencePrefix(dataset) + slug(presence.client), presence);
  }

  async presence(dataset: string) {
    return [...this.seen].filter(([k]) => k.startsWith(presencePrefix(dataset))).map(([, v]) => v);
  }

  private reports = new Map<string, string>();

  async reportSightings(dataset: string, report: SightingsReport) {
    this.reports.set(sightingsPrefix(dataset) + slug(report.computer), JSON.stringify(report));
  }

  async sightings(dataset: string) {
    return [...this.reports].filter(([k]) => k.startsWith(sightingsPrefix(dataset))).map(([, v]) => JSON.parse(v) as SightingsReport);
  }
}

// On globalThis so every route bundle shares one store (dev bundles each route separately).
const shared = globalThis as unknown as { nctInventoryStore?: Store };
export function getStore(): Store {
  if (!shared.nctInventoryStore) {
    shared.nctInventoryStore = process.env.INVENTORY_STORE === "memory" && process.env.NODE_ENV !== "production" ? new MemoryStore() : new BlobStore();
  }
  return shared.nctInventoryStore;
}
