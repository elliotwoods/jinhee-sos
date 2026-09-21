"""Standard-library client for the shared web inventory (web/ in this repository).

Network calls block; run them on a worker thread, never the Tk callback.
"""
import http.client
import json
import os
from pathlib import Path
import platform
import ssl
import tempfile
import time
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
    """`code`: the HTTP status, when the web answered at all."""
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class Unreachable(WebError):
    pass


class Transient(WebError):
    """The web answered but could not serve the request right now (5xx, 429, 408): worth another try."""


class Unauthorized(WebError):
    pass


class PushConflict(WebError):
    def __init__(self, records):
        self.records = records
        super().__init__('Web records changed during sync: ' + ', '.join(sorted(records)), 409)


RETRY_DELAYS = (1, 3)
SLOW_TIMEOUT = 30  # pushes and publishes make several storage round trips on the server
# Answers without the app's JSON body come from the platform in front of it, not from the inventory.
PLATFORM_ERRORS = {401: 'the web answered with a sign-in page instead of the inventory', 403: 'the web refused this computer',
                   408: 'the web took too long to answer', 413: 'too much data for one request',
                   429: 'the web is busy; try again in a moment', 500: 'the web had a temporary problem',
                   502: 'the web is temporarily unavailable', 503: 'the web is temporarily unavailable',
                   504: 'the web took too long to answer'}


def retrying(call, delays=None):
    """Run an idempotent request, trying again after a short wait when the web is briefly unavailable."""
    for delay in RETRY_DELAYS if delays is None else delays:
        try:
            return call()
        except (Transient, Unreachable):
            time.sleep(delay)
    return call()


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

    def request(self, method, path, body=None, public=False, timeout=None):
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
            with urllib.request.urlopen(request, timeout=timeout or self.timeout, context=context) as response:
                return json.loads(response.read() or b'{}')
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read() or b'{}')
            except (ValueError, OSError, http.client.HTTPException):
                payload = None
            finally:
                exc.close()
            ours = isinstance(payload, dict) and isinstance(payload.get('error'), str)  # the app's own answer
            if exc.code == 401 and ours:
                raise Unauthorized(payload['error'], 401) from None
            if exc.code == 409 and ours and 'records' in payload:
                raise PushConflict(payload['records']) from None
            message = payload['error'] if ours else PLATFORM_ERRORS.get(exc.code, exc.reason or 'request failed')
            kind = Transient if exc.code in (408, 429) or exc.code >= 500 else WebError
            raise kind(f'{exc.code}: {message}', exc.code) from None
        except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as exc:
            raise Unreachable(f'Web inventory unreachable: {getattr(exc, "reason", exc)}') from None

    def head(self):
        return self.request('GET', f'/api/inventory/head?dataset={quote(self.dataset)}')

    def pull(self):
        """Return {'revision': int, 'records': {mac: {'record': dict, 'revision': int}}}."""
        return self.request('GET', f'/api/inventory?dataset={quote(self.dataset)}')

    def push(self, records, base_revisions, name):
        return self.request('POST', '/api/inventory/push', {
            'dataset': self.dataset, 'records': records,
            'base_revisions': base_revisions, 'client': name}, timeout=max(self.timeout, SLOW_TIMEOUT))

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
            'inventory_revision': inventory_revision, 'client': name}, timeout=max(self.timeout, SLOW_TIMEOUT))
