"""Cross-app advisory ownership, in addition to pyserial's exclusive open."""
import hashlib

import hostos

class PortLock:
    def __init__(self, port):
        key = hashlib.sha256(hostos.canonical_port(port).encode()).hexdigest()[:24]
        self.file = (hostos.lock_dir() / f'neocore-{hostos.user_tag()}-{key}.lock').open('a')
        try:
            hostos.lock_file(self.file)
        except BlockingIOError:
            self.file.close()
            raise RuntimeError('USB port is owned by another Neocore application')
    def close(self):
        self.file.close()
    def __enter__(self): return self
    def __exit__(self, *args): self.close()
