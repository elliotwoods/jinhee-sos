"""A session holds one USB port for one identified role, on the hub's owner thread.

Lifecycle: open() -> pump() (drain the transport inbox) and tick(now) every 100 ms -> close(reason).
Subclasses never touch Tk or a worker; they may read/write the hub's SQLite because they run on
the owner thread. `snapshot()` must return plain JSON-able data.
"""
import paths  # noqa: F401
import time
import uuid
from collections import deque

import lines as line_rules


class Session:
    kind = 'base'
    rules_role = None       # lines.classify role when it differs from `kind` (pool/preshow plates are zones)
    SILENCE = None          # seconds without any line before the session gives up (None: never)

    def __init__(self, hub, device):
        self.hub, self.device = hub, device
        self.id = uuid.uuid4().hex[:10]
        self.clock = hub.clock
        self.transport = None
        self.opened_at = self.last_rx = 0.0
        self.recent = deque(maxlen=400)   # (t, dir, text) for backfill
        self.tags = deque(maxlen=200)     # (t, tag dict) notable classified lines
        self.closed_reason = None

    # ---- lifecycle ----
    def open(self):
        raise NotImplementedError

    def close(self, reason='closed'):
        self.closed_reason = reason

    def pump(self):
        pass

    def tick(self, now):
        if self.SILENCE and self.transport and self.last_rx and now - self.last_rx > self.SILENCE:
            self.hub.log(f'{self.label}: no answer for {self.SILENCE:.0f} s; link closed', 'warn', self.device.id)
            self.hub.close_session(self, 'silent')

    def stop_active(self):
        """Esc / global Stop: end anything this session is doing to hardware."""

    # ---- helpers ----
    @property
    def label(self):
        return f'{self.device.role_label()} on {self.device.port}'

    def saw(self, text, direction='rx', role=None):
        now = self.clock()
        self.last_rx = now if direction == 'rx' else self.last_rx
        self.recent.append((now, direction, text))
        self.hub.line_event(self.device.id, direction, text)
        if direction == 'rx':
            tag = line_rules.classify(role or self.rules_role or self.kind, text)
            if tag:
                self.tags.append((self.hub.wall(), tag))
                self.hub.tag_event(self.device.id, tag)
            return tag
        return None

    def snapshot(self):
        return dict(kind=self.kind, id=self.id, opened_at=self.opened_at, last_rx=self.last_rx,
                    age_s=round(self.clock() - self.last_rx, 1) if self.last_rx else None,
                    tags=[dict(t=t, **tag) for t, tag in list(self.tags)[-50:]])
