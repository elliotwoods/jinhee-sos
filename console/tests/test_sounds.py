"""The cube flasher's audio cues in the console (sounds.py): same moments as flashing_station/app.py."""
import unittest
from unittest.mock import PropertyMock, patch

import support
from support import simulated_hub, tick_until

import commands  # noqa: E402
import simulate  # noqa: E402
from sounds import Sounds  # noqa: E402
from test_flashflow import publish  # noqa: E402


class FakeAudio:
    def __init__(self):
        self.played = []

    def play(self, name):
        self.played.append(name)


class SoundTests(unittest.TestCase):
    def setUp(self):
        self.hub = simulated_hub()
        self.hub.builds.setdefault('cube', {})['error'] = None
        tick_until(self.hub, lambda: self.hub.pinned_mac, timeout=8)
        self.audio = self.hub.sounds.audio = FakeAudio()

    def tearDown(self):
        commands.run(self.hub, 'flash.enable', {'on': False})
        self.hub.shutdown(force=True)

    def flash_one(self, firmware='v1.4.1-USB.2', mac='A4:CF:12:34:56:9D'):
        commands.run(self.hub, 'flash.enable', {'on': True})
        self.hub.intake.cubes.attempted.update(d.key for d in self.hub.devices.values())
        board = simulate.FakeCube('/dev/sim.cube-sound', mac, firmware=firmware)
        self.hub.scanner.add(board)
        self.assertTrue(tick_until(self.hub, lambda: self.hub.flashflow.step in ('done', 'failed'), timeout=10))
        support.run_ticks(self.hub, 5)
        return board

    def test_silent_in_a_simulation(self):
        self.hub.settings['audio'] = True
        self.flash_one()
        self.assertEqual(self.audio.played, [])

    def test_flash_plays_connected_start_ticks_success(self):
        with patch.object(Sounds, 'enabled', new_callable=PropertyMock, return_value=True):
            self.flash_one()
        played = self.audio.played
        self.assertEqual(played[:2], ['connected', 'start'])
        self.assertIn('tick', played, 'each stage ticks')
        self.assertEqual(played[-1], 'success')

    def test_failure_sound(self):
        def broken(*args, **kwargs):
            raise RuntimeError('Disconnected while writing')
        self.hub.fake_cube_flash = broken
        with patch.object(Sounds, 'enabled', new_callable=PropertyMock, return_value=True):
            self.flash_one()
        self.assertEqual(self.audio.played[-1], 'failure')

    def test_skipped_is_a_tick_but_a_written_show_is_a_success(self):
        sounds = self.hub.sounds

        class Job:
            kind, state = 'cube.flash', 'done'
        with patch.object(Sounds, 'enabled', new_callable=PropertyMock, return_value=True):
            job = Job()
            job.result = dict(ui_result='skipped', show_result='current')
            sounds.job_done(job)
            job.result = dict(ui_result='skipped', show_result='written')
            sounds.job_done(job)
            job.result = dict(ui_result='boot_unconfirmed')
            sounds.job_done(job)
        self.assertEqual(self.audio.played, ['tick', 'success', 'failure'])

    def test_off_setting_is_silent_and_test_button_always_plays(self):
        self.hub.settings['audio'] = False
        self.hub.simulate = False
        try:
            self.hub.sounds.play('success')
            self.assertEqual(self.audio.played, [])
            commands.run(self.hub, 'audio.test', {'cue': 'success'})
            self.assertEqual(self.audio.played, ['success'])
        finally:
            self.hub.simulate = True


if __name__ == '__main__':
    unittest.main()
