import { beforeEach, describe, expect, it } from "vitest";
import { ago } from "./ago";
import { passwordMatches, sessionValue } from "./http";
import { head, pull, push } from "./inventory";
import { RecordError, validateRecords } from "./records";
import { MemoryStore, StoreConflict } from "./store";

const actor = "test";

function device(mac: string, cube_id: number | null, uid: string | null = null) {
  return { mac, cube_id, uid, pending_uid: null, source: "paired", status: "acknowledged", updated_at: "2026-09-21T00:00:00+00:00", detail: "", role: "auto" };
}

describe("validateRecords (mirror of inventory_sync.validate)", () => {
  it("accepts full and role-only records", () => {
    validateRecords({ "02:00:00:00:00:01": device("02:00:00:00:00:01", 5, "04:11:22:33"), "02:00:00:00:00:02": { mac: "02:00:00:00:00:02", role: "excluded" } });
  });
  it.each([
    [{ "02:00:00:00:00:01": { ...device("02:00:00:00:00:01", 5), extra: 1 } }, "Unexpected fields"],
    [{ "02:00:00:00:00:01": device("02:00:00:00:00:02", 5) }, "Invalid MAC"],
    [{ "02:00:00:00:00:0a": device("02:00:00:00:00:0a", 5) }, "Invalid MAC"],
    [{ "02:00:00:00:00:01": { ...device("02:00:00:00:00:01", 5), role: "cube" } }, "Invalid role"],
    [{ "02:00:00:00:00:01": device("02:00:00:00:00:01", 0) }, "Invalid number"],
    [{ "02:00:00:00:00:01": device("02:00:00:00:00:01", 1.5) }, "Invalid number"],
    [{ "02:00:00:00:00:01": device("02:00:00:00:00:01", 5, "04:11:22") }, "Invalid tag"],
    [{ "02:00:00:00:00:01": device("02:00:00:00:00:01", 5), "02:00:00:00:00:02": device("02:00:00:00:00:02", 5) }, "Duplicate number 5"],
    [{ "02:00:00:00:00:01": device("02:00:00:00:00:01", 5, "04:11:22:33"), "02:00:00:00:00:02": device("02:00:00:00:00:02", 6, "04:11:22:33") }, "Duplicate NFC"],
    [{ "02:00:00:00:00:01": { ...device("02:00:00:00:00:01", 5), detail: null } }, "Invalid text"],
  ])("rejects %#", (records, message) => {
    expect(() => validateRecords(records)).toThrow(RecordError);
    expect(() => validateRecords(records)).toThrow(message);
  });
});

describe("push / pull", () => {
  let db: MemoryStore;
  beforeEach(() => {
    db = new MemoryStore();
  });

  it("compare-and-swap per record, one revision per push", async () => {
    const a = device("02:00:00:00:00:01", 5);
    expect((await push(db, "d", { [a.mac]: a }, { [a.mac]: 0 }, actor)).status).toBe(200);
    expect(await head(db, "d")).toMatchObject({ revision: 1, count: 1 });
    // Stale base: nothing written, current record returned.
    const stale = await push(db, "d", { [a.mac]: { ...a, cube_id: 6 } }, { [a.mac]: 0 }, actor);
    expect(stale.status).toBe(409);
    expect(stale.body).toMatchObject({ records: { [a.mac]: { revision: 1 } } });
    expect((await head(db, "d")).revision).toBe(1);
    const ok = await push(db, "d", { [a.mac]: { ...a, cube_id: 6 } }, { [a.mac]: 1 }, actor);
    expect(ok).toMatchObject({ status: 200, body: { revision: 2, changed: 1 } });
    expect((await pull(db, "d")).records[a.mac]).toMatchObject({ revision: 2, record: { cube_id: 6 } });
    expect((await pull(db, "other")).revision).toBe(0);
  });

  it("validates the whole post-push set and supports swaps in one push", async () => {
    const a = device("02:00:00:00:00:01", 5), b = device("02:00:00:00:00:02", 6);
    await push(db, "d", { [a.mac]: a, [b.mac]: b }, { [a.mac]: 0, [b.mac]: 0 }, actor);
    const clash = await push(db, "d", { [a.mac]: { ...a, cube_id: 6 } }, { [a.mac]: 1 }, actor);
    expect(clash).toMatchObject({ status: 400, body: { error: expect.stringContaining("Duplicate number 6") } });
    const swap = await push(db, "d", { [a.mac]: { ...a, cube_id: 6 }, [b.mac]: { ...b, cube_id: 5 } }, { [a.mac]: 1, [b.mac]: 1 }, actor);
    expect(swap.status).toBe(200);
    expect(await push(db, "d", { x: 1 }, {}, actor)).toMatchObject({ status: 400 });
  });

  it("re-checks a push when another write lands between read and write", async () => {
    const a = device("02:00:00:00:00:01", 5), b = device("02:00:00:00:00:02", 6);
    await push(db, "d", { [a.mac]: a, [b.mac]: b }, { [a.mac]: 0, [b.mac]: 0 }, actor);
    // Unrelated concurrent edit: retried and both survive.
    db.beforeWrite = async () => { await push(db, "d", { [b.mac]: { ...b, detail: "other" } }, { [b.mac]: 1 }, "other"); };
    expect(await push(db, "d", { [a.mac]: { ...a, cube_id: 7 } }, { [a.mac]: 1 }, actor)).toMatchObject({ status: 200, body: { revision: 3 } });
    expect((await pull(db, "d")).records).toMatchObject({ [a.mac]: { record: { cube_id: 7 } }, [b.mac]: { record: { detail: "other" } } });
    // Same-record concurrent edit: the later push becomes a 409, never an overwrite.
    db.beforeWrite = async () => { await push(db, "d", { [a.mac]: { ...a, cube_id: 8 } }, { [a.mac]: 3 }, "other"); };
    expect((await push(db, "d", { [a.mac]: { ...a, cube_id: 9 } }, { [a.mac]: 3 }, actor)).status).toBe(409);
    expect((await pull(db, "d")).records[a.mac]).toMatchObject({ record: { cube_id: 8 } });
    const doc = (await db.read("d")).doc;
    expect(doc.changes[0]).toMatchObject({ mac: a.mac, client: "other" });
  });

  it("memory store rejects stale etags", async () => {
    await db.write("x", { revision: 1, records: {}, changes: [] }, null);
    await expect(db.write("x", { revision: 2, records: {}, changes: [] }, null)).rejects.toBeInstanceOf(StoreConflict);
  });
});

describe("password", () => {
  it("accepts only INVENTORY_PASSWORD and refuses everything when it is unset", () => {
    const saved = process.env.INVENTORY_PASSWORD;
    try {
      delete process.env.INVENTORY_PASSWORD;
      expect(passwordMatches("")).toBe(false);
      expect(passwordMatches("anything")).toBe(false);
      process.env.INVENTORY_PASSWORD = "test-password";
      expect(passwordMatches("test-password")).toBe(true);
      expect(passwordMatches("test")).toBe(false);
      expect(passwordMatches(null)).toBe(false);
    } finally {
      if (saved === undefined) delete process.env.INVENTORY_PASSWORD;
      else process.env.INVENTORY_PASSWORD = saved;
    }
  });
});

describe("last seen", () => {
  it("keeps one latest entry per client and dataset", async () => {
    const store = new MemoryStore();
    await store.touch("d", { client: "bench · Web Sync", action: "check / pull", at: "2026-09-21T10:00:00Z", ip: "" });
    await store.touch("d", { client: "bench · Web Sync", action: "upload", at: "2026-09-21T10:05:00Z", ip: "" });
    await store.touch("d", { client: "laptop · Pairing app", action: "status check", at: "2026-09-21T09:00:00Z", ip: "" });
    await store.touch("other", { client: "x", action: "upload", at: "2026-09-21T09:00:00Z", ip: "" });
    const seen = await store.presence("d");
    expect(seen).toHaveLength(2);
    expect(seen.find((p) => p.client.startsWith("bench"))).toMatchObject({ action: "upload" });
  });

  it("formats relative times", () => {
    const now = Date.parse("2026-09-21T12:00:00Z");
    expect(ago("2026-09-21T11:59:40Z", now)).toBe("just now");
    expect(ago("2026-09-21T11:56:00Z", now)).toBe("4 min ago");
    expect(ago("2026-09-21T09:00:00Z", now)).toBe("3 h ago");
    expect(ago("2026-09-19T12:00:00Z", now)).toBe("2 days ago");
    expect(ago(null, now)).toBe("never");
  });

  it("session cookie value depends on the password", async () => {
    expect(await sessionValue("a")).toBe(await sessionValue("a"));
    expect(await sessionValue("a")).not.toBe(await sessionValue("b"));
  });
});
