"""Cross-app advisory ownership, in addition to pyserial's exclusive open."""
import fcntl
import hashlib
import os
from pathlib import Path

class PortLock:
    def __init__(self, port):
        key = hashlib.sha256(port.replace('/tty.', '/cu.').encode()).hexdigest()[:24]
        self.file = (Path('/tmp') / f'neocore-{os.getuid()}-{key}.lock').open('a')
        try:
            fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.file.close()
            raise RuntimeError('USB port is owned by another Neocore application')
    def close(self):
        self.file.close()
    def __enter__(self): return self
    def __exit__(self, *args): self.close()
