"""The owner thread. Everything stateful (SQLite, sessions, controllers, jobs bookkeeping, the
snapshot the UI polls) lives here, exactly as it lived on the Tk thread in the old apps.

`call(fn, *args)` enqueues work from any thread and returns a Future. `tick()` runs every 100 ms.
Nothing in a command or a tick may sleep, read serial synchronously or talk to the network.
"""
import paths  # noqa: F401
import concurrent.futures
import json
import queue
import threading
import time
from collections import deque
from pathlib import Path

from database import timestamp
from http_api import AppAPI
from zone_registry import ZoneStore
import dongle
import sightings
import web_client
from usb_identify import firmware_result

import advisor
import state as state_builders
from devices import Device, presumed_role
from intake import Intake
from jobs.base import JobRunner
from locks import instance_locks
from probe import Prober
from scanner import PortScanner
from sessions.cube import CubeConsoleSession
from sessions.general_radio import GeneralRadioSession
from sessions.mainshow import MainshowSession
from sessions.pool_central import PoolCentralSession
from sessions.pool_radio import PoolRadioSession
from sessions.pool_test_bridge import PoolTestBridgeSession
from sessions.preshow_bridge import PreshowBridgeSession
from sessions.preshow_plate import PreshowPlateSession
from sessions.rangetest import RangeTestSession
from sessions.station import StationSession
from sessions.zone_console import ZoneConsoleSession
from store import ConsoleStore
from showedit import ShowEditor

SECTIONS = ('meta', 'ports', 'devices', 'inventory', 'station', 'registry', 'sessions', 'jobs', 'sync', 'advisor',
            'locks', 'builds', 'show', 'settings', 'showedit')
DATA = paths.CONSOLE / 'data'


class IdleController:
    """What http_api.AppAPI.status() reads when no station session exists."""
    connected = reader_ok = False
    mode = phase = ''
    active = None
    message = 'No station session'
    tag_present = False
    discovered = {}
    telemetry = {}
    station = {}
    feedback = {}


class Facade:
    """The `app` object http_api.AppAPI expects."""
    root = None

    def __init__(self, hub):
        self.hub = hub
        self.db = hub.db
        self.recent_events = hub.recent_events
        self.recent_logs = hub.recent_logs

    @property
    def controller(self):
        session = self.hub.station_session()
        return session.controller if session else IdleController()


class Hub:
    TICK = 0.1
    GONE_AFTER = 2.0

    def __init__(self, database, api_port=8765, clock=time.monotonic, wall=time.time, scanner=None, prober=None,
                 workers=True, simulate=False):
        self.database = Path(database)
        self.api_port, self.clock, self.wall = api_port, clock, wall
        self.simulate = simulate
        self.scanner = scanner or PortScanner()
        self.prober = prober or Prober()
        self.workers = workers
        self.commands = queue.Queue()
        self.stopping = threading.Event()
        self.stopped = threading.Event()
        self.thread = None
        self.owner = None
        self.db = self.store = self.api = None
        self.showedit = None
        self.devices = {}          # key -> Device
        self.present_keys = set()
        self.sessions = {}         # device id -> Session
        self.manual_off = set()    # device ids the operator disconnected
        self.probing = None        # key being probed
        self.jobs = JobRunner(self)
        self.intake = Intake(self)
        self.events = deque(maxlen=4000)
        self.notable = deque(maxlen=1500)   # everything but console lines: what a fresh page should see first
        self.seq = 0
        self.recent_events = deque(maxlen=300)
        self.recent_logs = deque(maxlen=300)
        self.sections, self.versions, self.serialized = {}, {name: 0 for name in SECTIONS}, {}
        self.dirty = set(SECTIONS)
        self.dismissed = set()
        self.suggestions = []
        self.actions = {}
        self.confirm_tokens = {}
        self.sync = dict(status=None, checked_at=None, busy=False, last_result=None, last_error=None,
                         summary='', password_known=False)
        self.builds = {}
        self.locks_held = {}
        self.own_locks = ()            # lock suffixes this process holds (set by app.py from InstanceLocks.held)
        self.settings = dict(auto_sessions=True, preview_flash=True, audio=True)
        self.pinned_mac = None
        self.usb_firmware = {}
        self.inventory_cache = dict(rows_by_mac={}, roles={}, zones_by_mac={}, controllers=set())
        self.idle_flag = threading.Event()
        self.idle_flag.set()
        self.timers = {}
        self.last_tick = 0.0
        self.started_at = wall()
        self.booted = False
        self.on_wake = None        # optional callable to nudge the UI (never carries data)
        self.pull_count = 0        # proves the page is polling (checked over the local API)

    # ---------------------------------------------------------------- lifecycle
    def boot(self):
        """Create the owner-thread state. Called by run(), or directly by tests."""
        self.owner = threading.get_ident()
        DATA.mkdir(parents=True, exist_ok=True)
        self.db = ConsoleStore(self.database)
        self.store = ZoneStore(self.db, self.wall)
        self.showedit = ShowEditor(self)  # main show editor + wireless show updater (showedit.py)
        self.refresh_inventory_cache()
        self.sync['password_known'] = bool(web_client.load_password())
        self.dismissed = set(json.loads(self.db.metadata('console_dismissed') or '[]'))
        if self.api_port:
            self.api = AppAPI(Facade(self), self.database.parent, self.api_port)
            self.api.namespace.update(hub=self, sessions=self.sessions, jobs=self.jobs, devices=self.devices,
                                      zones=None, store=self.store)
        if self.workers:
            self.scanner.start()
            self.prober.start()
        self.refresh_builds()
        if self.simulate and getattr(self, '_sim_seed', None):
            self._sim_seed()
        self.booted = True
        self.log(f'NCT Console started · database {self.database}', 'info', source='console')

    def run(self):
        try:
            self.boot()
            while not self.stopping.is_set():
                self.drain_commands()
                now = self.clock()
                if now - self.last_tick >= self.TICK:
                    self.last_tick = now
                    try:
                        self.tick()
                    except Exception as exc:
                        self.log(f'Tick failed: {exc}', 'bad', source='console')
                else:
                    time.sleep(min(0.02, self.TICK - (now - self.last_tick)))
        finally:
            self.stopped.set()

    def start_thread(self):
        self.thread = threading.Thread(target=self.run, name='nct-owner', daemon=True)
        self.thread.start()
        return self.thread

    def call(self, fn, *args, **kwargs):
        future = concurrent.futures.Future()
        if threading.get_ident() == self.owner:
            try:
                future.set_result(fn(*args, **kwargs))
            except BaseException as exc:
                future.set_exception(exc)
            return future
        self.commands.put((fn, args, kwargs, future))
        return future

    def drain_commands(self, limit=50):
        for _ in range(limit):
            try:
                fn, args, kwargs, future = self.commands.get_nowait()
            except queue.Empty:
                return
            try:
                future.set_result(fn(*args, **kwargs))
            except BaseException as exc:
                future.set_exception(exc)

    def shutdown(self, force=False):
        """Orderly close on the owner thread. Refuses while an esptool write is in progress."""
        if self.jobs.writing() and not force:
            raise ValueError('A flash write is in progress; wait for it to finish before closing')
        graceful = [s for s in self.sessions.values() if isinstance(s, StationSession) and s.prepare_close()]
        if graceful:
            end = self.clock() + 1.2
            while self.clock() < end:
                for s in list(self.sessions.values()):
                    s.pump()
                time.sleep(0.05)
        for session in list(self.sessions.values()):
            try:
                session.close('console closing')
            except Exception:
                pass
        self.sessions.clear()
        if self.workers:
            self.scanner.stop()
            self.prober.stop()
        if self.api:
            self.api.close()
            self.api = None
        if self.db:
            self.db.close()
            self.db = None
        self.stopping.set()
        return True

    # ---------------------------------------------------------------- tick
    def tick(self):
        now = self.clock()
        ports = self.scanner.latest()
        if ports is not None:
            self.apply_ports(ports)
        self.purge_gone(now)
        self.apply_probe_results()
        self.request_probe()
        for session in list(self.sessions.values()):
            session.pump()
        for session in list(self.sessions.values()):
            if session.device.id in self.sessions:
                session.tick(now)
        self.open_sessions()
        self.jobs.pump()
        try:
            self.intake.tick()
        except Exception as exc:
            self.log(f'Auto intake failed: {exc}', 'bad', source='intake')
        if self.api:
            self.api.drain()
        self.expire_confirmations(now)
        self.periodic(now)
        self.rebuild_sections()
        self.update_idle_flag()

    def every(self, name, seconds, now):
        if now - self.timers.get(name, -1e9) >= seconds:
            self.timers[name] = now
            return True
        return False

    def periodic(self, now):
        if self.every('inventory', 2.0, now):
            self.dirty.update(('inventory', 'registry'))
        if self.every('locks', 5.0, now):
            # The console holds the old apps' locks itself (app.py); flock would report its own handles as
            # "held by another process", so those are skipped: only locks it does not own are probed.
            held = instance_locks(self.database, skip=('.console.lock',) + tuple(self.own_locks))
            held.update({suffix: False for suffix in self.own_locks})
            if held != self.locks_held:
                self.locks_held = held
                self.dirty.add('locks')
        if self.every('builds', 60.0, now):
            self.refresh_builds()
        if self.every('sync_status', 60.0, now) and self.workers and not self.simulate:
            self.check_sync_status()
        if self.every('dismissed', 30.0, now):
            self.db.set_metadata('console_dismissed', json.dumps(sorted(self.dismissed)))
        self.dirty.update(('sessions', 'station', 'devices', 'show'))
        if self.showedit and self.every('showedit', 0.25, now):
            self.showedit.tick(now)
            self.dirty.add('showedit')

    def update_idle_flag(self):
        station = self.station_session()
        busy = bool(station and (station.controller.mode or station.zones.publication)) or \
            any(j.hardware for j in self.jobs.running()) or \
            any(getattr(s, 'arm_requested', False) or getattr(s, 'want_armed', False) for s in self.sessions.values())
        if busy:
            self.idle_flag.clear()
        else:
            self.idle_flag.set()

    # ---------------------------------------------------------------- ports and devices
    def refresh_inventory_cache(self):
        rows = self.db.rows()
        zones = self.store.zones()
        try:
            radios = set(json.loads(self.db.metadata('general_radios') or '[]'))
        except ValueError:
            radios = set()
        self.inventory_cache = dict(rows_by_mac={r['mac']: r for r in rows}, roles=self.db.roles(),
                                    zones_by_mac={z['mac']: z for z in zones}, controllers=dongle.controllers(self.db),
                                    general_radios=radios, rows=rows, zones=zones)

    def apply_ports(self, ports):
        seen = set()
        for port in ports:
            if not port.get('candidate') and not port.get('serial') and (port.get('description') or 'n/a') == 'n/a':
                continue  # Bluetooth / debug consoles: not USB serial devices
            seen.add(port['key'])
            device = self.devices.get(port['key'])
            if device is None:
                device = Device(port, self.clock)
                self.devices[port['key']] = device
                self.presume(device)
                self.log(f'USB: {device.description or device.port} on {device.port}' +
                         (f' · {device.presumed["label"]}' if device.presumed else ''), 'info', device.id, source='usb')
                self.dirty.add('devices')
            else:
                if device.port != port['port']:
                    self.dirty.add('devices')
                device.refresh(port)
        self.present_keys = seen
        self.dirty.add('ports')
        self.sections['ports'] = ports

    def purge_gone(self, now):
        for key, device in list(self.devices.items()):
            if key in self.present_keys:
                continue
            if device.gone_since is None:
                device.gone_since = now
            if now - device.gone_since < self.GONE_AFTER or device.state == 'job':
                continue
            session = self.sessions.get(device.id)
            if session:
                self.close_session(session, 'unplugged')
            self.log(f'USB: {device.role_label()} on {device.port} unplugged', 'info', device.id, source='usb')
            del self.devices[key]
            self.dirty.add('devices')

    def presume(self, device):
        c = self.inventory_cache
        device.presumed = presumed_role(device.mac, c['rows_by_mac'], c['roles'], c['zones_by_mac'], c['controllers'],
                                        c.get('general_radios', ()))

    def request_probe(self):
        if self.probing is not None or not self.workers:
            return
        for device in self.devices.values():
            if device.wants_probe() and device.id not in self.sessions:
                device.probe_started()
                self.probing = device.key
                self.prober.request(dict(port=device.port, key=device.key, serial=device.serial,
                                         native_usb=device.native_usb, candidate=device.candidate))
                self.dirty.add('devices')
                return

    def apply_probe_results(self):
        for _ in range(20):
            try:
                port, role, details, transcript, error = self.prober.results.get_nowait()
            except queue.Empty:
                return
            if self.probing == port['key']:
                self.probing = None
            device = self.devices.get(port['key'])
            if not device:
                continue
            device.probe_result(role, details, transcript, error)
            self.dirty.add('devices')
            if device.state == 'foreign':
                self.log(f'{device.port}: {error}', 'warn', device.id, source='usb')
            elif error:
                self.log(f'{device.port}: probe failed: {error}', 'warn', device.id, source='usb')
            elif device.state == 'idle' and device.role:
                self.identified(device, transcript)

    def identified(self, device, transcript):
        label = device.role_label()
        detail = ''
        if device.role == 'zone':
            d = device.details
            detail = f' · {d.get("name") or "unconfigured"} · {d.get("firmware")} · database v{d.get("db_version")}'
        elif device.role in ('station', 'mainshow', 'generalradio'):
            detail = f' · {device.details.get("firmware")}'
        elif device.role == 'cube':
            detail = f' · {device.details.get("firmware")}'
        self.log(f'Identified {label} on {device.port}{detail}' + (f' · {device.mac}' if device.mac else ''), 'ok',
                 device.id, source='usb')
        self.presume(device)
        if device.role == 'cube' and device.mac:
            station = self.station_session()
            if station and station.controller.mode and (self.pinned_mac or '') != device.mac:
                # As the pairing app did: a newly identified USB cube stops the active operation before it
                # takes the pin, so an interrupted registration never continues on the wrong cube.
                try:
                    station.controller.stop()
                    self.log(f'Stopped the active pairing operation before pinning {device.mac} (identified on {device.port})',
                             'warn', device.id, source='usb')
                except Exception as exc:
                    self.log(f'Could not stop the active pairing operation: {exc}', 'warn', device.id)
            expected = self.builds.get('cube', {}).get('version')
            device.fw_status = firmware_result('\n'.join(transcript), device.mac, expected)
            if device.fw_status:
                self.usb_firmware[device.mac] = device.fw_status
            try:
                self.db.reserve(device.mac, source='usb')   # as the pairing app's USB identification does
            except ValueError as exc:
                self.log(str(exc), 'warn', device.id)
            sightings.record(self.db.conn, device.mac, 'usb', f'USB identified on {device.port}')
            self.pinned_mac = device.mac
            device.pinned = True
            self.dirty.add('inventory')
        if device.role == 'zone' and device.details.get('mac'):
            self.zone_report(device, device.details, {})

    # ---------------------------------------------------------------- sessions
    def make_transport(self, kind, session):
        if self.simulate:
            from simulate import fake_transport
            return fake_transport(self, kind, session)
        from linetransport import LineTransport
        from transport import Transport
        return Transport() if kind == 'json' else LineTransport()

    def session_class(self, device):
        role = device.role
        if role == 'cube':
            return CubeConsoleSession
        if role == 'zone':
            return {3: PoolRadioSession, 1: PreshowPlateSession}.get(device.zone_type, ZoneConsoleSession)
        return {'station': StationSession, 'generalradio': GeneralRadioSession, 'mainshow': MainshowSession, 'poolcentral': PoolCentralSession,
                'preshowbridge': PreshowBridgeSession, 'pooltest': PoolTestBridgeSession,
                'rangetest': RangeTestSession}.get(role)

    def open_sessions(self):
        if not self.settings['auto_sessions']:
            return
        for device in list(self.devices.values()):
            if device.state == 'idle' and device.id not in self.sessions and device.id not in self.manual_off:
                cls = self.session_class(device)
                if cls:
                    self.open_session(device, cls)

    def open_session(self, device, cls=None):
        cls = cls or self.session_class(device)
        if not cls:
            raise ValueError(f'No console session for a {device.role_label()}')
        if device.id in self.sessions:
            return self.sessions[device.id]
        if device.state == 'job':
            raise ValueError('A job is using that port')
        session = cls(self, device)
        try:
            session.open()
        except Exception as exc:
            text = str(exc)
            device.error = text
            if 'owned by another' in text or 'Resource busy' in text or 'Permission denied' in text:
                device.state = 'foreign'
                device.next_probe = self.clock() + Device.FOREIGN_RETRY
            else:
                device.state = 'present'
                device.attempts = 0
                device.next_probe = self.clock() + Device.RETRY_AFTER
            self.log(f'Could not open {device.port}: {text}', 'warn', device.id)
            self.dirty.add('devices')
            return None
        self.sessions[device.id] = session
        device.session, device.state, device.error = session.id, 'session', None
        self.manual_off.discard(device.id)
        self.dirty.update(('devices', 'sessions'))
        return session

    def close_session(self, session, reason='closed', manual=False):
        device = session.device
        try:
            session.close(reason)
        except Exception as exc:
            self.log(f'Closing {device.port}: {exc}', 'warn', device.id)
        if self.sessions.get(device.id) is session:
            del self.sessions[device.id]
        device.session = None
        if manual:
            self.manual_off.add(device.id)
        if device.state == 'session':
            if manual:
                device.state = 'idle'
            elif reason in ('silent', 'unplugged') or 'disconnect' in reason.lower() or 'Device not configured' in reason:
                device.state, device.attempts, device.next_probe = 'present', 0, self.clock() + 3.0
            else:
                device.state = 'idle'
        self.dirty.update(('devices', 'sessions', 'station', 'registry'))

    def station_session(self, device=None):
        """The link that carries the pairing protocol: a pairing station, a dongle or a General Radio.

        With `device`, that board's own link (a station or a General Radio), so a General Radio's
        discover/identify/zone relay stay reachable while a real pairing station is also plugged in.
        """
        if device:
            return self.session_for(device, ('station', 'generalradio'))
        for session in self.sessions.values():
            if isinstance(session, StationSession) and not isinstance(session, GeneralRadioSession):
                return session
        for session in self.sessions.values():
            if isinstance(session, GeneralRadioSession):
                return session
        return None

    def show_session(self):
        """Whatever can make a cube mainshow-ready and start the show: the Mainshow controller or a General Radio."""
        for session in self.sessions.values():
            if isinstance(session, MainshowSession):
                return session
        for session in self.sessions.values():
            if isinstance(session, GeneralRadioSession) and session.controller.connected:
                return session
        return None

    def record_general_radio(self, mac):
        radios = set(self.inventory_cache.get('general_radios', ()))
        if mac not in radios:
            radios.add(mac)
            self.db.set_metadata('general_radios', json.dumps(sorted(radios)))
            self.mark_dirty('inventory')

    def zone_relay(self, device=None):
        """The station/dongle session whose registry can talk to zones (`device`: that board's), or raise."""
        session = self.station_session(device)
        if not session:
            raise ValueError('Connect a pairing station or ESP-NOW dongle first')
        session.zones.require(session.controller.station, session.controller.connected)
        return session

    def device_by_id(self, device_id):
        for device in self.devices.values():
            if device.id == device_id or device.port == device_id or device.key == device_id:
                return device
        raise ValueError(f'No USB device {device_id}')

    def session_for(self, device_id, kinds=None):
        device = self.device_by_id(device_id)
        session = self.sessions.get(device.id)
        if not session:
            raise ValueError(f'{device.role_label()} on {device.port} has no open session')
        if kinds and session.kind not in kinds:
            raise ValueError(f'That device is a {device.role_label()}, not a {"/".join(kinds)}')
        return session

    # ---------------------------------------------------------------- jobs and ports
    def hold_port(self, device, job):
        session = self.sessions.get(device.id)
        if session:
            self.close_session(session, 'job')
        device.state, device.job = 'job', job.id
        self.dirty.add('devices')

    def job_finished(self, job):
        for device in self.devices.values():
            if device.job == job.id:
                device.job = None
                device.state, device.attempts, device.next_probe = 'present', 0, self.clock() + 2.5
                device.role = device.role  # re-probed: the firmware may have changed
                self.dirty.add('devices')
        self.dirty.update(('jobs', 'inventory'))

    def port_dict(self, device):
        return dict(port=device.port, key=device.key, serial=device.serial, description=device.description,
                    candidate=device.candidate, native_usb=device.native_usb, location=None)

    # ---------------------------------------------------------------- events and logging
    def next_seq(self):
        self.seq += 1
        return self.seq

    def push_event(self, kind, **fields):
        event = dict(seq=self.next_seq(), t=self.wall(), kind=kind, **fields)
        self.events.append(event)
        if kind != 'line':
            self.notable.append(event)
        return event

    def log(self, text, level='info', device=None, source='console'):
        line = dict(time=timestamp(), level=level, device=device, source=source, text=str(text))
        self.recent_logs.append(line)
        self.push_event('log', level=level, device=device, source=source, text=str(text))
        self.on_wake and self.on_wake()

    def line_event(self, device_id, direction, text):
        self.push_event('line', device=device_id, dir=direction, text=text)

    def tag_event(self, device_id, tag):
        self.push_event('tag', device=device_id, **tag)
        if tag['level'] in ('warn', 'bad'):
            self.dirty.add('advisor')

    def station_event(self, device_id, event):
        self.recent_events.append(dict(time=self.wall(), **event))
        self.push_event('station', device=device_id, event=event)

    def zone_report(self, device, report, stats):
        """A zone's `?` report over USB updates the registry row (as a flash does)."""
        if not report.get('mac'):
            return
        status = dict(report, staging_version=0, staging_chunks=0, staging_total=0, uptime=0,
                      tags=stats.get('tags', 0), unknown_tags=stats.get('unknown', 0), send_fail=stats.get('send_fail', 0))
        try:
            self.store.seen(report['mac'], status, source='usb')
            self.dirty.update(('inventory', 'registry'))
        except Exception as exc:
            self.log(f'Registry update failed: {exc}', 'warn', device.id)

    def mark_dirty(self, *names):
        self.dirty.update(names)

    # ---------------------------------------------------------------- snapshot
    def rebuild_sections(self):
        if 'inventory' in self.dirty:
            self.refresh_inventory_cache()
            for device in self.devices.values():
                self.presume(device)
        changed = state_builders.build(self, self.dirty)
        self.dirty = set()
        for name, data in changed.items():
            text = json.dumps(data, default=repr, sort_keys=True)
            if self.serialized.get(name) != text:
                self.serialized[name] = text
                self.versions[name] += 1
                self.sections[name] = data
        if any(self.versions[n] for n in ('devices', 'sessions', 'inventory', 'station', 'registry', 'jobs', 'sync', 'locks', 'builds')):
            self.evaluate_advisor()

    def evaluate_advisor(self):
        try:
            suggestions = advisor.evaluate(self.sections, self.wall(), self.dismissed)
        except Exception as exc:
            self.log(f'Advisor failed: {exc}', 'bad', source='advisor')
            suggestions = []
        previous = {s['id'] for s in self.suggestions}
        current = {s['id'] for s in suggestions}
        for gone in previous - current:
            title = next((s['title'] for s in self.suggestions if s['id'] == gone), gone)
            if gone not in self.dismissed:
                self.push_event('resolved', suggestion=gone, text=f'Resolved: {title}')
        self.suggestions = suggestions
        self.actions = {f'{s["id"]}#{a["id"]}': (s, a) for s in suggestions for a in s.get('actions', [])}
        data = advisor.section(suggestions)
        text = json.dumps(data, default=repr, sort_keys=True)
        if self.serialized.get('advisor') != text:
            self.serialized['advisor'] = text
            self.versions['advisor'] += 1
            self.sections['advisor'] = data
            self.on_wake and self.on_wake()

    def pull(self, since=None, since_seq=0):
        self.pull_count += 1
        since = since or {}
        sections = {name: dict(version=self.versions[name], data=self.sections.get(name))
                    for name in SECTIONS if self.versions[name] > int(since.get(name, 0) or 0)}
        since_seq = int(since_seq or 0)
        if since_seq:
            events = [e for e in self.events if e['seq'] > since_seq][-1500:]
        else:
            # A fresh page: the timeline history (log, tags, station events) plus the most recent lines, so the
            # dock is not empty after a reload just because console lines outnumber everything else.
            lines = [e for e in self.events if e['kind'] == 'line'][-300:]
            events = sorted(list(self.notable) + lines, key=lambda e: e['seq'])[-1800:]
        return dict(sections=sections, events=events, seq=self.seq, t=self.wall())

    def lines_for(self, device_id, since_seq=0, limit=500):
        out = [e for e in self.events if e['kind'] == 'line' and e.get('device') == device_id and e['seq'] > int(since_seq or 0)]
        return out[-limit:]

    # ---------------------------------------------------------------- confirmation tokens (destructive commands)
    def confirm(self, name, args):
        import secrets
        token = secrets.token_urlsafe(12)
        self.confirm_tokens[token] = dict(name=name, args=json.dumps(args or {}, sort_keys=True, default=repr),
                                      expires=self.clock() + 12.0)
        return dict(token=token, expires_s=12.0)

    def check_confirmation(self, token, name, args):
        entry = self.confirm_tokens.pop(token or '', None)
        if not entry or entry['name'] != name or entry['args'] != json.dumps(args or {}, sort_keys=True, default=repr):
            raise ValueError('This action needs a confirming hold (press and hold the button)')
        if self.clock() > entry['expires']:
            raise ValueError('The confirmation expired; hold the button again')

    def expire_confirmations(self, now):
        for token in [t for t, e in self.confirm_tokens.items() if now > e['expires']]:
            del self.confirm_tokens[token]

    # ---------------------------------------------------------------- builds, sync
    def refresh_builds(self):
        self.builds = state_builders.builds(self.builds)
        self.dirty.add('builds')

    def check_sync_status(self):
        if self.sync['busy'] or any(j.kind == 'sync.status' and j.state == 'running' for j in self.jobs.jobs.values()):
            return
        from jobs.sync import status_job
        status_job(self)

    def snapshot_facts(self):
        return self.sections
