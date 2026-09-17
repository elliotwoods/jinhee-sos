"""Optional USB identity watcher. No resets, uploads, or database writes."""
import json
from pathlib import Path
import queue
import re
import threading
import time
import serial
from serial.tools import list_ports
from port_lock import PortLock

MAC = re.compile(r'^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$')
CUBE_MAC = re.compile(r'Cube MAC:\s*([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})')
STATION_MAC = '3C:0F:02:AD:83:24'

def native_mac(port):
    value = (port.serial_number or '').upper()
    return value if port.vid == 0x303A and MAC.fullmatch(value) and not int(value[:2],16)&1 else None

def port_key(port):
    return (port.device, port.serial_number, port.location)

def eligible(port, blocked_macs, blocked_ports):
    return bool(port.vid and '/tty.' not in port.device and port.device not in blocked_ports
                and (port.serial_number or '').upper() not in blocked_macs
                and native_mac(port) not in blocked_macs)

def identify(port, stop):
    mac = native_mac(port)
    if mac:
        return mac, 'ESP32 native USB identity'
    with PortLock(port.device):
        conn = serial.Serial(port=None, baudrate=115200, timeout=.1, write_timeout=.5, exclusive=True)
        try:
            conn.dtr = conn.rts = True
            conn.port = port.device
            conn.open()
            conn.rts = False; conn.dtr = False
            deadline = time.monotonic()+4
            text = ''
            next_query = 0
            while not stop.is_set() and time.monotonic()<deadline:
                if time.monotonic() >= next_query:
                    conn.write(b'?'); next_query = time.monotonic()+1
                text = (text + conn.read(4096).decode(errors='replace'))[-8192:]
                found = CUBE_MAC.search(text)
                if found:
                    mac = found[1].upper()
                    if not int(mac[:2],16)&1:
                        return mac, 'Cube serial firmware response'
            raise RuntimeError('No cube MAC response. Older firmware may need the cube unplugged/reconnected; native ESP32 USB is also supported.')
        finally:
            conn.close()

def firmware_result(text, mac, expected):
    """Only attribute a version to a matching cube identity and ready response."""
    identity = CUBE_MAC.search(text)
    version = re.search(r'(?m)^FW:\s*([^\r\n]+)', text)
    if not identity or identity[1].upper() != mac or not version or 'Cube READY' not in text:
        return None
    actual = version[1].strip()
    return dict(version=actual, expected=expected,
                status='current' if expected and actual==expected else 'different' if expected else 'unknown',
                detail='Reported version matches local build' if actual==expected else 'Use USB Flash Station to update' if expected else 'Local build version unavailable')

def check_firmware(port, mac, stop):
    expected = None
    try:
        manifest = Path(__file__).resolve().parents[1]/'flashing_station/build/manifest.json'
        expected = json.loads(manifest.read_text())['version']
    except (OSError, ValueError, KeyError):
        pass
    try:
        with PortLock(port.device):
            conn = serial.Serial(port=None, baudrate=115200, timeout=.1, write_timeout=.5, exclusive=True)
            try:
                conn.dtr = conn.rts = True
                conn.port = port.device
                conn.open()
                conn.rts = False; conn.dtr = False
                deadline = time.monotonic()+4
                text = ''; next_query = 0
                while not stop.is_set() and time.monotonic()<deadline:
                    if time.monotonic()>=next_query:
                        conn.write(b'?'); next_query=time.monotonic()+1
                    text = (text+conn.read(4096).decode(errors='replace'))[-8192:]
                    result = firmware_result(text,mac,expected)
                    if result: return result
                reason = 'No matching firmware/version response; reconnect to retry'
            finally:
                conn.close()
    except Exception as exc:
        reason = str(exc)
    return dict(version=None, expected=expected, status='unknown', detail=reason)

class UsbIdentifier:
    def __init__(self):
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.thread = None
        self.generation = 0

    def start(self, blocked_macs, blocked_ports):
        if self.thread and self.thread.is_alive():
            raise ValueError('USB identification is still stopping; try again shortly')
        self.stop_event = threading.Event()
        self.generation += 1
        generation = self.generation
        self.thread = threading.Thread(target=self._run, args=(set(blocked_macs)|{STATION_MAC}, set(blocked_ports), generation), daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.generation += 1

    def _run(self, blocked_macs, blocked_ports, generation):
        seen = set()
        while not self.stop_event.is_set():
            try:
                ports = [p for p in list_ports.comports() if eligible(p,blocked_macs,blocked_ports)]
                current = {port_key(p) for p in ports}
                for key in seen-current:
                    self.events.put(dict(kind='removed', key=key, generation=generation))
                for port in ports:
                    key = port_key(port)
                    if key in seen: continue
                    try:
                        mac, source = identify(port, self.stop_event)
                        if mac not in blocked_macs and not self.stop_event.is_set():
                            self.events.put(dict(kind='identified',mac=mac,source=source,key=key,generation=generation))
                            firmware = check_firmware(port, mac, self.stop_event)
                            self.events.put(dict(kind='firmware',mac=mac,firmware=firmware,key=key,generation=generation))
                    except Exception as exc:
                        self.events.put(dict(kind='error',detail=str(exc),key=key,generation=generation))
                seen = current
            except Exception as exc:
                self.events.put(dict(kind='error',detail=str(exc),generation=generation))
            self.stop_event.wait(.75)
