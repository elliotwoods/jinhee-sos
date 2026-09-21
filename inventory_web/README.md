# Web inventory sync (desktop)

`./Launch.command` opens the sync app for `pairing_station/data/devices.sqlite3`. It asks
for the shared password on launch (kept in memory only, never saved; asked again if
rejected), then checks the web inventory. See [web/README.md](../web/README.md).

- **Check** compares local, web and the last-synced baseline without writing.
- **Sync now** uploads local changes, then applies web changes if the pairing and
  cube-flasher apps are closed (otherwise they wait for the next sync).
- Sync never needs a decision. When two computers changed the same device, the newest
  change wins; a number or tag claimed by two devices stays with the newest claim. Rows
  marked **Decided** show what the merge chose and why ("After sync" column, detail pane,
  log); each is also a `sync_resolved` event. To reverse one, make the change again on
  either computer and sync.

Options: `--database`, `--server`, `--dataset`. Logic lives in
`pairing_station/web_sync.py` (tests: `pairing_station/tests/test_web_sync.py`).
