"""Workstation client and command line with a fake serial link: id matching, event routing, the
verbs' JSON, cube-number resolution, leases released on exit, and the flash entry point. The hello
fixture is a legacy General Radio 1.0.0, driven by the same client; the Workstation hello is checked
beside it, and the old general_radio module name still loads."""
import importlib.util
import queue
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / 'pairing_station'))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gr = load('workstation', ROOT / 'tools/workstation.py')
from database import Database  # noqa: E402
import zonedb  # noqa: E402

MAC = 'AC:27:6E:82:68:54'
CUBE = 'AC:27:6E:80:00:D0'
HELLO = dict(event='hello', protocol=1, firmware='general-radio-1.0.0', zones=1, mac=MAC, channel=2, radio_ok=True, nfc_ok=False,
             roles=['cube', 'zone', 'pool', 'preshow'], pool=dict(armed=False, member=0), preshow=dict(armed=False, point=0))
WS_HELLO = dict(HELLO, firmware='workstation-1.0.0', nfc_ok=True, show=1, roles=['cube', 'zone', 'pool', 'preshow', 'nfc'])
# What the pairing-station relay says: no roles, no pool/preshow state.
RELAY_HELLO = {k: v for k, v in HELLO.items() if k not in ('roles', 'pool', 'preshow')} | dict(firmware='nct-pairing-1.8-zones')


class Clock:
    """Advances a little on every read, so a reply that never comes times out without real waiting."""

    def __init__(self, step=0.05):
        self.now, self.step = 100.0, step

    def __call__(self):
        self.now += self.step
        return self.now


class FakeTransport:
    """Scripted dongle: `replies(message)` returns the events to queue for each command sent."""

    def __init__(self, replies):
        self.inbox = queue.Queue()
        self.sent, self.replies, self.port, self.opened, self.closed = [], replies, object(), None, False

    def open(self, path):
        self.opened = path

    def send(self, message):
        self.sent.append(message)
        for event in self.replies(message) or ():
            self.inbox.put(event)

    def close(self):
        self.closed = True


def echo(message, **fields):
    return dict(event=message['cmd'] if message['cmd'] not in ('hello', 'status') else message['cmd'], id=message['id'], **fields)


def scripted(message):
    cmd = message['cmd']
    if cmd in ('hello', 'status'):
        return [dict(HELLO, event=cmd, id=message['id'])]
    if cmd == 'ping':
        return [dict(event='pong', id=message['id'])]
    if cmd == 'discover':
        return [dict(event='radio', id='', mac='FF:FF:FF:FF:FF:FF', type=1, status='delivered'),
                dict(event='discover_sent', id=message['id']),
                dict(event='device', id='', mac='ac:27:6e:80:00:d0'), dict(event='device', id='', mac=CUBE),
                dict(event='device', id='', mac='01:00:5E:00:00:01')]
    if cmd == 'zone_send':
        return [dict(event='zone_sent', id=message['id'], mac=message['mac'], kind=0x20, status='delivered'),
                dict(event='zone_frame', id='', mac='14:63:93:c0:ec:14', kind=0x21, rssi=-61, hex=STATUS_HEX),
                dict(event='zone_frame', id='', mac='14:63:93:C0:EC:14', kind=0x26, hex='4E5A012600000000300000')]
    if cmd == 'set_zone':
        return [dict(event='zone_sent', id=message['id'], mac=message['mac'], zone=message['zone'], status='delivered', repeats=3)]
    if cmd == 'show_start':
        return [dict(event='show_start', id=message['id'], source='usb', show_id=7, target=message['target'], sent=5, repeats=5)]
    if cmd == 'pool':
        return [dict(event='pool_state', id=message['id'], armed=message['member'] != 0, member=message['member'])]
    if cmd == 'preshow':
        if message['point'] == 4:
            return [dict(event='error', id=message['id'], detail='Point 2 is still ON; turn it off first')]
        return [dict(event='preshow_state', id=message['id'], armed=True, point=message['point'], state=message['state'])]
    if cmd == 'led_test':
        return [dict(event='led_test', id=message['id'], on=bool(message['on']), pin=10)]
    return [dict(event='error', id=message['id'], detail='Unknown command')]


STATUS_HEX = zonedb.STATUS.pack(b'NZ', 1, zonedb.ZONE_STATUS, 0, 1, 2, b'Preshow 2'.ljust(16, b'\0'),
                                b'preshow-3.4.0'.ljust(16, b'\0'), 32, 30, 0xABCD, 0, 0, 0, 5, 1, 1, 0, 0, 2, 1, 0).hex().upper()


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.link = FakeTransport(scripted)
        self.radio = gr.GeneralRadio(self.link, Clock(), self.events.append)

    def test_open_hello_and_id_matching(self):
        info = self.radio.open('/dev/cu.fake')
        self.assertEqual(self.link.opened, '/dev/cu.fake')
        self.assertEqual((info['firmware'], self.radio.general, self.radio.firmware), ('general-radio-1.0.0', True, 'general-radio-1.0.0'))
        self.assertEqual(self.link.sent[-1]['cmd'], 'hello')
        self.assertEqual(len(self.link.sent[-1]['id']), 12)
        # A stray event with another id goes to on_event; the reply is the one with our id.
        self.link.inbox.put(dict(event='zone_frame', id='', mac='x', kind=0x21, hex='00'))
        self.assertEqual(self.radio.ping()['event'], 'pong')
        self.assertEqual([e['event'] for e in self.events], ['zone_frame'])
        self.radio.close()
        self.assertTrue(self.link.closed)

    def test_error_reply_raises_and_silence_times_out_without_resend(self):
        self.radio.hello()
        with self.assertRaisesRegex(gr.RadioError, 'Unknown command'):
            self.radio.request('dance')
        silent = gr.GeneralRadio(FakeTransport(lambda m: []), Clock(step=1.0))
        with self.assertRaisesRegex(gr.RadioError, 'No reply to hello'):
            silent.hello()
        self.assertEqual(len(silent.transport.sent), 1)
        dead = gr.GeneralRadio(FakeTransport(lambda m: [dict(event='disconnected', detail='gone')]), Clock())
        with self.assertRaisesRegex(gr.RadioError, 'disconnected'):
            dead.hello()

    def test_discover_collects_unicast_macs(self):
        self.radio.hello()
        self.assertEqual(self.radio.discover(wait=0.3), [CUBE])
        self.assertTrue(any(e['event'] == 'radio' for e in self.events))  # the pairing events still reach on_event

    def test_zone_query_parses_status_frames(self):
        self.radio.hello()
        self.radio.clock.now += 5  # the heartbeat is due: the ping inside collect() must not swallow the replies
        zones = self.radio.zone_query(wait=0.3)
        query = [m for m in self.link.sent if m['cmd'] == 'zone_send'][-1]
        self.assertEqual((query['mac'], zonedb.frame_kind(bytes.fromhex(query['hex']))), (gr.BROADCAST, zonedb.ZONE_QUERY))
        self.assertEqual(self.link.sent[-1]['cmd'], 'ping')
        self.assertEqual(len(zones), 1)
        self.assertEqual((zones[0]['mac'], zones[0]['rssi'], zones[0]['name'], zones[0]['db_version'], zones[0]['point_id']),
                         ('14:63:93:C0:EC:14', -61, 'Preshow 2', 32, 2))
        self.assertEqual([e['kind'] for e in self.events if e['event'] == 'zone_frame'], [0x26])  # settings frame passed on

    def test_mainshow_verbs(self):
        self.radio.hello()
        self.assertEqual(self.radio.set_zone(CUBE, 4)['status'], 'delivered')
        self.assertEqual({k: v for k, v in self.link.sent[-1].items() if k != 'id'}, dict(cmd='set_zone', mac=CUBE, zone=4))
        self.radio.set_zone('broadcast', 0)
        self.assertEqual(self.link.sent[-1]['mac'], 'broadcast')
        self.radio.set_zone(gr.BROADCAST, 0)
        self.assertEqual(self.link.sent[-1]['mac'], 'broadcast')
        with self.assertRaisesRegex(gr.RadioError, 'Zone must be 0-4'):
            self.radio.set_zone(CUBE, 5)
        self.assertEqual(self.radio.show_start()['target'], 'broadcast')
        self.assertEqual(self.radio.show_start(CUBE)['target'], CUBE)

    def test_pool_and_preshow_are_released(self):
        self.radio.hello()
        self.assertEqual(self.radio.pool(5)['member'], 5)
        self.assertEqual({k: v for k, v in self.link.sent[-1].items() if k != 'id'}, dict(cmd='pool', member=5))
        self.radio.pool(6, radio_id=3)
        self.assertEqual(self.link.sent[-1]['radio_id'], 3)
        self.assertEqual(self.radio.preshow(2, True)['point'], 2)
        self.assertEqual({k: v for k, v in self.link.sent[-1].items() if k != 'id'}, dict(cmd='preshow', point=2, state=1))
        with self.assertRaisesRegex(gr.RadioError, 'still ON'):
            self.radio.preshow(4, True)
        self.assertTrue(self.radio.pool_held and self.radio.preshow_held == 2)
        count = len(self.link.sent)
        self.link.inbox.put(dict(event='preshow_ack', id='', point=2, state=1, seq=1, ms=40, applied=True))
        self.radio.keepalive(2.5)
        self.assertIn('preshow_ack', [e['event'] for e in self.events])  # what arrives while holding is reported
        pings = [m for m in self.link.sent[count:] if m['cmd'] == 'ping']
        self.assertGreaterEqual(len(pings), 2)
        tail = [{k: v for k, v in m.items() if k != 'id'} for m in self.link.sent[-2:]]
        self.assertEqual(tail, [dict(cmd='pool', member=0), dict(cmd='preshow', point=2, state=0)])
        self.assertFalse(self.radio.pool_held or self.radio.preshow_held)
        self.radio.release()  # nothing held: nothing sent
        self.assertEqual(len(self.link.sent), count + len(pings) + 2)

    def test_keepalive_releases_on_interrupt(self):
        self.radio.hello()
        self.radio.preshow(1, True)
        with patch.object(self.radio, 'collect', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.radio.keepalive(None)
        self.assertEqual({k: v for k, v in self.link.sent[-1].items() if k != 'id'}, dict(cmd='preshow', point=1, state=0))

    def test_roles_need_the_workstation_or_general_firmware(self):
        relay = gr.Workstation(FakeTransport(lambda m: [dict(RELAY_HELLO, id=m['id'])]), Clock())
        relay.hello()
        self.assertFalse(relay.general)
        self.assertEqual(relay.roles, [])
        for call in (lambda: relay.pool(1), lambda: relay.preshow(1, 1), lambda: relay.set_zone(CUBE, 0), lambda: relay.show_start()):
            with self.assertRaisesRegex(gr.RadioError, 'Workstation .* or the general radio firmware'):
                call()
        controller = gr.Workstation(FakeTransport(lambda m: [dict(RELAY_HELLO, id=m['id'], firmware='mainshow-1.2.0')]), Clock())
        controller.hello()
        with self.assertRaisesRegex(gr.RadioError, 'general radio firmware'):
            controller.pool(1)
        controller.set_zone(CUBE, 4)  # the controller answers this one
        self.assertEqual(controller.transport.sent[-1]['cmd'], 'set_zone')
        relay.status()  # falls back to hello on a plain relay (no `roles`, no status verb)
        self.assertEqual(relay.transport.sent[-1]['cmd'], 'hello')

    def test_workstation_hello_answers_every_verb(self):
        radio = gr.Workstation(FakeTransport(lambda m: scripted(m) if m['cmd'] not in ('hello', 'status')
                                             else [dict(WS_HELLO, event=m['cmd'], id=m['id'])]), Clock())
        info = radio.hello()
        self.assertEqual((info['firmware'], radio.general, radio.roles), ('workstation-1.0.0', True, ['cube', 'zone', 'pool', 'preshow', 'nfc']))
        self.assertEqual(radio.set_zone(CUBE, 4)['status'], 'delivered')
        self.assertEqual(radio.show_start()['target'], 'broadcast')
        self.assertEqual(radio.pool(3)['member'], 3)
        self.assertEqual(radio.preshow(1, True)['point'], 1)
        radio.status()
        self.assertEqual(radio.transport.sent[-1]['cmd'], 'status')
        # A board of an unknown name is judged by its roles too, never by the firmware prefix.
        odd = gr.Workstation(FakeTransport(lambda m: [dict(WS_HELLO, event='hello', id=m['id'], firmware='bench-0.1', roles=['cube', 'pool'])]), Clock())
        odd.hello()
        self.assertFalse(odd.general)
        odd.set_zone(CUBE, 0)
        odd.pool(1)
        with self.assertRaisesRegex(gr.RadioError, 'preshow needs'):
            odd.preshow(1, True)

    def test_general_radio_module_is_an_alias(self):
        alias = load('general_radio', ROOT / 'tools/general_radio.py')
        self.assertIs(alias.GeneralRadio, alias.Workstation)
        self.assertIs(alias.flash_general, alias.flash_workstation)
        self.assertTrue(callable(alias.main) and issubclass(alias.RadioError, RuntimeError))
        radio = alias.GeneralRadio(FakeTransport(scripted), Clock())
        self.assertEqual(radio.hello()['firmware'], 'general-radio-1.0.0')
        self.assertTrue(radio.general)


class TargetTests(unittest.TestCase):
    def test_resolve_target(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / 'devices.sqlite3')
            try:
                first = db.rows()[0]
                self.assertEqual(gr.resolve_target(db, 'broadcast'), 'broadcast')
                self.assertEqual(gr.resolve_target(db, 'ac:27:6e:80:00:d0'), CUBE)
                self.assertEqual(gr.resolve_target(db, str(first['cube_id'])), first['mac'])
                self.assertEqual(gr.resolve_target(db, f'#{first["cube_id"]}'), first['mac'])
                with self.assertRaisesRegex(gr.RadioError, 'No cube #9999'):
                    gr.resolve_target(db, '9999')
                with self.assertRaisesRegex(gr.RadioError, 'not "broadcast"'):
                    gr.resolve_target(db, 'cube')
                db.set_role(first['mac'], 'excluded')
                with self.assertRaisesRegex(gr.RadioError, 'excluded'):
                    gr.resolve_target(db, str(first['cube_id']))
            finally:
                db.close()


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / 'devices.sqlite3')
        self.link = FakeTransport(scripted)
        self.radio = gr.GeneralRadio(self.link, Clock())
        self.radio.hello()
        self.out = []

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def main(self, *argv):
        return gr.main(['--port', '/dev/cu.fake', *argv], radio=self.radio, db=self.db, out=self.out.append)

    def commands(self):
        return [{k: v for k, v in m.items() if k != 'id'} for m in self.link.sent]

    def test_commands_become_requests(self):
        first = self.db.rows()[0]
        self.assertEqual(self.main('set-zone', str(first['cube_id']), '4'), 0)
        self.assertIn(dict(cmd='set_zone', mac=first['mac'], zone=4), self.commands())
        self.assertEqual(self.main('set-zone', 'broadcast', '0'), 0)
        self.assertIn(dict(cmd='set_zone', mac='broadcast', zone=0), self.commands())
        self.assertEqual(self.main('show-start'), 0)
        self.assertIn(dict(cmd='show_start', target='broadcast'), self.commands())
        self.assertEqual(self.main('pool', '7', '--radio-id', '2'), 0)
        self.assertIn(dict(cmd='pool', member=7, radio_id=2), self.commands())
        self.assertEqual(self.main('preshow', '3', 'on', '--hold', '0.2'), 0)
        self.assertEqual(self.commands()[-1], dict(cmd='preshow', point=3, state=0))  # held, then turned off
        self.assertEqual(self.main('discover', '--wait', '0.2'), 0)
        self.assertIn('"cubes": ["AC:27:6E:80:00:D0"]', self.out[-1])
        self.assertEqual(self.main('zones', '--wait', '0.2'), 0)
        self.assertIn('"Preshow 2"', self.out[-1])
        self.assertEqual(self.main('hello'), 0)
        self.assertIn('general-radio-1.0.0', self.out[-1])
        self.assertFalse(self.link.closed, 'an injected radio is left open')

    def test_bad_target_is_an_error_exit(self):
        self.assertEqual(self.main('set-zone', '9999', '0'), 1)
        self.assertFalse(any(m['cmd'] == 'set_zone' for m in self.link.sent))
        with self.assertRaises(SystemExit):
            self.main('set-zone', str(self.db.rows()[0]['cube_id']), '5')

    def test_flash_uses_the_dongle_pipeline(self):
        port = dict(port='/dev/cu.fake', key='k', candidate=True, serial=MAC)
        with patch.object(gr.dongle, 'ports', return_value=[port]), patch.object(gr.dongle, 'flash', return_value=MAC) as flash, \
                patch.object(gr, 'DATA', Path(self.tmp.name)):
            self.assertEqual(gr.main(['--port', '/dev/cu.fake', '--database', str(self.db.path), 'flash'], out=self.out.append), 0)
        self.assertEqual(flash.call_args.kwargs, dict(firmware=gr.dongle.WORKSTATION, backup='always'))
        self.assertEqual(flash.call_args.args[0], port)
        self.assertEqual(len(flash.call_args.args[1]['cubes']), 32)  # the inventory snapshot the refusal rules need
        self.assertEqual(self.db.roles().get(MAC), 'excluded')
        self.assertIn('"flashed": "AC:27:6E:82:68:54"', self.out[-1])
        self.assertIn('"firmware": "workstation-1.0.0"', self.out[-1])
        with patch.object(gr.dongle, 'ports', return_value=[]):
            self.assertEqual(gr.main(['--port', '/dev/cu.fake', '--database', str(self.db.path), 'flash'], out=self.out.append), 1)


if __name__ == '__main__':
    unittest.main()
