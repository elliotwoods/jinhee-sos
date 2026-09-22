"""Instance locks: the console holds every old app's lock while it runs, so the two never share
one database at the same time (the old apps refuse at their own startup with their existing
message; the console names the app that is in the way)."""
import paths  # noqa: F401

import hostos

APP_NAMES = {'.console.lock': 'Another NCT Console window', '.lock': 'The Pairing station app',
             '.flasher.lock': 'The Cube USB flasher', '.zonedb.lock': 'The Zone Database Manager',
             '.mainshow.lock': 'The Mainshow controller app'}
SUFFIXES = tuple(APP_NAMES)


class AlreadyOpen(RuntimeError):
    pass


class InstanceLocks:
    def __init__(self, database):
        self.database = database
        self.handles = []
        for suffix in SUFFIXES:
            handle = database.with_suffix(suffix).open('a')
            try:
                hostos.lock_file(handle)
            except BlockingIOError:
                handle.close()
                self.close()
                raise AlreadyOpen(f'{APP_NAMES[suffix]} is already open on this database; close it before starting the NCT Console')
            self.handles.append(handle)

    @property
    def held(self):
        return SUFFIXES

    def close(self):
        for handle in self.handles:
            try:
                handle.close()
            except OSError:
                pass
        self.handles = []


def instance_locks(database, skip=('.console.lock',)):
    """Which of the old apps' locks are held by another process (open-then-close; never holds)."""
    held = {}
    for suffix in SUFFIXES:
        if suffix in skip:
            continue
        try:
            with database.with_suffix(suffix).open('a') as handle:
                try:
                    hostos.lock_file(handle)
                    held[suffix] = False
                except BlockingIOError:
                    held[suffix] = True
        except OSError:
            held[suffix] = False
    return held
