"""Automatic database updates: persisted settings, one walking relay, USB database-only updates, web pulls."""
import unittest
from unittest import mock

import support  # noqa: F401
from support import run_ticks, simulated_hub, tick_until
import commands
import commands_show  # noqa: F401  (registers show.*)
import simdocs
import simulate


class AutoUpdateTests(unittest.TestCase):
    def setUp(self):
        self.hub = simulated_hub()
        self.assertTrue(tick_until(self.hub, lambda: len(self.hub.sessions) == 6))

    def tearDown(self):
        self.hub.shutdown(force=True)

    def db_jobs(self):
        return [j for j in self.hub.jobs.jobs.values() if j.kind == 'zone.db_usb']

    def test_settings_default_on_and_survive_a_restart(self):
        for key in ('auto_zone_db_radio', 'auto_zone_db_usb', 'auto_show', 'auto_pull'):
            self.assertTrue(self.hub.settings[key], key)
        commands.run(self.hub, 'console.settings', dict(key='auto_show', value=False))
        commands.run(self.hub, 'zones.walkaround', dict(enabled=False))
        from hub import Hub
        again = Hub(self.hub.database, api_port=0, simulate=True)
        simulate.install(again, 'empty')
        again.boot()
        try:
            self.assertFalse(again.settings['auto_show'])
            self.assertFalse(again.settings['auto_zone_db_radio'])
            self.assertTrue(again.settings['auto_zone_db_usb'])
        finally:
            again.shutdown(force=True)

    def test_only_the_preferred_relay_walks(self):
        run_ticks(self.hub, 60)
        station = self.hub.station_session()
        radio = self.hub.sessions[self.hub.device_by_id('/dev/sim.radio').id]
        workstation = self.hub.sessions[self.hub.device_by_id('/dev/sim.workstation').id]
        self.assertIs(station, self.hub.sessions[self.hub.device_by_id('/dev/sim.station').id], 'the earliest reader link is primary')
        self.assertTrue(station.zones.walkaround and station.zones.auto_refresh)
        self.assertFalse(radio.zones.walkaround or workstation.zones.walkaround)
        commands.run(self.hub, 'zones.walkaround', dict(enabled=False))
        self.assertFalse(station.zones.walkaround or radio.zones.walkaround or workstation.zones.walkaround)
        commands.run(self.hub, 'zones.walkaround', dict(enabled=True))
        self.assertTrue(station.zones.walkaround)
        # the station goes away: the Workstation (the next reader link) takes over walking, alone
        self.hub.close_session(station, 'test')
        self.hub.apply_auto_modes()
        self.assertTrue(workstation.zones.walkaround)
        self.assertFalse(radio.zones.walkaround)
        # then the legacy General Radio, the last relay left
        self.hub.close_session(workstation, 'test')
        self.hub.apply_auto_modes()
        self.assertTrue(radio.zones.walkaround)

    def test_show_walkaround_follows_the_setting(self):
        self.hub.apply_auto_modes()
        self.assertTrue(self.hub.showedit.registry.walkaround)
        commands.run(self.hub, 'show.auto_update', dict(enabled=False))
        self.assertFalse(self.hub.showedit.registry.walkaround)
        self.assertFalse(self.hub.settings['auto_show'])

    def test_behind_zone_on_usb_gets_one_database_update(self):
        self.assertEqual(self.db_jobs(), [])      # nothing published: nothing to do
        publication = simdocs.seed_publication(self.hub, 32)
        plate, pool = self.hub._sim['plate'], self.hub._sim['pool']
        self.assertTrue(tick_until(self.hub, lambda: plate.db_version == 32, timeout=10))
        self.assertEqual((plate.db_crc, plate.db_count), (publication.crc, publication.count))
        run_ticks(self.hub, 100)
        jobs = self.db_jobs()
        self.assertEqual(len(jobs), 1)            # once per board and publication
        self.assertEqual(jobs[0].device, self.hub.device_by_id('/dev/sim.preshow1').id)
        self.assertEqual(pool.db_version, 32)     # same version, other content: 'ahead', left alone
        self.assertNotEqual(pool.db_crc, publication.crc)

    def test_usb_database_updates_can_be_switched_off(self):
        commands.run(self.hub, 'console.settings', dict(key='auto_zone_db_usb', value=False))
        simdocs.seed_publication(self.hub, 32)
        run_ticks(self.hub, 100)
        self.assertEqual(self.db_jobs(), [])
        self.assertEqual(self.hub._sim['plate'].db_version, 31)

    def test_zone_pull_needs_a_password_and_runs_once_per_web_version(self):
        with mock.patch('jobs.sync.zone_pull_job') as pull:
            self.hub.sync['password_known'] = False
            self.assertIsNone(self.hub.auto_zone_pull(33))
            self.hub.sync['password_known'] = True
            self.hub.auto_zone_pull(33)
            self.hub.auto_zone_pull(33)
            self.assertEqual(pull.call_count, 1)
            pull.assert_called_with(self.hub, auto=True)
            self.hub.settings['auto_pull'] = False
            self.assertIsNone(self.hub.auto_zone_pull(34))
            self.assertEqual(pull.call_count, 1)

    def test_auto_build_one_stale_target_at_a_time_and_no_retry_after_failure(self):
        self.assertTrue(self.hub.settings['auto_build'])
        stale = dict(tools=dict(arduino_cli='arduino-cli', core_ok=True), cube=dict(error=None),
                     zones=dict(DesertZone=dict(error='Firmware source changed'), PoolZone=dict(error='No firmware build yet'),
                                PreshowZone=dict(error=None)),
                     workstation=dict(state='current'), mainshow=dict(state='current'))
        built = []

        def fake_build(sketch, runner):
            built.append(sketch)
            if sketch == 'DesertZone':
                raise RuntimeError('compile error')
            return dict(version='test')

        with mock.patch.object(self.hub, 'refresh_builds'), mock.patch('jobs.build.zone_build.build', side_effect=fake_build):
            self.hub.builds = dict(stale, tools=dict(arduino_cli=None, core_ok=True))
            self.assertIsNone(self.hub.auto_build_step(), 'no Arduino tools: nothing starts')
            self.hub.builds = stale
            self.hub.settings['auto_build'] = False
            self.assertIsNone(self.hub.auto_build_step())
            self.hub.settings['auto_build'] = True
            first = self.hub.auto_build_step()
            self.assertEqual(first.title, 'Build DesertZone')
            self.assertIsNone(self.hub.auto_build_step(), 'one build at a time')
            self.assertTrue(tick_until(self.hub, lambda: first.state == 'failed'))
            self.assertIn('DesertZone', self.hub.auto_build_failed)
            second = self.hub.auto_build_step()
            self.assertEqual(second.title, 'Build PoolZone')
            self.assertTrue(tick_until(self.hub, lambda: second.state == 'done'))
            stale['zones']['PoolZone']['error'] = None   # what refresh_builds would now report
            self.assertIsNone(self.hub.auto_build_step(), 'the failed target is not retried by itself')
        self.assertEqual(built, ['DesertZone', 'PoolZone'])


if __name__ == '__main__':
    unittest.main()
