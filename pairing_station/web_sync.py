"""Three-way synchronization between local SQLite and the shared web inventory.

Uses the same records, validation and merge rules as the Git sync, with its own baseline.
Checking and uploading work while the desktop apps run; writing web changes into SQLite
requires the pairing and cube-flasher apps to be closed (their instance locks).
"""
from contextlib import ExitStack
import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from database import Database
from inventory_sync import AppsOpen, app_locks, apply, load_baseline, merge, save_baseline, snapshot, validate
import sightings
from web_client import PushConflict, WebError

KEY = 'web_inventory_baseline_v1'
STATE_KEY = 'web_inventory_state_v1'


def load_state(conn):
    row = conn.execute('SELECT value FROM metadata WHERE key=?', (STATE_KEY,)).fetchone()
    try:
        return json.loads(row[0]) if row else {}
    except ValueError:
        return {}


def save_state(db, state):
    with db.conn:
        db.conn.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', (STATE_KEY, json.dumps(state, sort_keys=True)))


def plan(db, client, pulled, resolutions=None):
    """Compare local, web and baseline without writing anything."""
    remote = {mac: entry['record'] for mac, entry in pulled['records'].items()}
    validate(remote)
    baseline, saved = load_baseline(db, KEY)
    state = load_state(db.conn)
    if saved and (state.get('server'), state.get('dataset')) != (client.server, client.dataset):
        baseline, saved = {}, False  # a different web inventory has no shared history with this one
    local = snapshot(db)
    merged, conflicts = merge(local, remote, baseline, saved, resolutions)
    resolved = resolutions or {}
    return {
        'local': local, 'remote': remote, 'merged': merged, 'conflicts': conflicts,
        # Both sides changed, only bookkeeping differed: merge picked the newest without asking.
        'auto_resolved': sorted(mac for mac in merged if mac not in resolved and local.get(mac) != remote.get(mac)
                                and baseline.get(mac) not in (local.get(mac), remote.get(mac))),
        'upload': sorted(mac for mac, row in merged.items() if remote.get(mac) != row),
        'download': sorted(mac for mac, row in merged.items() if local.get(mac) != row),
        'revisions': {mac: entry['revision'] for mac, entry in pulled['records'].items()},
        'revision': pulled['revision'],
    }


def report_sightings(database, client):
    """Upload this computer's cube "last seen" evidence. Telemetry only; failures are ignored.

    Returns the number of cubes reported, or None if it could not be sent.
    """
    try:
        conn = sqlite3.connect(Path(database), timeout=2)  # reads only (mode=ro can fail on a WAL database)
        try:
            report = sightings.collect(conn)
        finally:
            conn.close()
        client.report_sightings(report)
        return len(report['cubes'])
    except (WebError, sqlite3.Error, OSError, ValueError):
        return None


def check(database, client):
    db = Database(database, recover_pending=False)
    try:
        result = plan(db, client, client.pull())
    finally:
        db.close()
    return dict(result, sightings=report_sightings(database, client))


def run(database, client, name, resolutions=None, retries=3, upload=True, download=True, held=(), apply_ok=True):
    """Pull, merge, upload local changes, then apply web changes if the apps are closed.

    Returns the final plan plus 'applied' (bool) and 'unapplied' (web changes left for later).
    Unresolved conflicts return early with nothing written anywhere.

    upload=False (download only) keeps local changes waiting; download=False (upload only) leaves web
    changes waiting. `held`: instance-lock suffixes the calling app holds itself; `apply_ok`: that app
    is idle, so web changes may be written into SQLite underneath it.
    """
    with ExitStack() as stack:
        try:
            stack.enter_context(app_locks(database, skip=held))
            locked = download and apply_ok
        except AppsOpen:
            locked = False
        db = Database(database, recover_pending=False)
        stack.callback(db.close)
        for _ in range(retries):
            result = plan(db, client, client.pull(), resolutions)
            if result['conflicts']:
                return dict(result, applied=False, unapplied=0)
            validate(result['merged'])
            revision = result['revision']
            if result['upload'] and upload:
                try:
                    pushed = client.push({mac: result['merged'][mac] for mac in result['upload']},
                                         {mac: result['revisions'].get(mac, 0) for mac in result['upload']}, name)
                except PushConflict:
                    continue  # someone else pushed in between; re-plan against their records
                # Only claim the new head if nobody else wrote since our pull; otherwise the
                # status check must keep reporting web changes we have not merged yet.
                if pushed['revision'] == result['revision'] + 1:
                    revision = pushed['revision']
            break
        else:
            raise WebError('The web inventory kept changing during sync; try again')
        applied = locked and bool(result['download'])
        if applied:
            apply(db, result['merged'])
        # Web now equals merged. Unapplied web changes keep the local value as baseline so the
        # next sync takes them, while a local edit in the meantime becomes a real conflict.
        baseline = dict(result['merged'] if locked else result['local'])
        if not upload:
            # Download only: local changes were not uploaded, so they keep the previous baseline and
            # still count as uploads next time.
            previous, _ = load_baseline(db, KEY)
            for mac in result['upload']:
                if mac in previous:
                    baseline[mac] = previous[mac]
                else:
                    baseline.pop(mac, None)
        save_baseline(db, KEY, baseline)
        unapplied = 0 if locked else len(result['download'])
        save_state(db, {'server': client.server, 'dataset': client.dataset, 'revision': revision,
                        'synced_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                        'unapplied': unapplied})
        with db.conn:
            db.event(None, 'web_sync', f"revision {revision}; uploaded {len(result['upload']) if upload else 0}; "
                     f"applied {len(result['download']) if applied else 0}; waiting {unapplied}; "
                     f"auto-resolved {len(result['auto_resolved'])}")
    reported = report_sightings(database, client)  # after the locks and connection are released
    return dict(result, revision=revision, applied=applied, unapplied=unapplied, sightings=reported,
                uploaded=result['upload'] if upload else [], waiting_upload=[] if upload else result['upload'])
