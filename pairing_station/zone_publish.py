"""Publish and pull the zone database through the web inventory, which allocates universal versions.

Zones accept only a higher database version. Versions therefore come from one place (the web),
never from a per-computer counter. `publish` first synchronizes the device inventory so the
published content is exactly the web records; `pull` fetches the current publication so a
computer can distribute it (also later, offline). Network calls block: run them on a worker.
"""
import base64

from database import Database
from web_client import WebError
from zone_registry import ZoneStore
import web_sync
import zonedb


class PublishBlocked(WebError):
    pass


def records_from_inventory(records):
    """Zone records from web-inventory records (same rule as ZoneStore.records: committed, not excluded)."""
    rows = [r for r in records.values() if 'cube_id' in r and r.get('role') != 'excluded']
    return zonedb.records_from_rows(rows)


def pull(database, client):
    """Fetch the web publication into the local cache.

    Returns (published dict, status): 'updated', 'current', 'none' (nothing on the web yet) or
    'legacy_ahead' (a legacy local version is above the web's: Push & publish lifts the web above it).
    """
    doc = client.zonedb_pull()
    db = Database(database, recover_pending=False)
    try:
        store = ZoneStore(db)
        if not doc.get('version'):
            return store.published(), 'none'
        if store.cache(doc):
            return store.published(), 'updated'
        published = store.published()
        return published, 'current' if published['hash'] == doc['hash'] else 'legacy_ahead'
    finally:
        db.close()


def publish(database, client, name, seen_versions=(), sync=None):
    """Sync the inventory, then publish its zone records as the next universal version.

    `seen_versions`: database versions reported on air this session, so the new version is higher
    than anything a zone already runs (legacy local counters). `sync`: an already-run web_sync.run
    result (the inventory is then not synchronized again). Identical content keeps the current
    version, and the returned publication is cached either way (so this is also a pull).
    """
    sync = sync or web_sync.run(database, client, name)
    if sync['conflicts']:
        raise PublishBlocked(f'{len(sync["conflicts"])} inventory conflict(s) need a decision in Web Inventory Sync first')
    records = records_from_inventory(sync['merged'])
    if not records:
        raise PublishBlocked('The inventory has no committed cube mappings; refusing to publish an empty database')
    db = Database(database, recover_pending=False)
    try:
        store = ZoneStore(db)
        min_version = max([store.published()['version'], store.highest_seen(), *seen_versions])
        body = zonedb.pack_records(records)
        doc = client.zonedb_publish(base64.b64encode(body).decode(), min_version, sync['revision'], name)
        if doc.get('hash') != zonedb.content_hash(records):
            raise WebError('Web returned a different zone database than was published')
        store.cache(doc)
        return dict(published=store.published(), changed=bool(doc.get('changed')), sync=sync,
                    local_differs=store.local_differs())
    finally:
        db.close()
