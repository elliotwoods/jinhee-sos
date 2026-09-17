"""One serial worker; heartbeat is driven by the responsive GUI thread."""
import json
import queue
import threading
import serial
from port_lock import PortLock

class Transport:
    def __init__(self):
        self.inbox = queue.Queue()
        self.outbox = queue.Queue()
        self.stopping = threading.Event()
        self.thread = None
        self.port = None
        self.port_lock = None

    def open(self, path):
        self.close()
        self.inbox = queue.Queue()
        self.outbox = queue.Queue()
        self.stopping = threading.Event()
        self.port_lock = PortLock(path)
        self.port = serial.Serial(port=None, baudrate=115200, timeout=0.1, write_timeout=1, exclusive=True)
        # Follow esp-idf-monitor's no-reset open: assert both before open,
        # then release RTS before DTR. Opening directly with both False can
        # reset native USB-JTAG ESP32-C3 and interrupt an I2C transaction.
        try:
            self.port.dtr = True
            self.port.rts = True
            self.port.port = path
            self.port.open()
            self.port.rts = False
            self.port.dtr = False
        except Exception:
            self.close()
            raise
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def send(self, data):
        if not self.port or not self.port.is_open or self.stopping.is_set():
            raise ValueError('Serial port is disconnected')
        self.outbox.put(data)

    def _run(self):
        buffer = bytearray()
        try:
            while not self.stopping.is_set():
                for _ in range(20):
                    try:
                        message = self.outbox.get_nowait()
                    except queue.Empty:
                        break
                    self.port.write((json.dumps(message, separators=(',', ':'))+'\n').encode())
                buffer.extend(self.port.read(self.port.in_waiting or 1))
                while b'\n' in buffer:
                    line, _, remainder = buffer.partition(b'\n')
                    buffer = bytearray(remainder)
                    try:
                        event = json.loads(line)
                        if isinstance(event, dict):
                            self.inbox.put(event)
                    except (ValueError, UnicodeDecodeError):
                        self.inbox.put(dict(event='boot_log', detail=line.decode(errors='replace')))
                if len(buffer) > 8192:
                    buffer.clear()
        except (serial.SerialException, OSError) as exc:
            self.inbox.put(dict(event='disconnected', detail=str(exc)))
            self.stopping.set()

    def close(self):
        self.stopping.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)
        if self.port:
            self.port.close()
        self.port = self.thread = None
        if self.port_lock:
            self.port_lock.close()
            self.port_lock = None
