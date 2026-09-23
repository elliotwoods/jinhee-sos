"""Automatic firmware upgrades: build what is out of date, then bring USB boards up to that build.

Two settings, both on by default (Settings › Automatic updates):
  auto_build         rebuild a firmware target whose source changed (cube, the zone sketches, the Workstation,
                     the Mainshow controller), one build at a time, before anything is flashed from it
  auto_firmware_usb  flash a USB board whose firmware differs from the source version: zone plates (keeping the
                     identity the board reports), a legacy pairing station / General Radio (to the Workstation),
                     an old Workstation or Mainshow controller, and cubes while Register and Flash are off

Pool radios, the pool central and the preshow bridge are reported, never flashed here: the pool radios and
the central are a matched set, and the last two have no flash pipeline. The installed pairing station is
never touched (its port is `protected`, and every flasher refuses its MAC).

It never interrupts the operator: nothing starts while the console is busy (pairing, a publication, any
hardware job, an armed intake, Register), while a board is still settling after it was identified, or
within a minute of the operator sending that board a command. One automatic job runs at a time, and each
board is tried once per plug-in and target version; Skip and Retry are the panel's.

Runs on the owner thread from Hub.tick; it only starts jobs through the existing job modules.
"""
import paths  # noqa: F401
from collections import deque

import core
import dongle
import zone_build
import zone_detect

from jobs import build as build_jobs, cube as cube_jobs, dongle as dongle_jobs, zone as zone_jobs

REPORT_SKETCHES = {'poolcentral': 'PoolCentral', 'preshowbridge': 'PreshowBridge'}
MATCHED_SET = 'Pool radios and the pool central are a matched set: upgrade them together by hand'


def sketch_for(firmware):
    return next((sketch for prefix, sketch in zone_build.FIRMWARE_PREFIX.items() if (firmware or '').startswith(prefix)), None)


def source_version(sketch):
    """FIRMWARE_VERSION in zones/firmware/<sketch>/<sketch>.ino: what a build of the current source reports."""
    try:
        return zone_build.firmware_version(sketch)
    except (OSError, ValueError):
        return None


class AutoUpgrade:
    TICK = 1.0
    SETTLE = 20.0        # seconds after a board was identified before it may be flashed
    QUIET = 60.0         # seconds after the operator's last command to a board
    HISTORY = 8

    def __init__(self, hub):
        self.hub = hub
        self.paused = False            # the panel's Pause (not saved: a restart resumes)
        self.last = -1e9
        self.skipped = set()           # device keys the operator skipped (until unplugged)
        self.attempted = {}            # device key -> (target version, clock) tried on this plug-in
        self.failed = {}               # device key -> why the last automatic flash failed
        self.builds = {}               # target -> dict(fingerprint, ok, text) of the last automatic build
        self.fingerprints = {}         # target -> source fingerprint at the last builds refresh
        self.fingerprinted_at = None
        self.jobs = {}                 # job id -> dict(type='build'|'flash', target, key, label, version)
        self.plans = []
        self.targets = []
        self.history = deque(maxlen=self.HISTORY)

    # ---------------------------------------------------------------- targets and builds
    def target_list(self):
        """Every build target with its state: current, stale (source changed), missing, or unknown."""
        b = self.hub.builds or {}
        out = []
        cube = b.get('cube')
        if cube is not None:
            out.append(dict(target='cube', label='Cube', version=cube.get('version') or core.VERSION,
                            current=not cube.get('error'), reason=cube.get('error')))
        for sketch, z in (b.get('zones') or {}).items():
            out.append(dict(target=f'zone:{sketch}', label=sketch, version=z.get('version') or source_version(sketch),
                            current=not z.get('error'), reason=z.get('error')))
        for name in ('workstation', 'mainshow'):
            d = b.get(name)
            if d:
                out.append(dict(target=name, label=d.get('label') or name, version=d.get('version'),
                                current=d.get('state') == 'current', reason=None if d.get('state') == 'current' else
                                d.get('error') or ('No build yet' if d.get('state') == 'missing' else 'Source changed since the last build')))
        return out

    def fingerprint(self, target):
        """What the source looks like now: an automatic build is not repeated for the same fingerprint."""
        try:
            if target == 'cube':
                return core.source_digest()
            if target.startswith('zone:'):
                return zone_build.source_hash(target[5:])
            firmware = dongle_jobs.FIRMWARES[target]
            return str(max(p.stat().st_mtime for p in dongle.sources(firmware)))
        except (OSError, KeyError, ValueError):
            return None

    def refresh_fingerprints(self):
        """Forget the fingerprints whenever the builds are checked again (every minute and after each build)."""
        checked = (self.hub.builds or {}).get('checked_at')
        if checked != self.fingerprinted_at:
            self.fingerprinted_at = checked
            self.fingerprints = {}

    def source_fingerprint(self, target):
        if target not in self.fingerprints:
            self.fingerprints[target] = self.fingerprint(target)
        return self.fingerprints[target]

    def build_ready(self, target):
        """The build a flash of `target` needs is current (in simulation: an automatic build of it succeeded)."""
        entry = next((t for t in self.targets if t['target'] == target), None)
        if entry and entry['current']:
            return True
        return bool(self.hub.simulate and self.builds.get(target, {}).get('ok'))

    def tools_ok(self):
        tools = (self.hub.builds or {}).get('tools') or {}
        return bool(tools.get('arduino_cli') and tools.get('core_ok'))

    def build_state(self, t):
        if t['current']:
            return 'current', None
        running = next((j for j in self.running() if j['type'] == 'build' and j['target'] == t['target']), None)
        if running:
            return 'building', None
        memory = self.builds.get(t['target'])
        if memory and memory['fingerprint'] == self.source_fingerprint(t['target']):
            if not memory['ok']:
                return 'failed', memory['text']
            if not self.hub.simulate:
                return 'failed', f'Built, but the build is still not usable: {t["reason"]}'
            return 'current', None
        if not self.hub.simulate and not self.tools_ok():
            return 'no_tools', 'Install Arduino IDE or arduino-cli with ESP32 core 3.3.11 to build firmware'
        return 'queued', t['reason']

    def next_build(self, needed):
        if not self.hub.settings.get('auto_build'):
            return None
        queued = [t for t in self.targets if self.build_state(t)[0] == 'queued']
        queued.sort(key=lambda t: t['target'] not in needed)   # boards waiting for a build go first
        return queued[0] if queued else None

    def start_build(self, t):
        hub, target = self.hub, t['target']
        fake = getattr(hub, 'fake_build', None)   # --simulate: no arduino-cli (simulate.fake_build)
        if fake:
            job = fake(hub, target)
        elif target == 'cube':
            job = build_jobs.cube_build_job(hub)
        elif target.startswith('zone:'):
            job = build_jobs.zone_build_job(hub, target[5:])
        else:
            job = build_jobs.dongle_build_job(hub, target)
        job.origin = 'auto'
        self.jobs[job.id] = dict(type='build', target=target, key=None, label=t['label'], version=t['version'],
                                 fingerprint=self.source_fingerprint(target))
        hub.log(f'Automatic build: {t["label"]} {t["version"] or ""} ({t["reason"] or "out of date"})'.replace('  ', ' '),
                'info', source='auto')
        return job

    # ---------------------------------------------------------------- USB boards
    def hello(self, device):
        session = self.hub.sessions.get(device.id)
        return getattr(session, 'hello', None) or getattr(session, 'status', None) or device.details or {}

    def plan(self, device):
        """What an automatic upgrade would do for this board, or None when there is nothing to say."""
        role, details = device.role, device.details or {}
        base = dict(key=device.key, device=device.id, port=device.port, mac=device.mac, role=role,
                    label=device.role_label(), current=device.firmware, action=None)
        if device.state == 'protected' or (device.mac or '') in core.PROTECTED:
            return None
        if role == 'zone':
            firmware = details.get('firmware')
            sketch = sketch_for(firmware)
            version = sketch and source_version(sketch)
            if not version or firmware == version:
                return None
            base.update(label=details.get('name') or base['label'], target=f'zone:{sketch}', version=version)
            profile = zone_build.profile_for(firmware, details.get('zone_type'))
            if profile == 'pool':
                return dict(base, action='report', reason=MATCHED_SET)
            try:
                detection = zone_detect.from_report(details)
            except (KeyError, TypeError):
                return dict(base, action='report', reason='Incomplete zone report; identify the board again')
            if not detection.get('configured'):
                return dict(base, action='report', reason='Unconfigured board: give it an identity on the Flash page once')
            if not self.hub.store.published().get('version'):
                return dict(base, action='report', reason='No zone database is published yet')
            decided = zone_detect.plan(detection, self.hub.intake.zone_form, {sketch: dict(version=version)},
                                       self.hub.store.published(), auto=True)
            if decided['action'] != 'flash':
                return dict(base, action='report', reason=decided['reason'])
            return dict(base, action='zone', flash=dict(profile=decided['profile'], point=decided['point'],
                                                        name=decided['name'], params=decided.get('params') or [],
                                                        rx_gain=decided.get('rx_gain')))
        if role in ('workstation', 'mainshow'):
            hello = self.hello(device)
            family = dongle.family(hello)
            if role == 'mainshow' or family == 'mainshow':
                if family != 'mainshow' or dongle.current(hello):
                    return None
                firmware, which = dongle.MAINSHOW, 'mainshow'
            elif family in ('pairing', 'general') or (family == 'workstation' and not dongle.current(hello)):
                firmware, which = dongle.WORKSTATION, 'workstation'
            else:
                return None
            base.update(current=dongle._firmware(hello) or device.firmware, target=which, version=firmware.version,
                        label=dongle.label(hello) if isinstance(hello, dict) else base['label'])
            if device.mac:
                known = dongle.known_boards(self.hub.db, self.hub.store.zones())
                if which == 'workstation':
                    known = dict(known, controllers=set())
                reason = dongle.refusal(device.mac, known, firmware)
                if reason:
                    return dict(base, action='report', reason=reason)
            return dict(base, action=which)
        if role == 'cube':
            status = device.fw_status or {}
            if not status.get('version') or status['version'] == core.VERSION:
                return None   # unverified (no matching identity and READY) or current: the advisor speaks for it
            if device.mac and self.hub.inventory_cache.get('roles', {}).get(device.mac) == 'excluded':
                return None
            base.update(current=status['version'], target='cube', version=core.VERSION,
                        label=device.presumed.get('label') or base['label'])
            return dict(base, action='cube')
        if role in REPORT_SKETCHES:
            sketch = REPORT_SKETCHES[role]
            version = source_version(sketch)
            running = details.get('firmware') or details.get('version')
            if not version or not running or running == version:
                return None
            base.update(current=running, target=None, version=version)
            return dict(base, action='report', reason='No automatic flash for this board; upload it from its sketch by hand'
                        + (f' ({MATCHED_SET.lower()})' if role == 'poolcentral' else ''))
        return None

    def recently_touched(self, device, now):
        touched = getattr(self.hub, 'touched', {})
        return any(now - touched.get(name, -1e9) < self.QUIET for name in (device.id, device.port, device.key, device.mac) if name)

    def blocked(self, plan, device, now):
        """Why this board may not be flashed right now (None: go). Order: the operator's choices first."""
        hub = self.hub
        key = plan['key']
        if key in self.skipped:
            return 'skipped', 'Skipped until it is plugged in again'
        if key in self.failed:
            return 'failed', self.failed[key]
        tried = self.attempted.get(key)
        if tried and tried[0] == plan['version']:
            if (device.probed_at or 0) <= tried[1] or device.state in ('present', 'probing', 'job'):
                return 'checking', 'Checking the new firmware'
            return 'failed', f'Still reports {plan["current"]} after the automatic upgrade; use Retry or flash it by hand'
        if not hub.settings.get('auto_firmware_usb'):
            return 'off', 'Automatic firmware upgrades are off (Settings › Automatic updates)'
        if self.paused:
            return 'paused', 'Paused'
        if not self.build_ready(plan['target']):
            return 'build', 'Waiting for the firmware build'
        if plan['action'] == 'cube' and (hub.settings.get('auto_register') or hub.flashflow.enabled or hub.intake.cubes.armed):
            return 'waiting', 'Waiting: Register or Flash is on'
        if hub.intake.zones.armed or hub.intake.cubes.armed:
            return 'waiting', 'Waiting: the Flash page intake is armed'
        if any(j.hardware for j in hub.jobs.running()):
            return 'waiting', 'Waiting for the running job'
        if not hub.idle_flag.is_set() or hub.regflow.step not in ('idle', 'done', 'failed'):
            return 'waiting', 'Waiting: the console is busy'
        if device.state not in ('idle', 'session') or hub.probing == key:
            return 'waiting', 'Waiting for the board to be identified'
        settle = self.SETTLE - (now - (device.probed_at or now))
        if settle > 0:
            return 'settling', f'Starts in {int(settle) + 1} s'
        if self.recently_touched(device, now):
            return 'waiting', 'Waiting: in use (a command was sent to it in the last minute)'
        session = hub.sessions.get(device.id)
        if session is not None:
            zones = getattr(session, 'zones', None)
            controller = getattr(session, 'controller', None)
            if (zones is not None and (zones.publication or zones.inflight)) or (controller is not None and controller.mode):
                return 'waiting', 'Waiting: it is relaying right now'
            if hub.showedit and hub.showedit.active_relay is session and hub.showedit.registry.publication:
                return 'waiting', 'Waiting: it is sending the show'
        if plan['action'] in ('mainshow', 'workstation') and hub.showedit and hub.showedit.controller_show_running():
            return 'waiting', 'Waiting: the show is running'
        return None

    def start_flash(self, plan, device):
        hub = self.hub
        fake = getattr(hub, 'fake_firmware_flash', None)   # --simulate: no esptool (simulate.fake_firmware_flash)
        action = plan['action']
        if fake and action != 'cube':
            job = fake(hub, device, plan['target'], plan['version'])
        elif action == 'zone':
            f = plan['flash']
            job = zone_jobs.flash_job(hub, device, f['profile'], f['point'], f['name'], f['params'],
                                      **({'rx_gain': f['rx_gain']} if f.get('rx_gain') else {}))
        elif action in ('workstation', 'mainshow'):
            job = dongle_jobs.flash_job(hub, device, action)
        else:
            job = cube_jobs.flash_job(hub, device, manual=False, show=cube_jobs.published_show(hub))
        job.origin = 'auto'
        self.attempted[plan['key']] = (plan['version'], hub.clock())
        self.jobs[job.id] = dict(type='flash', target=plan['target'], key=plan['key'], label=plan['label'],
                                 version=plan['version'], port=plan['port'], device=plan['device'])
        hub.log(f'Automatic firmware upgrade: {plan["label"]} on {plan["port"]}: {plan["current"] or "?"} → {plan["version"]}',
                'info', device.id, source='auto')
        return job

    # ---------------------------------------------------------------- tick
    def running(self):
        jobs = self.hub.jobs.jobs
        return [dict(entry, id=job_id) for job_id, entry in self.jobs.items()
                if jobs.get(job_id) is not None and jobs[job_id].state == 'running']

    def collect(self):
        """Record finished automatic jobs (history, build memory, per-board failure)."""
        for job_id, entry in list(self.jobs.items()):
            job = self.hub.jobs.jobs.get(job_id)
            if job is not None and job.state == 'running':
                continue
            del self.jobs[job_id]
            ok = job is not None and job.state == 'done' and (job.outcome or {}).get('level') != 'failed'
            text = ((job.outcome or {}).get('text') or job.error or job.state) if job is not None else 'job lost'
            if entry['type'] == 'build':
                self.builds[entry['target']] = dict(fingerprint=entry['fingerprint'], ok=ok, text=text)
                self.hub.auto_error(f'build {entry["label"]}', None if ok else text)
            elif not ok:
                self.failed[entry['key']] = f'Automatic upgrade failed: {text}'
            self.history.appendleft(dict(type=entry['type'], label=entry['label'], version=entry['version'],
                                         port=entry.get('port'), ok=ok, text=text, at=self.hub.wall()))
            self.hub.mark_dirty('autoupdate')

    def tick(self):
        hub = self.hub
        now = hub.clock()
        if now - self.last < self.TICK:
            return
        self.last = now
        self.collect()
        present = {d.key for d in hub.devices.values()}
        self.skipped &= present                      # unplugged: a replug starts afresh
        for memory in (self.attempted, self.failed):
            for key in [k for k in memory if k not in present]:
                del memory[key]
        self.targets = self.target_list()
        self.refresh_fingerprints()
        plans = []
        for device in list(hub.devices.values()):
            try:
                plan = self.plan(device)
            except Exception as exc:     # a malformed report must never stop the others
                plan = dict(key=device.key, device=device.id, port=device.port, label=device.role_label(), role=device.role,
                            current=device.firmware, target=None, version=None, action='report', reason=f'Could not plan: {exc}')
            if plan:
                plans.append((plan, device))
        busy = bool(self.running())
        needed = {p['target'] for p, _ in plans if p['action'] not in (None, 'report')}
        started = False
        for plan, device in plans:
            job = next((j for j in self.running() if j['type'] == 'flash' and j['key'] == plan['key']), None)
            if job:
                plan.update(state='running', job=job['id'], reason=None)
                continue
            if plan['action'] == 'report':
                plan['state'] = 'report'
                continue
            reason = self.blocked(plan, device, now)
            if reason:
                plan['state'], plan['reason'] = reason
            elif busy or started:
                plan['state'], plan['reason'] = 'waiting', 'Queued behind another automatic update'
            else:
                try:
                    job = self.start_flash(plan, device)
                    plan.update(state='running', job=job.id, reason=None)
                    started = True
                except Exception as exc:
                    self.failed[plan['key']] = f'Could not start: {exc}'
                    plan['state'], plan['reason'] = 'failed', self.failed[plan['key']]
                    hub.log(f'Automatic firmware upgrade on {plan["port"]}: {exc}', 'warn', plan['device'], source='auto')
        if not busy and not started and hub.idle_flag.is_set() and not self.paused and \
                not any(j.kind.startswith('build') for j in hub.jobs.running()):
            target = self.next_build(needed)
            if target:
                try:
                    self.start_build(target)
                except Exception as exc:
                    self.builds[target['target']] = dict(fingerprint=self.source_fingerprint(target['target']), ok=False, text=str(exc))
                    hub.auto_error(f'build {target["label"]}', str(exc))
        self.plans = [p for p, _ in plans]
        hub.mark_dirty('autoupdate')

    # ---------------------------------------------------------------- operator
    def _plan_for(self, key):
        device = next((d for d in self.hub.devices.values() if key in (d.key, d.id, d.port)), None)
        if device is None:
            raise ValueError('That board is no longer plugged in')
        return device

    def skip(self, device):
        d = self._plan_for(device)
        self.skipped.add(d.key)
        self.hub.log(f'Automatic firmware upgrade skipped for {d.role_label()} on {d.port} until it is plugged in again',
                     'info', d.id, source='auto')
        self.hub.mark_dirty('autoupdate')

    def retry(self, device):
        d = self._plan_for(device)
        self.skipped.discard(d.key)
        self.failed.pop(d.key, None)
        self.attempted.pop(d.key, None)
        self.last = -1e9
        self.hub.mark_dirty('autoupdate')

    def retry_build(self, target):
        self.builds.pop(target, None)
        self.last = -1e9
        self.hub.mark_dirty('autoupdate')

    def pause(self, paused):
        self.paused = bool(paused)
        self.hub.log('Automatic firmware updates ' + ('paused' if self.paused else 'resumed'), 'info', source='auto')
        self.hub.mark_dirty('autoupdate')

    # ---------------------------------------------------------------- snapshot
    RECENT = 24 * 3600   # firmware heard over the air within this many seconds is listed

    @staticmethod
    def tally(rows):
        """State counts, plus `nearby`: behind and in range now (the registry walks these by itself) against
        `away`: behind but not heard lately (they update when a radio next reaches them)."""
        counts = {}
        for row in rows:
            counts[row['state']] = counts.get(row['state'], 0) + 1
        behind = [row for row in rows if row['state'] == 'behind']
        counts['nearby'] = sum(1 for row in behind if row.get('in_range'))
        counts['away'] = len(behind) - counts['nearby']
        return counts

    def air(self):
        """What the radios report: zone databases and cube shows (updated over the air by the registries), and
        firmware heard over the air that only a USB upgrade can fix."""
        hub = self.hub
        out = dict(zones=None, show=None, firmware=[])
        relays = [s for s in hub._workstations() if getattr(s, 'zones', None) is not None and s.relay_capable]
        if relays:
            rows = relays[0].zones.zone_rows()
            counts = self.tally(rows)
            walking = [dict(device=s.device.id, label=s.label, message=s.zones.message,
                            publishing=bool(s.zones.publication)) for s in relays if s.zones.walkaround]
            out['zones'] = dict(counts=counts, published=relays[0].zones.store.published().get('version'), walking=walking,
                                auto=bool(hub.settings.get('auto_zone_db_radio')))
            for z in rows:
                sketch = sketch_for(z.get('firmware'))
                version = sketch and source_version(sketch)
                if version and z.get('firmware') != version and (z.get('age_s') or 0) <= self.RECENT:
                    out['firmware'].append(dict(kind='zone', mac=z['mac'], label=z.get('name') or z['mac'],
                                                current=z.get('firmware'), version=version))
        if hub.showedit:
            registry = hub.showedit.registry
            rows = registry.cube_rows()
            counts = self.tally(rows)
            relay = hub.showedit.relay()
            out['show'] = dict(counts=counts, published=registry.store.published().get('version'), message=registry.message,
                               publishing=bool(registry.publication), relay=relay.device.id if relay else None,
                               auto=bool(hub.settings.get('auto_show')))
            for c in rows:
                if c.get('fw') and c['fw'] != core.VERSION and (c.get('age_s') or 0) <= self.RECENT:
                    out['firmware'].append(dict(kind='cube', mac=c['mac'], label=f'Cube #{c["number"]}' if c.get('number') else c['mac'],
                                                current=c['fw'], version=core.VERSION))
        return out

    def snapshot(self):
        hub = self.hub
        jobs = hub.jobs.jobs
        builds = []
        for t in self.targets:
            state, reason = self.build_state(t)
            entry = dict(t, state=state, reason=reason)
            job = next((j for j in self.running() if j['type'] == 'build' and j['target'] == t['target']), None)
            if job:
                live = jobs[job['id']]
                entry.update(job=job['id'], stage=live.stage, progress=live.progress)
            builds.append(entry)
        devices = []
        for plan in self.plans:
            entry = {k: v for k, v in plan.items() if k != 'flash'}
            live = jobs.get(plan.get('job')) if plan.get('job') else None
            if live is not None:
                entry.update(stage=live.stage, progress=live.progress)
            devices.append(entry)
        try:
            air = self.air()
        except Exception as exc:
            air = dict(zones=None, show=None, firmware=[], error=str(exc))
        return dict(auto_build=bool(hub.settings.get('auto_build')), auto_firmware_usb=bool(hub.settings.get('auto_firmware_usb')),
                    paused=self.paused, builds=builds, devices=devices, air=air, history=list(self.history),
                    running=len(self.running()))

