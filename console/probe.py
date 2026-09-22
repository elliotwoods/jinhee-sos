"""What is on a USB port? Asked without resetting the board.

`classify(lines)` is pure: it turns a transcript into (role, details). `Prober` runs the probe
sequence on a worker, one port at a time, and only for ports the hub says are free (no session,
no job, not the protected station, not held by another app):
  1. listen 0.4 s               PoolCentral status and RangeTest STAT lines are unsolicited
  2. "?"                        cube (bare byte; a trailing newline is ignored), zone plate,
                                Mainshow controller, PreshowBridge; a pairing station answers
                                {"event":"error","detail":"Invalid JSON"}, which is a hint
  3. {"cmd":"hello"}            pairing station / ESP-NOW dongle / Mainshow controller
  4. "STATUS"                   PoolRadioTest bridge, PoolCentral, RangeTest, PreshowBridge
Nothing that arms, sets or moves anything is ever sent while probing.
"""
import paths  # noqa: F401
import json
import queue
import re
import threading
import time
import uuid

from port_lock import PortLock
from serial_open import open_serial
from zone_build import FIRMWARE_PREFIX
from zone_flash import parse_report

CUBE_MAC = re.compile(r'Cube MAC:\s*([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})')
FW = re.compile(r'(?m)^FW:\s*([^\r\n]+)')
MAC = re.compile(r'(?m)^MAC:\s*([0-9A-Fa-f:]{17})')
CHANNEL = re.compile(r'(?m)^CHANNEL:\s*(\d+)')
ROLES = ('cube', 'zone', 'station', 'generalradio', 'mainshow', 'poolcentral', 'preshowbridge', 'pooltest', 'rangetest', 'unknown')
ZONE_ROLE_BY_TYPE = {1: 'preshow', 2: 'desert', 3: 'pool', 4: 'mainshow_plate', 5: 'reset'}


def _json_lines(lines):
    for line in lines:
        if line.startswith('{'):
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                yield value


def classify(lines):
    """(role, details) from a transcript. `role` is one of ROLES; details are role-specific."""
    text = '\n'.join(lines)
    for value in _json_lines(lines):
        if value.get('event') == 'hello':
            firmware = str(value.get('firmware') or '')
            if firmware.startswith('mainshow-'):
                return 'mainshow', dict(value, mac=(value.get('mac') or '').upper())
            if firmware.startswith('general-radio-') or 'roles' in value:
                return 'generalradio', dict(value, mac=(value.get('mac') or '').upper())
            return 'station', dict(value, mac=(value.get('mac') or '').upper())
        device = value.get('device')
        if device == 'PoolCentral':
            return 'poolcentral', dict(value, mac=(value.get('mac') or '').upper())
        if device == 'PreshowBridge':
            return 'preshowbridge', dict(value, mac=(value.get('mac') or '').upper())
        if device == 'PoolRadioTest':
            return 'pooltest', dict(value, mac=(value.get('mac') or '').upper())
    cube = CUBE_MAC.search(text)
    if cube:
        fw = FW.search(text)
        channel = re.search(r'ESP-NOW CHANNEL:\s*(\d+)', text)
        return 'cube', dict(mac=cube[1].upper(), firmware=fw[1].strip() if fw else None,
                            channel=int(channel[1]) if channel else None, ready='Cube READY' in text,
                            unregistered='UNREGISTERED' in text)
    report = parse_report(text)
    if report and any(report['firmware'].startswith(p) for p in FIRMWARE_PREFIX):
        return 'zone', report
    if 'NCT GENERAL RADIO' in text or re.search(r'(?m)^FW:\s*general-radio-', text):
        fw, mac, ch = FW.search(text), MAC.search(text), CHANNEL.search(text)
        return 'generalradio', dict(firmware=fw[1].strip() if fw else None, mac=mac[1].upper() if mac else '',
                                    channel=int(ch[1]) if ch else None, radio_ok='RADIO: OK' in text)
    if 'NCT MAINSHOW CONTROLLER' in text or re.search(r'(?m)^FW:\s*mainshow-', text):
        fw, mac, ch = FW.search(text), MAC.search(text), CHANNEL.search(text)
        return 'mainshow', dict(firmware=fw[1].strip() if fw else None, mac=mac[1].upper() if mac else '',
                                channel=int(ch[1]) if ch else None, radio_ok='RADIO: OK' in text)
    if 'NCT PRESHOW MEDIA BRIDGE' in text:
        mac = re.search(r'MAC=([0-9A-Fa-f:]{17})', text)
        return 'preshowbridge', dict(mac=mac[1].upper() if mac else '')
    if 'POOL CENTRAL' in text:
        mac = re.search(r'MAC=([0-9A-Fa-f:]{17})', text)
        version = re.search(r'POOL CENTRAL (\S+)', text)
        return 'poolcentral', dict(mac=mac[1].upper() if mac else '', version=version[1] if version else None)
    if 'NCT RANGE TEST' in text or re.search(r'(?m)^STAT role=', text):
        role = re.search(r'(?m)^STAT role=(\w+)', text)
        return 'rangetest', dict(role=role[1] if role else None)
    if 'NCT NEOCORE CUBE' in text:
        return 'cube', dict(mac=None, firmware=None, channel=None, ready=False, booting=True)
    if any(v.get('event') == 'error' and v.get('detail') == 'Invalid JSON' for v in _json_lines(lines)):
        return 'unknown', dict(hint='station')
    return 'unknown', {}


def run_probe(path, listen=0.4, wait=1.5, status_wait=1.0, opener=open_serial, clock=time.monotonic,
              sleep=time.sleep):
    """The full sequence on one open port. Returns (role, details, transcript)."""
    transcript = []
    buffer = b''

    def collect(conn, seconds, stop_when):
        nonlocal buffer
        deadline = clock() + seconds
        while clock() < deadline:
            data = conn.read(4096)
            if data:
                buffer += data
                while b'\n' in buffer:
                    raw, buffer = buffer.split(b'\n', 1)
                    text = raw.decode(errors='replace').strip('\r')
                    if text.strip():
                        transcript.append(text)
                if stop_when and stop_when(transcript):
                    return
            else:
                sleep(0.02)

    def known(lines):
        return classify(lines)[0] != 'unknown'

    with PortLock(path):
        conn = opener(path, timeout=0.05, write_timeout=0.5)
        try:
            collect(conn, listen, known)
            if not known(transcript):
                conn.write(b'?\n')
                collect(conn, wait, known)
            if not known(transcript):
                conn.write((json.dumps(dict(cmd='hello', id='probe-' + uuid.uuid4().hex[:8])) + '\n').encode())
                collect(conn, wait, known)
            if not known(transcript):
                conn.write(b'STATUS\n')
                collect(conn, status_wait, known)
        finally:
            conn.close()
    role, details = classify(transcript)
    return role, details, transcript


class Prober:
    """Worker that probes one port at a time. Results: (port_dict, role, details, transcript, error)."""

    def __init__(self, probe_fn=run_probe):
        self.probe_fn = probe_fn
        self.requests = queue.Queue()
        self.results = queue.Queue()
        self.stopping = threading.Event()
        self.thread = None
        self.busy_with = None

    def start(self):
        self.thread = threading.Thread(target=self._run, name='usb-probe', daemon=True)
        self.thread.start()
        return self

    def request(self, port):
        self.requests.put(port)

    def _run(self):
        while not self.stopping.is_set():
            try:
                port = self.requests.get(timeout=0.2)
            except queue.Empty:
                continue
            self.busy_with = port['port']
            try:
                role, details, transcript = self.probe_fn(port['port'])
                self.results.put((port, role, details, transcript, None))
            except Exception as exc:
                self.results.put((port, None, None, [], str(exc)))
            finally:
                self.busy_with = None

    def stop(self):
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=3)
