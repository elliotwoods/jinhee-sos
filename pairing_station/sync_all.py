"""One-button web synchronization shared by every app (see sync_widget.py).

`status` counts what a Sync would move without writing anything; `sync` uploads local inventory
changes, downloads web changes (applied when the apps allow it), and publishes/pulls the zone
database. A new zone-database version is allocated only when the cube mappings changed.
Network calls block: run both on a worker thread.
"""
import sqlite3

from database import Database
from web_client import Unauthorized, Unreachable, WebError, retrying
from zone_registry import ZoneStore
import web_sync
import zone_publish
import zonedb


def _local_zone(database):
    db = Database(database, recover_pending=False)
    try:
        return ZoneStore(db).published()
    finally:
        db.close()


def status(database, client):
    """Returns dict(state, up, down, conflicts, lost, inventory_up, inventory_down, zone_publish, zone_pull,
    waiting, web_version, local_version). state: ok | signin | unauthorized | offline | error (with
    'message': the web or the local database answered, but not usefully). `conflicts` is always 0:
    the merge resolves by itself; `lost` counts local numbers/tags a Sync would give up."""
    local = _local_zone(database)
    result = dict(state='ok', up=0, down=0, conflicts=0, lost=0, inventory_up=0, inventory_down=0, zone_publish=False,
                  zone_pull=False, waiting=0, web_version=None, local_version=local['version'])
    if not client.password:
        return dict(result, state='signin')
    try:
        pulled = client.pull()
        head = client.zonedb_head()
    except Unauthorized:
        return dict(result, state='unauthorized')
    except (Unreachable, OSError):
        return dict(result, state='offline')
    except WebError as exc:
        return dict(result, state='error', message=f'The web could not answer ({exc})')
    db = Database(database, recover_pending=False)
    try:
        plan = web_sync.plan(db, client, pulled)  # read-only (check() would also report sightings)
        waiting = web_sync.load_state(db.conn).get('unapplied', 0)
    finally:
        db.close()
    result.update(inventory_up=len(plan['upload']), inventory_down=len(plan['download']),
                  lost=len(plan['lost']), web_version=head.get('version', 0), waiting=waiting)
    try:
        records = zone_publish.records_from_inventory(plan['merged'])
        result['zone_publish'] = bool(records) and zonedb.content_hash(records) != head.get('hash')
    except ValueError:
        result['zone_publish'] = False
    result['zone_pull'] = (head.get('version', 0) > local['version'] and head.get('hash') != local['hash']
                           and not result['zone_publish'])
    result['up'] = result['inventory_up'] + result['zone_publish']
    result['down'] = result['inventory_down'] + result['zone_pull']
    return result


def sync(database, client, name, held=(), apply_ok=True, seen_versions=()):
    """Everything in one go. Returns dict(sync=web_sync result, zone=zone_publish result or None,
    blocked=None, zone_error=str or None).

    The inventory and the zone database are separate steps: if publishing fails after the inventory
    synced, that is reported as `zone_error`, not as a failed sync. Raises what web_sync.run raises.
    """
    inventory = web_sync.run(database, client, name, held=held, apply_ok=apply_ok)
    zone, zone_error = None, None
    try:
        if zone_publish.records_from_inventory(inventory['merged']):
            zone = retrying(lambda: zone_publish.publish(database, client, name, seen_versions=seen_versions, sync=inventory))
    except (WebError, ValueError, sqlite3.Error) as exc:  # PublishBlocked is a WebError
        zone_error = str(exc)
    return dict(sync=inventory, zone=zone, blocked=None, zone_error=zone_error)
