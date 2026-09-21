"""Standard-library client for the shared web inventory (web/ in this repository).

Network calls block; run them on a worker thread, never the Tk callback.
"""
import json
import os
import platform
import ssl
import urllib.error
from urllib.parse import quote
import urllib.request

DEFAULT_SERVER = os.environ.get('NCT_INVENTORY_SERVER', 'https://nct-inventory.auroravision.xyz')
DEFAULT_DATASET = os.environ.get('NCT_INVENTORY_DATASET', 'jinhee-sos')
# The shared password is never stored: apps ask for it when they need the web and keep it
# in memory only (see web/README.md).


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
    def __init__(self, server=DEFAULT_SERVER, password=None, dataset=DEFAULT_DATASET, timeout=10,
                 client=None):
        self.server = server.rstrip('/')
        self.client = client or client_name()  # shown under "Last seen" on the web page
        self.password = password
        self.dataset = dataset
        self.timeout = timeout

    def request(self, method, path, body=None):
        if not self.password:
            raise Unauthorized('No inventory password entered')
        headers = {'Accept': 'application/json', 'X-Inventory-Client': self.client}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers['Content-Type'] = 'application/json'
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
