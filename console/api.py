"""The surface JavaScript calls (pywebview js_api, or the browser fallback's POST /api/<method>).

Every method is thin: it enqueues onto the owner thread and waits. Results are plain JSON.
`call` never raises: it answers {ok, result} or {ok: False, error, kind}.
"""
import paths  # noqa: F401
import json
import time
import traceback

import commands
import commands_extra  # noqa: F401  (registers into commands.COMMANDS)
import commands_show  # noqa: F401  (registers into commands.COMMANDS)
import uitext


def plain(value):
    return json.loads(json.dumps(value, default=repr, allow_nan=False))


class Api:
    def __init__(self, hub):
        self.hub = hub

    def ping(self):
        return dict(ok=True, t=time.time(), booted=self.hub.booted)

    def pull(self, since=None, since_seq=0):
        try:
            return plain(self.hub.call(self.hub.pull, since, since_seq).result(timeout=15))
        except Exception as exc:
            return dict(ok=False, error=str(exc))

    def call(self, name, args=None):
        try:
            result = self.hub.call(commands.run, self.hub, name, args or {}).result(timeout=60)
            return plain(dict(ok=True, result=result))
        except ValueError as exc:
            return dict(ok=False, error=str(exc), kind='value')
        except Exception as exc:
            self.hub.log(f'{name} failed: {exc}', 'bad', source='api')
            return dict(ok=False, error=str(exc) or exc.__class__.__name__, kind='internal',
                        traceback=traceback.format_exc()[-2000:])

    def confirm(self, name, args=None):
        try:
            return plain(self.hub.call(self.hub.confirm, name, args or {}).result(timeout=5))
        except Exception as exc:
            return dict(ok=False, error=str(exc))

    def get_copy(self):
        return plain(dict(copy=uitext.as_dict(), commands=commands.catalogue()))

    def get_lines(self, device, since_seq=0, limit=500):
        try:
            return plain(self.hub.call(self.hub.lines_for, device, since_seq, limit).result(timeout=5))
        except Exception as exc:
            return dict(ok=False, error=str(exc))

    def shutdown(self, force=False):
        try:
            return dict(ok=bool(self.hub.call(self.hub.shutdown, force).result(timeout=10)))
        except ValueError as exc:
            return dict(ok=False, error=str(exc))
