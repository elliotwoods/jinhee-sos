"""One record per USB-attached board (and what the console believes about it).

State machine per port:
  present   just enumerated; a probe may be requested
  probing   the prober is talking to it
  idle      identified (or given up on); nobody holds the port
  session   a role session holds the port
  job       a flash/build job holds the port
  foreign   another application owns the port (PortLock refused); re-checked later
  protected the installed pairing station's USB identity: never opened by a probe
"""
import paths  # noqa: F401
import time

from core import PROTECTED
from usb_identify import MAC as MAC_RE

LABELS = {'cube': 'Neocore cube', 'zone': 'Zone plate', 'station': 'Pairing station / ESP-NOW dongle',
          'mainshow': 'Mainshow controller', 'generalradio': 'General Radio (all-in-one dongle)', 'poolcentral': 'Pool central controller',
          'preshowbridge': 'Preshow media bridge', 'pooltest': 'Pool light test bridge',
          'rangetest': 'ESP-NOW range test board', 'unknown': 'Unidentified ESP32 board', 'other': 'USB serial device'}


def usb_mac(port):
    value = (port.get('serial') or '').upper()
    return value if port.get('native_usb') and MAC_RE.fullmatch(value) and not int(value[:2], 16) & 1 else None


class Device:
    MAX_ATTEMPTS = 3
    RETRY_AFTER = 5.0
    FOREIGN_RETRY = 5.0

    def __init__(self, port, clock=time.monotonic):
        self.clock = clock
        self.port = port['port']
        self.key = port['key']
        self.serial = port.get('serial')
        self.description = port.get('description')
        self.native_usb = bool(port.get('native_usb'))
        self.candidate = bool(port.get('candidate'))
        self.usb_mac = usb_mac(port)
        self.first_seen = self.last_seen = clock()
        self.role = None            # from the probe
        self.details = {}
        self.transcript = []
        self.firmware = None
        self.mac = self.usb_mac
        self.presumed = {}          # dict(role, label, detail) from the inventory, before/without a probe
        self.state = 'protected' if (self.serial or '').upper() in PROTECTED else 'present'
        self.attempts = 0
        self.next_probe = 0.0
        self.probed_at = None
        self.error = None
        self.session = None         # session id while a session holds the port
        self.job = None             # job id while a job holds the port
        self.pinned = False         # a cube identified over USB stays selected until unpinned
        self.fw_status = None       # usb_identify.firmware_result for cubes
        self.detection = None       # zone_detect result from an explicit bootloader read
        self.gone_since = None

    @property
    def id(self):
        return self.mac or f'usb:{self.key}'

    def role_label(self):
        return LABELS.get(self.role or self.presumed.get('role') or 'unknown')

    @property
    def zone_type(self):
        return (self.details or {}).get('zone_type')

    def refresh(self, port):
        self.port, self.description = port['port'], port.get('description')
        self.last_seen = self.clock()
        self.gone_since = None

    def wants_probe(self):
        if self.state != 'present' or not self.candidate:
            return False
        return self.clock() >= self.next_probe and self.attempts < self.MAX_ATTEMPTS

    def probe_started(self):
        self.state = 'probing'
        self.attempts += 1

    def probe_result(self, role, details, transcript, error):
        now = self.clock()
        self.probed_at = now
        self.transcript = list(transcript)[-200:]
        if error:
            if 'owned by another' in error or 'Resource busy' in error or 'Permission denied' in error:
                self.state, self.error = 'foreign', error
                self.next_probe = now + self.FOREIGN_RETRY
                self.attempts = max(0, self.attempts - 1)
                return
            self.error = error
            self.state = 'present' if self.attempts < self.MAX_ATTEMPTS else 'idle'
            self.next_probe = now + self.RETRY_AFTER
            return
        self.error = None
        if role == 'unknown' or (role == 'cube' and details.get('booting')):
            # Not answering yet (a cube before usbReady, a board still booting): try again a few times.
            if self.attempts < self.MAX_ATTEMPTS:
                self.state = 'present'
                self.next_probe = now + self.RETRY_AFTER
                self.role = self.role or role
                self.details = details or self.details
                return
            self.state = 'idle'
            self.role = 'unknown'
            self.details = details
            return
        self.role, self.details, self.state = role, dict(details), 'idle'
        self.firmware = details.get('firmware') or details.get('version') or self.firmware
        mac = details.get('mac')
        if mac and MAC_RE.fullmatch(mac.upper()):
            self.mac = mac.upper()

    def to_dict(self):
        return dict(id=self.id, port=self.port, key=self.key, serial=self.serial, description=self.description,
                    native_usb=self.native_usb, candidate=self.candidate, usb_mac=self.usb_mac, mac=self.mac,
                    role=self.role, role_label=LABELS.get(self.role or self.presumed.get('role') or 'unknown'),
                    presumed=self.presumed, firmware=self.firmware, details=self.details, state=self.state,
                    attempts=self.attempts, error=self.error, session=self.session, job=self.job, pinned=self.pinned,
                    fw_status=self.fw_status, detection=self.detection, first_seen=self.first_seen, last_seen=self.last_seen,
                    probed_at=self.probed_at)


def presumed_role(mac, rows_by_mac, roles, zones_by_mac, controllers, general_radios=()):
    """What the inventory says about a MAC before (or without) a probe."""
    if not mac:
        return {}
    if mac in PROTECTED:
        return dict(role='station', label='Installed pairing station (protected)')
    if mac in general_radios:
        return dict(role='generalradio', label='Recorded as a General Radio')
    if mac in controllers:
        return dict(role='mainshow', label='Recorded as the Mainshow controller')
    if mac in zones_by_mac:
        zone = zones_by_mac[mac]
        return dict(role='zone', label=f'Zone "{zone.get("name") or mac}" in the registry', zone=zone)
    if roles.get(mac) == 'excluded':
        return dict(role='station', label='Excluded from the cube inventory (station or dongle)')
    row = rows_by_mac.get(mac)
    if row and (row.get('cube_id') is not None or row.get('uid')):
        number = row.get('cube_id')
        return dict(role='cube', label=f'Cube #{number}' if number else 'Cube without a number', row=row)
    return {}
