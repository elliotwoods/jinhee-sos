"""Session behaviour that protects hardware: leases, farewells, and station routing."""
import time
import unittest

import support
from support import run_ticks, simulated_hub, tick_until
import commands
import simulate


class RecordingBoard(simulate.FakeZone):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.received = []

    def handle(self, line):
        self.received.append(line)
        return super().handle(line)


class LeaseTests(unittest.TestCase):
    def setUp(self):
        simulate.BOARDS.clear()
        from hub import Hub
        self.hub = Hub(support.temp_database(), api_port=0, simulate=True)
        simulate.install(self.hub, scenario='empty')
        self.hub.boot()

    def tearDown(self):
        self.hub.shutdown(force=True)

    def add(self, board):
        self.hub.scanner.add(board)
        self.assertTrue(tick_until(self.hub, lambda: board.mac in self.hub.sessions))
        return self.hub.sessions[board.mac]

    def test_pool_override_pings_only_while_touched_then_disarms(self):
        board = RecordingBoard('/dev/sim.pool', '14:63:93:C0:EC:33', zone_type=3, point=3, name='Pool Radio 3', firmware='pool-3.2.0')
        session = self.add(board)
        self.assertTrue(tick_until(self.hub, lambda: session.ready))
        commands.run(self.hub, 'pool.arm', dict(device=board.mac))
        self.assertIn('HOST ARM', board.received)
        armed_at = len(board.received)
        end = time.monotonic() + 0.8
        while time.monotonic() < end:
            commands.run(self.hub, 'pool.touch', dict(device=board.mac))
            self.hub.tick()
            time.sleep(0.05)
        pings = board.received.count('HOST PING')
        self.assertGreaterEqual(pings, 1)
        # stop touching: the session lets the lease go instead of pretending to be in control
        self.assertTrue(tick_until(self.hub, lambda: 'HOST DISARM' in board.received[armed_at:], timeout=2))
        self.assertFalse(session.arm_requested)

    def test_preshow_cue_needs_arming_and_disarms_on_close(self):
        board = RecordingBoard('/dev/sim.preshow', '14:63:93:C0:EC:14')
        session = self.add(board)
        with self.assertRaises(ValueError):
            session.cue(1, True)
        commands.run(self.hub, 'preshow.arm', dict(device=board.mac))
        run_ticks(self.hub, 3)
        self.assertTrue(session.armed)
        commands.run(self.hub, 'preshow.cue', dict(device=board.mac, point=2, on=True))
        self.assertIn('HOST ON 2', board.received)
        self.assertTrue(tick_until(self.hub, lambda: board.received.count('HOST PING') >= 2, timeout=2))
        transport = session.transport
        self.hub.close_session(session, 'test')
        self.assertEqual(transport.farewell, 'HOST DISARM')

    def test_pool_test_bridge_releases_everything_on_close(self):
        board = simulate.FakeBoard('/dev/sim.pooltest', 'AA:BB:CC:DD:EE:03')
        board.role = 'pooltest'
        board.received = []
        status = '{"device":"PoolRadioTest","version":2,"ready":true,"channel":2,"mac":"AA:BB:CC:DD:EE:03","queued":0,"errors":0,"members":[%s],"unicast":true}'
        board.slots = [0] * 6

        def handle(line):
            board.received.append(line)
            if line.startswith('SET '):
                board.slots = [int(v) for v in line.split()[1:]]
            if line == 'OFF':
                board.slots = [0] * 6
            return [status % ','.join(map(str, board.slots))]
        board.handle = handle
        board.probe_lines = lambda: [status % '0,0,0,0,0,0']
        session = self.add(board)
        self.assertTrue(tick_until(self.hub, lambda: session.ready))
        commands.run(self.hub, 'pooltest.toggle', dict(device=board.mac, member=7))
        self.assertEqual(session.slots[0], 7)
        transport = session.transport
        commands.run(self.hub, 'device.stop', dict(device=board.mac))
        self.assertIn('OFF', board.received)
        self.hub.close_session(session, 'test')
        self.assertEqual(transport.farewell, 'OFF')

    def test_station_query_is_suppressed_while_registering(self):
        station = simulate.FakeStation('/dev/sim.station', '30:ED:A0:5B:6D:D8')
        session = self.add(station)
        self.assertTrue(tick_until(self.hub, lambda: session.controller.connected))
        session.controller.phase = 'registering'
        before = session.zones.next_query
        session.tick(self.hub.clock())
        self.assertGreaterEqual(session.zones.next_query, self.hub.clock() + 0.9)
        session.controller.phase = ''


if __name__ == '__main__':
    unittest.main()
