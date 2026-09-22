"""The console's view of the shared devices.sqlite3: the cube flasher's Store (flash_runs) plus
the pairing app's startup recovery of interrupted registrations."""
import paths  # noqa: F401

from core import Store


class ConsoleStore(Store):
    def __init__(self, path):
        super().__init__(path)
        with self.conn:
            # As pairing_station/database.py does with recover_pending=True: a registration that
            # was in flight when the app died is retryable, never silently pending.
            self.conn.execute("UPDATE devices SET status='unconfirmed', detail='Interrupted; retry the saved transaction' "
                              "WHERE status='pending'")
        self.recover()

    def nfc_seen_macs(self):
        return {r[0] for r in self.conn.execute("SELECT DISTINCT mac FROM events WHERE action='nfc_seen'")}

    def reserved_numbers(self):
        try:
            return sorted(int(r[0]) for r in self.conn.execute('SELECT cube_id FROM reserved_numbers'))
        except Exception:
            return []

    def recent_events(self, limit=300, mac=None):
        if mac:
            rows = self.conn.execute('SELECT time, mac, action, detail FROM events WHERE mac=? ORDER BY id DESC LIMIT ?',
                                     (mac, limit))
        else:
            rows = self.conn.execute('SELECT time, mac, action, detail FROM events ORDER BY id DESC LIMIT ?', (limit,))
        return [dict(time=r[0], mac=r[1], action=r[2], detail=r[3]) for r in rows]

    def sightings(self, mac):
        try:
            rows = self.conn.execute('SELECT kind, at, detail FROM sightings WHERE mac=? ORDER BY at DESC', (mac,))
            return [dict(kind=r[0], at=r[1], detail=r[2]) for r in rows]
        except Exception:
            return []
