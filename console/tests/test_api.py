"""The js_api surface: never raises, always plain JSON, enforces the destructive confirmation end to end."""
import json
import threading
import unittest

import support
from support import simulated_hub
from api import Api


class ApiTests(unittest.TestCase):
    def setUp(self):
        # The hub boots and runs on its own owner thread, exactly as console/app.py starts it.
        from hub import Hub
        import simulate
        simulate.BOARDS.clear()
        self.hub = Hub(support.temp_database(), api_port=0, simulate=True)
        simulate.install(self.hub)
        self.api = Api(self.hub)
        self.hub.start_thread()
        self.assertTrue(self.wait(lambda: self.hub.booted, 15))
        self.hub.call(self.hub._sim_seed).result(timeout=5)

    def tearDown(self):
        try:
            self.hub.call(self.hub.shutdown, True).result(timeout=10)
        finally:
            self.hub.stopping.set()
            self.hub.thread.join(timeout=5)

    def test_pull_and_copy_are_json(self):
        snap = self.api.pull(None, 0)
        json.dumps(snap)
        self.assertIn('devices', snap['sections'])
        copy = self.api.get_copy()
        self.assertIn('panels', copy['copy'])
        self.assertIn('zone.update_db_usb', copy['commands'])
        self.assertEqual(copy['commands']['zone.update_db_usb']['kind'], 'hardware')

    def test_call_answers_errors_instead_of_raising(self):
        self.assertEqual(self.api.call('no.such', {})['ok'], False)
        answer = self.api.call('mainshow.trigger_all', {})
        self.assertEqual((answer['ok'], answer['kind']), (False, 'value'))
        self.assertIn('hold', answer['error'])

    def test_hardware_runs_on_one_call(self):
        self.assertTrue(self.wait(lambda: '14:63:93:C0:EC:14' in self.hub.sessions))
        answer = self.api.call('monitor.zone', dict(device='14:63:93:C0:EC:14', cube_id=12, zone=1))
        self.assertTrue(answer['ok'], answer)

    def test_confirm_returns_a_token(self):
        answer = self.api.confirm('mainshow.trigger_all', {})
        self.assertTrue(answer['token'], answer)

    def test_get_lines(self):
        self.wait(lambda: any(e['kind'] == 'line' for e in self.hub.events))
        device = next(e['device'] for e in self.hub.events if e['kind'] == 'line')
        lines = self.api.get_lines(device, 0, 10)
        self.assertTrue(lines and all(l['device'] == device for l in lines))

    def wait(self, predicate, timeout=5):
        import time
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if predicate():
                return True
            time.sleep(0.05)
        return predicate()


if __name__ == '__main__':
    unittest.main()
