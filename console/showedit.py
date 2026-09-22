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
- Mirroring (`live`): while the editor's "Mirror on real cubes" is on, the page sends the colour each
  previewed cube number shows at the playhead; each call becomes broadcast SHOW_LIVE frames through the
  relay (general-radio-1.2.0). Cubes on firmware v1.7.0+ whose number is listed show that colour for the
  lease, then fall back; a cube playing a show ignores it. Fire-and-forget: the relay's `show_sent` /
  `error` replies for those frames are swallowed here, never counted by the registry.
"""
import paths  # noqa: F401
import json
import uuid
from collections import OrderedDict

import showfile
from show_registry import ShowRegistry

DRAFT_KEY = 'show_draft'
BROADCAST = 'FF:FF:FF:FF:FF:FF'
LIVE_MIN_INTERVAL_S = 0.04   # calls closer than this are dropped (the page sends every ~60 ms)
LIVE_ACTIVE_S = 1.0          # "mirroring" in the snapshot while calls arrived this recently
LIVE_NEEDS = 'needs a General Radio running general-radio-1.2.0 and cubes with firmware v1.7.0-USB.1'


class ShowEditor:
    def __init__(self, hub):
        self.hub = hub
        self.registry = ShowRegistry(hub.db, self._send, self._log, hub.clock, hub.wall)
        self.draft, self.origin = self._initial_draft()
        self.saved_at = None
        self.config_sent = {}     # controller device id -> (length, version, crc) last confirmed
        self.relay_error = None
        self.clock = hub.clock
        # Mirroring (live): request ids of fire-and-forget SHOW_LIVE frames, newest last.
        self.live_ids = OrderedDict()
        self.live_last = None       # clock of the last sent live call
        self.live_held = None       # why the last call sent nothing (show update / running show)
        self.live_error = None      # the relay refused a live frame (older firmware)
        self.live_sent = 0
        self.live_cubes = []
        self._live_reported = None
        default = showfile.load()
        self.default_length = default['length_ms']
        self.default_crc = showfile.crc32(showfile.pack(default))
        self.default_doc = default

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

    # ---------------------------------------------------------------- mirroring on real cubes
    def live(self, entries, lease_ms=600):
        """Broadcast the colours the editor shows for each cube number (SHOW_LIVE), rate limited.

        Returns dict(sent=frames, ...); dropped=True when closer than LIVE_MIN_INTERVAL_S to the last send,
        held=<reason> while a show update is being sent or the show controller reports a running show.
        """
        relay = self.relay()
        if not relay:
            raise ValueError(f'No show relay connected: mirroring on real cubes {LIVE_NEEDS}')
        if self.live_error:
            error, self.live_error = self.live_error, None
            self.hub.mark_dirty('showedit')
            raise ValueError(f'The General Radio refused the live colours ({error}): mirroring {LIVE_NEEDS}')
        try:
            clean = [(int(cube), [int(v) for v in rgb]) for cube, rgb in entries or ()]
        except (TypeError, ValueError) as exc:
            raise ValueError(f'Live entries are [[cube number, [r, g, b]], ...]: {exc}') from exc
        frames = showfile.live(clean, int(lease_ms))  # validates numbers, levels and the lease
        held = None
        if self.registry.publication is not None:
            held = 'A show update is being sent; mirroring resumes when it finishes'
        elif self.controller_show_running():
            held = 'A show is running on the controller; mirroring resumes when it ends'
        if held != self.live_held:
            self.live_held = held
            self.hub.mark_dirty('showedit')
        if held:
            return dict(sent=0, held=held)
        now = self.clock()
        if self.live_last is not None and 0 <= now - self.live_last < LIVE_MIN_INTERVAL_S:
            return dict(sent=0, dropped=True)
        for frame in frames:
            request = uuid.uuid4().hex
            self.live_ids[request] = now
            # Listed with the registry so general_radio.py routes a refusal (`error`) here; event() swallows it.
            self.registry.requests[request] = 'live'
            relay.transport.send(dict(cmd='show_send', id=request, mac=BROADCAST, hex=frame.hex().upper()))
        while len(self.live_ids) > 64:
            old, _ = self.live_ids.popitem(last=False)
            self.registry.requests.pop(old, None)
        self.live_last, self.live_sent = now, self.live_sent + len(frames)
        cubes = [cube for cube, _ in clean]
        if cubes != self.live_cubes:
            self.live_cubes = cubes
            self.hub.mark_dirty('showedit')
        return dict(sent=len(frames), cubes=len(clean))

    def _live_event(self, event):
        request = event.get('id')
        if not request or request not in self.live_ids:
            return False
        kind = event.get('event')
        if kind in ('show_sent', 'error'):
            self.live_ids.pop(request, None)
            self.registry.requests.pop(request, None)
        if kind == 'error' and not self.live_error:
            self.live_error = str(event.get('detail') or 'refused')
            self.hub.log(f'The General Radio refused a live colour frame ({self.live_error}); mirroring {LIVE_NEEDS}',
                         'warn', source='show')
            self.hub.mark_dirty('showedit')
        return True

    def live_snapshot(self):
        active = self.live_last is not None and self.clock() - self.live_last < LIVE_ACTIVE_S
        return dict(active=active, cubes=self.live_cubes if active else [], held=self.live_held,
                    error=self.live_error, sent=self.live_sent)

    # ---------------------------------------------------------------- hub hooks
    def event(self, event):
        if self._live_event(event):
            return True
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
        live = self.live_snapshot()['active']
        if live != self._live_reported:  # mirroring started or stopped: refresh the page's status line
            self._live_reported = live
            self.hub.mark_dirty('showedit')

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
                    default_crc=self.default_crc, default_doc=self.default_doc,
                    relay=dict(present=bool(relay), device=relay.device.id if relay else None, error=self.relay_error,
                               firmware=(getattr(relay, 'status', None) or {}).get('firmware') if relay else None),
                    live=self.live_snapshot(),
                    show_running=self.controller_show_running(), **self.registry.snapshot())


def draft_from_json(text):
    """Parse an imported JSON show (the editor's Import box)."""
    try:
        return showfile.validate(json.loads(text))
    except json.JSONDecodeError as exc:
        raise ValueError(f'Not JSON: {exc}') from exc
