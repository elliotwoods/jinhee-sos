import { readFileSync } from "node:fs";
import { join } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";
import { MemoryStore, StoreConflict } from "./store";
import { head, pack, publish, ShowBusy, ShowError, validateSource } from "./show";
import { crc32 } from "./zonedb";

// The committed default show; its image CRC is compiled into the cube (DefaultShow.h).
const DEFAULT = JSON.parse(readFileSync(join(__dirname, "../../../shows/mainshow.json"), "utf-8"));
const HEADER = readFileSync(join(__dirname, "../../../flashing_station/firmware/neocore_usb/DefaultShow.h"), "utf-8");
const b64 = (image: Uint8Array) => Buffer.from(image).toString("base64");
const clone = () => JSON.parse(JSON.stringify(DEFAULT));

describe("show image", () => {
  it("packs byte-identically to showfile.py (the cube's compiled-in CRC)", () => {
    const image = pack(validateSource(DEFAULT));
    const crc = Number(/DEFAULT_SHOW_CRC = (0x[0-9a-f]+)/.exec(HEADER)![1]);
    expect(image.length).toBe(12 + 24 * 21);
    expect(crc32(image)).toBe(crc);
  });
  it("packs fanned cues like showfile.py (the vector show, CRC from the cube tests)", () => {
    const vectors = JSON.parse(readFileSync(join(__dirname, "../../../console/web/tests/show_vectors.json"), "utf-8"));
    const image = pack(validateSource(vectors.doc));
    expect(crc32(image)).toBe(vectors.crc);
  });
  it.each([
    [(d: any) => (d.cues[0].fan = { mode: "scatter", spread_ms: 5 }), "cannot fan"],
    [(d: any) => (d.cues[2].fan = { mode: "wave" }), "sequential or scatter"],
    [(d: any) => (d.cues[2].fan = { mode: "sequential", step_ms: 5 }), "needs step_ms and groups"],
    [(d: any) => (d.cues[2].fan = { mode: "sequential", step_ms: 5, groups: 0 }), "groups must be"],
    [(d: any) => (d.cues[0].start_ms = 5), "first cue must start at 0"],
    [(d: any) => (d.cues[2].start_ms = d.cues[1].start_ms), "must start after"],
    [(d: any) => (d.cues[0].colours[0][0] = 101), "from 0 to 100"],
    [(d: any) => (d.cues[2].params.on_ms = 5000), "on_ms cannot exceed"],
    [(d: any) => delete d.cues[3].params.duration_ms, "needs parameters"],
    [(d: any) => (d.cues[3].type = "sparkle"), "unknown type"],
    [(d: any) => (d.cues[7].colours = []), "1 to 3 colours"],
    [(d: any) => (d.cues[10].params.level_min = 60), "level_min cannot exceed"],
    [(d: any) => (d.cues[3].params.duration_ms = 1.5), "whole number"],
    [(d: any) => (d.cues = []), "1 to 128 cues"],
  ])("rejects %#", (change, message) => {
    const doc = clone();
    change(doc);
    expect(() => validateSource(doc)).toThrow(ShowError);
    expect(() => validateSource(doc)).toThrow(message);
  });
});

describe("show publish", () => {
  let db: MemoryStore;
  beforeEach(() => {
    db = new MemoryStore();
  });
  const image = () => b64(pack(validateSource(DEFAULT)));

  it("allocates increasing versions and no-ops identical content", async () => {
    const first = await publish(db, "t", DEFAULT, image(), 0, "a");
    expect(first).toMatchObject({ changed: true, doc: { version: 1, length: 516 } });
    expect((await publish(db, "t", DEFAULT, image(), 0, "b")).changed).toBe(false);
    const edited = clone();
    edited.cues[0].colours = [[30, 30, 1]];
    const second = await publish(db, "t", edited, b64(pack(validateSource(edited))), 7, "b");
    expect(second.doc.version).toBe(8);
    expect(await head(db, "t")).toMatchObject({ version: 8, length: 516 });
  });
  it("refuses an image that does not match its source", async () => {
    const edited = clone();
    edited.cues[0].colours = [[30, 30, 1]];
    await expect(publish(db, "t", edited, image(), 0, "a")).rejects.toThrow("does not match");
  });
  it("retries a conflicting write, then reports busy", async () => {
    let conflicts = 0;
    db.beforeWrite = async () => {
      conflicts++;
      await db.writeShow("t", { ...(await db.readShow("t")).doc, version: 3 }, (await db.readShow("t")).etag);
    };
    const result = await publish(db, "t", DEFAULT, image(), 0, "a");
    expect(conflicts).toBe(1);
    expect(result.doc.version).toBe(4);
    const always = new MemoryStore();
    always.writeShow = async () => { throw new StoreConflict("busy"); };
    await expect(publish(always, "t", DEFAULT, image(), 0, "a")).rejects.toThrow(ShowBusy);
  });
});
