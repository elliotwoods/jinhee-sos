"""Standard-library client for the shared web inventory (web/ in this repository).

Network calls block; run them on a worker thread, never the Tk callback.
"""
import json
import os
from pathlib import Path
import platform
import ssl
import tempfile
import urllib.error
from urllib.parse import quote
import urllib.request

DEFAULT_SERVER = os.environ.get('NCT_INVENTORY_SERVER', 'https://nct-inventory.auroravision.xyz')
DEFAULT_DATASET = os.environ.get('NCT_INVENTORY_DATASET', 'jinhee-sos')
# The shared password is asked for once and stored on this computer, owner-only and outside git
# (pairing_station/data/ is gitignored). Every app uses it until the web rejects it, which deletes it.
PASSWORD_FILE = Path(os.environ.get('NCT_INVENTORY_PASSWORD_FILE') or
                     Path(__file__).resolve().parent / 'data' / 'web_password')
STORED = object()  # WebClient(password=STORED): use the stored password (explicit None = no password)


def load_password():
    try:
        return PASSWORD_FILE.read_text().strip() or None
    except OSError:
        return None


def save_password(password):
    """Atomic, owner-only (0600) write."""
    PASSWORD_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=PASSWORD_FILE.parent, prefix='.web_password.')
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as handle:
            handle.write(password + '\n')
        os.replace(temp, PASSWORD_FILE)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def forget_password():
    PASSWORD_FILE.unlink(missing_ok=True)


class WebError(RuntimeError):
    pass


class Unreachable(WebError):
    pass


class Unauthorized(WebError):
    pass


class PushConflict(WebError):
    def __init__(self, records):
        self.records = records
        super().__init__('Web records changed during sync: ' + ', '.join(sorted(records)))


def client_name(app='Web Sync'):
    return f'{platform.node() or "unknown host"} · {app}'


class WebClient:
    def __init__(self, server=DEFAULT_SERVER, password=STORED, dataset=DEFAULT_DATASET, timeout=10,
                 client=None):
        self.server = server.rstrip('/')
        self.client = client or client_name()  # shown under "Last seen" on the web page
        self.password = load_password() if password is STORED else password
        self.dataset = dataset
        self.timeout = timeout

    def request(self, method, path, body=None, public=False):
        if not self.password and not public:
            raise Unauthorized('No inventory password entered')
        headers = {'Accept': 'application/json', 'X-Inventory-Client': self.client}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers['Content-Type'] = 'application/json'
        if self.password:
            headers['Authorization'] = 'Bearer ' + self.password
        request = urllib.request.Request(self.server + path, data, headers, method=method)
        context = ssl.create_default_context()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=context) as response:
                return json.loads(response.read() or b'{}')
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read() or b'{}')
            except ValueError:
                payload = {}
            finally:
                exc.close()
            if exc.code == 401:
                raise Unauthorized(payload.get('error', 'Wrong inventory password')) from None
            if exc.code == 409 and 'records' in payload:
                raise PushConflict(payload['records']) from None
            raise WebError(f'{exc.code}: ' + payload.get('error', exc.reason or 'request failed')) from None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise Unreachable(f'Web inventory unreachable: {getattr(exc, "reason", exc)}') from None

    def head(self):
        return self.request('GET', f'/api/inventory/head?dataset={quote(self.dataset)}')

    def pull(self):
        """Return {'revision': int, 'records': {mac: {'record': dict, 'revision': int}}}."""
        return self.request('GET', f'/api/inventory?dataset={quote(self.dataset)}')

    def push(self, records, base_revisions, name):
        return self.request('POST', '/api/inventory/push', {
            'dataset': self.dataset, 'records': records,
            'base_revisions': base_revisions, 'client': name})

    def report_sightings(self, report):
        """Replace this computer's cube/zone sightings on the web (see sightings.collect)."""
        return self.request('POST', '/api/sightings', dict(report, dataset=self.dataset))

    def zonedb_head(self):
        """Public: {version, hash, count, published_at} of the published zone database (no password)."""
        return self.request('GET', f'/api/zonedb/head?dataset={quote(self.dataset)}', public=True)

    def zonedb_pull(self):
        """The published zone database: {version, hash, count, crc, records_b64, published_at, published_by, ...}."""
        return self.request('GET', f'/api/zonedb?dataset={quote(self.dataset)}')

    def zonedb_publish(self, records_b64, min_version, inventory_revision, name):
        """The server allocates the next universal version (or returns the current one for identical content)."""
        return self.request('POST', '/api/zonedb/publish', {
            'dataset': self.dataset, 'records_b64': records_b64, 'min_version': min_version,
            'inventory_revision': inventory_revision, 'client': name})
