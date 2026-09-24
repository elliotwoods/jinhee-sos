"""The owner thread. Everything stateful (SQLite, sessions, controllers, jobs bookkeeping, the
snapshot the UI polls) lives here, exactly as it lived on the Tk thread in the old apps.

`call(fn, *args)` enqueues work from any thread and returns a Future. `tick()` runs every 100 ms.
Nothing in a command or a tick may sleep, read serial synchronously or talk to the network.
"""
import paths  # noqa: F401
import concurrent.futures
import hashlib
import json
import queue
import threading
import time
from collections import deque
from pathlib import Path

from database import NEW_UNNUMBERED, timestamp
from http_api import AppAPI
from zone_registry import ZoneStore
import dongle
import sightings
import web_client
from usb_identify import firmware_result

import advisor
import state as state_builders
from devices import Device, presumed_role
from autoupgrade import AutoUpgrade
from intake import Intake
from jobs.base import JobRunner
from locks import instance_locks
from probe import Prober
from scanner import PortScanner
from sessions.cube import CubeConsoleSession
from sessions.mainshow import MainshowSession
from sessions.pool_central import PoolCentralSession
from sessions.pool_radio import PoolRadioSession
from sessions.pool_test_bridge import PoolTestBridgeSession
from sessions.preshow_bridge import PreshowBridgeSession
from sessions.preshow_plate import PreshowPlateSession
from sessions.rangetest import RangeTestSession
from sessions.workstation import WorkstationSession
from sessions.zone_console import ZoneConsoleSession
from store import ConsoleStore
from showedit import ShowEditor
from regflow import RegistrationFlow
from flashflow import FlashFlow
from sounds import Sounds

SECTIONS = ('meta', 'ports', 'devices', 'inventory', 'station', 'registry', 'sessions', 'jobs', 'sync', 'advisor',
            'locks', 'builds', 'show', 'settings', 'showedit', 'register', 'flash', 'autoupdate')
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
        self.autoupgrade = AutoUpgrade(self)
        self.touched = {}          # device id / port / key / MAC -> clock of the operator's last command naming it
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
        # Persisted in metadata `console_settings`. The auto_* keys keep every database current everywhere:
        # zone databases over the air (one relay walks) and over USB, the main show over the air, web pulls,
        # and the inventory itself (auto_sync: upload, download and publish without pressing Sync).
        # auto_build / auto_firmware_usb keep firmware current too: out-of-date builds are rebuilt and USB boards
        # with old firmware are upgraded (autoupgrade.py).
        self.settings = dict(auto_sessions=True, preview_flash=True, audio=True, auto_zone_db_radio=True,
                             auto_zone_db_usb=True, auto_show=True, auto_pull=True, auto_sync=True, auto_register=False,
                             auto_build=True, auto_firmware_usb=True)
        # Automatic sync bookkeeping (auto_sync()): the local-data fingerprint at the last sync, when a debounced
        # sync is due, the back-off after failures, and whether the web last rejected the password.
        self.autosync = dict(fingerprint=None, due=None, failures=0, retry_at=0.0, last_at=None, waiting=False)
        self.auto_web = not simulate   # the timers reach the web (the tests switch it on against a loopback fake)
        # Cube numbers handed out by the web (claim_numbers()): MACs asked for explicitly, the last failure, back-off.
        self.numbering = dict(wanted=set(), error=None, retry_at=0.0)
        self.auto_errors = {}      # auto-mode name -> last error text (logged once per change)
        self.auto_pulled = set()   # web zone database versions already pulled automatically
        self.pinned_mac = None
        self.usb_firmware = {}
        self.regflow = RegistrationFlow(self)   # the guided registration workflow (regflow.py)
        self.flashflow = FlashFlow(self)        # the guided USB flashing workflow (flashflow.py)
        self.sounds = Sounds(self)              # the cube flasher's audio cues (sounds.py)
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
        self.autosync['fingerprint'] = self.local_fingerprint()
        self.sync['password_known'] = bool(web_client.load_password())
        self.dismissed = set(json.loads(self.db.metadata('console_dismissed') or '[]'))
        try:
            saved = json.loads(self.db.metadata('console_settings') or '{}')
        except ValueError:
            saved = {}
        self.settings.update({k: bool(v) for k, v in saved.items() if k in self.settings})
        if paths.PACKAGED:
            self.settings['auto_build'] = False   # the app's firmware is fixed per release (no Arduino tools)
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
        graceful = [s for s in self.sessions.values() if isinstance(s, WorkstationSession) and s.prepare_close()]
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
                try:
                    session.tick(now)
                except Exception as exc:   # one board's failure must not stop every other board's tick
                    self.auto_error(f'session {session.device.port}', f'tick failed: {exc}')
        self.open_sessions()
        self.jobs.pump()
        try:
            self.regflow.tick()
        except Exception as exc:
            self.log(f'Registration workflow failed: {exc}', 'bad', source='register')
        try:
            self.flashflow.tick()
        except Exception as exc:
            self.log(f'Flash workflow failed: {exc}', 'bad', source='flash')
        self.sounds.tick(now)
        try:
            self.intake.tick()
        except Exception as exc:
            self.log(f'Auto intake failed: {exc}', 'bad', source='intake')
        try:
            self.autoupgrade.tick()
        except Exception as exc:
            self.auto_error('firmware upgrade', f'failed: {exc}')
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
            if self.workers and self.auto_web:
                self.claim_numbers(now)
                self.watch_local_changes(now)
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
        if self.every('sync_status', 60.0, now) and self.workers and self.auto_web:
            self.check_sync_status()
        if self.every('auto_modes', 1.0, now):
            self.apply_auto_modes()
        if self.every('show_pull', 300.0, now) and self.workers and self.auto_web:
            self.auto_show_pull()
        if self.every('dismissed', 30.0, now):
            self.db.set_metadata('console_dismissed', json.dumps(sorted(self.dismissed)))
        self.dirty.update(('sessions', 'station', 'devices', 'show', 'register', 'flash'))
        if self.showedit and self.every('showedit', 0.25, now):
            self.showedit.tick(now)
            self.dirty.add('showedit')

    def save_settings(self):
        self.db.set_metadata('console_settings', json.dumps(self.settings, sort_keys=True))
        self.mark_dirty('settings')

    def apply_auto_modes(self):
        """Keep the automatic database updates switched as the settings say, whatever sessions come and go.

        Zones over the air: every relay-capable link walks the zones its own radio hears
        (ZoneRegistry.walk_candidates), so a zone only a second Workstation can reach is still updated.
        zone_walk_allowed() lets one radio publish at a time, so two never broadcast chunks over each other.
        The main show: the show registry walks through the show relay that hears the cubes (showedit.relay).
        """
        want = bool(self.settings['auto_zone_db_radio'])
        for session in self.sessions.values():
            zones = getattr(session, 'zones', None)
            if not isinstance(session, WorkstationSession) or zones is None:
                continue
            walk = want and bool(session.relay_capable)
            if zones.walkaround != walk:
                zones.set_walkaround(walk)
                if walk:
                    zones.set_auto_refresh(True)
                self.dirty.add('registry')
        if self.showedit and self.showedit.registry.walkaround != bool(self.settings['auto_show']):
            self.showedit.registry.set_walkaround(bool(self.settings['auto_show']))
            self.dirty.add('showedit')

    def zone_walk_allowed(self, session):
        """A radio may start a zone database walk only while no other radio on this computer is publishing."""
        return not any(other is not session and getattr(other, 'zones', None) is not None and other.zones.publication
                       for other in self.sessions.values() if isinstance(other, WorkstationSession))

    def touch(self, *names):
        """The operator just sent a command naming these boards: automatic upgrades leave them alone a while."""
        now = self.clock()
        for name in names:
            if isinstance(name, str) and name:
                self.touched[name] = now
                self.touched[name.upper()] = now

    def auto_error(self, name, text):
        """Log an automatic-update failure once per distinct text (None clears it)."""
        if self.auto_errors.get(name) != text:
            self.auto_errors[name] = text
            if text:
                self.log(f'Automatic {name}: {text}', 'warn', source='auto')

    def auto_zone_pull(self, web_version=None):
        """The web has a newer zone database: pull it (called when a status check says so).
        Each web version is tried once per run, so a refused pull does not repeat after every status check."""
        if not (self.settings['auto_pull'] and self.sync['password_known']) or self.sync['busy'] or \
                web_version in self.auto_pulled or \
                any(j.kind in ('zone.pull', 'sync') and j.state == 'running' for j in self.jobs.jobs.values()):
            return None
        self.auto_pulled.add(web_version)
        from jobs.sync import zone_pull_job
        return zone_pull_job(self, auto=True)

    # ---------------------------------------------------------------- automatic sync
    SYNC_DEBOUNCE = 5.0        # seconds of quiet after a local change before it is uploaded
    SYNC_MIN_GAP = 15.0        # never two automatic syncs closer than this
    SYNC_BACKOFF = (60.0, 600.0)

    def local_fingerprint(self):
        """A hash of everything a sync uploads from here (devices and roles), cheap enough for every 2 s."""
        digest = hashlib.sha1()
        for table in ('devices', 'device_roles'):
            for row in self.db.conn.execute(f'SELECT * FROM {table} ORDER BY mac'):
                digest.update(repr(tuple(row)).encode())
        return digest.hexdigest()

    def watch_local_changes(self, now):
        """Any local write (register, renumber, rename, role, intake, a download applied) moves the fingerprint:
        schedule a sync SYNC_DEBOUNCE after the last change. Downloads left waiting retry once the console is idle."""
        auto = self.autosync
        fingerprint = self.local_fingerprint()
        if fingerprint != auto['fingerprint']:
            auto['fingerprint'] = fingerprint
            auto['due'] = now + self.SYNC_DEBOUNCE
            self.mark_dirty('sync')
        elif auto['waiting'] and self.idle_flag.is_set() and auto['due'] is None:
            auto['due'] = now
        if auto['due'] is not None and now >= auto['due'] and self.auto_sync('local change') is not None:
            auto['due'] = None
        if auto['due'] is not None or auto['retry_at'] > now:
            self.mark_dirty('sync')      # the Sync chip counts down

    def auto_sync(self, reason=''):
        """Start an automatic sync when allowed: auto_sync on, a password known, no sync running, not backing off.
        Returns the job or None. The merge never asks anything (newest wins, audited), so running it unattended
        is the same as the operator pressing Sync."""
        auto, now = self.autosync, self.clock()
        if not (self.settings['auto_sync'] and self.sync['password_known']) or self.sync['busy'] or \
                now < auto['retry_at'] or (auto['last_at'] is not None and now - auto['last_at'] < self.SYNC_MIN_GAP) or \
                any(j.kind == 'sync' and j.state == 'running' for j in self.jobs.jobs.values()):
            return None
        auto['last_at'] = now
        from jobs.sync import sync_job
        return sync_job(self, auto=True)

    def auto_sync_finished(self, ok, kind=None, text=None, waiting=0):
        """Called when any sync ends (manual or automatic): remember the synced state, or back off after a failure."""
        auto = self.autosync
        auto['waiting'] = bool(waiting)
        if ok or kind == 'zone':          # the inventory synced (downloads may have changed the local data)
            auto['fingerprint'] = self.local_fingerprint()
        if ok:
            auto.update(failures=0, retry_at=0.0, fingerprint=self.local_fingerprint(), due=None)
            self.auto_error('sync', None)
            return
        if kind == 'after_push' and auto['failures'] == 0:
            auto.update(failures=1, retry_at=0.0, last_at=None, due=self.clock())   # retry once, straight away
        elif kind == 'busy':
            auto['retry_at'] = self.clock() + self.SYNC_MIN_GAP
        elif kind != 'unauthorized':           # unauthorized: the password is forgotten; sign-in resumes
            auto['failures'] += 1
            first, cap = self.SYNC_BACKOFF
            auto['retry_at'] = self.clock() + min(cap, first * 2 ** (auto['failures'] - 1))
        self.auto_error('sync', text)

    # ---------------------------------------------------------------- cube numbers from the web
    def web_numbering(self):
        """New cube numbers come from the web whenever this computer syncs with it: every synced computer has
        auto_number=0 (web_sync), and a locally chosen number could collide with another computer's."""
        return bool(self.auto_web and self.sync['password_known'])

    def request_number(self, mac):
        """The guided registration needs a number for `mac` now (claimed on the next 2 s tick)."""
        self.numbering['wanted'].add(mac)

    def claim_numbers(self, now):
        """Brand-new unnumbered cubes (and any MAC asked for) get the next free number from the web."""
        state = self.numbering
        if not self.web_numbering() or now < state['retry_at'] or \
                any(j.kind == 'number.claim' and j.state == 'running' for j in self.jobs.jobs.values()):
            return None
        roles = self.db.roles()
        macs = {r['mac'] for r in self.db.rows() if r['cube_id'] is None and r['status'] == 'needs_number'
                and r['detail'] == NEW_UNNUMBERED and roles.get(r['mac']) != 'excluded'}
        macs |= {mac for mac in state['wanted'] if (self.db.get(mac) or {}).get('cube_id') is None}
        state['wanted'] &= macs
        if not macs:
            return None
        exclude = {r['cube_id'] for r in self.db.rows() if r['cube_id'] is not None} | set(self.db.reserved_numbers())
        from jobs.sync import claim_job
        return claim_job(self, sorted(macs), exclude)

    def numbers_claimed(self, numbers, error=None):
        state = self.numbering
        for mac, number in (numbers or {}).items():
            row = self.db.get(mac)
            if not row or row['cube_id'] is not None:
                continue
            try:
                self.db.rename(mac, number, fresh_scan=True)
                self.log(f'New number #{number} for {mac} (handed out by the web)', 'ok', source='sync')
            except ValueError as exc:     # taken here meanwhile: the next claim excludes it
                self.log(f'Web number #{number} for {mac} not applied: {exc}', 'warn', source='sync')
            state['wanted'].discard(mac)
        state['error'] = error
        state['retry_at'] = self.clock() + 60.0 if error else 0.0
        self.auto_error('numbering', f'new cubes stay at Needs number: {error}' if error else None)
        self.mark_dirty('inventory', 'register')

    def auto_show_pull(self):
        """Pull a newer published show while a show relay is connected ("no show yet" is silent)."""
        if not (self.settings['auto_pull'] and self.settings['auto_show'] and self.sync['password_known']) or \
                not (self.showedit and self.showedit.relay()) or \
                any(j.kind == 'show.pull' and j.state == 'running' for j in self.jobs.jobs.values()):
            return None
        from jobs.show import show_pull_job
        return show_pull_job(self, auto=True)

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
            workstations = set(json.loads(self.db.metadata(dongle.WORKSTATIONS_KEY) or '[]'))
        except ValueError:
            workstations = set()
        self.inventory_cache = dict(rows_by_mac={r['mac']: r for r in rows}, roles=self.db.roles(),
                                    zones_by_mac={z['mac']: z for z in zones}, controllers=dongle.controllers(self.db),
                                    workstations=workstations, rows=rows, zones=zones)

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
                                        workstations=c.get('workstations', ()))

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
            if device.state == 'job':
                continue   # a probe that raced a job (e.g. a flash started meanwhile): the job owns the port now
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
        elif device.role in ('workstation', 'mainshow'):
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
            before = self.db.get(device.mac)
            try:
                self.db.reserve(device.mac, source='usb')   # as the pairing app's USB identification does
            except ValueError as exc:
                self.log(str(exc), 'warn', device.id)
            sightings.record(self.db.conn, device.mac, 'usb', f'USB identified on {device.port}')
            self.pinned_mac = device.mac
            device.pinned = True
            self.dirty.add('inventory')
            try:
                self.regflow.cube_identified(device, before)
            except Exception as exc:
                self.log(f'Registration workflow failed: {exc}', 'bad', device.id, source='register')
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
        return {'workstation': WorkstationSession, 'mainshow': MainshowSession, 'poolcentral': PoolCentralSession,
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

    def _workstations(self):
        """Every Workstation link (pairing station, dongle, General Radio, Workstation), oldest first, so the
        primary never hops between boards as hellos come and go; ties keep the order the sessions opened in."""
        return sorted((s for s in self.sessions.values() if isinstance(s, WorkstationSession)), key=lambda s: s.opened_at)

    def station_session(self, device=None):
        """The link that carries the pairing protocol, picked by what the boards report rather than by kind:
        the first connected link with a reader, else the first connected, else any.

        With `device`, that board's own link, so a second Workstation's discover/identify/zone relay stay
        reachable while the pairing station is also plugged in.
        """
        if device:
            return self.session_for(device, ('workstation',))
        links = self._workstations()
        for wanted in (lambda s: s.has_reader, lambda s: s.controller.connected):
            for session in links:
                if wanted(session):
                    return session
        return links[0] if links else None

    def relay_session(self):
        """The link whose registry talks to zones: the primary when it relays, else the first connected relay."""
        primary = self.station_session()
        if primary and primary.relay_capable:
            return primary
        return next((s for s in self._workstations() if s.relay_capable), None)

    def show_session(self):
        """Whatever can make a cube mainshow-ready and start the show: the Mainshow controller, else the first
        connected Workstation with the cube role."""
        for session in self.sessions.values():
            if isinstance(session, MainshowSession):
                return session
        return next((s for s in self._workstations() if s.show_verbs), None)

    def record_workstation(self, mac):
        """Remember a board that reported `roles` (the metadata key predates the Workstation name)."""
        # A board that is now a Workstation is no longer a zone: forget its old zone row (and its warnings).
        if self.store.forget(mac, 'now runs the Workstation firmware'):
            self.log(f'{mac} is now a Workstation; removed its old zone record', 'ok', source='zones')
            self.mark_dirty('inventory')
        macs = set(self.inventory_cache.get('workstations', ()))
        if mac not in macs:
            macs.add(mac)
            self.db.set_metadata(dongle.WORKSTATIONS_KEY, json.dumps(sorted(macs)))
            self.mark_dirty('inventory')

    def zone_relay(self, device=None):
        """The Workstation session whose registry can talk to zones (`device`: that board's), or raise."""
        session = self.station_session(device) if device else (self.relay_session() or self.station_session())
        if not session:
            raise ValueError('Connect a pairing station, ESP-NOW dongle or Workstation first')
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
        if any(self.versions[n] for n in ('devices', 'sessions', 'inventory', 'station', 'registry', 'jobs', 'sync', 'locks', 'builds',
                                          'autoupdate')):
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
