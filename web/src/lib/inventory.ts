import { RecordError, validateRecords } from "./records";
import { type Store, StoreConflict } from "./store";

export const DATASET_PATTERN = /^[a-z0-9][a-z0-9-]{0,62}$/;
export const MAX_RECORDS = 5000;
const KEEP_CHANGES = 500;
const WRITE_ATTEMPTS = 5;

export async function head(store: Store, dataset: string) {
  const { doc } = await store.read(dataset);
  return { revision: doc.revision, count: Object.keys(doc.records).length, updated_at: doc.changes[0]?.at ?? null };
}

export async function pull(store: Store, dataset: string) {
  const { doc } = await store.read(dataset);
  const records: Record<string, { record: unknown; revision: number }> = {};
  for (const [mac, r] of Object.entries(doc.records)) records[mac] = { record: r.record, revision: r.revision };
  return { revision: doc.revision, records };
}

export type PushResult =
  | { status: 200; body: { revision: number; changed: number } }
  | { status: 409; body: { error: string; records: Record<string, { record: unknown; revision: number }> } }
  | { status: 400; body: { error: string } };

/**
 * Compare-and-swap upload. Every pushed MAC names the revision it was merged against
 * (0 = new); if any differs, nothing is written and the current records come back (409) so
 * the client can re-merge. The complete post-push set must pass the same validation as the
 * local sync. Records are never deleted. Each accepted push advances the revision by exactly
 * 1, and the whole document is written conditionally, so concurrent pushes are re-checked
 * against each other instead of overwriting.
 */
export async function push(
  store: Store,
  dataset: string,
  records: Record<string, unknown>,
  baseRevisions: Record<string, unknown>,
  client: string,
): Promise<PushResult> {
  const macs = Object.keys(records);
  if (macs.length === 0) return { status: 400, body: { error: "Nothing to push" } };
  if (macs.length > MAX_RECORDS) return { status: 400, body: { error: "Too many records" } };
  for (const mac of macs) {
    if (typeof baseRevisions[mac] !== "number") return { status: 400, body: { error: `Missing base revision for ${mac}` } };
  }
  for (let attempt = 0; ; attempt++) {
    const { doc, etag } = await store.read(dataset);
    const stale: Record<string, { record: unknown; revision: number }> = {};
    for (const mac of macs) {
      const existing = doc.records[mac];
      if ((existing?.revision ?? 0) !== baseRevisions[mac]) {
        stale[mac] = existing ? { record: existing.record, revision: existing.revision } : { record: null, revision: 0 };
      }
    }
    if (Object.keys(stale).length > 0) {
      return { status: 409, body: { error: "Records changed since your last pull", records: stale } };
    }
    const merged: Record<string, unknown> = {};
    for (const [mac, r] of Object.entries(doc.records)) merged[mac] = r.record;
    Object.assign(merged, records);
    try {
      validateRecords(merged);
    } catch (error) {
      if (error instanceof RecordError) return { status: 400, body: { error: error.message } };
      throw error;
    }
    const revision = doc.revision + 1;
    const at = new Date().toISOString();
    let changed = 0;
    for (const mac of macs) {
      const before = doc.records[mac]?.record ?? null;
      if (JSON.stringify(before) === JSON.stringify(records[mac])) continue;
      changed++;
      doc.records[mac] = { record: records[mac], revision, updated_at: at, updated_from: client };
      doc.changes.unshift({ revision, mac, before, after: records[mac], client, at });
    }
    doc.revision = revision;
    doc.changes = doc.changes.slice(0, KEEP_CHANGES);
    try {
      await store.write(dataset, doc, etag);
      return { status: 200, body: { revision, changed } };
    } catch (error) {
      if (!(error instanceof StoreConflict) || attempt + 1 >= WRITE_ATTEMPTS) throw error;
    }
  }
}

export async function snapshot(store: Store, dataset: string) {
  return (await store.read(dataset)).doc;
}
