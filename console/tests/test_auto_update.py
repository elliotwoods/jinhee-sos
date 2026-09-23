"""Automatic database updates: persisted settings, one walking relay, USB database-only updates, web pulls, web sync."""
import sys
import unittest
from pathlib import Path
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
        for key in ('auto_zone_db_radio', 'auto_zone_db_usb', 'auto_show', 'auto_pull', 'auto_sync'):
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

    def test_every_relay_walks_and_one_publishes_at_a_time(self):
        run_ticks(self.hub, 60)
        station = self.hub.sessions[self.hub.device_by_id('/dev/sim.station').id]
        radio = self.hub.sessions[self.hub.device_by_id('/dev/sim.radio').id]
        workstation = self.hub.sessions[self.hub.device_by_id('/dev/sim.workstation').id]
        links = (station, radio, workstation)
        self.assertTrue(all(s.zones.walkaround and s.zones.auto_refresh for s in links))
        commands.run(self.hub, 'zones.walkaround', dict(enabled=False))
        self.assertFalse(any(s.zones.walkaround for s in links))
        commands.run(self.hub, 'zones.walkaround', dict(enabled=True))
        self.assertTrue(all(s.zones.walkaround for s in links))
        # a radio publishing holds every other radio's walk back
        self.assertTrue(self.hub.zone_walk_allowed(radio))
        station.zones.publication = object()
        self.assertFalse(self.hub.zone_walk_allowed(radio))
        self.assertTrue(self.hub.zone_walk_allowed(station))
        station.zones.publication = None

    def test_a_zone_is_walked_only_by_a_radio_that_heard_it(self):
        run_ticks(self.hub, 60)
        station = self.hub.sessions[self.hub.device_by_id('/dev/sim.station').id]
        radio = self.hub.sessions[self.hub.device_by_id('/dev/sim.radio').id]
        pool = next(z for z in station.zones.zone_rows() if z['name'].startswith('Pool'))
        plate = next(z for z in station.zones.zone_rows() if z['name'].startswith('Preshow'))
        self.assertNotIn(pool['mac'], radio.zones.heard, 'the simulated General Radio hears only the plate')
        published = dict(station.zones.store.published(), version=pool['db_version'] + 1, crc=1)
        with mock.patch('zone_registry.ZoneStore.published', return_value=published):
            self.assertEqual(station.zones.walk_candidates(), sorted([pool['mac'], plate['mac']]))
            self.assertEqual(radio.zones.walk_candidates(), [plate['mac']])

    def test_a_walk_that_cannot_publish_does_not_break_the_tick(self):
        run_ticks(self.hub, 60)
        station = self.hub.sessions[self.hub.device_by_id('/dev/sim.station').id]
        station.zones.stop()
        with mock.patch.object(station.zones.store, 'current', side_effect=ValueError('cache inconsistent')), \
                mock.patch.object(station.zones, 'walk_candidates', return_value=['AA:BB:CC:DD:EE:FF']):
            station.zones.tick(True, station.controller.station)
            self.assertEqual(station.zones.walk_error, 'cache inconsistent')
            self.assertIsNone(station.zones.publication)
            self.assertIn('AA:BB:CC:DD:EE:FF', station.zones.backoff)

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


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'pairing_station' / 'tests'))
from fake_web_inventory import FakeWebInventory  # noqa: E402
import web_client  # noqa: E402


class AutoSyncTests(unittest.TestCase):
    """The console syncs by itself against a fake web inventory: nobody presses Sync."""

    def setUp(self):
        self.server = FakeWebInventory()
        import jobs.sync as sync_jobs
        self.sync_jobs, self.previous_client = sync_jobs, sync_jobs.client
        sync_jobs.client = lambda hub, password=web_client.STORED: web_client.WebClient(
            server=self.server.url, password=web_client.load_password() or '', client='NCT Console test')
        web_client.save_password('test-password')
        self.hub = simulated_hub()
        self.hub.SYNC_DEBOUNCE, self.hub.SYNC_MIN_GAP = 0.2, 0.0
        self.hub.sync['password_known'] = True
        self.hub.auto_web = True          # the timers talk to the loopback fake

    def tearDown(self):
        self.hub.shutdown(force=True)
        self.server.close()
        self.sync_jobs.client = self.previous_client
        web_client.forget_password()

    def settled(self):
        return not self.hub.sync['busy'] and not any(j.state == 'running' for j in self.hub.jobs.jobs.values()
                                                    if j.kind.startswith('sync'))

    def synced(self, timeout=20):
        return tick_until(self.hub, lambda: self.hub.sync['last_result'] is not None and self.settled(), timeout=timeout)

    def test_catches_up_then_uploads_a_local_change_without_a_click(self):
        hub, mac = self.hub, self.hub._sim['known_mac']
        self.assertTrue(self.synced(), hub.sync)            # the boot status check found local records to upload
        self.assertIn(mac, self.server.records)
        self.assertGreater(self.server.zonedb['version'], 0, 'the zone database was published')
        number = hub.db.suggested_number()
        commands.run(hub, 'inventory.rename', dict(mac=mac, number=number))
        ok = tick_until(hub, lambda: self.server.records[mac]['record'].get('cube_id') == number, timeout=20)
        self.assertTrue(ok, (hub.autosync, hub.sync['last_error']))
        self.assertFalse(any(j.kind == 'sync' and not j.quiet for j in hub.jobs.jobs.values()), 'every sync was automatic')

    def test_a_change_on_the_web_is_downloaded_by_the_next_status_check(self):
        hub, mac = self.hub, self.hub._sim['known_mac']
        self.assertTrue(self.synced())
        self.server.edit(mac, detail='edited on another computer', updated_at='2099-01-01T00:00:00+00:00')
        hub.timers['sync_status'] = -1e9
        ok = tick_until(hub, lambda: (hub.db.get(mac) or {}).get('detail') == 'edited on another computer', timeout=20)
        self.assertTrue(ok, (hub.sync['status'], hub.sync['last_error']))

    def test_nothing_runs_without_a_password_or_with_the_setting_off(self):
        hub = self.hub
        hub.sync['password_known'] = False
        self.assertIsNone(hub.auto_sync())
        hub.sync['password_known'] = True
        hub.settings['auto_sync'] = False
        self.assertIsNone(hub.auto_sync())
        run_ticks(hub, 60)
        self.assertFalse(any(j.kind == 'sync' for j in hub.jobs.jobs.values()), 'no sync while switched off')
        self.assertTrue(hub.sync['status'] and hub.sync['status'].get('inventory_up'), 'the status check still runs')

    def test_unreachable_backs_off_and_a_success_resets_it(self):
        hub = self.hub
        hub.settings['auto_sync'] = False
        self.server.offline = True
        hub.settings['auto_sync'] = True
        self.assertIsNotNone(hub.auto_sync('test'))
        self.assertTrue(tick_until(hub, self.settled, timeout=20))
        self.assertEqual(hub.sync['last_error']['kind'], 'unreachable', hub.sync['last_error'])
        self.assertGreater(hub.autosync['retry_at'], hub.clock())
        self.assertIsNone(hub.auto_sync('while backing off'))
        self.assertIn('retry in', support_section(hub)['text'])
        self.server.offline = False
        hub.autosync['retry_at'] = 0.0
        self.assertIsNotNone(hub.auto_sync('back online'))
        self.assertTrue(self.synced())
        self.assertIsNone(hub.sync['last_error'])
        self.assertEqual((hub.autosync['failures'], hub.autosync['retry_at']), (0, 0.0))

    def test_a_rejected_password_stops_automatic_sync_until_sign_in(self):
        hub = self.hub
        self.server.password = 'changed'
        tick_until(hub, lambda: hub.sync['last_error'] is not None or (hub.sync['status'] or {}).get('state') == 'unauthorized',
                   timeout=20)
        self.assertTrue(tick_until(hub, self.settled, timeout=20))
        hub.sync['password_known'] = bool(web_client.load_password())
        if hub.sync['password_known']:            # the status check saw it first: a sync attempt forgets it
            hub.auto_sync('test')
            self.assertTrue(tick_until(hub, self.settled, timeout=20))
        self.assertFalse(hub.sync['password_known'])
        self.assertIsNone(hub.auto_sync('no password'))


    NEW_A, NEW_B = '02:AA:00:00:00:01', '02:AA:00:00:00:02'

    def new_unnumbered(self, mac):
        self.hub.db.set_metadata('auto_number', '0')      # as after any sync
        row = self.hub.db.reserve(mac, source='usb')
        self.assertIsNone(row['cube_id'])
        return row

    def test_the_web_hands_out_numbers_so_two_computers_never_collide(self):
        hub = self.hub
        other = web_client.WebClient(server=self.server.url, password='test-password', client='other laptop')
        self.assertTrue(self.synced())
        taken = other.claim_number(self.NEW_B, [], 'other laptop')['number']     # the other computer, first
        self.new_unnumbered(self.NEW_A)
        ok = tick_until(hub, lambda: (hub.db.get(self.NEW_A) or {}).get('cube_id') is not None, timeout=10)
        self.assertTrue(ok, hub.numbering)
        mine = hub.db.get(self.NEW_A)['cube_id']
        self.assertNotEqual(mine, taken)
        self.assertEqual(hub.db.get(self.NEW_A)['status'], 'awaiting_tag')
        self.assertEqual(self.server.claims[mine], self.NEW_A)
        # and the automatic sync uploads it with that number
        ok = tick_until(hub, lambda: (self.server.records.get(self.NEW_A) or {}).get('record', {}).get('cube_id') == mine, timeout=20)
        self.assertTrue(ok)

    def test_an_old_web_or_no_web_leaves_new_cubes_at_needs_number(self):
        hub = self.hub
        self.server.claims_missing = True
        self.new_unnumbered(self.NEW_A)
        ok = tick_until(hub, lambda: hub.numbering['error'] is not None, timeout=10)
        self.assertTrue(ok, hub.numbering)
        self.assertIsNone(hub.db.get(self.NEW_A)['cube_id'])
        self.assertGreater(hub.numbering['retry_at'], hub.clock())
        # a computer that never synced (no password) numbers locally, as before
        hub.sync['password_known'] = False
        self.assertFalse(hub.web_numbering())

    def test_numbers_already_used_here_are_never_handed_out(self):
        hub = self.hub
        used = {r['cube_id'] for r in hub.db.rows() if r['cube_id'] is not None} | set(hub.db.reserved_numbers())
        self.new_unnumbered(self.NEW_A)
        self.assertTrue(tick_until(hub, lambda: (hub.db.get(self.NEW_A) or {}).get('cube_id') is not None, timeout=10))
        self.assertNotIn(hub.db.get(self.NEW_A)['cube_id'], used)
        self.assertGreaterEqual(hub.db.get(self.NEW_A)['cube_id'], 33)


def support_section(hub):
    import support
    return support.section(hub, 'sync')


if __name__ == '__main__':
    unittest.main()
