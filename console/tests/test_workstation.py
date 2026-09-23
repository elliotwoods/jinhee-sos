"""The Workstation session: superset routing, leases and the show verbs, against the simulated boards.

One session kind for a legacy General Radio, a legacy pairing station and the Workstation firmware; what
is live comes from the hello, and a legacy station must see no new traffic."""
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
    """A legacy General Radio (general-radio-1.2.0) on the Workstation session."""

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

    def test_identified_as_workstation_and_recorded(self):
        self.assertEqual(self.session.kind, 'workstation')
        self.assertEqual(classify(self.board.probe_lines())[0], 'workstation')
        run_ticks(self.hub, 3)
        self.assertIn(self.board.mac, self.hub.inventory_cache['workstations'])
        self.assertEqual(self.hub.db.roles().get(self.board.mac), 'excluded')
        snap = self.session.snapshot()
        self.assertEqual(snap['roles'], ['cube', 'zone', 'pool', 'preshow'])
        self.assertTrue(snap['dongle'])
        self.assertEqual((snap['label'], snap['family']), ('General Radio', 'general'))
        self.assertEqual(snap['capabilities'], dict(reader=False, relay=True, show_verbs=True, show_relay=True, pool=True, preshow=True, live=True))

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
        self.assertEqual(self.hub.sections['show']['via'], 'workstation')

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


class WorkstationBesideLegacyTests(unittest.TestCase):
    """A legacy pairing station, a Workstation and a General Radio plugged in together, in that order."""

    def setUp(self):
        simulate.BOARDS.clear()
        from hub import Hub
        self.hub = Hub(support.temp_database(), api_port=0, simulate=True)
        simulate.install(self.hub, scenario='empty')
        self.hub.boot()
        plate = simulate.FakeZone('/dev/sim.preshow1', '14:63:93:C0:EC:14')
        self.station = simulate.FakeStation('/dev/sim.station', '30:ED:A0:5B:6D:D8', cubes=[CUBE], zones=[plate])
        self.workstation = simulate.FakeWorkstation('/dev/sim.workstation', '02:AA:BB:CC:DD:F0', cubes=[CUBE], zones=[plate],
                                                    bridge=BRIDGE, clock=self.hub.clock)
        self.radio = simulate.FakeGeneralRadio('/dev/sim.radio', '02:AA:BB:CC:DD:EE', cubes=[CUBE], zones=[plate], central=CENTRAL,
                                               clock=self.hub.clock)
        for board in (self.station, self.workstation, self.radio):
            self.hub.scanner.add(board)
        self.assertTrue(tick_until(self.hub, lambda: all(b.mac in self.hub.sessions and self.hub.sessions[b.mac].controller.connected
                                                         for b in (self.station, self.workstation, self.radio))))

    def tearDown(self):
        self.hub.shutdown(force=True)

    def session(self, board):
        return self.hub.sessions[board.mac]

    def test_every_board_is_the_workstation_role_and_reports_itself(self):
        for board, label, family, reader in ((self.station, 'Pairing station', 'pairing', True),
                                             (self.workstation, 'Workstation', 'workstation', True),
                                             (self.radio, 'General Radio', 'general', False)):
            snap = self.session(board).snapshot()
            self.assertEqual((snap['kind'], snap['label'], snap['family'], snap['capabilities']['reader']),
                             ('workstation', label, family, reader), board.port)
            self.assertEqual(self.hub.device_by_id(board.mac).role, 'workstation')
        self.assertEqual(classify(self.workstation.probe_lines())[0], 'workstation')
        self.assertEqual(self.session(self.workstation).snapshot()['roles'], ['cube', 'zone', 'pool', 'preshow', 'nfc'])
        self.assertEqual(self.session(self.station).snapshot()['capabilities'],
                         dict(reader=True, relay=True, show_verbs=False, show_relay=False, pool=False, preshow=False, live=False))
        self.assertTrue(self.session(self.workstation).snapshot()['capabilities']['live'])

    def test_primary_is_the_earliest_reader_link(self):
        self.assertIs(self.hub.station_session(), self.session(self.station))
        self.assertIs(self.hub.relay_session(), self.session(self.station))
        self.assertIs(self.hub.show_session(), self.session(self.workstation), 'the first link with the cube role')
        self.assertIs(self.hub.station_session(self.radio.mac), self.session(self.radio))
        self.hub.close_session(self.session(self.station), 'test')
        self.assertIs(self.hub.station_session(), self.session(self.workstation))
        run_ticks(self.hub, 3)
        self.assertIn(self.workstation.mac, self.hub.inventory_cache['workstations'])
        self.assertNotIn(self.station.mac, self.hub.inventory_cache['workstations'], 'a legacy station is never recorded')

    def test_legacy_station_sees_no_new_traffic(self):
        run_ticks(self.hub, 70, dt=0.1)   # past the 5 s status period
        self.assertNotIn('status', self.station.sent)
        self.assertIn('status', self.workstation.sent)
        self.assertLessEqual(set(self.station.sent), {'hello', 'ping', 'discover', 'zone_send'})
        with self.assertRaisesRegex(ValueError, 'Pairing station has no cube role; connect a Workstation'):
            commands.run(self.hub, 'radio.set_zone', dict(device=self.station.mac, mac=CUBE, zone=4))
        with self.assertRaisesRegex(ValueError, 'no pool role'):
            commands.run(self.hub, 'radio.pool', dict(device=self.station.mac, member=3))
        with self.assertRaisesRegex(ValueError, 'no preshow role'):
            commands.run(self.hub, 'radio.preshow', dict(device=self.station.mac, point=1, on=True))
        self.assertNotIn('set_zone', self.station.sent)
        # Its own verbs still route to it by device.
        commands.run(self.hub, 'pairing.discover', dict(device=self.station.mac))
        self.assertEqual(self.station.sent[-1], 'discover')

    def test_reader_verbs_work_on_the_workstation(self):
        session = self.session(self.workstation)
        self.assertTrue(session.has_reader and session.controller.reader_ok)
        self.workstation.sent.clear()
        commands.run(self.hub, 'station.nfc_status', dict(device=self.workstation.mac))
        run_ticks(self.hub, 2)
        self.assertIn('nfc_status', self.workstation.sent)
        self.assertEqual(session.hello.get('nfc_diagnostic', {}).get('i2c_status'), 0)
        # and the radio verbs on the same link
        commands.run(self.hub, 'radio.set_zone', dict(device=self.workstation.mac, mac=CUBE, zone=4))
        run_ticks(self.hub, 2)
        self.assertIn('set_zone', self.workstation.sent)

    def test_tag_on_the_reader_is_read_back_and_resolved(self):
        session = self.session(self.workstation)
        uid = '04:A2:2B:1C:53:80:01'
        self.hub.db.reserve(CUBE, source='test')
        self.hub.db.rename(CUBE, 44)
        self.hub.db.prepare(CUBE, uid, take_over=True)
        self.assertIsNone(session.snapshot()['reader_tag']['uid'])
        self.workstation.sent.clear()
        self.workstation.place_tag(uid)
        self.assertTrue(tick_until(self.hub, lambda: session.reader['uid'] == uid))
        self.assertIn('nfc_poll', self.workstation.sent, 'tag_state carries no UID; the reader is asked for it')
        snap = session.snapshot()
        self.assertEqual((snap['reader_tag']['present'], snap['reader_history'][0]['cube_id'], snap['reader_history'][0]['mac']),
                         (True, 44, CUBE))
        self.assertTrue(logs(self.hub, f'Tag {uid} on the Workstation reader: cube #44'))
        run_ticks(self.hub, 20, dt=0.1)
        self.assertEqual(self.workstation.sent.count('nfc_poll'), 1, 'asked once, not every tick')
        self.workstation.lift_tag()
        run_ticks(self.hub, 2)
        self.assertEqual((session.reader['present'], session.reader['uid']), (False, None))
        self.assertIsNotNone(session.reader_history[0]['held_ms'])
        # An unknown tag is shown as such; nothing is written to the inventory.
        self.workstation.place_tag('04:11:22:33')
        self.assertTrue(tick_until(self.hub, lambda: session.reader['uid'] == '04:11:22:33'))
        self.assertEqual((session.reader_history[0]['mac'], session.reader_history[0]['cube_id']), (None, None))
        self.assertNotIn('nfc_seen', [r[0] for r in self.hub.db.conn.execute('SELECT action FROM events')])
        # The primary legacy station's reader works the same way (nfc_poll is a station command).
        station = self.session(self.station)
        self.station.place_tag(uid)
        self.assertTrue(tick_until(self.hub, lambda: station.reader['uid'] == uid))
        self.assertEqual(station.snapshot()['reader_history'][0]['cube_id'], 44)

    def test_flash_on_tag_read(self):
        session = self.session(self.workstation)
        uid = '04:A2:2B:1C:53:80:01'
        self.hub.db.reserve(CUBE, source='test')
        self.hub.db.rename(CUBE, 44)
        self.hub.db.prepare(CUBE, uid, take_over=True)
        received, handle = [], self.workstation.handle_json
        self.workstation.handle_json = lambda m: (received.append(m), handle(m))[1]
        identifies = lambda: [m for m in received if m.get('cmd') == 'identify']
        # Off by default: a tag on the reader is only shown.
        self.assertFalse(session.snapshot()['reader_flash'])
        self.workstation.place_tag(uid)
        self.assertTrue(tick_until(self.hub, lambda: session.reader['uid'] == uid))
        run_ticks(self.hub, 5)
        self.assertEqual(identifies(), [])
        self.workstation.lift_tag()
        run_ticks(self.hub, 2)
        # On: each placement flashes the owning cube once, for two seconds.
        commands.run(self.hub, 'radio.reader_flash', dict(device=self.workstation.mac, on=True))
        self.workstation.place_tag(uid)
        self.assertTrue(tick_until(self.hub, lambda: len(identifies()) == 1))
        self.assertEqual((identifies()[0]['mac'], identifies()[0]['duration_ms']), (CUBE, 2000))
        self.assertEqual(session.snapshot()['reader_flash_last']['result'], 'flashed (pending tag)')
        self.assertTrue(logs(self.hub, 'Flashing cube #44 for 2 s'))
        # The identify's synthetic tag_state and a flicker while it runs do not flash the cube again.
        self.workstation.emit(dict(event='tag_state', id='', present=False))
        self.workstation.emit(dict(event='tag_state', id='', present=True))
        run_ticks(self.hub, 5)
        commands.run(self.hub, 'radio.stop', dict(device=self.workstation.mac))
        run_ticks(self.hub, 20, dt=0.1)
        self.assertEqual(len(identifies()), 1)
        # Lifted while idle and placed again: a second flash.
        self.workstation.lift_tag()
        run_ticks(self.hub, 2)
        self.workstation.place_tag(uid)
        self.assertTrue(tick_until(self.hub, lambda: len(identifies()) == 2))
        commands.run(self.hub, 'radio.stop', dict(device=self.workstation.mac))
        run_ticks(self.hub, 2)
        self.workstation.lift_tag()
        run_ticks(self.hub, 2)
        # An unknown tag sends nothing.
        self.workstation.place_tag('04:11:22:33')
        self.assertTrue(tick_until(self.hub, lambda: session.reader['uid'] == '04:11:22:33'))
        self.assertEqual((len(identifies()), session.reader_flash_last['result']), (2, 'unknown tag'))
        self.assertNotIn('nfc_seen', [r[0] for r in self.hub.db.conn.execute('SELECT action FROM events')])
        # Off again; a board without a reader refuses it.
        commands.run(self.hub, 'radio.reader_flash', dict(device=self.workstation.mac, on=False))
        self.assertFalse(session.reader_flash)
        with self.assertRaises(Exception):
            commands.run(self.hub, 'radio.reader_flash', dict(device=self.radio.mac, on=True))

    def test_identify_does_not_invent_a_tag(self):
        session = self.session(self.workstation)
        self.hub.db.reserve(CUBE, source='test')
        commands.run(self.hub, 'radio.identify', dict(device=self.workstation.mac, macs=[CUBE]))
        self.workstation.emit(dict(event='tag_state', id='', present=True))   # the firmware's synthetic clear-interval start
        run_ticks(self.hub, 5)
        self.assertFalse(session.reader['present'])
        self.assertNotIn('nfc_poll', self.workstation.sent, 'nfc_poll is refused while the reader is identifying')
        commands.run(self.hub, 'radio.stop', dict(device=self.workstation.mac))
        run_ticks(self.hub, 2)

    def test_general_radio_has_no_reader_view(self):
        self.assertIsNone(self.session(self.radio).snapshot()['reader_tag'])

    def test_pool_beacon_from_a_central_is_kept(self):
        session = self.session(self.radio)
        commands.run(self.hub, 'radio.status', dict(device=self.radio.mac))
        run_ticks(self.hub, 2)
        self.assertEqual(session.snapshot()['pool_beacon']['mac'], CENTRAL)
        session.pool_set(3, radio_id=2)
        run_ticks(self.hub, 2)
        self.assertEqual((session.pool['unicast'], session.pool['radio_mask']), (True, 2))


class RadioAdvisorTests(unittest.TestCase):
    def sections(self, **session):
        s = dict(kind='workstation', connected=True, fatal=None, pool_held=0, preshow_held=0, pool={}, preshow={}, last_rx=fixtures.NOW)
        s.update(session)
        return fixtures.sections(devices=[dict(id='r1', port='/dev/cu.radio', role='workstation', mac='02:AA:BB:CC:DD:EE')],
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

    def test_legacy_station_session_fires_nothing(self):
        # A pairing station snapshot has no fatal and holds nothing: same kind, no radio cards.
        out = advisor.evaluate(self.sections(label='Pairing station', pool_held=0, preshow_held=0), fixtures.NOW, ())
        self.assertFalse([s for s in out if s['rule'].startswith('radio.')])


class BuildJobTests(unittest.TestCase):
    def test_workstation_firmware_builds_the_workstation(self):
        hub = simulated_hub('empty', seed=False)
        try:
            with patch.object(build_jobs.dongle, 'build') as build:
                job = build_jobs.dongle_build_job(hub, 'workstation')
                self.assertIn('workstation', job.title.lower())
                self.assertTrue(tick_until(hub, lambda: job.state in ('done', 'failed'), timeout=5))
            self.assertEqual(job.state, 'done')
            self.assertEqual(build.call_args.args[1].version, 'workstation-1.0.0')
            for gone in ('general', 'dongle', 'nonsense'):
                with self.assertRaises(ValueError):
                    build_jobs.dongle_build_job(hub, gone)
        finally:
            hub.shutdown(force=True)


if __name__ == '__main__':
    unittest.main()
