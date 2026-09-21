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
    """Fetch the web publication into the local cache. Returns (published dict, updated bool)."""
    doc = client.zonedb_pull()
    db = Database(database, recover_pending=False)
    try:
        store = ZoneStore(db)
        updated = bool(doc.get('version')) and store.cache(doc)
        return store.published(), updated
    finally:
        db.close()


def publish(database, client, name, seen_versions=()):
    """Sync the inventory, then publish its zone records as the next universal version.

    `seen_versions`: database versions reported on air this session, so the new version is higher
    than anything a zone already runs (legacy local counters). Returns a result dict.
    """
    sync = web_sync.run(database, client, name)
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
