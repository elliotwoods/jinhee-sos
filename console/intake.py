"""Automatic USB intake: switch it on once, then plug boards in one after another.

Cubes: the cube flasher's Scheduler (core.Scheduler) decides which candidate port is next; each key
is attempted once per plug-in. Zones: zone_detect.plan() on the probe's report decides flash /
database / skip / ask, exactly as the zone flasher's auto mode. Both start off at every launch.
"""
import paths  # noqa: F401

from core import Scheduler
import zone_build
import zone_detect
import zonedb

from jobs import cube as cube_jobs, zone as zone_jobs


class Intake:
    def __init__(self, hub):
        self.hub = hub
        self.cubes = Scheduler()
        self.zones = Scheduler()
        self.zone_form = dict(profile='preshow', point=1, name='Preshow 1', params=[], rx_gain=zonedb.RX_GAIN_DEFAULT)
        self.zone_options = dict(next_point=True, allow_unidentified=False, database_only=True)
        self.results = {}   # key -> text

    def arm_cubes(self, enabled):
        if enabled:
            self.hub.builds.get('cube', {}).get('error') and self._raise(self.hub.builds['cube']['error'])
        self.cubes.armed = bool(enabled)
        if enabled:
            self.cubes.attempted = set()
        self.hub.log('Auto-flash cubes ' + ('ON · plug cubes in one after another' if enabled else 'stopped'),
                     'ok' if enabled else 'info', source='intake')
        self.hub.mark_dirty('inventory')

    def arm_zones(self, enabled, form=None, options=None):
        if form:
            self.zone_form.update(form)
        if options:
            self.zone_options.update(options)
        if enabled:
            profile = zone_build.PROFILES.get(self.zone_form['profile'])
            if not profile:
                self._raise('Choose a zone profile first')
            zone_build.load_manifest(profile['sketch'])
        self.zones.armed = bool(enabled)
        if enabled:
            self.zones.attempted = set()
        self.hub.log('Auto-flash zones ' + ('ON · plug zone boards in one after another' if enabled else 'stopped'),
                     'ok' if enabled else 'info', source='intake')
        self.hub.mark_dirty('inventory')

    @staticmethod
    def _raise(text):
        raise ValueError(text)

    def tick(self):
        hub = self.hub
        ports = [hub.port_dict(d) for d in hub.devices.values()]
        busy = any(j.hardware for j in hub.jobs.running())
        self.cubes.scan(ports, busy)
        self.zones.scan(ports, busy)
        if busy:
            return
        if self.cubes.armed:
            port = self.cubes.next()
            if port:
                device = hub.devices.get(port['key'])
                self.cubes.mark(port)
                if device and device.role in ('cube', 'unknown', None) and device.state != 'protected' \
                        and not (device.presumed.get('role') in ('zone', 'station', 'mainshow')):
                    try:
                        cube_jobs.flash_job(hub, device, manual=False)
                        self.results[port['key']] = 'flashing'
                    except Exception as exc:
                        self.results[port['key']] = f'NOT FLASHED · {exc}'
                        hub.log(f'Auto-flash cube {port["port"]}: {exc}', 'warn', device.id, source='intake')
                else:
                    self.results[port['key']] = 'skipped · not a cube'
                return
        if self.zones.armed:
            for device in list(hub.devices.values()):
                if device.key in self.zones.attempted or device.state not in ('idle', 'session') or not device.candidate:
                    continue
                detection = device.detection or (zone_detect.from_report(device.details) if device.role == 'zone' and device.details.get('firmware') else None)
                if detection is None:
                    if device.role in ('cube', 'station', 'mainshow', 'poolcentral', 'preshowbridge', 'pooltest', 'rangetest'):
                        detection = dict(kind={'cube': 'cube', 'station': 'station'}.get(device.role, 'other'),
                                         label=device.role_label(), mac=device.mac, profile=None, source='serial probe')
                    else:
                        continue  # unknown boards need an explicit bootloader detect
                manifests = {}
                for sketch in zone_build.SKETCHES:
                    try:
                        manifests[sketch] = zone_build.load_manifest(sketch)
                    except ValueError:
                        pass
                plan = zone_detect.plan(detection, self.zone_form, manifests, hub.store.published(), auto=True,
                                        allow_unidentified=self.zone_options['allow_unidentified'])
                self.zones.mark(dict(key=device.key))
                self.results[device.key] = f'{plan["action"]} · {plan["reason"]}'
                try:
                    if plan['action'] == 'flash':
                        zone_jobs.flash_job(hub, device, plan['profile'], plan['point'], plan['name'], plan.get('params', ()),
                                            plan.get('rx_gain', zonedb.RX_GAIN_DEFAULT))
                        if self.zone_options['next_point'] and detection.get('kind') != 'nctzone':
                            self.advance_point()
                    elif plan['action'] == 'database' and self.zone_options['database_only']:
                        zone_jobs.update_db_job(hub, device)
                    else:
                        hub.log(f'Auto-flash zone {device.port}: {plan["action"]} · {plan["reason"]}', 'info', device.id, source='intake')
                except Exception as exc:
                    self.results[device.key] = f'NOT FLASHED · {exc}'
                    hub.log(f'Auto-flash zone {device.port}: {exc}', 'warn', device.id, source='intake')
                return

    def advance_point(self):
        profile = zone_build.PROFILES[self.zone_form['profile']]
        points = list(profile['points'])
        try:
            index = points.index(int(self.zone_form['point']))
        except ValueError:
            index = -1
        if index + 1 < len(points):
            self.zone_form['point'] = points[index + 1]
            self.zone_form['name'] = profile['name'].format(point=self.zone_form['point'])

    def snapshot(self):
        return dict(cubes_armed=self.cubes.armed, zones_armed=self.zones.armed, zone_form=self.zone_form,
                    zone_options=self.zone_options, results=self.results)
