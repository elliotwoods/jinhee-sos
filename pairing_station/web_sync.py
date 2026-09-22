"""Three-way synchronization between local SQLite and the shared web inventory.

Uses the same records, validation and merge rules as the Git sync, with its own baseline.
Checking and uploading work while the desktop apps run; writing web changes into SQLite
requires the pairing and cube-flasher apps to be closed or idle (their instance locks).

The merge never needs a decision (inventory_sync.merge_records). A sync is safe to repeat after any
failure: a push is a compare-and-swap on the pushed records, and the baseline moves only at the end.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time
from datetime import datetime, timezone
from database import Database
import hostos
from inventory_sync import (AppsOpen, LocalChanged, _device, _identity, _label, app_locks, apply, load_baseline,
                            merge_records, record_decisions, save_baseline, snapshot, validate)
import sightings
from web_client import PushConflict, Transient, Unreachable, WebError, retrying

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


class SyncBusy(RuntimeError):
    """Another app on this computer is syncing this database right now. Harmless: it does the same work."""


@contextmanager
def sync_lock(database):
    with Path(database).with_suffix('.sync.lock').open('a') as handle:
        try:
            hostos.lock_file(handle)
        except BlockingIOError:
            raise SyncBusy('Another app on this computer is syncing right now') from None
        yield


def _lost(local, merged, baseline):
    """Numbers and tags this computer's devices give up to a decision of the merge: [dict(mac, text)].

    Counts a local change that lost to a newer one, and a repair of a number/tag claimed twice, which
    also reaches the computer that merely downloads it, so its operator hears about it too. An ordinary
    change made on another computer (a renumber, a deliberate clear) is not a loss.
    """
    lost = []
    for mac, row in sorted(merged.items()):
        ours, theirs = _device(local.get(mac)), _device(row)
        if not ours or not theirs or not (theirs['detail'].startswith('Sync:') or local.get(mac) != baseline.get(mac)):
            continue
        gone = []
        if ours['cube_id'] is not None and theirs['cube_id'] is None:
            gone.append(f"number {ours['cube_id']}")
        gone += [f'tag {tag}' for tag in sorted({ours['uid'], ours['pending_uid']} - {None, theirs['uid'], theirs['pending_uid']})]
        if gone:
            name = f"#{ours['cube_id']} ({mac})" if ours['cube_id'] is not None else mac
            lost.append(dict(mac=mac, text=f"{name} loses {' and '.join(gone)}: now {_label(theirs)}. {theirs['detail']}".strip()))
    return lost


def plan(db, client, pulled, resolutions=None):
    """Compare local, web and baseline without writing anything."""
    remote = {mac: entry['record'] for mac, entry in pulled['records'].items()}
    baseline, saved = load_baseline(db, KEY)
    state = load_state(db.conn)
    if saved and (state.get('server'), state.get('dataset')) != (client.server, client.dataset):
        baseline, saved = {}, False  # a different web inventory has no shared history with this one
    local = snapshot(db)
    merged, notes = merge_records(local, remote, baseline, saved, resolutions)
    resolved = resolutions or {}
    return {
        'local': local, 'remote': remote, 'merged': merged,
        'conflicts': [],  # the merge always resolves; kept for callers that still look
        # Decisions the merge took by itself (newest change wins, numbers/tags claimed twice), and what
        # this computer's devices lose to them.
        'notes': notes, 'lost': _lost(local, merged, baseline),
        # Both sides changed: merge picked without asking.
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


def _apply(db, database, result, held, apply_ok):
    """Write web changes into SQLite if the apps allow it right now. Returns (applied, reason it was not)."""
    if not (apply_ok() if callable(apply_ok) else apply_ok):
        return False, 'an operation is running in this app'
    try:
        with app_locks(database, skip=held):
            apply(db, result['merged'], only=result['download'], expected=result['local'])
    except AppsOpen:
        return False, 'the pairing or cube-flasher app is open'
    except sqlite3.Error as exc:  # e.g. a record this version skipped still holds a number: nothing was written
        return False, f'the local database refused them ({exc})'
    return True, None


def run(database, client, name, resolutions=None, retries=5, upload=True, download=True, held=(), apply_ok=True):
    """Pull, merge, upload local changes, then apply web changes if the apps are closed or idle.

    Returns the final plan plus 'applied' (bool), 'unapplied' (web changes left for later) and 'deferred'
    (why they were left). Raises SyncBusy if another app on this computer is syncing. An exception
    raised after an upload was attempted has `after_push` set: the web may or may not have the changes,
    and the next sync finds out.

    upload=False (download only) keeps local changes waiting; download=False (upload only) leaves web
    changes waiting. `held`: instance-lock suffixes the calling app holds itself; `apply_ok`: that app
    is idle (bool, or a callable asked just before writing), so web changes may be written into SQLite
    underneath it.
    """
    with sync_lock(database):
        db = Database(database, recover_pending=False)
        attempted = False
        try:
            uploaded, last = set(), None
            for attempt in range(retries):
                final = attempt == retries - 1
                result = plan(db, client, retrying(client.pull), resolutions)
                validate(result['merged'])
                revision = result['revision']
                if result['upload'] and upload:
                    attempted = True
                    try:
                        pushed = client.push({mac: result['merged'][mac] for mac in result['upload']},
                                             {mac: result['revisions'].get(mac, 0) for mac in result['upload']}, name)
                    except PushConflict as exc:
                        last = exc
                        continue  # someone else pushed in between; re-plan against their records
                    except (Transient, Unreachable) as exc:
                        if final:
                            raise
                        last = exc
                        time.sleep(min(attempt + 1, 3))
                        continue  # it may even have been stored: the next plan sees either outcome
                    except WebError as exc:
                        # The web validates the whole inventory: another computer's change since our pull can
                        # make a correct push invalid (a number now used twice). The next plan reconciles it.
                        if exc.code != 400 or final:
                            raise
                        last = exc
                        continue
                    uploaded.update(result['upload'])
                    # Only claim the new head if nobody else wrote since our pull; otherwise the
                    # status check must keep reporting web changes we have not merged yet.
                    if pushed['revision'] == result['revision'] + 1:
                        revision = pushed['revision']
                applied, deferred = False, None
                if download and result['download']:
                    try:
                        applied, deferred = _apply(db, database, result, held, apply_ok)
                    except LocalChanged:
                        if not final:
                            continue  # an app wrote to SQLite meanwhile: merge that in rather than overwrite it
                        deferred = 'local records kept changing'
                break
            else:
                raise WebError(f'The web inventory kept changing during sync; try again ({last})')
            # Web now equals merged. Unapplied web changes keep the local value as baseline so the
            # next sync takes them, while a local edit in the meantime is merged against them again.
            settled = applied or not result['download']
            baseline = dict(result['merged'] if settled else result['local'])
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
            unapplied = 0 if settled else len(result['download'])
            save_state(db, {'server': client.server, 'dataset': client.dataset, 'revision': revision,
                            'synced_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                            'unapplied': unapplied})
            with db.conn:
                # Decisions are audited once, when they take effect somewhere (uploaded or applied here).
                moved = uploaded | (set(result['download']) if applied else set())
                record_decisions(db, [note for note in result['notes'] if note['mac'] in moved])
                db.event(None, 'web_sync', f"revision {revision}; uploaded {len(uploaded)}; "
                         f"applied {len(result['download']) if applied else 0}; waiting {unapplied}; "
                         f"decided {len(result['notes'])}")
                # Independent computers cannot safely allocate the next free number.
                db.conn.execute("INSERT OR REPLACE INTO metadata VALUES ('auto_number','0')")
        except Exception as exc:
            exc.after_push = attempted
            raise
        finally:
            db.close()
    reported = report_sightings(database, client)  # after the locks and connection are released
    return dict(result, revision=revision, applied=applied, unapplied=unapplied, deferred=deferred, sightings=reported,
                uploaded=sorted(uploaded), waiting_upload=[] if upload else result['upload'])
