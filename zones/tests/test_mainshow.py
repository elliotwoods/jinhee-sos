"""Mainshow Controller app: session logic with a fake link and clock, cube lookup, and the real Tk window."""
import importlib.util
import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / 'pairing_station'))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mainshow = load('mainshow_app', ROOT / 'mainshow/app.py')
from database import Database  # noqa: E402

HELLO = dict(event='hello', id='', firmware=mainshow.FIRMWARE, mac='AC:27:6E:82:68:54', channel=2, radio_ok=True,
             button_pin=9, trigger_pin=3, lockout_ms=3000, rearm_ms=1000, last_show_id=0, shows=0)
CUBE = 'AC:27:6E:80:00:D0'


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.sent, self.logs, self.clock = [], [], Clock()
        self.session = mainshow.Session(self.sent.append, self.logs.append, self.clock)

    def connect(self, **changes):
        self.session.open()
        self.assertEqual(self.sent[-1]['cmd'], 'hello')
        self.session.handle(dict(HELLO, **changes))

    def test_refuses_until_a_mainshow_controller_answers(self):
        with self.assertRaisesRegex(ValueError, 'Connect'):
            self.session.set_zone(CUBE, 4, '#44')
        self.connect(firmware='nct-pairing-1.7-zones', zones=1)
        self.assertFalse(self.session.usable())
        self.assertIn('Flash controller firmware', self.session.problem)
        with self.assertRaises(ValueError):
            self.session.trigger('broadcast')
        self.connect(channel=6)
        self.assertIn('channel 6', self.session.problem)
        self.connect()
        self.assertTrue(self.session.usable())
        self.assertIsNone(self.session.problem)

    def test_ready_trigger_idle_and_wording(self):
        self.connect()
        request = self.session.set_zone(CUBE, 4, '#44')
        self.assertEqual({k: v for k, v in self.sent[-1].items() if k != 'id'}, dict(cmd='set_zone', mac=CUBE, zone=4))
        self.assertTrue(self.session.busy())
        with self.assertRaisesRegex(ValueError, 'previous command'):
            self.session.trigger(CUBE, '#44')
        self.session.handle(dict(event='zone_sent', id=request, mac=CUBE, zone=4, status='delivered'))
        self.assertFalse(self.session.busy())
        self.assertIn('#44 → mainshow: delivered (radio ACK only', self.logs[-1])

        request = self.session.trigger(CUBE, '#44')
        self.assertEqual(self.sent[-1]['target'], CUBE)
        self.session.handle(dict(event='show_start', id=request, source='usb', show_id=77, target=CUBE, sent=5,
                                 repeats=5, delivered=5))
        self.assertIn('#44: 5/5 delivered (radio ACK); starts only if the cube is mainshow-ready', self.logs[-1])
        self.clock.now += 40
        elapsed, segment = self.session.show_state()
        self.assertEqual((elapsed, segment), (40, 'White blink, 1 Hz'))

        self.session.forget_show('02:00:00:00:00:99')  # idling another cube leaves this show running
        self.assertIsNotNone(self.session.show)
        request = self.session.set_zone(CUBE, 0, '#44')
        self.session.handle(dict(event='zone_sent', id=request, mac=CUBE, zone=0, status='unconfirmed'))
        self.assertIn('no radio ACK', self.logs[-1])
        self.session.forget_show(CUBE)
        self.assertIsNone(self.session.show_state())

    def test_physical_triggers_and_lockout_are_reported(self):
        self.connect()
        self.session.handle(dict(event='show_start', id='', source='pin', show_id=5, target='broadcast', sent=5, repeats=5))
        self.assertIn('SHOW START by the trigger input', self.logs[-1])
        self.assertIn('broadcast ×5 (no ACK)', self.logs[-1])
        self.assertEqual(self.session.show['name'], 'all cubes')
        self.session.forget_show(CUBE)  # a broadcast show keeps running when one cube is idled
        self.assertIsNotNone(self.session.show)
        self.session.handle(dict(event='locked', id='', source='button', retry_ms=2500))
        self.assertIn('locked for another 2.5 s', self.logs[-1])
        self.session.handle(dict(event='ignored', id='', source='pin', open_ms=400, rearm_ms=1000))
        self.assertIn('only 400 ms open: treated as a dropout and ignored', self.logs[-1])
        self.assertEqual(self.session.show['show_id'], 5)  # an ignored dropout is not a new show

    def test_unanswered_command_times_out_without_resend(self):
        self.connect()
        self.session.set_zone(CUBE, 4, '#44')
        count = len(self.sent)
        self.clock.now += 5
        self.assertFalse(self.session.busy())
        self.assertIn('not retried', self.logs[-1])
        self.assertEqual(len(self.sent), count)

    def test_heartbeat_and_silence(self):
        self.connect()
        self.clock.now += 1.5
        self.session.heartbeat()
        self.assertEqual(self.sent[-1]['cmd'], 'ping')
        self.clock.now += 9
        self.session.heartbeat()
        self.assertFalse(self.session.connected)
        self.assertIn('stopped answering', self.session.problem)
        self.session.heartbeat()
        self.assertEqual(self.sent[-1]['cmd'], 'hello')

    def test_timeline_matches_the_cube_firmware(self):
        source = (ROOT.parent / 'flashing_station/firmware/neocore_usb/neocore_usb.ino').read_text(encoding='utf-8')
        body = source[source.index('void updateMainShowTimeline()'):source.index('MAIN SHOW TIMELINE END')]
        import re
        ends = [int(v) for v in re.findall(r't\s*<\s*(\d+)\s*\)', body)]
        self.assertEqual(ends, [end for end, _ in mainshow.TIMELINE])
        self.assertEqual(mainshow.segment_at(0), 'Neon hold (entrance)')
        self.assertEqual(mainshow.segment_at(74100), 'Neon flash')
        self.assertTrue(mainshow.segment_at(298000).startswith('Ended'))
        self.assertEqual(mainshow.clock_text(125.9), '2:05')


class CubeLookupTests(unittest.TestCase):
    def test_find_cube(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / 'devices.sqlite3')
            try:
                first = db.rows()[0]
                mac, row = mainshow.find_cube(db, first['cube_id'])
                self.assertEqual(mac, first['mac'])
                with self.assertRaisesRegex(ValueError, 'No cube #9999'):
                    mainshow.find_cube(db, 9999)
                db.set_role(first['mac'], 'excluded')
                with self.assertRaisesRegex(ValueError, 'excluded'):
                    mainshow.find_cube(db, first['cube_id'])
            finally:
                db.close()


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()
        self.tmp.cleanup()

    def test_window_drives_the_session(self):
        port = dict(port='/dev/cu.controller', key='c', description='USB JTAG', candidate=True, serial=HELLO['mac'])
        path = Path(self.tmp.name) / 'devices.sqlite3'
        db = Database(path)
        first = db.rows()[0]
        mainshow.dongle.set_controller(db, HELLO['mac'], True)
        db.close()
        with patch.object(mainshow.dongle, 'ports', return_value=[port]):
            app = mainshow.App(self.root, path, cube=first['cube_id'])
        try:
            self.assertIn('Mainshow controller', app.port.get())
            self.assertEqual(app.cube, (first['cube_id'], first['mac']))
            app.render()
            self.assertTrue(app.ready_button.instate(['disabled']))  # nothing to talk to yet
            sent = []
            app.transport.port = MagicMock()
            app.transport.send = sent.append
            app.session.open()
            app.transport.inbox.put(dict(HELLO))
            app.transport.inbox.put(dict(event='boot_log', detail='NCT MAINSHOW CONTROLLER'))
            app.poll()
            self.assertIn('Connected', app.link_status.cget('text'))
            self.assertFalse(app.ready_button.instate(['disabled']))
            app.make_ready()
            self.assertEqual(sent[-1]['zone'], 4)
            self.assertEqual(sent[-1]['mac'], first['mac'])
            app.transport.inbox.put(dict(event='zone_sent', id=sent[-1]['id'], mac=first['mac'], zone=4, status='delivered'))
            app.poll()
            app.trigger()  # this cube only (the default): no broadcast confirmation
            self.assertEqual(sent[-1], dict(cmd='show_start', id=sent[-1]['id'], target=first['mac']))
            app.transport.inbox.put(dict(event='show_start', id=sent[-1]['id'], source='usb', show_id=9,
                                         target=first['mac'], sent=5, repeats=5, delivered=5))
            app.poll()
            self.assertEqual(app.segment_label.cget('text'), 'Neon hold (entrance)')
            app.cube_var.set('9999')
            with self.assertRaisesRegex(ValueError, 'No cube'):
                app.make_ready()
            self.assertIsNone(app.cube)
        finally:
            app.closing = True
            app.transport.port = None
            app.db.close()


if __name__ == '__main__':
    unittest.main()
