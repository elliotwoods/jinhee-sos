import { beforeEach, describe, expect, it } from "vitest";
import { claim, NumberError } from "./numbers";
import { MemoryStore, StoreConflict } from "./store";
import { push } from "./inventory";

const A = "02:00:00:00:00:0A", B = "02:00:00:00:00:0B", C = "02:00:00:00:00:0C";
const record = (mac: string, cube_id: number | null) => ({
  mac, cube_id, uid: null, pending_uid: null, source: "usb", status: cube_id === null ? "needs_number" : "awaiting_tag",
  updated_at: "2026-09-23T00:00:00+00:00", detail: "", role: "auto",
});

describe("cube number claims", () => {
  let store: MemoryStore;
  beforeEach(() => { store = new MemoryStore(); });

  it("hands out the lowest free number from 33, skipping inventory numbers and the caller's exclusions", async () => {
    await push(store, "t", { [C]: record(C, 33) }, { [C]: 0 }, "x");
    expect(await claim(store, "t", A, [34, 2, 22], "laptop 1")).toEqual({ number: 35, existing: false });
  });

  it("never gives two MACs the same number, and repeats a MAC's own claim", async () => {
    const a = await claim(store, "t", A, [], "laptop 1");
    const b = await claim(store, "t", B, [], "laptop 2");
    expect(a.number).not.toBe(b.number);
    expect(await claim(store, "t", A, [], "laptop 2")).toEqual({ number: a.number, existing: true });
  });

  it("returns the number the inventory already holds for the MAC", async () => {
    await push(store, "t", { [A]: record(A, 57) }, { [A]: 0 }, "x");
    expect(await claim(store, "t", A, [], "laptop")).toEqual({ number: 57, existing: true });
  });

  it("re-reads when another computer claims at the same moment", async () => {
    store.beforeWrite = async () => {
      store.beforeWrite = null;
      await claim(store, "t", B, [], "laptop 2");
    };
    const a = await claim(store, "t", A, [], "laptop 1");
    const b = await claim(store, "t", B, [], "laptop 2");
    expect(b).toEqual({ number: 33, existing: true });
    expect(a).toEqual({ number: 34, existing: false });
  });

  it("rejects a malformed MAC", async () => {
    await expect(claim(store, "t", "aa:bb", [], "x")).rejects.toThrow(NumberError);
  });

  it("keeps StoreConflict as the write contract", () => {
    expect(new StoreConflict("x")).toBeInstanceOf(Error);
  });
});
