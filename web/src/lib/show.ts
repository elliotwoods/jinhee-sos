// Universal main show versions. Mirrors pairing_station/showfile.py (validate/pack) and the cube
// firmware's nctshow::validImage (zones/firmware/libraries/NctShow/src/NctShowEngine.h); change
// them together. Cubes accept only a HIGHER version, so the server allocates versions and they
// never go down.
import { createHash } from "node:crypto";
import { backoff } from "./inventory";
import { type ShowDoc, type Store, StoreConflict } from "./store";
import { crc32 } from "./zonedb";

const FORMAT = 1;
const MAX_CUES = 128;
const MAX_LENGTH_MS = 3_600_000;
const LEVEL_MAX = 100;
const U16 = 0xffff;
const HEADER = 12;
const CUE = 24;
const WRITE_ATTEMPTS = 5;
const MAX_VERSION = 0xffffffff;
const MAX_SOURCE_BYTES = 64 * 1024;

/** Cue types: wire value, colour count (null = 1..3), parameter names in wire order. */
const TYPES: Record<string, [number, number | null, string[]]> = {
  off: [0, 0, []],
  solid: [1, 1, []],
  fade: [2, 2, ["duration_ms"]],
  blink: [3, 2, ["period_ms", "on_ms"]],
  pulse: [4, 2, ["attack_ms", "release_ms"]],
  cycle: [5, null, ["step_ms"]],
  random: [6, 1, ["level_min", "level_max", "dur_min_ms", "dur_max_ms", "start_level"]],
};
const LEVELS = new Set(["level_min", "level_max", "start_level"]);

export class ShowError extends Error {}
/** The document kept changing underneath the publish: worth another try (503). */
export class ShowBusy extends Error {}

/** Per-cube offsets from the registered number (cube firmware v1.6.0+); absent = none. */
type Fan = { mode: "sequential"; step_ms: number; groups: number } | { mode: "scatter"; spread_ms: number };
type Cue = { start_ms: number; label: string; type: string; colours: number[][]; params: Record<string, number>; fan?: Fan };
const FANNABLE = new Set(["fade", "blink", "pulse", "cycle"]);
export type ShowSource = { format: number; length_ms: number; cues: Cue[] };

function whole(value: unknown, where: string, low: number, high: number): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < low || value > high) {
    throw new ShowError(`${where} must be a whole number from ${low} to ${high}`);
  }
  return value;
}

/** showfile.validate(): a normalised copy, or ShowError naming the first problem. */
export function validateSource(doc: unknown): ShowSource {
  if (!doc || typeof doc !== "object" || Array.isArray(doc)) throw new ShowError("show must be an object");
  const d = doc as Record<string, unknown>;
  if ((d.format ?? FORMAT) !== FORMAT) throw new ShowError(`unsupported show format ${JSON.stringify(d.format)}`);
  const length = whole(d.length_ms, "length_ms", 1, MAX_LENGTH_MS);
  if (!Array.isArray(d.cues) || d.cues.length < 1 || d.cues.length > MAX_CUES) throw new ShowError(`a show needs 1 to ${MAX_CUES} cues`);
  let previous: number | null = null;
  const cues = d.cues.map((raw, i): Cue => {
    const where = `cue ${i + 1}`;
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new ShowError(`${where} must be an object`);
    const cue = raw as Record<string, unknown>;
    const start = whole(cue.start_ms, `${where} start_ms`, 0, length - 1);
    if (i === 0 && start !== 0) throw new ShowError("the first cue must start at 0");
    if (previous !== null && start <= previous) throw new ShowError(`${where} must start after cue ${i}`);
    previous = start;
    const kind = cue.type;
    if (typeof kind !== "string" || !(kind in TYPES)) throw new ShowError(`${where} has unknown type ${JSON.stringify(kind)}`);
    const [, count, names] = TYPES[kind];
    const colours = cue.colours ?? [];
    if (!Array.isArray(colours)) throw new ShowError(`${where} colours must be a list`);
    if (count === null && (colours.length < 1 || colours.length > 3)) throw new ShowError(`${where} (${kind}) needs 1 to 3 colours`);
    if (count !== null && colours.length !== count) throw new ShowError(`${where} (${kind}) needs ${count} colour${count !== 1 ? "s" : ""}`);
    const clean = colours.map((rgb, c) => {
      if (!Array.isArray(rgb) || rgb.length !== 3) throw new ShowError(`${where} colour ${c + 1} must be [r, g, b]`);
      return rgb.map((v) => whole(v, `${where} colour ${c + 1}`, 0, LEVEL_MAX));
    });
    const params = (cue.params ?? {}) as Record<string, unknown>;
    const keys = typeof params === "object" && !Array.isArray(params) ? Object.keys(params) : null;
    if (!keys || keys.length !== names.length || !names.every((n) => keys.includes(n))) {
      throw new ShowError(`${where} (${kind}) needs parameters ${names.join(", ") || "none"}`);
    }
    const p: Record<string, number> = {};
    for (const name of names) {
      const low = LEVELS.has(name) || name === "on_ms" ? 0 : 1;
      p[name] = whole(params[name], `${where} ${name}`, low, LEVELS.has(name) ? LEVEL_MAX : U16);
    }
    if (kind === "blink" && p.on_ms > p.period_ms) throw new ShowError(`${where} on_ms cannot exceed period_ms`);
    if (kind === "random" && p.level_min > p.level_max) throw new ShowError(`${where} level_min cannot exceed level_max`);
    if (kind === "random" && p.dur_min_ms > p.dur_max_ms) throw new ShowError(`${where} dur_min_ms cannot exceed dur_max_ms`);
    const label = cue.label ?? "";
    if (typeof label !== "string") throw new ShowError(`${where} label must be text`);
    const out: Cue = { start_ms: start, label, type: kind, colours: clean, params: p };
    const fan = cue.fan as Record<string, unknown> | undefined | null;
    if (fan != null && !(typeof fan === "object" && !Array.isArray(fan) && Object.keys(fan).length === 0)) {
      if (!FANNABLE.has(kind)) throw new ShowError(`${where} (${kind}) cannot fan; only fade, blink, pulse, cycle can`);
      if (typeof fan !== "object" || Array.isArray(fan) || (fan.mode !== "sequential" && fan.mode !== "scatter")) {
        throw new ShowError(`${where} fan mode must be sequential or scatter`);
      }
      const keys = Object.keys(fan).sort().join(",");
      if (fan.mode === "sequential") {
        if (keys !== "groups,mode,step_ms") throw new ShowError(`${where} sequential fan needs step_ms and groups`);
        out.fan = { mode: "sequential", step_ms: whole(fan.step_ms, `${where} fan step_ms`, 1, U16),
                    groups: whole(fan.groups, `${where} fan groups`, 1, 255) };
      } else {
        if (keys !== "mode,spread_ms") throw new ShowError(`${where} scatter fan needs spread_ms`);
        out.fan = { mode: "scatter", spread_ms: whole(fan.spread_ms, `${where} fan spread_ms`, 1, U16) };
      }
    }
    return out;
  });
  return { format: FORMAT, length_ms: length, cues };
}

/** showfile.pack(): the binary image a cube stores. */
export function pack(source: ShowSource): Uint8Array {
  const out = new Uint8Array(HEADER + CUE * source.cues.length);
  const view = new DataView(out.buffer);
  out.set([0x4e, 0x53, 0x48, 0x57], 0); // "NSHW"
  out[4] = FORMAT;
  view.setUint16(6, source.cues.length, true);
  view.setUint32(8, source.length_ms, true);
  source.cues.forEach((cue, i) => {
    const at = HEADER + CUE * i;
    const [code, , names] = TYPES[cue.type];
    const p = cue.params;
    view.setUint32(at, cue.start_ms, true);
    out[at + 4] = code;
    out[at + 5] = cue.colours.length;
    cue.colours.forEach((rgb, c) => out.set(rgb, at + 8 + 3 * c));
    const params = cue.type === "random"
      ? [p.level_min | (p.level_max << 8), p.dur_min_ms, p.dur_max_ms]
      : names.map((n) => p[n]);
    if (cue.type === "random") out[at + 6] = p.start_level;
    if (cue.fan) {
      out[at + 7] = cue.fan.mode === "sequential" ? 1 : 2;
      if (cue.fan.mode === "sequential") out[at + 6] = cue.fan.groups;
      params[2] = cue.fan.mode === "sequential" ? cue.fan.step_ms : cue.fan.spread_ms;
    }
    params.forEach((value, k) => view.setUint16(at + 18 + 2 * k, value, true));
  });
  return out;
}

/** What the public head route reveals. */
export async function head(store: Store, dataset: string) {
  const { version, hash, crc, length, published_at } = (await store.readShow(dataset)).doc;
  return { version, hash, crc, length, published_at };
}

export async function current(store: Store, dataset: string): Promise<ShowDoc> {
  return (await store.readShow(dataset)).doc;
}

/**
 * Publishes a show. The image must be exactly pack(validateSource(source)). Identical content
 * returns the current document; otherwise version = max(current, minVersion) + 1, where
 * minVersion lifts the counter above versions already running on cubes.
 */
export async function publish(
  store: Store, dataset: string, source: unknown, imageB64: string, minVersion: number, client: string,
): Promise<{ doc: ShowDoc; changed: boolean }> {
  if (!Number.isInteger(minVersion) || minVersion < 0 || minVersion >= MAX_VERSION) throw new ShowError("Invalid min_version");
  if (JSON.stringify(source ?? null).length > MAX_SOURCE_BYTES) throw new ShowError("Show source is too large");
  if (!/^[A-Za-z0-9+/]*={0,2}$/.test(imageB64)) throw new ShowError("image_b64 is not base64");
  const clean = validateSource(source);
  const image = new Uint8Array(Buffer.from(imageB64, "base64"));
  const expected = pack(clean);
  if (image.length !== expected.length || !image.every((b, i) => b === expected[i])) {
    throw new ShowError("Show image does not match its source");
  }
  const hash = createHash("sha256").update(image).digest("hex");
  for (let attempt = 0; ; attempt++) {
    const { doc, etag } = await store.readShow(dataset);
    if (doc.hash === hash && doc.version >= minVersion && JSON.stringify(doc.source) === JSON.stringify(clean)) {
      return { doc, changed: false };
    }
    const version = Math.max(doc.version, minVersion) + 1;
    if (version > MAX_VERSION) throw new ShowError("Show version space exhausted");
    const next: ShowDoc = {
      version, hash, crc: crc32(image), length: image.length, image_b64: Buffer.from(image).toString("base64"),
      source: clean, published_at: new Date().toISOString(), published_by: client,
    };
    try {
      await store.writeShow(dataset, next, etag);
      return { doc: next, changed: true };
    } catch (error) {
      if (!(error instanceof StoreConflict)) throw error;
      if (attempt + 1 >= WRITE_ATTEMPTS) throw new ShowBusy("The show is busy with other publishes; try again");
      await backoff(attempt);
    }
  }
}
