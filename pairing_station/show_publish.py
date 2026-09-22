"""Publish and pull the main show through the web, which allocates universal show versions.

Cubes accept only a higher show version, so versions come from one place (the web), never from a
per-computer counter. `publish` sends the editor's JSON with its packed image (the server checks
they agree); `pull` fetches the current publication so this computer can distribute it (also
later, offline). Network calls block: run them on a worker.
"""
import base64

from database import Database
from show_registry import ShowStore
from web_client import WebError
import showfile


def pull(database, client):
    """Fetch the web show into the local cache. Returns (published, 'updated' | 'current' | 'none')."""
    doc = client.show_pull()
    db = Database(database, recover_pending=False)
    try:
        store = ShowStore(db)
        if not doc.get('version'):
            return store.published(), 'none'
        status = 'updated' if store.cache(doc) else 'current'
        return store.published(), status
    finally:
        db.close()


def publish(database, client, name, doc, seen_versions=()):
    """Publish a show document as the next universal version (identical content keeps the current one).

    `seen_versions`: show versions reported on air, so the new version is above anything a cube runs.
    The returned publication is cached either way, so this is also a pull.
    """
    doc = showfile.validate(doc)
    image = showfile.pack(doc)
    db = Database(database, recover_pending=False)
    try:
        store = ShowStore(db)
        min_version = max([store.published()['version'], store.highest_seen(), *seen_versions])
        result = client.show_publish(doc, base64.b64encode(image).decode(), min_version, name)
        if base64.b64decode(result.get('image_b64', '')) != image:
            raise WebError('Web returned a different show than was published')
        store.cache(result)
        return dict(published=store.published(), changed=bool(result.get('changed')))
    finally:
        db.close()
