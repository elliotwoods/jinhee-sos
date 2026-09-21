// Universal zone database versions. Mirrors zones/tools/zonedb.py (record layout) and the
// NctZone firmware's validRecords(); change them together. Zones accept only a HIGHER
// version, so the server allocates versions and they never go down.
import { createHash } from "node:crypto";
import { type Store, StoreConflict, type ZoneDbDoc } from "./store";

export const RECORD_SIZE = 18; // <IB7s6s: cubeID, uidLength, uid[7], mac[6]
export const SLOT_CAPACITY = Math.floor((0x8000 - 24 - 4) / RECORD_SIZE);
const WRITE_ATTEMPTS = 5;
const MAX_VERSION = 0xffffffff;

export class ZoneDbError extends Error {}

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

export function crc32(data: Uint8Array): number {
  let crc = 0xffffffff;
  for (const byte of data) crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function compareUid(a: Uint8Array, b: Uint8Array): number {
  if (a.length !== b.length) return a.length < b.length ? -1 : 1;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1;
  return 0;
}

/** Validates packed records exactly as the zone firmware would before committing them. */
export function validateImage(body: Uint8Array): number {
  if (body.length === 0) throw new ZoneDbError("Refusing to publish an empty zone database");
  if (body.length % RECORD_SIZE) throw new ZoneDbError("Zone database length is not a whole number of records");
  const count = body.length / RECORD_SIZE;
  if (count > SLOT_CAPACITY) throw new ZoneDbError(`${count} records exceed zone capacity ${SLOT_CAPACITY}`);
  const view = new DataView(body.buffer, body.byteOffset, body.byteLength);
  let previous: Uint8Array | null = null;
  for (let i = 0; i < count; i++) {
    const at = i * RECORD_SIZE;
    const cubeId = view.getUint32(at, true), length = body[at + 4];
    const uidField = body.subarray(at + 5, at + 12), mac = body.subarray(at + 12, at + 18);
    if (cubeId === 0) throw new ZoneDbError(`Record ${i}: cube ID 0`);
    if (length < 1 || length > 7 || uidField.subarray(length).some((b) => b !== 0)) throw new ZoneDbError(`Record ${i}: invalid tag`);
    if (mac[0] & 1 || mac.every((b) => b === 0)) throw new ZoneDbError(`Record ${i}: invalid cube MAC`);
    const uid = uidField.subarray(0, length);
    if (previous && compareUid(previous, uid) >= 0) throw new ZoneDbError(`Record ${i}: tags not sorted/unique`);
    previous = uid;
  }
  return count;
}

export async function current(store: Store, dataset: string): Promise<ZoneDbDoc> {
  return (await store.readZoneDb(dataset)).doc;
}

/**
 * Publishes packed records. Identical content returns the current document unchanged;
 * otherwise the version becomes max(current, minVersion) + 1, where minVersion lets a
 * computer lift the counter above versions already running on zones (legacy local counters).
 */
export async function publish(
  store: Store,
  dataset: string,
  recordsB64: string,
  minVersion: number,
  inventoryRevision: number,
  client: string,
): Promise<{ doc: ZoneDbDoc; changed: boolean }> {
  if (!Number.isInteger(minVersion) || minVersion < 0 || minVersion >= MAX_VERSION) throw new ZoneDbError("Invalid min_version");
  if (!Number.isInteger(inventoryRevision) || inventoryRevision < 0) throw new ZoneDbError("Invalid inventory_revision");
  if (!/^[A-Za-z0-9+/]*={0,2}$/.test(recordsB64)) throw new ZoneDbError("records_b64 is not base64");
  const body = new Uint8Array(Buffer.from(recordsB64, "base64"));
  const count = validateImage(body);
  const hash = createHash("sha256").update(body).digest("hex");
  for (let attempt = 0; ; attempt++) {
    const { doc, etag } = await store.readZoneDb(dataset);
    if (doc.hash === hash && doc.version >= minVersion) return { doc, changed: false };
    const version = Math.max(doc.version, minVersion) + 1;
    if (version > MAX_VERSION) throw new ZoneDbError("Zone database version space exhausted");
    const next: ZoneDbDoc = {
      version, hash, count, crc: crc32(body), records_b64: Buffer.from(body).toString("base64"),
      published_at: new Date().toISOString(), published_by: client, inventory_revision: inventoryRevision,
    };
    try {
      await store.writeZoneDb(dataset, next, etag);
      return { doc: next, changed: true };
    } catch (error) {
      if (!(error instanceof StoreConflict) || attempt + 1 >= WRITE_ATTEMPTS) throw error;
    }
  }
}
