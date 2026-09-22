"""The owner thread against simulated boards: identification, sessions, snapshot deltas, commands, jobs."""
import json
import time
import unittest

import support
from support import run_ticks, section, simulated_hub, tick_until
import commands
import simulate
from jobs.base import Job


class HubTests(unittest.TestCase):
    def setUp(self):
        self.hub = simulated_hub()

    def tearDown(self):
        self.hub.shutdown(force=True)

    def devices(self):
        return {d['port']: d for d in section(self.hub, 'devices')}

    def test_identifies_every_board_and_opens_the_right_session(self):
        self.assertTrue(tick_until(self.hub, lambda: len(self.hub.sessions) == 5))
        devices = self.devices()
        self.assertEqual({p: (d['role'], d['session_kind']) for p, d in devices.items()},
                         {'/dev/sim.cube': ('cube', 'cube'), '/dev/sim.station': ('station', 'station'),
                          '/dev/sim.pool3': ('zone', 'pool'), '/dev/sim.preshow1': ('zone', 'preshow'),
                          '/dev/sim.radio': ('generalradio', 'generalradio')})
        self.assertTrue(all(d['state'] == 'session' for d in devices.values()))
        station = section(self.hub, 'station')
        self.assertTrue(station['connected'] and station['reader_ok'])
        self.assertEqual(section(self.hub, 'registry')['present'], True)
        # the cube identified over USB is pinned and reserved in the inventory, as the pairing app did
        self.assertEqual(self.hub.pinned_mac, 'A4:CF:12:34:56:78')
        self.assertIsNotNone(self.hub.db.get('A4:CF:12:34:56:78'))

    def test_zone_frames_reach_the_registry_not_the_controller(self):
        self.assertTrue(tick_until(self.hub, lambda: len(self.hub.sessions) == 5))
        station = self.hub.station_session()
        station.zones.query()
        run_ticks(self.hub, 5)
        rows = {z['name']: z for z in station.zones.zone_rows()}
        self.assertIn('Preshow 1', rows)
        self.assertEqual(rows['Preshow 1']['db_version'], 31)
        self.assertTrue(rows['Preshow 1']['in_range'])
        self.assertEqual(station.controller.mode, '')  # untouched by zone traffic

    def test_snapshot_pull_is_delta_and_json(self):
        run_ticks(self.hub, 10)
        first = self.hub.pull()
        json.dumps(first)
        since = {name: s['version'] for name, s in first['sections'].items()}
        again = self.hub.pull(since, first['seq'])
        self.assertNotIn('meta', again['sections'])          # unchanged sections are not resent
        self.assertNotIn('inventory', again['sections'])
        self.assertEqual([e for e in again['events'] if e['seq'] <= first['seq']], [])

    def test_plate_taps_become_history_and_tags(self):
        plate = self.hub._sim['plate']
        plate.taps = [(0.0, '04:11:22:33:44:55:66'), (0.5, self.hub._sim['known_uid'])]
        plate.started = time.monotonic() - 1
        self.assertTrue(tick_until(self.hub, lambda: any(
            s.kind == 'preshow' and len(s.state.history) >= 2 for s in self.hub.sessions.values()), timeout=8))
        session = next(s for s in self.hub.sessions.values() if s.kind == 'preshow')
        states = [(h['cube_id'], h['state']) for h in session.state.history]
        self.assertIn((12, 'delivered'), states)
        self.assertIn((None, 'unknown tag'), states)
        tags = [e['tag'] for e in self.hub.events if e['kind'] == 'tag']
        self.assertIn('zone.unknown_cube', tags)
        self.assertIn('zone.found_cube', tags)
        self.assertEqual(session.stats['unknown'], 1)

    def test_hardware_commands_run_on_one_click(self):
        self.assertTrue(tick_until(self.hub, lambda: len(self.hub.sessions) == 5))
        plate_id = '14:63:93:C0:EC:14'
        self.assertTrue(commands.run(self.hub, 'monitor.zone', dict(device=plate_id, cube_id=12, zone=1)))
        # a stray token (an old page) is ignored, never passed to the command
        self.assertTrue(commands.run(self.hub, 'monitor.zone', dict(device=plate_id, cube_id=12, zone=2, token='stale')))

    def test_destructive_commands_need_a_confirmation_token(self):
        self.assertTrue(tick_until(self.hub, lambda: len(self.hub.sessions) == 5))
        name = 'mainshow.trigger_all'
        with self.assertRaises(ValueError) as refused:
            commands.run(self.hub, name, {})
        self.assertIn('hold', str(refused.exception))
        token = self.hub.confirm(name, {})['token']
        with self.assertRaises(ValueError):  # arguments must match what was confirmed
            commands.run(self.hub, name, dict(extra=1, token=token))
        token = self.hub.confirm(name, {})['token']
        self.hub.check_confirmation(token, name, {})
        with self.assertRaises(ValueError):  # single use
            self.hub.check_confirmation(token, name, {})

    def test_safe_monitor_commands_and_console(self):
        self.assertTrue(tick_until(self.hub, lambda: len(self.hub.sessions) == 5))
        plate_id = '14:63:93:C0:EC:14'
        self.assertTrue(commands.run(self.hub, 'monitor.flash', dict(device=plate_id, cube_id=12, seconds=2)))
        self.assertEqual(self.hub._sim['plate'].flashing[0], 12)
        commands.run(self.hub, 'device.console', dict(device=plate_id, line='db'))
        run_ticks(self.hub, 3)
        session = self.hub.sessions[plate_id]
        self.assertTrue(any(l.startswith('DB END') for l in session.db_lines))
        with self.assertRaises(ValueError):
            commands.run(self.hub, 'device.console', dict(device=plate_id, line='rm -rf'))

    def test_disconnect_is_sticky_until_connect(self):
        self.assertTrue(tick_until(self.hub, lambda: len(self.hub.sessions) == 5))
        cube_id = 'A4:CF:12:34:56:78'
        commands.run(self.hub, 'device.disconnect', dict(device=cube_id))
        run_ticks(self.hub, 5)
        self.assertNotIn(cube_id, self.hub.sessions)
        commands.run(self.hub, 'device.connect', dict(device=cube_id))
        self.assertIn(cube_id, self.hub.sessions)

    def test_unplug_closes_the_session(self):
        self.assertTrue(tick_until(self.hub, lambda: len(self.hub.sessions) == 5))
        self.hub.scanner.remove('/dev/sim.cube')
        self.assertTrue(tick_until(self.hub, lambda: 'A4:CF:12:34:56:78' not in self.hub.sessions, timeout=5))
        self.assertNotIn('/dev/sim.cube', self.devices())

    def test_job_runner_applies_results_on_the_owner_thread(self):
        seen = []
        job = Job('test', 'x', 'A test job')

        def work(emit, cancel):
            emit('stage', 'Working')
            emit('progress', 50.0)
            emit('log', '$ esptool write-flash')
            emit('log', 'Hash of data verified')
            return dict(answer=42)

        self.hub.jobs.start(job, work, lambda j: seen.append(j.result))
        self.assertTrue(tick_until(self.hub, lambda: job.state == 'done', timeout=5))
        self.assertEqual(seen, [dict(answer=42)])
        self.assertEqual(job.stage, 'Working')
        self.assertFalse(job.writing)
        snap = section(self.hub, 'jobs')
        self.assertEqual(snap[0]['id'], job.id)
        with self.assertRaises(ValueError):
            self.hub.jobs.cancel(job.id)

    def test_failed_job_reports_outcome(self):
        job = Job('test', 'x', 'A failing job')

        def work(emit, cancel):
            raise RuntimeError('USB identity changed; upload stopped')

        self.hub.jobs.start(job, work)
        self.assertTrue(tick_until(self.hub, lambda: job.state == 'failed', timeout=5))
        self.assertEqual(job.outcome['level'], 'failed')
        self.assertIn('USB identity changed', job.outcome['text'])

    def test_shutdown_refuses_while_writing(self):
        job = Job('test', 'x', 'Writing')
        job.writing = True
        job.state = 'running'
        self.hub.jobs.jobs[job.id] = job
        with self.assertRaises(ValueError):
            self.hub.shutdown()
        job.writing = False
        job.state = 'done'

    def test_call_from_another_thread(self):
        import threading
        result = []
        thread = threading.Thread(target=lambda: result.append(self.hub.call(lambda: 'pong')))
        thread.start()
        thread.join()
        self.hub.drain_commands()
        self.assertEqual(result[0].result(timeout=1), 'pong')

    def test_advisor_section_and_dismiss(self):
        run_ticks(self.hub, 5)
        adv = section(self.hub, 'advisor')
        self.assertIn('suggestions', adv)
        commands.run(self.hub, 'advisor.dismiss', dict(id='x:y', scope='once'))
        self.assertIn('x:y', self.hub.dismissed)


if __name__ == '__main__':
    unittest.main()


class UsbPinningTests(unittest.TestCase):
    """A cube identified over USB while a pairing operation runs stops it before taking the pin (pairing app rule)."""

    def setUp(self):
        self.hub = simulated_hub()

    def tearDown(self):
        self.hub.shutdown(force=True)

    def test_identifying_another_cube_stops_the_active_operation(self):
        hub = self.hub
        tick_until(hub, lambda: hub.station_session() and hub.station_session().controller.connected, timeout=8)
        c = hub.station_session().controller
        c.discover()
        tick_until(hub, lambda: hub._sim['known_mac'] in c.discovered, timeout=4)
        c.preview(hub._sim['known_mac'])
        self.assertEqual(c.mode, 'preview')
        other = simulate.FakeCube('/dev/sim.cube-late', 'A4:CF:12:34:56:99', number=None)
        hub.scanner.add(other)
        tick_until(hub, lambda: hub.pinned_mac == other.mac, timeout=8)
        self.assertEqual(hub.pinned_mac, other.mac)
        tick_until(hub, lambda: not c.mode, timeout=4)
        self.assertFalse(c.mode, 'the preview was stopped before the pin moved')
        self.assertTrue(any('Stopped the active pairing operation' in (e.get('text') or '') for e in hub.notable))

    def test_initial_pull_carries_the_timeline_history(self):
        hub = self.hub
        tick_until(hub, lambda: sum(1 for e in hub.notable if 'Identified' in (e.get('text') or '')) >= 3, timeout=10)
        events = hub.pull()['events']
        kinds = {e['kind'] for e in events}
        self.assertIn('log', kinds)
        self.assertTrue(any('Identified' in (e.get('text') or '') for e in events))
