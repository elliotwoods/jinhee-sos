# NCT device inventory (web)

Shared web copy of the Neocore device inventory: the same per-MAC records as
`inventory/devices/*.json`, kept in step with each computer's local SQLite by
`inventory_web/` (desktop app) or `scripts/web_sync.py` (CLI).

Deployed as Vercel project `kimchiandchips/nct-inventory` at
https://nct-inventory.auroravision.xyz (also https://nct-inventory.vercel.app).
It is independent of AuroraVision: no accounts login, no shared database.

## Storage

One private Vercel Blob store (`nct-inventory`, connected to the project as
`BLOB_READ_WRITE_TOKEN`) holds one JSON document per dataset,
`inventory/<dataset>.json` (default dataset `jinhee-sos`):

```json
{ "revision": 12, "records": { "<MAC>": { "record": {…}, "revision": 9, "updated_at": "…", "updated_from": "…" } },
  "changes": [ { "revision": 12, "mac": "…", "before": {…}, "after": {…}, "client": "…", "at": "…" } ] }
```

Reads bypass the CDN cache. Writes are conditional on the ETag that was read
(`ifMatch`), so a concurrent push makes the other one re-read and re-check instead of
overwriting it. Uncached reads report a weak ETag (`W/"…"`); `store.ts` strips the
prefix because conditional writes only accept the strong form. The last 500 changes
are kept in the document.

## Password

Deliberately simple: one shared password, set only as `INVENTORY_PASSWORD` in the
Vercel project environment and never committed. Unset, every request is refused.
Each computer asks for it once and stores it owner-only in `pairing_station/data/web_password` (gitignored; never in git, source or docs). Every app uses it until the web rejects it, which deletes it. The API expects `Authorization: Bearer <password>`. The web page has a
sign-in form (`/login` → `POST /api/session`) that sets a year-long httpOnly cookie
holding a hash of the password, so changing the password signs everyone out.

## Last seen

**Computers.** Every authenticated API call records its caller (`X-Inventory-Client`, e.g.
`host · Web Sync`), the action, time and IP in `presence/<dataset>/<client>.json`, one
small blob per client, written after the response so it never delays or contends with
the inventory document.

**Cubes and zone boards.** Each computer keeps its own evidence of when it last
physically saw each cube (`pairing_station/sightings.py`): radio discovery (throttled to
once a minute), radio acknowledgements, NFC scans, USB identify, USB flashes and cube taps
reported by zone boards, plus the zone boards' own status. Web Sync (Check or Sync now)
uploads it with `POST /api/sightings`, stored as `sightings/<dataset>/<computer>.json`
(one blob per computer, replaced each time). The page merges all computers and shows the
latest sighting per cube and per kind. Sightings are telemetry: they never enter the
inventory records or the three-way merge, so they are only as fresh as each computer's
last Web Sync.

## Web page

Summary tiles (click to filter), then tabs:
- **Cubes**: grid or table (remembered per browser); search by number, MAC or NFC
  (separators optional), detail or computer (`/` focuses search); filters for status,
  last seen (1 h / 24 h / 7 days / older / never), role, number and tag; sort by
  number, last seen, last changed, status or MAC; CSV export of the filtered list. Click
  a cube for its fields, every sighting (kind, computer, time) and change history. Filters,
  tab and the open cube are kept in the URL, so links can be shared.
- **Computers**: each computer, its apps' last contact and its last sightings report.
- **Zones**: zone boards with type, point, firmware, database version, tag count and last seen.
- **Activity**: searchable change feed.

The page refreshes itself every minute.

## API

| Route | Purpose |
|---|---|
| `GET /api/inventory/head?dataset=` | Revision + count, used by the apps' status line |
| `GET /api/inventory?dataset=` | All records with per-record revisions |
| `POST /api/inventory/push` | `{dataset, records, base_revisions, client}`. Compare-and-swap: 409 with current records if any base is stale; 400 if the post-push set fails validation (duplicate number/NFC, bad fields). Each accepted push advances the revision by exactly 1. Records are never deleted |
| `/login`, `POST /api/session` | Password sign-in / sign-out for the web page |
| `POST /api/sightings` | `{dataset, cubes: {mac: {kind: {at, detail}}}, zones: [...]}`: replaces the calling computer's sightings report |
| `/` | Read-only inventory app (cubes, computers, zones, activity) |

`src/lib/records.ts` mirrors `pairing_station/inventory_sync.py::validate`; change both together.

## Develop, test, deploy

```sh
npm install
npm test            # vitest on an in-memory store: validation, CAS/409, concurrent writes, password
npm run typecheck
npm run build
npm run dev:local   # http://localhost:3100 with an in-memory store (no Blob token needed)
vercel deploy --prod --scope kimchiandchips
```

Point desktop tools at a local server with `--server http://localhost:3100`, and use
`--dataset <name>` for throwaway test data (delete it afterwards with
`vercel blob del inventory/<name>.json`).

## Zone database

`zonedb/<dataset>.json` holds the published zone database: `{version, hash, count, crc, records_b64,
published_at, published_by, inventory_revision}`. Writes use the same ETag compare-and-swap as the inventory.

| Route | Purpose |
|---|---|
| `GET /api/zonedb?dataset=` | The current publication (version 0 = nothing published) |
| `GET /api/zonedb/head?dataset=` | **Public** (no password): `{version, hash, count, published_at}` only, so every app's status line can say "pull the new zone database". Records (UIDs/MACs) stay behind the password |
| `POST /api/zonedb/publish` | `{dataset, records_b64, min_version, inventory_revision, client}`. The packed records are validated as the zone firmware would (`src/lib/zonedb.ts`). Identical content returns the current document; otherwise the version becomes `max(current, min_version) + 1`. The version never goes down |

Zones accept only a higher version, so this server is the only place versions are allocated
(see `pairing_station/zone_publish.py` and `zones/README.md`). `src/lib/zonedb.ts` mirrors
`zones/tools/zonedb.py` and the NctZone `validRecords()`; change them together.
