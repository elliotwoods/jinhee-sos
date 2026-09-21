"""Three-way synchronization between local SQLite and the shared web inventory.

Uses the same records, validation and merge rules as the Git sync, with its own baseline.
Checking and uploading work while the desktop apps run; writing web changes into SQLite
requires the pairing and cube-flasher apps to be closed (their instance locks).
"""
from contextlib import ExitStack
import json
from datetime import datetime, timezone
from database import Database
from inventory_sync import AppsOpen, app_locks, apply, load_baseline, merge, save_baseline, snapshot, validate
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
    return {
        'local': local, 'remote': remote, 'merged': merged, 'conflicts': conflicts,
        'upload': sorted(mac for mac, row in merged.items() if remote.get(mac) != row),
        'download': sorted(mac for mac, row in merged.items() if local.get(mac) != row),
        'revisions': {mac: entry['revision'] for mac, entry in pulled['records'].items()},
        'revision': pulled['revision'],
    }


def check(database, client):
    db = Database(database, recover_pending=False)
    try:
        return plan(db, client, client.pull())
    finally:
        db.close()


def run(database, client, name, resolutions=None, retries=3):
    """Pull, merge, upload local changes, then apply web changes if the apps are closed.

    Returns the final plan plus 'applied' (bool) and 'unapplied' (web changes left for later).
    Unresolved conflicts return early with nothing written anywhere.
    """
    with ExitStack() as stack:
        try:
            stack.enter_context(app_locks(database))
            locked = True
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
            if result['upload']:
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
        save_baseline(db, KEY, result['merged'] if locked else result['local'])
        unapplied = 0 if locked else len(result['download'])
        save_state(db, {'server': client.server, 'dataset': client.dataset, 'revision': revision,
                        'synced_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                        'unapplied': unapplied})
        with db.conn:
            db.event(None, 'web_sync', f"revision {revision}; uploaded {len(result['upload'])}; "
                     f"applied {len(result['download']) if applied else 0}; waiting {unapplied}")
        return dict(result, revision=revision, applied=applied, unapplied=unapplied)
