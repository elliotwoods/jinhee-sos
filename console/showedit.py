"""The main show editor and wireless show updater, owned by the hub thread.

- The draft is this computer's working copy (metadata `show_draft` in the device database, so a
  --simulate copy never touches it), validated by showfile.py on every save. It starts from the published show (web cache), else shows/mainshow.json (the cube's
  compiled-in default).
- Publishing sends the draft to the web, which allocates the next universal version (jobs/show.py).
- The ShowRegistry distributes the published show to cubes through a relay that speaks `show_send`
  (General Radio general-radio-1.1.0 and later); it holds while the Mainshow controller reports a show.
- After a publish (and whenever a controller that knows `show_config` connects) the controller is told
  the show's length/version/CRC, which bounds its timecode. An older controller is left alone: it works
  exactly as before, without timecode.
"""
import paths  # noqa: F401
import json

import showfile
from show_registry import ShowRegistry

DRAFT_KEY = 'show_draft'


class ShowEditor:
    def __init__(self, hub):
        self.hub = hub
        self.registry = ShowRegistry(hub.db, self._send, self._log, hub.clock, hub.wall)
        self.draft, self.origin = self._initial_draft()
        self.saved_at = None
        self.config_sent = {}     # controller device id -> (length, version, crc) last confirmed
        self.relay_error = None
        default = showfile.load()
        self.default_length = default['length_ms']
        self.default_crc = showfile.crc32(showfile.pack(default))

    # ---------------------------------------------------------------- draft
    def _initial_draft(self):
        try:
            text = self.hub.db.metadata(DRAFT_KEY)
            if text:
                return showfile.validate(json.loads(text)), 'draft'
        except ValueError:
            pass
        try:
            publication = self.registry.store.current()
            return publication.doc, f'published v{publication.version}'
        except ValueError:
            return showfile.load(), 'default'

    def save(self, doc):
        """Validate and keep the working copy. Raises showfile.ShowError (a ValueError) with operator text."""
        doc = showfile.validate(doc)
        self.hub.db.set_metadata(DRAFT_KEY, json.dumps(doc, separators=(',', ':')))
        self.draft, self.origin, self.saved_at = doc, 'draft', self.hub.wall()
        self.hub.mark_dirty('showedit')
        return self.summary()

    def revert(self, source):
        if source == 'published':
            publication = self.registry.store.current()  # ValueError when nothing is published
            doc = publication.doc
            origin = f'published v{publication.version}'
        elif source == 'default':
            doc, origin = showfile.load(), 'default'
        else:
            raise ValueError('Revert to "published" or "default"')
        self.save(doc)
        self.origin = origin
        return self.summary()

    def summary(self):
        image = showfile.pack(self.draft)
        return dict(cues=len(self.draft['cues']), length_ms=self.draft['length_ms'], bytes=len(image),
                    crc=showfile.crc32(image))

    # ---------------------------------------------------------------- relay and controller
    def relay(self):
        """The session that can carry show frames (a General Radio that announced `show` support)."""
        for session in self.hub.sessions.values():
            if getattr(session, 'show_relay', None) and session.show_relay():
                return session
        return None

    def _send(self, message):
        relay = self.relay()
        if not relay:
            raise ValueError('Connect a General Radio (general-radio-1.1.0 or later) to update cube shows')
        relay.transport.send(message)

    def _log(self, text):
        self.hub.log(str(text), 'info', source='show')
        self.hub.mark_dirty('showedit')

    def controller_show_running(self):
        session = self.hub.show_session()
        if not session:
            return False
        state = session.show_state() if hasattr(session, 'show_state') else session.session.show_state()
        length = self._length_for(session)
        return bool(state) and state[0] * 1000 < length

    def _length_for(self, session):
        info = getattr(getattr(session, 'session', None), 'info', None) or getattr(session, 'status', {}) or {}
        return int(info.get('show_length_ms') or self.default_length)

    def push_config(self, session=None):
        """Tell the Mainshow controller (or General Radio) the published show's length. Old firmware: skipped."""
        session = session or self.hub.show_session()
        if not session:
            raise ValueError('No Mainshow controller or General Radio connected')
        info = getattr(getattr(session, 'session', None), 'info', None) or getattr(session, 'status', {}) or {}
        if not info.get('timecode'):
            raise ValueError(f'{info.get("firmware") or "This firmware"} has no show timecode; it still starts '
                             'the show, but reflash it to send timecode')
        publication = self.registry.store.current()
        fields = dict(length_ms=publication.doc['length_ms'], version=publication.version, crc=publication.crc)
        if hasattr(session, 'session'):
            session.session.request('show_config', **fields)
        else:
            session._request('show_config', **fields)
        self.config_sent[session.device.id] = (fields['length_ms'], fields['version'], fields['crc'])
        self._log(f'Show v{publication.version} ({fields["length_ms"] / 1000:.1f} s) sent to the show controller')
        return fields

    def _auto_config(self):
        """Keep a timecode-capable controller in step with the published show, once per change."""
        session = self.hub.show_session()
        if not session:
            return
        info = getattr(getattr(session, 'session', None), 'info', None) or getattr(session, 'status', {}) or {}
        if not info.get('timecode') or not self.registry.store.published()['version']:
            return
        try:
            publication = self.registry.store.current()
        except ValueError:
            return
        wanted = (publication.doc['length_ms'], publication.version, publication.crc)
        reported = (info.get('show_length_ms'), info.get('show_version'), info.get('show_crc'))
        if reported == wanted or self.config_sent.get(session.device.id) == wanted:
            return
        try:
            self.push_config(session)
        except ValueError as exc:
            self.relay_error = str(exc)

    # ---------------------------------------------------------------- hub hooks
    def event(self, event):
        consumed = self.registry.event(event)
        if consumed:
            self.hub.mark_dirty('showedit')
        return consumed

    def tick(self, now):
        relay = self.relay()
        try:
            self.registry.tick(bool(relay), show_running=self.controller_show_running())
            self.relay_error = None
        except ValueError as exc:
            self.relay_error = str(exc)
        self._auto_config()

    def snapshot(self):
        relay = self.relay()
        published = self.registry.store.published()
        try:
            source = self.registry.store.current().doc if published['version'] else None
        except ValueError:
            source = None
        summary = self.summary()
        return dict(draft=self.draft, origin=self.origin, saved_at=self.saved_at, summary=summary,
                    types={name: dict(colours=count, params=list(names)) for name, (_, count, names) in showfile.TYPES.items()},
                    limits=dict(max_cues=showfile.MAX_CUES, max_length_ms=showfile.MAX_LENGTH_MS, level_max=showfile.LEVEL_MAX),
                    published_source=source,
                    draft_published=bool(source) and showfile.pack(source) == showfile.pack(self.draft) and source == self.draft,
                    default_crc=self.default_crc,
                    relay=dict(present=bool(relay), device=relay.device.id if relay else None, error=self.relay_error),
                    show_running=self.controller_show_running(), **self.registry.snapshot())


def draft_from_json(text):
    """Parse an imported JSON show (the editor's Import box)."""
    try:
        return showfile.validate(json.loads(text))
    except json.JSONDecodeError as exc:
        raise ValueError(f'Not JSON: {exc}') from exc
