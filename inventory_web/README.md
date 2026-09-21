# Web inventory sync (desktop)

`./Launch.command` opens the sync app for `pairing_station/data/devices.sqlite3`. It asks
for the shared password on launch (kept in memory only, never saved; asked again if
rejected), then checks the web inventory. See [web/README.md](../web/README.md).

- **Check** compares local, web and the last-synced baseline without writing.
- **Sync now** uploads local changes, then applies web changes if the pairing and
  cube-flasher apps are closed (otherwise they wait for the next sync).
- Conflicts block the whole sync until you select them and choose
  **keep local** or **take web**.

Options: `--database`, `--server`, `--dataset`. Logic lives in
`pairing_station/web_sync.py` (tests: `pairing_station/tests/test_web_sync.py`).
