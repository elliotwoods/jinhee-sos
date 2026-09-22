"""The General Radio session: superset routing, leases and the show verbs, against the simulated board."""
import unittest
from unittest.mock import patch

import support
from support import run_ticks, simulated_hub, tick_until
import advisor
import commands
import simulate
from jobs import build as build_jobs
from probe import classify
from tests import fixtures

CUBE = 'A4:CF:12:34:56:78'
BRIDGE = 'AC:27:6E:83:21:C4'
CENTRAL = '02:50:4F:4F:4C:01'


def logs(hub, needle):
    return [l['text'] for l in hub.recent_logs if needle in l['text']]


class GeneralRadioTests(unittest.TestCase):
    def setUp(self):
        simulate.BOARDS.clear()
        from hub import Hub
        self.hub = Hub(support.temp_database(), api_port=0, simulate=True)
        simulate.install(self.hub, scenario='empty')
        self.hub.boot()
        self.plate = simulate.FakeZone('/dev/sim.preshow1', '14:63:93:C0:EC:14')
        self.board = simulate.FakeGeneralRadio('/dev/sim.radio', '02:AA:BB:CC:DD:EE', cubes=['A4:CF:12:34:56:78'], zones=[self.plate])
        self.hub.scanner.add(self.board)
        self.assertTrue(tick_until(self.hub, lambda: self.board.mac in self.hub.sessions))
        self.session = self.hub.sessions[self.board.mac]
        self.assertTrue(tick_until(self.hub, lambda: self.session.controller.connected))
        self.hub.db.reserve('A4:CF:12:34:56:78', source='test')
        self.hub.db.rename('A4:CF:12:34:56:78', 44)

    def tearDown(self):
        self.hub.shutdown(force=True)

    def test_identified_as_general_radio_and_recorded(self):
        self.assertEqual(self.session.kind, 'generalradio')
        self.assertEqual(classify(self.board.probe_lines())[0], 'generalradio')
        run_ticks(self.hub, 3)
        self.assertIn(self.board.mac, self.hub.inventory_cache['general_radios'])
        self.assertEqual(self.hub.db.roles().get(self.board.mac), 'excluded')
        snap = self.session.snapshot()
        self.assertEqual(snap['roles'], ['cube', 'zone', 'pool', 'preshow'])
        self.assertTrue(snap['dongle'])

    def test_station_protocol_still_works_through_it(self):
        self.assertIs(self.hub.station_session(), self.session)
        self.session.controller.discover()
        run_ticks(self.hub, 3)
        self.assertIn('A4:CF:12:34:56:78', self.session.controller.discovered)
        self.session.zones.query()
        run_ticks(self.hub, 3)
        self.assertTrue(any(z['mac'] == self.plate.mac for z in self.session.zones.zone_rows()))

    def test_set_zone_reply_is_not_swallowed_by_the_registry(self):
        failures = self.session.zones.send_failures
        commands.run(self.hub, 'radio.set_zone', dict(device=self.board.mac, mac='A4:CF:12:34:56:78', zone=4))
        run_ticks(self.hub, 3)
        self.assertEqual(self.session.zones.send_failures, failures)
        self.assertTrue(any('#44 → mainshow: delivered' in l['text'] for l in self.hub.recent_logs))
        with self.assertRaises(ValueError):
            commands.run(self.hub, 'radio.set_zone', dict(device=self.board.mac, mac='broadcast', zone=0, token='x'))

    def test_broadcast_recolour_is_destructive(self):
        self.assertEqual(commands.COMMANDS['radio.set_zone_all']['kind'], 'destructive')
        token = self.hub.confirm('radio.set_zone_all', dict(device=self.board.mac, zone=0))['token']
        commands.run(self.hub, 'radio.set_zone_all', dict(device=self.board.mac, zone=0, token=token))
        run_ticks(self.hub, 2)
        self.assertIn('set_zone', self.board.sent)
        self.assertTrue(any('every cube in range → idle: broadcast' in l['text'] for l in self.hub.recent_logs))

    def test_show_start_through_the_show_commands(self):
        self.assertIs(self.hub.show_session(), self.session)
        commands.run(self.hub, 'mainshow.trigger', dict(cube=44))
        run_ticks(self.hub, 2)
        show = self.session.snapshot()['show']
        self.assertEqual(show['target'], 'A4:CF:12:34:56:78')
        self.assertIn('Neon hold', show['segment'])
        self.assertEqual(self.hub.sections['show']['via'], 'generalradio')

    def test_pool_lamp_is_leased_by_touches(self):
        commands.run(self.hub, 'radio.pool', dict(device=self.board.mac, member=7, radio_id=2))
        run_ticks(self.hub, 2)
        self.assertEqual((self.board.pool['member'], self.board.pool['radio_id'], self.session.pool_held), (7, 2, 7))
        for _ in range(4):
            commands.run(self.hub, 'radio.pool_touch', dict(device=self.board.mac))
            run_ticks(self.hub, 2, dt=0.1)
        self.assertEqual(self.board.pool['member'], 7)
        self.assertTrue(tick_until(self.hub, lambda: self.board.pool['member'] == 0, timeout=3))   # touches stopped
        self.assertEqual(self.session.pool_held, 0)

    def test_preshow_cue_switching_and_lease(self):
        commands.run(self.hub, 'radio.preshow', dict(device=self.board.mac, point=2, on=True))
        run_ticks(self.hub, 2)
        self.assertEqual((self.board.preshow['point'], self.board.preshow['state']), (2, 1))
        with self.assertRaises(ValueError):
            self.session.preshow_set(3, True)
        self.assertTrue(tick_until(self.hub, lambda: self.board.preshow['state'] == 0, timeout=3))

    def test_stop_releases_everything(self):
        self.session.pool_set(5)
        self.session.preshow_set(1, True)
        run_ticks(self.hub, 2)
        commands.run(self.hub, 'device.stop', dict(device=self.board.mac))
        run_ticks(self.hub, 2)
        self.assertEqual((self.board.pool['member'], self.board.preshow['state']), (0, 0))

    def test_led_test_and_status(self):
        commands.run(self.hub, 'radio.led_test', dict(device=self.board.mac, on=True))
        run_ticks(self.hub, 2)
        self.assertTrue(self.board.led)
        commands.run(self.hub, 'radio.status', dict(device=self.board.mac))
        run_ticks(self.hub, 2)
        self.assertTrue(self.session.snapshot()['led_test'])

    # ---- the gaps closed on 2026-09-23 ----
    def test_colour_results_count_the_plate_style_repeats(self):
        commands.run(self.hub, 'radio.set_zone', dict(device=self.board.mac, mac=CUBE, zone=2))
        run_ticks(self.hub, 3)
        [entry] = self.session.snapshot()['colour_sends']
        self.assertEqual((entry['name'], entry['zone_name'], entry['sent'], entry['delivered']), ('#44', 'desert', 3, 3))
        self.assertFalse(logs(self.hub, 'repeat'))
        self.board.dead.add(CUBE)
        commands.run(self.hub, 'radio.set_zone', dict(device=self.board.mac, mac=CUBE, zone=0))
        run_ticks(self.hub, 3)
        [entry] = self.session.snapshot()['colour_sends']  # the new colour replaces the old entry for that cube
        self.assertEqual((entry['zone_name'], entry['sent'], entry['delivered']), ('idle', 3, 0))
        self.assertTrue(logs(self.hub, 'repeat 2 unconfirmed'))

    def test_lockout_and_show_running(self):
        for _ in range(2):
            commands.run(self.hub, 'radio.show_start', dict(device=self.board.mac, cube=CUBE))
            run_ticks(self.hub, 2)
        self.assertEqual(self.board.shows, 1)
        self.assertTrue(logs(self.hub, 'locked for another'))
        commands.run(self.hub, 'radio.status', dict(device=self.board.mac))
        run_ticks(self.hub, 2)
        self.assertTrue(self.session.snapshot()['show_running'])

    def test_bridge_acknowledges_cues_and_beacons_are_kept(self):
        self.board.bridge = BRIDGE
        self.board.preshow.update(bridge_mac=BRIDGE, unicast=True, mode='modern')
        commands.run(self.hub, 'radio.status', dict(device=self.board.mac))
        run_ticks(self.hub, 2)
        self.assertEqual(self.session.snapshot()['preshow_beacon']['mac'], BRIDGE)
        self.session.preshow_set(3, True)
        run_ticks(self.hub, 2)
        snap = self.session.snapshot()
        self.assertTrue(snap['preshow']['acked'])
        self.assertEqual((snap['recent_acks'][-1]['point'], snap['recent_acks'][-1]['applied']), (3, True))
        self.assertEqual(snap['preshow']['mode'], 'modern')
        self.assertIsNone(snap['problem'])

    def test_cue_without_a_bridge_is_reported_after_three_seconds(self):
        self.session.preshow_set(1, True)
        end = self.hub.clock() + 3.6
        while self.hub.clock() < end:
            self.session.preshow_touch()
            run_ticks(self.hub, 2, dt=0.05)
        self.assertTrue(logs(self.hub, 'not acknowledged by the bridge'))
        self.assertEqual(self.session.preshow_held, 1)  # still held; the radio keeps re-asserting

    def test_expired_leases_clear_what_this_side_holds(self):
        self.session.pool_set(5)
        self.session.preshow_set(2, True)
        run_ticks(self.hub, 2)
        self.board.expire_leases()
        run_ticks(self.hub, 2)
        self.assertEqual((self.session.pool_held, self.session.preshow_held), (0, 0))
        self.assertTrue(logs(self.hub, 'Pool lamp released by the radio'))
        self.assertTrue(logs(self.hub, 'Preshow cue dropped by the radio'))

    def test_fatal_radio_is_surfaced_and_cleared_by_a_reboot(self):
        self.session.pool_set(5)
        run_ticks(self.hub, 2)
        self.board.fail_radio()
        run_ticks(self.hub, 3)
        snap = self.session.snapshot()
        self.assertTrue(snap['fatal'] and not snap['usable'] and snap['pool_held'] == 0)
        self.assertIn('unplug and replug', snap['problem'])
        self.assertTrue(logs(self.hub, 'Radio driver stopped answering'))
        with self.assertRaisesRegex(ValueError, 'not answering'):
            self.session.set_zone(CUBE, 0)
        self.hub.rebuild_sections()
        cards = [s for s in self.hub.suggestions if s['rule'] == 'radio.fatal']
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]['actions'][0]['command'], 'device.probe')
        self.board.reboot()
        # The Controller dropped the link on `fatal`; the station heartbeat re-hellos within 3 s and the
        # board's radio_ok:true hello clears the fault.
        self.assertTrue(tick_until(self.hub, lambda: self.session.controller.connected and not self.session.fatal, timeout=6))
        self.assertTrue(self.session.snapshot()['usable'])

    def test_device_scoped_verbs(self):
        self.assertEqual(commands.COMMANDS['radio.identify']['kind'], 'hardware')
        self.assertEqual(commands.COMMANDS['radio.transmit']['kind'], 'hardware')
        for name in ('radio.discover', 'radio.stop', 'radio.preshow_release'):
            self.assertEqual(commands.COMMANDS[name]['kind'], 'safe')
        self.board.sent.clear()
        commands.run(self.hub, 'radio.discover', dict(device=self.board.mac))
        self.assertIn('discover', self.board.sent)
        commands.run(self.hub, 'radio.identify', dict(device=self.board.mac, macs=[CUBE]))
        run_ticks(self.hub, 2)
        self.assertEqual(self.board.identify['mac'], CUBE)
        commands.run(self.hub, 'radio.stop', dict(device=self.board.mac))
        run_ticks(self.hub, 2)
        self.assertIsNone(self.board.identify)
        self.hub.db.prepare(CUBE, '04:A2:2B:1C:53:80:01', take_over=True)
        commands.run(self.hub, 'radio.transmit', dict(device=self.board.mac, macs=[CUBE]))
        run_ticks(self.hub, 4)
        self.assertIn('register', self.board.sent)
        self.session.preshow_set(4, True)
        run_ticks(self.hub, 2)
        commands.run(self.hub, 'radio.preshow_release', dict(device=self.board.mac))
        run_ticks(self.hub, 2)
        self.assertEqual((self.session.preshow_held, self.board.preshow['state']), (0, 0))
        self.assertIsNone(commands.run(self.hub, 'radio.preshow_release', dict(device=self.board.mac))['request'])

    def test_rx_gain_is_accepted_through_the_radio(self):
        self.session.zones.query()
        run_ticks(self.hub, 3)
        self.board.sent.clear()
        commands.run(self.hub, 'zones.set_rx_gain', dict(mac=self.plate.mac, db=33, device=self.board.mac))
        run_ticks(self.hub, 3)
        self.assertIn('zone_send', self.board.sent)


class RadioBesideStationTests(unittest.TestCase):
    """A real pairing station and a General Radio plugged in together: the radio's own verbs stay reachable."""

    def setUp(self):
        simulate.BOARDS.clear()
        from hub import Hub
        self.hub = Hub(support.temp_database(), api_port=0, simulate=True)
        simulate.install(self.hub, scenario='empty')
        self.hub.boot()
        plate = simulate.FakeZone('/dev/sim.preshow1', '14:63:93:C0:EC:14')
        self.station = simulate.FakeStation('/dev/sim.station', '30:ED:A0:5B:6D:D8', cubes=[CUBE], zones=[plate])
        self.radio = simulate.FakeGeneralRadio('/dev/sim.radio', '02:AA:BB:CC:DD:EE', cubes=[CUBE], zones=[plate], central=CENTRAL,
                                               clock=self.hub.clock)
        for board in (self.station, self.radio):
            self.hub.scanner.add(board)
        self.assertTrue(tick_until(self.hub, lambda: all(b.mac in self.hub.sessions and self.hub.sessions[b.mac].controller.connected
                                                         for b in (self.station, self.radio))))

    def tearDown(self):
        self.hub.shutdown(force=True)

    def test_primary_link_is_the_station_but_device_routes_to_the_radio(self):
        self.assertIs(self.hub.station_session(), self.hub.sessions[self.station.mac])
        self.assertIs(self.hub.station_session(self.radio.mac), self.hub.sessions[self.radio.mac])
        self.station.sent = []
        self.radio.sent.clear()
        commands.run(self.hub, 'pairing.discover', dict(device=self.radio.mac))
        commands.run(self.hub, 'zones.query', dict(device=self.radio.mac))
        run_ticks(self.hub, 3)
        self.assertIn('discover', self.radio.sent)
        self.assertIn('zone_send', self.radio.sent)
        commands.run(self.hub, 'pairing.discover', dict())  # no device: the station, as before
        run_ticks(self.hub, 2)
        self.assertNotIn('discover', self.radio.sent[-1:])
        with self.assertRaises(ValueError):
            commands.run(self.hub, 'pairing.discover', dict(device='/dev/sim.preshow1'))

    def test_pool_beacon_from_a_central_is_kept(self):
        session = self.hub.sessions[self.radio.mac]
        commands.run(self.hub, 'radio.status', dict(device=self.radio.mac))
        run_ticks(self.hub, 2)
        self.assertEqual(session.snapshot()['pool_beacon']['mac'], CENTRAL)
        session.pool_set(3, radio_id=2)
        run_ticks(self.hub, 2)
        self.assertEqual((session.pool['unicast'], session.pool['radio_mask']), (True, 2))


class RadioAdvisorTests(unittest.TestCase):
    def sections(self, **session):
        s = dict(kind='generalradio', connected=True, fatal=None, pool_held=0, preshow_held=0, pool={}, preshow={}, last_rx=fixtures.NOW)
        s.update(session)
        return fixtures.sections(devices=[dict(id='r1', port='/dev/cu.radio', role='generalradio', mac='02:AA:BB:CC:DD:EE')],
                                 sessions={'r1': s})

    def test_fatal_card(self):
        [card] = [s for s in advisor.evaluate(self.sections(fatal='Radio completion timeout; reboot the radio'), fixtures.NOW, ())
                  if s['rule'] == 'radio.fatal']
        self.assertEqual((card['severity'], card['scope'], card['device']), ('bad', 'port:/dev/cu.radio', 'r1'))
        self.assertEqual([a['command'] for a in card['actions']], ['device.probe'])

    def test_held_without_beacon_cards(self):
        out = advisor.evaluate(self.sections(pool_held=5, pool=dict(central_mac=''), preshow_held=2, preshow=dict(mode='legacy')),
                               fixtures.NOW, ())
        cards = {s['id']: s for s in out if s['rule'] == 'radio.held_without_beacon'}
        self.assertEqual(set(cards), {'radio.held_without_beacon:port:/dev/cu.radio:pool', 'radio.held_without_beacon:port:/dev/cu.radio:preshow'})
        self.assertEqual([a['command'] for a in cards['radio.held_without_beacon:port:/dev/cu.radio:pool']['actions']], ['radio.pool_release'])
        quiet = advisor.evaluate(self.sections(pool_held=5, pool=dict(central_mac=CENTRAL), preshow_held=2, preshow=dict(mode='modern')),
                                 fixtures.NOW, ())
        self.assertFalse([s for s in quiet if s['rule'].startswith('radio.')])


class BuildJobTests(unittest.TestCase):
    def test_general_firmware_builds_the_general_radio(self):
        hub = simulated_hub('empty', seed=False)
        try:
            with patch.object(build_jobs.dongle, 'build') as build:
                job = build_jobs.dongle_build_job(hub, 'general')
                self.assertIn('general radio', job.title.lower())
                self.assertTrue(tick_until(hub, lambda: job.state in ('done', 'failed'), timeout=5))
            self.assertEqual(job.state, 'done')
            self.assertEqual(build.call_args.args[1].version, 'general-radio-1.0.0')
            with self.assertRaises(ValueError):
                build_jobs.dongle_build_job(hub, 'nonsense')
        finally:
            hub.shutdown(force=True)


if __name__ == '__main__':
    unittest.main()
