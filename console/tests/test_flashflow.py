"""The guided USB flashing workflow (flashflow.py) on the simulated bench: plug in → firmware → show."""
import base64
import copy
import unittest

import support
from support import simulated_hub, tick_until

import commands  # noqa: E402
import showfile  # noqa: E402
import simulate  # noqa: E402
from show_registry import image_hash  # noqa: E402

NEW_MAC = 'A4:CF:12:34:56:9B'
PORT = '/dev/sim.cube-flash'


def publish(hub, version, level=30):
    doc = copy.deepcopy(showfile.load())
    doc['cues'][0]['colours'] = [[level, level, 1]]
    doc = showfile.validate(doc)
    image = showfile.pack(doc)
    hub.showedit.registry.store.cache(dict(version=version, hash=image_hash(image), crc=showfile.crc32(image), length=len(image),
                                           image_b64=base64.b64encode(image).decode(), source=doc,
                                           published_at='2026-09-23T00:00:00Z', published_by='test'))
    return showfile.crc32(image)


def crash_logs(hub):
    return [line['text'] for line in hub.recent_logs if line['text'].startswith(('Flash workflow failed', 'Registration workflow failed',
                                                                                 'Auto intake failed'))]


class FlashFlowTests(unittest.TestCase):
    def setUp(self):
        self.hub = simulated_hub()
        self.hub.builds.setdefault('cube', {})['error'] = None   # independent of the local build's state
        tick_until(self.hub, lambda: self.hub.pinned_mac, timeout=8)

    def tearDown(self):
        commands.run(self.hub, 'flash.enable', {'on': False})
        self.hub.shutdown(force=True)

    def flow(self):
        return self.hub.flashflow

    def enable(self):
        """Switch on with the seeded bench's own boards (already plugged in) counted as done, as a real
        operator would have them already flashed: only cubes plugged in by the test are taken."""
        commands.run(self.hub, 'flash.enable', {'on': True})
        self.hub.intake.cubes.attempted.update(d.key for d in self.hub.devices.values())

    def plug(self, mac=NEW_MAC, port=PORT, firmware='v1.4.1-USB.2'):
        board = simulate.FakeCube(port, mac, firmware=firmware)
        self.hub.scanner.add(board)
        return board

    def finished(self, timeout=10):
        ok = tick_until(self.hub, lambda: self.flow().step in ('done', 'failed'), timeout=timeout)
        self.assertTrue(ok, self.flow().snapshot())
        return self.flow().snapshot()

    def test_off_by_default_and_does_nothing(self):
        self.assertFalse(self.flow().enabled)
        board = self.plug()
        support.run_ticks(self.hub, 40)
        self.assertEqual(self.flow().step, 'idle')
        self.assertEqual(board.firmware, 'v1.4.1-USB.2')

    def test_new_cube_gets_firmware_and_show(self):
        crc = publish(self.hub, 5)
        self.enable()
        board = self.plug()
        f = self.finished()
        self.assertEqual(f['step'], 'done', f['error'])
        self.assertEqual((f['result']['ui_result'], f['result']['show_result'], f['result']['show_version']), ('success', 'written', 5))
        self.assertEqual((board.show_version, board.show_crc), (5, crc))
        self.assertEqual(board.firmware, f['firmware']['version'])
        self.assertEqual(f['history'][0]['result'], 'flashed')
        self.assertEqual(f['mac'], NEW_MAC)
        self.assertEqual(crash_logs(self.hub), [])

    def test_matching_firmware_still_gets_the_new_show(self):
        publish(self.hub, 5)
        self.enable()
        board = self.plug()
        self.assertEqual(self.finished()['step'], 'done')
        self.hub.scanner.remove(PORT)
        support.run_ticks(self.hub, 20)
        tick_until(self.hub, lambda: self.hub.devices.get(PORT) is None and PORT not in [d.port for d in self.hub.devices.values()], timeout=4)
        support.run_ticks(self.hub, 120)   # the scheduler forgets an unplugged port after 2 s
        publish(self.hub, 6, level=40)
        self.hub.scanner.add(board)
        ok = tick_until(self.hub, lambda: self.flow().step == 'done' and (self.flow().result or {}).get('show_version') == 6, timeout=12)
        self.assertTrue(ok, self.flow().snapshot())
        r = self.flow().snapshot()['result']
        self.assertEqual((r['ui_result'], r['show_result']), ('skipped', 'written'), 'firmware skipped, show still written')
        self.assertEqual(board.show_version, 6)

    def test_current_show_is_left_alone(self):
        crc = publish(self.hub, 5)
        self.enable()
        board = self.plug(firmware='v1.7.0-USB.1')
        board.show_version, board.show_crc = 5, crc
        f = self.finished()
        self.assertEqual(f['result']['show_result'], 'current')

    def test_no_published_show_flashes_firmware_only(self):
        self.enable()
        board = self.plug()
        f = self.finished()
        self.assertEqual(f['step'], 'done')
        self.assertIsNone(f['show'])
        self.assertEqual(board.show_version, 0)
        self.assertIn('no published show', f['notice']['text'])

    def test_failure_waits_for_retry(self):
        publish(self.hub, 5)
        real = self.hub.fake_cube_flash
        calls = []

        def broken(port, manifest, manual, show, emit, show_only=None):
            calls.append(manual)
            if len(calls) == 1:
                raise RuntimeError('Disconnected while writing')
            return real(port, manifest, manual, show, emit, show_only=show_only)
        self.hub.fake_cube_flash = broken
        self.enable()
        board = self.plug()
        f = self.finished()
        self.assertEqual(f['step'], 'failed')
        self.assertIn('Disconnected', f['error'])
        support.run_ticks(self.hub, 30)
        self.assertEqual(len(calls), 1, 'no automatic retry')
        commands.run(self.hub, 'flash.retry', {})
        f = self.finished()
        self.assertEqual(f['step'], 'done', f['error'])
        self.assertEqual(calls, [False, True], 'Retry rewrites the firmware (manual)')
        self.assertEqual(board.show_version, 5)

    def test_switching_on_takes_cubes_already_plugged_in_but_never_other_boards(self):
        cubes = [d for d in self.hub.devices.values() if d.role == 'cube']
        others = {d.port: d.role for d in self.hub.devices.values() if d.role not in ('cube', 'unknown', None)}
        self.assertTrue(cubes and others)
        commands.run(self.hub, 'flash.enable', {'on': True})
        ok = tick_until(self.hub, lambda: all(k in self.hub.intake.cubes.attempted for k in (d.key for d in self.hub.devices.values()))
                        and self.flow().step in ('done', 'failed') and not self.hub.jobs.running(), timeout=15)
        self.assertTrue(ok, self.flow().snapshot())
        flashed = {h['port'] for h in self.flow().history}
        self.assertEqual(flashed, {d.port for d in cubes})
        self.assertFalse(flashed & set(others), 'the station, zones and radios are never flashed')

    def test_register_waits_for_the_flash(self):
        publish(self.hub, 5)
        self.enable()
        commands.run(self.hub, 'register.enable', {'on': True})
        waits = []

        def watch():   # the seeded, pinned cube starts first; follow the one plugged in here
            r = self.hub.regflow
            if r.mac == NEW_MAC and r.wait:
                waits.append(r.wait)
            return r.mac == NEW_MAC and r.armed
        board = self.plug()
        ok = tick_until(self.hub, watch, timeout=12)
        self.assertTrue(ok, self.hub.regflow.snapshot())
        self.assertEqual(self.flow().step, 'done', 'the flash finished before the NFC step armed')
        self.assertIn('Waiting for the Flash page to finish this cube', waits)
        self.assertEqual(board.show_version, 5)
        commands.run(self.hub, 'register.cancel', {})
        commands.run(self.hub, 'register.enable', {'on': False})
        self.assertEqual(crash_logs(self.hub), [])

    def test_update_show_only_from_the_cube_panel(self):
        publish(self.hub, 7)
        board = self.plug(firmware='v1.6.0-USB.1')
        tick_until(self.hub, lambda: any(d.port == PORT and d.role == 'cube' for d in self.hub.devices.values()), timeout=8)
        device = next(d for d in self.hub.devices.values() if d.port == PORT)
        self.assertEqual(device.details['show'], dict(version=0, crc=0, source='builtin'))
        commands.run(self.hub, 'cube.update_show', {'device': device.id})
        tick_until(self.hub, lambda: board.show_version == 7 and not self.hub.jobs.running(), timeout=8)
        self.assertEqual(board.firmware, 'v1.6.0-USB.1', 'firmware untouched')
        self.assertEqual(board.show_version, 7)

    def test_never_starts_while_the_console_probes_the_port(self):
        """The probe (and a live session) hold the PortLock: esptool started meanwhile failed with
        "USB port is owned by another Neocore application". Intake waits until the port has settled."""
        self.enable()
        self.plug()
        self.assertTrue(tick_until(self.hub, lambda: PORT in [d.port for d in self.hub.devices.values()], timeout=4))
        device = next(d for d in self.hub.devices.values() if d.port == PORT)
        for state, probing in (('present', None), ('probing', device.key), ('foreign', None), ('idle', device.key)):
            device.state = state
            self.hub.probing = probing
            self.assertIsNone(self.hub.intake.next_settled_cube(), state)
        self.hub.probing = None
        for state in ('idle', 'session'):
            device.state = state
            self.assertEqual(self.hub.intake.next_settled_cube()['key'], device.key, state)

    def test_a_probe_result_never_overrides_a_running_job(self):
        self.plug()
        self.assertTrue(tick_until(self.hub, lambda: any(d.port == PORT and d.state in ('idle', 'session') for d in self.hub.devices.values()), timeout=8))
        device = next(d for d in self.hub.devices.values() if d.port == PORT)
        device.state = 'job'
        self.hub.prober.results.put((dict(port=PORT, key=device.key), 'unknown', {}, [], 'USB port is owned by another Neocore application'))
        self.hub.apply_probe_results()
        self.assertEqual(device.state, 'job')

    def test_section_is_published(self):
        data = support.section(self.hub, 'flash')
        self.assertFalse(data['enabled'])
        self.assertEqual(data['steps'], ['usb', 'firmware', 'show'])


if __name__ == '__main__':
    unittest.main()
