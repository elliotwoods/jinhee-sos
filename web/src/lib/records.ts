// Server-side mirror of pairing_station/inventory_sync.py `validate()`. Keep the two in step:
// a record set accepted here must be accepted by every computer's local sync, or that
// computer could never apply it.

export type DeviceRecord = Record<string, unknown> & { mac: string; role: string };

const FULL = ["cube_id", "detail", "mac", "pending_uid", "role", "source", "status", "uid", "updated_at"];
const ROLE_ONLY = ["mac", "role"];
const ROLES = new Set(["auto", "led", "excluded"]);
const TEXT = ["source", "status", "updated_at", "detail"];

export class RecordError extends Error {}

/** Canonical colon-separated upper-case hex with an allowed byte count (Python hex_bytes). */
function isHexBytes(value: unknown, lengths: number[]): value is string {
  return (
    typeof value === "string" &&
    /^[0-9A-F]{2}(?::[0-9A-F]{2})*$/.test(value) &&
    lengths.includes(value.split(":").length)
  );
}

function sameKeys(record: object, keys: string[]): boolean {
  const own = Object.keys(record).sort();
  return own.length === keys.length && own.every((k, i) => k === keys[i]);
}

/** Validate a complete record set keyed by MAC. Throws RecordError with a readable message. */
export function validateRecords(records: Record<string, unknown>): asserts records is Record<string, DeviceRecord> {
  const numbers = new Map<number, string>();
  const tags = new Map<string, string>();
  for (const [mac, value] of Object.entries(records)) {
    if (!isHexBytes(mac, [6]) || typeof value !== "object" || value === null || Array.isArray(value)) {
      throw new RecordError(`Invalid MAC record: ${mac}`);
    }
    const row = value as Record<string, unknown>;
    if (row.mac !== mac) throw new RecordError(`Invalid MAC record: ${mac}`);
    if (!sameKeys(row, FULL) && !sameKeys(row, ROLE_ONLY)) throw new RecordError(`Unexpected fields for ${mac}`);
    if (typeof row.role !== "string" || !ROLES.has(row.role)) throw new RecordError(`Invalid role for ${mac}`);
    if (!("cube_id" in row)) continue;
    const number = row.cube_id;
    if (number !== null) {
      if (typeof number !== "number" || !Number.isInteger(number) || number < 1 || number > 0xffffffff) {
        throw new RecordError(`Invalid number for ${mac}`);
      }
      const owner = numbers.get(number);
      if (owner) throw new RecordError(`Duplicate number ${number}: ${owner} and ${mac}; resolve inventory records first`);
      numbers.set(number, mac);
    }
    for (const field of ["uid", "pending_uid"]) {
      const uid = row[field];
      if (uid === null) continue;
      if (!isHexBytes(uid, [4, 7])) throw new RecordError(`Invalid tag for ${mac}`);
      const owner = tags.get(uid);
      if (owner && owner !== mac) throw new RecordError(`Duplicate NFC ${uid}: ${owner} and ${mac}; resolve inventory records first`);
      tags.set(uid, mac);
    }
    if (!TEXT.every((k) => typeof row[k] === "string")) throw new RecordError(`Invalid text fields for ${mac}`);
  }
}
