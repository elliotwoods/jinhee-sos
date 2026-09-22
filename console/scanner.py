"""USB port enumeration off the owner thread (comports() can take a few hundred ms on macOS)."""
import paths  # noqa: F401
import queue
import threading
import time

from backend import ports as list_usb_ports


class PortScanner:
    def __init__(self, ports_fn=list_usb_ports, interval=1.0):
        self.ports_fn, self.interval = ports_fn, interval
        self.results = queue.Queue()
        self.stopping = threading.Event()
        self.wake = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run, name='usb-scan', daemon=True)
        self.thread.start()
        return self

    def rescan(self):
        self.wake.set()

    def _run(self):
        while not self.stopping.is_set():
            try:
                self.results.put(('ports', self.ports_fn()))
            except Exception as exc:  # a broken enumeration must not kill the scanner
                self.results.put(('error', str(exc)))
            self.wake.wait(self.interval)
            self.wake.clear()

    def latest(self):
        """The newest port list since the last call, or None."""
        latest = None
        while True:
            try:
                kind, value = self.results.get_nowait()
            except queue.Empty:
                return latest
            if kind == 'ports':
                latest = value

    def stop(self):
        self.stopping.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=2)
