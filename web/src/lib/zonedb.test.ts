import { beforeEach, describe, expect, it } from "vitest";
import { MemoryStore } from "./store";
import { crc32, head, publish, RECORD_SIZE, validateImage, ZoneDbError } from "./zonedb";

function record(cubeId: number, uid: number[], mac = [0x02, 0, 0, 0, 0, cubeId]): Uint8Array {
  const out = new Uint8Array(RECORD_SIZE);
  new DataView(out.buffer).setUint32(0, cubeId, true);
  out[4] = uid.length;
  out.set(uid, 5);
  out.set(mac, 12);
  return out;
}
const pack = (...records: Uint8Array[]) => Buffer.concat(records).toString("base64");
const A = record(5, [4, 0x11, 0x22, 0x33]), B = record(6, [4, 0x11, 0x22, 0x34]);

describe("zone database image", () => {
  it("matches zlib CRC-32", () => {
    expect(crc32(new TextEncoder().encode("123456789"))).toBe(0xcbf43926);
  });
  it("accepts sorted valid records", () => {
    expect(validateImage(Buffer.concat([A, B]))).toBe(2);
  });
  it.each([
    [new Uint8Array(0), "empty"],
    [new Uint8Array(17), "whole number"],
    [Buffer.concat([B, A]), "not sorted"],
    [Buffer.concat([A, A]), "not sorted"],
    [record(0, [1, 2, 3, 4]), "cube ID 0"],
    [record(5, [1, 2, 3, 4], [1, 0, 0, 0, 0, 1]), "MAC"],
    [record(5, []), "invalid tag"],
  ])("rejects %#", (body, message) => {
    expect(() => validateImage(new Uint8Array(body))).toThrow(ZoneDbError);
    expect(() => validateImage(new Uint8Array(body))).toThrow(message);
  });
});

describe("zone database publish", () => {
  let db: MemoryStore;
  beforeEach(() => {
    db = new MemoryStore();
  });

  it("allocates increasing universal versions and ignores identical content", async () => {
    const first = await publish(db, "d", pack(A), 0, 1, "laptop A");
    expect(first).toMatchObject({ changed: true, doc: { version: 1, count: 1, published_by: "laptop A" } });
    expect((await publish(db, "d", pack(A), 0, 1, "laptop B")).changed).toBe(false);
    const second = await publish(db, "d", pack(A, B), 0, 2, "laptop B");
    expect(second.doc.version).toBe(2);
    // A stale laptop republishing old content still moves forward, never back.
    expect((await publish(db, "d", pack(A), 0, 2, "laptop A")).doc.version).toBe(3);
  });

  it("head reveals the version but no records", async () => {
    expect(await head(db, "d")).toEqual({ version: 0, hash: "", count: 0, published_at: null });
    await publish(db, "d", pack(A, B), 0, 1, "x");
    const h = await head(db, "d");
    expect(h).toMatchObject({ version: 1, count: 2 });
    expect(Object.keys(h).sort()).toEqual(["count", "hash", "published_at", "version"]);
  });

  it("lifts the version above min_version (versions already on zones)", async () => {
    await publish(db, "d", pack(A), 0, 1, "x");
    expect((await publish(db, "d", pack(A, B), 40, 1, "x")).doc.version).toBe(41);
    // Same content but zones report something higher: bump so the zones accept it.
    expect((await publish(db, "d", pack(A, B), 50, 1, "x")).doc).toMatchObject({ version: 51, count: 2 });
  });

  it("retries on a concurrent publish", async () => {
    db.beforeWrite = async () => {
      db.beforeWrite = null;
      await publish(db, "d", pack(B), 0, 1, "other");
    };
    const result = await publish(db, "d", pack(A), 0, 1, "me");
    expect(result.doc.version).toBe(2);
    expect((await db.readZoneDb("d")).doc.hash).toBe(result.doc.hash);
  });

  it("rejects bad input without writing", async () => {
    await expect(publish(db, "d", "!!", 0, 0, "x")).rejects.toThrow("base64");
    await expect(publish(db, "d", pack(A), -1, 0, "x")).rejects.toThrow("min_version");
    expect((await db.readZoneDb("d")).etag).toBeNull();
  });
});
