"""Automatic firmware builds and USB upgrades (autoupgrade.py) on the simulated bench."""
import unittest

import support  # noqa: F401
from support import section, simulated_hub, tick_until

import autoupgrade
import commands
import core
import simdocs
from devices import Device

WORKSTATION = 'workstation-1.0.0'


def all_current(hub):
    """Every build target current, whatever the checkout's build directories hold."""
    b = hub.builds
    b['cube'] = dict(version=core.VERSION, build_hash='test', error=None)
    for sketch in list(b.get('zones') or {}):
        b['zones'][sketch] = dict(version=autoupgrade.source_version(sketch), build_hash='test', error=None)
    for name in ('workstation', 'mainshow'):
        b[name] = dict(b.get(name) or {}, state='current')
    b['checked_at'] = 'test'


class AutoUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.hub = simulated_hub(auto_firmware=True)
        self.auto = self.hub.autoupgrade
        self.auto.SETTLE = 0
        self.hub.refresh_builds = lambda: None     # the tests decide what is stale
        all_current(self.hub)
        self.sim = self.hub._sim
        self.flash_overlap = False
        self.hub.settings.update(auto_build=False, auto_firmware_usb=False)   # each test switches them on
        self.assertTrue(tick_until(self.hub, lambda: len(self.hub.sessions) == 6))

    def on(self):
        self.hub.settings.update(auto_build=True, auto_firmware_usb=True)

    def tearDown(self):
        self.hub.shutdown(force=True)

    def tick_until(self, predicate, timeout=10):
        def check():
            if len([j for j in self.hub.jobs.running() if j.origin == 'auto']) > 1:
                self.flash_overlap = True
            return predicate()
        return tick_until(self.hub, check, timeout=timeout)

    def device(self, port):
        return self.hub.device_by_id(port)

    def plan(self, port):
        return next((p for p in self.auto.plans if p['port'] == port), None)

    def auto_jobs(self, prefix=''):
        return [j for j in self.hub.jobs.jobs.values() if j.origin == 'auto' and j.kind.startswith(prefix)]

    def reprobe(self, port):
        commands.run(self.hub, 'device.probe', dict(device=port))
        self.hub.touched.clear()     # the test's own command, not an operator using the board

    def test_settings_default_on(self):
        from hub import Hub
        hub = Hub(support.temp_database(), api_port=0, workers=False)
        self.assertTrue(hub.settings['auto_build'] and hub.settings['auto_firmware_usb'])

    def test_legacy_relays_become_workstations_one_at_a_time(self):
        self.on()
        station, radio = self.sim['station'], self.sim['radio']
        self.assertTrue(self.tick_until(lambda: station.firmware == WORKSTATION and radio.firmware == WORKSTATION, timeout=20),
                        section(self.hub, 'autoupdate'))
        self.assertFalse(self.flash_overlap, 'two automatic jobs ran at once')
        history = self.auto.history
        self.assertTrue(any(h['version'] == WORKSTATION and h['ok'] for h in history))

    def test_protected_station_is_never_planned(self):
        device = Device(dict(port='/dev/sim.protected', key='protected', serial=next(iter(core.PROTECTED)), native_usb=True,
                             candidate=False), self.hub.clock)
        device.role, device.details = 'workstation', dict(firmware='nct-pairing-1.8-zones', mac=next(iter(core.PROTECTED)))
        self.assertEqual(device.state, 'protected')
        self.assertIsNone(self.auto.plan(device))

    def test_old_zone_plate_is_flashed_keeping_its_identity(self):
        simdocs.seed_publication(self.hub, 32)
        plate = self.sim['plate']
        plate.firmware = 'preshow-3.0.0'
        self.reprobe('/dev/sim.preshow1')
        self.assertTrue(self.tick_until(lambda: (self.plan('/dev/sim.preshow1') or {}).get('state') == 'off'))
        flash = self.auto.plan(self.device('/dev/sim.preshow1'))['flash']
        self.assertEqual((flash['profile'], flash['point'], flash['name']), ('preshow', 1, 'Preshow 1'))
        self.on()
        self.assertTrue(self.tick_until(lambda: plate.firmware == autoupgrade.source_version('PreshowZone'), timeout=20))

    def test_pool_radio_is_only_reported(self):
        pool = self.sim['pool']
        pool.firmware = 'pool-3.0.0'
        self.on()
        self.reprobe('/dev/sim.pool3')
        self.assertTrue(self.tick_until(lambda: (self.plan('/dev/sim.pool3') or {}).get('state') == 'report'))
        self.assertIn('matched set', self.plan('/dev/sim.pool3')['reason'])
        self.tick_until(lambda: False, timeout=2)
        self.assertEqual(pool.firmware, 'pool-3.0.0')

    def test_cube_waits_while_register_is_on(self):
        self.hub.settings['auto_register'] = True
        self.on()
        self.assertTrue(self.tick_until(lambda: (self.plan('/dev/sim.cube') or {}).get('reason') == 'Waiting: Register or Flash is on'))
        self.hub.settings['auto_register'] = False
        cube = self.sim['cube']
        self.assertTrue(self.tick_until(lambda: cube.firmware != 'v1.4.1-USB.2', timeout=20))

    def test_gates_defer_the_upgrade(self):
        self.tick_until(lambda: self.plan('/dev/sim.radio'), timeout=5)
        self.on()
        radio = self.device('/dev/sim.radio')
        plan = self.plan('/dev/sim.radio')
        now = self.hub.clock()
        self.auto.SETTLE = 20
        radio.probed_at = now
        self.assertEqual(self.auto.blocked(plan, radio, now)[0], 'settling')
        self.auto.SETTLE = 0
        self.hub.touch(radio.id)
        self.assertIn('in use', self.auto.blocked(plan, radio, now)[1])
        self.hub.touched.clear()
        self.hub.idle_flag.clear()
        self.assertIn('busy', self.auto.blocked(plan, radio, now)[1])
        self.hub.idle_flag.set()
        self.auto.pause(True)
        self.assertEqual(self.auto.blocked(plan, radio, now)[0], 'paused')
        self.auto.pause(False)
        commands.run(self.hub, 'autoupgrade.skip', dict(device=radio.id))
        self.assertEqual(self.auto.blocked(plan, radio, now)[0], 'skipped')
        commands.run(self.hub, 'autoupgrade.retry', dict(device=radio.id))
        self.assertIsNone(self.auto.blocked(plan, radio, now))

    def test_operator_command_marks_a_board_in_use(self):
        radio = self.device('/dev/sim.radio')
        commands.run(self.hub, 'device.disconnect', dict(device=radio.id))
        self.assertTrue(self.auto.recently_touched(radio, self.hub.clock()))

    def test_stale_build_is_built_before_the_board_is_flashed(self):
        self.hub.builds['workstation']['state'] = 'stale'
        self.on()
        self.assertTrue(self.tick_until(lambda: self.sim['radio'].firmware == WORKSTATION, timeout=20))
        builds, flashes = self.auto_jobs('build'), self.auto_jobs('workstation')
        self.assertTrue(builds and flashes)
        self.assertLess(min(j.started_at for j in builds), min(j.started_at for j in flashes))

    def test_failed_build_waits_for_a_source_change(self):
        self.hub.settings['auto_build'] = True
        self.hub.builds['zones']['DesertZone']['error'] = 'Firmware source changed since the last build'
        calls = []

        def failing(hub, target):
            from jobs.base import Job
            job = Job('build.sim', 'build', f'Build {target}')
            calls.append(target)

            def work(emit, cancel):
                raise RuntimeError('compile error')
            hub.jobs.start(job, work)
            return job
        self.hub.fake_build = failing
        self.assertTrue(self.tick_until(lambda: self.auto.builds.get('zone:DesertZone')))
        self.tick_until(lambda: False, timeout=2.5)
        self.assertEqual(calls, ['zone:DesertZone'])
        state = next(b for b in section(self.hub, 'autoupdate')['builds'] if b['target'] == 'zone:DesertZone')
        self.assertEqual(state['state'], 'failed')
        self.auto.fingerprints['zone:DesertZone'] = 'edited'       # the source changed: try again
        self.assertTrue(self.tick_until(lambda: len(calls) == 2))

    def test_panel_section(self):
        self.on()
        self.assertTrue(self.tick_until(lambda: (section(self.hub, 'autoupdate') or {}).get('devices')))
        data = section(self.hub, 'autoupdate')
        self.assertTrue(data['auto_build'] and data['auto_firmware_usb'])
        self.assertIn('air', data)
        self.assertTrue(all('state' in d for d in data['devices']))


if __name__ == '__main__':
    unittest.main()
