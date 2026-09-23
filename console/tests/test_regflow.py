"""The guided registration workflow (regflow.py) on the simulated bench: USB → number → NFC → sync."""
import sys
import unittest
from pathlib import Path

import support
from support import simulated_hub, tick_until

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'pairing_station' / 'tests'))
from fake_web_inventory import FakeWebInventory  # noqa: E402

import commands  # noqa: E402
import simulate  # noqa: E402
import web_client  # noqa: E402

NEW_MAC = 'A4:CF:12:34:56:9A'


def crash_logs(hub):
    """Workflow exceptions the hub caught (a finished or failed flow must not raise on later ticks)."""
    return [line['text'] for line in hub.recent_logs if line['text'].startswith('Registration workflow failed')]


class RegistrationFlowTests(unittest.TestCase):
    def setUp(self):
        self.hub = simulated_hub()
        tick_until(self.hub, lambda: self.station() and self.station().connected and self.hub.pinned_mac, timeout=8)
        web_client.forget_password()

    def tearDown(self):
        self.hub.shutdown(force=True)
        web_client.forget_password()

    # ---------------------------------------------------------------- helpers
    def station(self):
        session = self.hub.station_session()
        return session.controller if session else None

    def flow(self):
        return self.hub.regflow

    def enable(self):
        commands.run(self.hub, 'register.enable', {'on': True})

    def plug(self, mac=NEW_MAC, port='/dev/sim.cube-new'):
        board = simulate.FakeCube(port, mac)
        self.hub.scanner.add(board)
        tick_until(self.hub, lambda: self.flow().mac == mac, timeout=8)
        return board

    def armed(self):
        return tick_until(self.hub, lambda: self.flow().armed and self.station().phase == 'identifying'
                          and (self.station().active or {}).get('mac') == self.flow().mac, timeout=6)

    def scan(self, uid):
        c = self.station()
        transport = self.hub.station_session().transport
        transport.receive(dict(event='tag_state', present=False))
        transport.receive(dict(event='tag', id=c.request, uid=uid))

    def manual_numbers(self):
        self.hub.db.set_metadata('auto_number', '0')

    # ---------------------------------------------------------------- tests
    def test_new_cube_gets_the_lowest_free_number_and_is_told(self):
        self.manual_numbers()
        expected = self.hub.db.suggested_number()
        self.enable()
        self.plug()
        f = self.flow()
        self.assertEqual(f.number, expected)
        self.assertNotIn(f.number, (39, 43))
        self.assertEqual(f.number_new, 'assigned')
        self.assertEqual(self.hub.db.get(NEW_MAC)['cube_id'], expected)
        self.assertIn(f'New number #{expected}', f.notice['text'])
        self.assertEqual(f.step, 'nfc')

    def test_numbers_skip_reserved(self):
        self.manual_numbers()
        db = self.hub.db
        taken = db.suggested_number()
        # Fill everything up to 38 so the next free number would be 39 without the reservation.
        for n in range(taken, 39):
            mac = f'A4:CF:12:00:00:{n:02X}'
            db.reserve(mac, source='test')
            db.rename(mac, n)
        self.enable()
        self.plug()
        self.assertEqual(self.flow().number, 40)

    def test_existing_number_is_kept(self):
        self.manual_numbers()
        self.hub.db.reserve(NEW_MAC, source='test')
        self.hub.db.rename(NEW_MAC, 77)
        self.enable()
        self.plug()
        self.assertEqual(self.flow().number, 77)
        self.assertEqual(self.flow().number_new, 'existing')

    def test_enabling_with_a_cube_plugged_in_starts_it(self):
        pinned = self.hub.pinned_mac
        self.enable()
        tick_until(self.hub, lambda: self.flow().mac == pinned, timeout=3)
        self.assertEqual(self.flow().mac, pinned)
        self.assertEqual(self.flow().number_new, 'existing')

    def test_disabled_does_nothing(self):
        self.plug_quiet = simulate.FakeCube('/dev/sim.cube-new', NEW_MAC)
        self.hub.scanner.add(self.plug_quiet)
        tick_until(self.hub, lambda: self.hub.pinned_mac == NEW_MAC, timeout=8)
        self.assertEqual(self.flow().step, 'idle')
        self.assertFalse(self.station().mode)

    def test_scan_registers_then_waits_for_sign_in(self):
        self.manual_numbers()
        self.enable()
        self.plug()
        self.assertTrue(self.armed())
        self.scan('04:77:66:55:44:33:22')
        tick_until(self.hub, lambda: self.flow().step == 'sync', timeout=4)
        row = self.hub.db.get(NEW_MAC)
        self.assertEqual(row['status'], 'acknowledged')
        self.assertEqual(row['uid'], '04:77:66:55:44:33:22')
        tick_until(self.hub, lambda: 'Sign in' in self.flow().wait, timeout=2)
        self.assertIn('Sign in', self.flow().wait)

    def test_unconfirmed_fails_and_does_not_retry_by_itself(self):
        self.enable()
        self.plug()
        self.assertTrue(self.armed())
        board = simulate.BOARDS['/dev/sim.station']
        original = board.handle_json

        def no_ack(message):
            out = original(message)
            for e in out:
                if e.get('event') == 'registered':
                    e['acknowledged'] = False
            return out
        board.handle_json = no_ack
        self.scan('04:77:66:55:44:33:23')
        tick_until(self.hub, lambda: self.flow().step == 'failed', timeout=4)
        self.assertEqual(self.flow().failed_step, 'nfc')
        self.assertEqual(self.hub.db.get(NEW_MAC)['status'], 'unconfirmed')
        support.run_ticks(self.hub, 10)
        self.assertEqual(self.flow().step, 'failed', 'no automatic retry')
        self.assertEqual(crash_logs(self.hub), [])
        board.handle_json = original
        commands.run(self.hub, 'register.retry', {})
        tick_until(self.hub, lambda: self.flow().step == 'sync', timeout=4)
        self.assertEqual(self.hub.db.get(NEW_MAC)['status'], 'acknowledged')

    def test_second_cube_restarts_the_flow(self):
        self.enable()
        self.plug()
        self.assertTrue(self.armed())
        other = 'A4:CF:12:34:56:9B'
        self.plug(other, '/dev/sim.cube-other')
        self.assertEqual(self.flow().mac, other)
        self.assertEqual(self.flow().history[0]['result'], 'interrupted')
        tick_until(self.hub, lambda: self.flow().armed and (self.station().active or {}).get('mac') == other, timeout=6)
        self.assertEqual(self.station().active['mac'], other)

    def test_waits_without_a_station(self):
        # Close every link with a reader (the station, then the Workstation that takes over as primary);
        # the General Radio is the remaining pairing link and has no NFC reader.
        self.assertTrue(tick_until(self.hub, lambda: len(self.hub.sessions) == 6 and
                                   all(s.controller.connected for s in self.hub.sessions.values() if hasattr(s, 'controller')), timeout=8))
        while self.hub.station_session() and self.hub.station_session().has_reader:
            self.hub.close_session(self.hub.station_session(), 'test', manual=True)
        self.assertIs(self.hub.station_session(), self.hub.sessions[self.hub.device_by_id('/dev/sim.radio').id])
        self.enable()
        self.plug()
        tick_until(self.hub, lambda: bool(self.flow().wait), timeout=3)
        self.assertEqual(self.flow().step, 'nfc')
        self.assertFalse(self.flow().armed)
        self.assertTrue(self.flow().wait)

    def test_renumber_before_the_scan(self):
        self.manual_numbers()
        self.enable()
        self.plug()
        self.assertTrue(self.armed())
        commands.run(self.hub, 'register.renumber', {'number': 150})
        self.assertEqual(self.hub.db.get(NEW_MAC)['cube_id'], 150)
        self.assertEqual(self.flow().number_new, 'label')
        tick_until(self.hub, lambda: self.flow().armed and self.station().phase == 'identifying', timeout=6)
        self.assertEqual(self.station().active['cube_id'], 150)
        taken = self.hub.db.get(self.hub._sim['known_mac'])['cube_id']
        with self.assertRaises(ValueError):
            commands.run(self.hub, 'register.renumber', {'number': taken})   # another cube's number

    def test_section_is_published(self):
        self.enable()
        self.plug()
        data = support.section(self.hub, 'register')
        self.assertTrue(data['enabled'])
        self.assertEqual(data['mac'], NEW_MAC)
        self.assertEqual(data['steps'], ['usb', 'number', 'nfc', 'sync'])


class RegistrationSyncTests(unittest.TestCase):
    """The last step runs one real Sync against a fake web inventory."""

    def setUp(self):
        self.server = FakeWebInventory()
        import jobs.sync as sync_jobs
        self.sync_jobs, self.previous_client = sync_jobs, sync_jobs.client
        sync_jobs.client = lambda hub, password=web_client.STORED: web_client.WebClient(server=self.server.url, password='test-password',
                                                                                        client='NCT Console test')
        web_client.save_password('test-password')
        self.hub = simulated_hub()
        self.hub.sync['password_known'] = True
        tick_until(self.hub, lambda: self.hub.station_session() and self.hub.station_session().controller.connected
                   and self.hub.pinned_mac, timeout=8)

    def tearDown(self):
        self.hub.shutdown(force=True)
        self.server.close()
        self.sync_jobs.client = self.previous_client
        web_client.forget_password()

    def test_registered_cube_is_synced(self):
        hub = self.hub
        commands.run(hub, 'register.enable', {'on': True})
        hub.scanner.add(simulate.FakeCube('/dev/sim.cube-new', NEW_MAC))
        c = hub.station_session().controller
        tick_until(hub, lambda: hub.regflow.mac == NEW_MAC and hub.regflow.armed and c.phase == 'identifying'
                   and (c.active or {}).get('mac') == NEW_MAC, timeout=8)
        transport = hub.station_session().transport
        transport.receive(dict(event='tag_state', present=False))
        transport.receive(dict(event='tag', id=c.request, uid='04:77:66:55:44:33:24'))
        ok = tick_until(hub, lambda: hub.regflow.step in ('done', 'failed'), timeout=20)
        self.assertTrue(ok, hub.regflow.snapshot())
        self.assertEqual(hub.regflow.step, 'done', hub.regflow.error)
        self.assertEqual(hub.regflow.history[0]['result'], 'registered')
        self.assertIn(NEW_MAC, self.server.records)
        self.assertGreater(self.server.zonedb['version'], 0, 'the zone database was published')
        support.run_ticks(hub, 10)
        self.assertEqual(crash_logs(hub), [])


    def test_the_number_comes_from_the_web_when_this_computer_syncs(self):
        hub = self.hub
        hub.auto_web = True                    # timers on, against the loopback fake
        hub.db.set_metadata('auto_number', '0')
        commands.run(hub, 'register.enable', {'on': True})
        hub.scanner.add(simulate.FakeCube('/dev/sim.cube-new', NEW_MAC))
        c = hub.station_session().controller
        ok = tick_until(hub, lambda: hub.regflow.mac == NEW_MAC and hub.regflow.armed and c.phase == 'identifying'
                        and (c.active or {}).get('mac') == NEW_MAC, timeout=15)
        self.assertTrue(ok, hub.regflow.snapshot())
        self.assertEqual(self.server.claims.get(hub.regflow.number), NEW_MAC, 'the web handed out this number')
        self.assertEqual(hub.regflow.number_new, 'assigned')

class SimulationNeverSyncsTests(unittest.TestCase):
    """A simulated console must never reach the real web inventory (it once uploaded fake cubes)."""

    def setUp(self):
        self.hub = simulated_hub()

    def tearDown(self):
        self.hub.shutdown(force=True)

    def test_client_refuses_in_simulation(self):
        import jobs.sync as sync_jobs
        with self.assertRaises(sync_jobs.SimulatedWeb):
            sync_jobs.client(self.hub)


if __name__ == '__main__':
    unittest.main()
