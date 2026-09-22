import json
import unittest

import support  # noqa: F401
from probe import classify, run_probe

CUBE = ['FW: v1.4.1-USB.2', 'Cube MAC: A4:CF:12:34:56:78', 'ESP-NOW CHANNEL: 2', 'Cube READY']
ZONE = ['FW: preshow-3.4.0', 'MAC: 14:63:93:C0:EC:14', 'CHANNEL: 2', 'ZONE: type=1 point=1 name=Preshow 1',
        'DB: version=31 count=32 crc=11E2A0F3 slot=A capacity=1819', 'STATS: tags=3 unknown=1 send_fail=0 error=0',
        'NFC: ok=1 fw=00000132 polls=10 found=3 last_ms=38 max_ms=52 fast_fail=0 recoveries=0 sda=1 scl=1 pins=4/3',
        'RXGAIN: stored=48dB applied=48dB', 'READY']
MAINSHOW = ['NCT MAINSHOW CONTROLLER', 'FW: mainshow-1.2.0', 'MAC: 34:85:18:AA:BB:CC', 'CHANNEL: 2', 'RADIO: OK', 'READY']
WORKSTATION = ['NCT WORKSTATION', 'FW: workstation-1.0.0', 'MAC: 02:AA:BB:CC:DD:F0', 'CHANNEL: 2', 'RADIO: OK', 'READY']
GENERAL_RADIO = ['NCT GENERAL RADIO', 'FW: general-radio-1.2.0', 'MAC: 02:AA:BB:CC:DD:EE', 'CHANNEL: 2', 'RADIO: OK', 'READY']


class ClassifyTests(unittest.TestCase):
    def test_cube(self):
        role, d = classify(CUBE)
        self.assertEqual(role, 'cube')
        self.assertEqual((d['mac'], d['firmware'], d['channel'], d['ready']), ('A4:CF:12:34:56:78', 'v1.4.1-USB.2', 2, True))

    def test_cube_still_booting(self):
        role, d = classify(['================================', 'NCT NEOCORE CUBE'])
        self.assertEqual(role, 'cube')
        self.assertTrue(d['booting'])

    def test_zone(self):
        role, d = classify(ZONE)
        self.assertEqual(role, 'zone')
        self.assertEqual((d['name'], d['db_version'], d['zone_type'], d['rx_gain']), ('Preshow 1', 31, 1, 48))

    def test_station_hello(self):
        hello = dict(event='hello', id='x', protocol=1, firmware='nct-pairing-1.8-zones', zones=1, mac='30:ed:a0:5b:6d:d8', channel=2,
                     radio_ok=True, nfc_ok=True)
        role, d = classify(['{"event":"error","detail":"Invalid JSON"}', json.dumps(hello)])
        self.assertEqual(role, 'workstation', 'a legacy pairing station is the workstation role; the hello says what it can do')
        self.assertEqual(d['mac'], '30:ED:A0:5B:6D:D8')

    def test_workstation_hello_and_banner(self):
        hello = dict(event='hello', id='x', protocol=1, firmware='workstation-1.0.0', zones=1, show=1, mac='02:aa:bb:cc:dd:f0', channel=2,
                     radio_ok=True, nfc_ok=True, roles=['cube', 'zone', 'pool', 'preshow', 'nfc'])
        role, d = classify([json.dumps(hello)])
        self.assertEqual((role, d['mac'], d['roles'][-1]), ('workstation', '02:AA:BB:CC:DD:F0', 'nfc'))
        role, d = classify(WORKSTATION)
        self.assertEqual((role, d['firmware'], d['mac'], d['radio_ok']), ('workstation', 'workstation-1.0.0', '02:AA:BB:CC:DD:F0', True))

    def test_legacy_general_radio_is_a_workstation(self):
        hello = dict(event='hello', firmware='general-radio-1.2.0', zones=1, show=1, mac='02:aa:bb:cc:dd:ee', nfc_ok=False,
                     roles=['cube', 'zone', 'pool', 'preshow'])
        self.assertEqual(classify([json.dumps(hello)])[0], 'workstation')
        self.assertEqual(classify(GENERAL_RADIO)[0], 'workstation')

    def test_station_hint_only(self):
        role, d = classify(['{"event":"error","detail":"Invalid JSON"}'])
        self.assertEqual((role, d.get('hint')), ('unknown', 'workstation'))

    def test_mainshow_banner_and_hello(self):
        self.assertEqual(classify(MAINSHOW)[0], 'mainshow')
        role, d = classify([json.dumps(dict(event='hello', firmware='mainshow-1.2.0', mac='34:85:18:aa:bb:cc', radio_ok=True))])
        self.assertEqual((role, d['mac']), ('mainshow', '34:85:18:AA:BB:CC'))

    def test_pool_central_bridge_pooltest(self):
        self.assertEqual(classify(['{"device":"PoolCentral","type":"status","version":3,"mac":"aa:bb:cc:dd:ee:01"}'])[0], 'poolcentral')
        self.assertEqual(classify(['POOL CENTRAL poolcentral-4.2.0 MAC=AA:BB:CC:DD:EE:01 channel=2 epoch=3 outputs=dark'])[0], 'poolcentral')
        self.assertEqual(classify(['NCT PRESHOW MEDIA BRIDGE', 'MAC=AA:BB:CC:DD:EE:02 epoch=1 radio=ready'])[0], 'preshowbridge')
        self.assertEqual(classify(['{"device":"PreshowBridge","type":"status"}'])[0], 'preshowbridge')
        self.assertEqual(classify(['{"device":"PoolRadioTest","version":2,"ready":true,"mac":"aa:bb:cc:dd:ee:03"}'])[0], 'pooltest')

    def test_rangetest(self):
        self.assertEqual(classify(['STAT role=RX loss_pct=0.0 rssi_avg=-61'])[0], 'rangetest')
        self.assertEqual(classify(['NCT RANGE TEST'])[0], 'rangetest')

    def test_unknown(self):
        self.assertEqual(classify(['Unknown command; try help', 'ERR unknown command'])[0], 'unknown')


class FakeSerial:
    """Answers scripted lines per command; `?` is answered only by `answers['?']`."""

    def __init__(self, answers, unsolicited=()):
        self.answers, self.pending = answers, list(unsolicited)
        self.written = []

    def read(self, n):
        if self.pending:
            return self.pending.pop(0)
        return b''

    def write(self, data):
        self.written.append(data)
        key = data.decode().strip()
        if key.startswith('{'):
            key = 'hello'
        for line in self.answers.get(key, []):
            self.pending.append((line + '\n').encode())

    def close(self):
        pass


class RunProbeTests(unittest.TestCase):
    def probe(self, answers, unsolicited=()):
        fake = FakeSerial(answers, unsolicited)
        clock = [0.0]

        def now():
            return clock[0]

        def sleep(s):
            clock[0] += max(s, 0.05)

        import probe as probe_module
        original = probe_module.PortLock
        probe_module.PortLock = lambda path: type('L', (), {'__enter__': lambda s: s, '__exit__': lambda s, *a: None})()
        try:
            return (*run_probe('/dev/fake', opener=lambda *a, **k: fake, clock=now, sleep=sleep), fake)
        finally:
            probe_module.PortLock = original

    def test_cube_answers_question_mark(self):
        role, details, transcript, fake = self.probe({'?': CUBE})
        self.assertEqual(role, 'cube')
        self.assertEqual(fake.written, [b'?\n'])  # stopped as soon as it was known

    def test_station_needs_hello(self):
        hello = json.dumps(dict(event='hello', protocol=1, firmware='nct-pairing-1.8-zones', zones=1, mac='30:ED:A0:5B:6D:D8', radio_ok=True))
        role, details, transcript, fake = self.probe({'?': ['{"event":"error","detail":"Invalid JSON"}'], 'hello': [hello]})
        self.assertEqual(role, 'workstation')
        self.assertEqual(len(fake.written), 2)
        self.assertTrue(fake.written[1].startswith(b'{"cmd": "hello"') or fake.written[1].startswith(b'{"cmd":"hello"'))

    def test_status_last_resort(self):
        role, details, transcript, fake = self.probe({'?': ['ERR unknown command'], 'STATUS': ['{"device":"PoolRadioTest","version":2,"ready":true,"mac":"aa:bb:cc:dd:ee:03","members":[0,0,0,0,0,0]}']})
        self.assertEqual(role, 'pooltest')
        self.assertEqual(fake.written[-1], b'STATUS\n')

    def test_unsolicited_wins_without_writing(self):
        role, details, transcript, fake = self.probe({}, unsolicited=[b'STAT role=RX loss_pct=1.5\n'])
        self.assertEqual(role, 'rangetest')
        self.assertEqual(fake.written, [])

    def test_never_sends_arming_commands(self):
        role, details, transcript, fake = self.probe({})
        self.assertEqual(role, 'unknown')
        for data in fake.written:
            self.assertFalse(any(data.startswith(bad) for bad in (b'HOST', b'CAL', b'TEST', b'SET', b'OFF')))


if __name__ == '__main__':
    unittest.main()
