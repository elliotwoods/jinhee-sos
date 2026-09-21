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
Computers never store it; the desktop tools ask for it each run. The API expects `Authorization: Bearer <password>`. The web page has a
sign-in form (`/login` → `POST /api/session`) that sets a year-long httpOnly cookie
holding a hash of the password, so changing the password signs everyone out.

## Last seen

Every authenticated API call records its caller (`X-Inventory-Client`, e.g.
`host · Pairing app`), the action (status check, check / pull, upload), time and IP in
`presence/<dataset>/<client>.json`, one small blob per client, written after the
response so it never delays or contends with the inventory document. The page shows
these as "Last seen", and per device who uploaded the last change and how long ago.

## API

| Route | Purpose |
|---|---|
| `GET /api/inventory/head?dataset=` | Revision + count, used by the apps' status line |
| `GET /api/inventory?dataset=` | All records with per-record revisions |
| `POST /api/inventory/push` | `{dataset, records, base_revisions, client}`. Compare-and-swap: 409 with current records if any base is stale; 400 if the post-push set fails validation (duplicate number/NFC, bad fields). Each accepted push advances the revision by exactly 1. Records are never deleted |
| `/login`, `POST /api/session` | Password sign-in / sign-out for the web page |
| `/` | Read-only devices, recent changes and last seen |

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
