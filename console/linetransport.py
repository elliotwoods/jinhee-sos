"""Raw newline-delimited serial link (pairing_station/transport.py carries JSON only).

Opened with the esp-idf-monitor no-reset sequence (rangetest/serial_open.py) under the cross-app
PortLock. One daemon thread reads and writes; the owner thread drains `inbox`:
  ('line', text)          one received line, CR/LF stripped
  ('disconnected', why)   the link died (the thread has stopped)
"""
import paths  # noqa: F401
import queue
import threading

import serial

from port_lock import PortLock
from serial_open import open_serial


class LineTransport:
    def __init__(self):
        self.inbox = queue.Queue()
        self.outbox = queue.Queue()
        self.stopping = threading.Event()
        self.thread = None
        self.port = None
        self.path = None
        self.port_lock = None

    def open(self, path):
        self.close()
        self.inbox, self.outbox, self.stopping = queue.Queue(), queue.Queue(), threading.Event()
        self.port_lock = PortLock(path)
        try:
            self.port = open_serial(path, timeout=0.05, write_timeout=0.5)
        except Exception:
            self.port_lock.close()
            self.port_lock = None
            raise
        self.path = path
        self.thread = threading.Thread(target=self._run, name=f'line-{path}', daemon=True)
        self.thread.start()

    @property
    def is_open(self):
        return bool(self.port and self.port.is_open and not self.stopping.is_set())

    def send(self, line):
        if not self.is_open:
            raise ValueError('Serial port is disconnected')
        self.outbox.put(line)

    def _run(self):
        buffer = bytearray()
        try:
            while not self.stopping.is_set():
                for _ in range(20):
                    try:
                        line = self.outbox.get_nowait()
                    except queue.Empty:
                        break
                    self.port.write((line + '\n').encode())
                buffer.extend(self.port.read(self.port.in_waiting or 1))
                while b'\n' in buffer:
                    raw, _, remainder = buffer.partition(b'\n')
                    buffer = bytearray(remainder)
                    text = raw.decode(errors='replace').strip('\r')
                    if text.strip():
                        self.inbox.put(('line', text))
                if len(buffer) > 16384:
                    buffer.clear()
        except (serial.SerialException, OSError) as exc:
            self.inbox.put(('disconnected', str(exc)))
            self.stopping.set()

    def write_now(self, line):
        """Best-effort synchronous write used only while closing (e.g. HOST DISARM, OFF)."""
        try:
            if self.port and self.port.is_open:
                self.port.write((line + '\n').encode())
                self.port.flush()
        except (serial.SerialException, OSError):
            pass

    def close(self, farewell=None):
        self.stopping.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)
        if farewell:
            self.write_now(farewell)
        if self.port:
            try:
                self.port.close()
            except (serial.SerialException, OSError):
                pass
        self.port = self.thread = self.path = None
        if self.port_lock:
            self.port_lock.close()
            self.port_lock = None
