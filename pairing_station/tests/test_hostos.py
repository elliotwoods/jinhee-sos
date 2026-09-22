"""hostos on the real host, plus its Windows branches driven through a fake msvcrt (no Windows needed)."""
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hostos  # noqa: E402


class FakeMsvcrt:
    """LockFile semantics: one lock per file; any further attempt, even by the owner, gets OSError."""
    LK_NBLCK = 2

    def __init__(self):
        self.owners = {}  # file identity -> descriptor holding the lock
        self.calls = 0

    def locking(self, descriptor, mode, count):
        self.calls += 1
        assert (mode, count) == (self.LK_NBLCK, 1)
        assert os.lseek(descriptor, 0, os.SEEK_CUR) == 0, 'the locked byte must be the first one'
        key = os.fstat(descriptor).st_ino
        if key in self.owners:
            raise OSError(13, 'Permission denied')
        self.owners[key] = descriptor

    def release(self, handle):
        self.owners = {k: v for k, v in self.owners.items() if v != handle.fileno()}


class RealHostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'app.lock'

    def test_second_handle_is_refused_until_the_first_closes(self):
        with self.path.open('a') as first:
            hostos.lock_file(first)
            with self.path.open('a') as second:
                with self.assertRaises(BlockingIOError):
                    hostos.lock_file(second)
        with self.path.open('a') as third:
            hostos.lock_file(third)

    def test_host_paths_exist_in_shape(self):
        env = Path(self.tmp.name) / '.venv'
        self.assertEqual(hostos.venv_python(env).parent.parent, env)
        self.assertEqual(hostos.venv_site_packages(env).name, 'site-packages')
        self.assertTrue(hostos.lock_dir().is_dir())
        self.assertTrue(hostos.user_tag())
        self.assertEqual(hostos.esp32_core('3.3.11').parts[-5:], ('packages', 'esp32', 'hardware', 'esp32', '3.3.11'))
        self.assertTrue(hostos.same_folder(self.tmp.name, Path(self.tmp.name) / '.'))
        self.assertFalse(hostos.same_folder(self.tmp.name, Path(self.tmp.name) / 'missing'))

    def test_private_file_accepts_path_and_descriptor(self):
        self.path.write_text('secret', encoding='utf-8')
        hostos.private_file(self.path)
        with self.path.open('a') as handle:
            hostos.private_file(handle.fileno())
        if not hostos.WINDOWS:
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)


class WindowsBranchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'app.lock'
        self.msvcrt = FakeMsvcrt()
        for patcher in (patch.object(hostos, 'WINDOWS', True), patch.object(hostos, 'MAC', False),
                        patch.dict(sys.modules, msvcrt=self.msvcrt)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_contention_is_blockingioerror_like_flock(self):
        with self.path.open('a') as first, self.path.open('a') as second:
            first.write('x'); first.flush()  # a non-empty append-mode file: position is not 0 by itself
            hostos.lock_file(first)
            with self.assertRaises(BlockingIOError):
                hostos.lock_file(second)

    def test_blocking_waits_for_release(self):
        with self.path.open('a') as first, self.path.open('a') as second:
            hostos.lock_file(first)
            naps = []
            def nap(seconds):
                naps.append(seconds)
                if len(naps) == 3:
                    self.msvcrt.release(first)
            with patch.object(hostos.time, 'sleep', nap):
                hostos.lock_file(second, blocking=True)
            self.assertEqual(len(naps), 3)

    def test_port_names_venv_and_toolchain(self):
        self.assertEqual(hostos.canonical_port('com3'), 'COM3')
        self.assertEqual(hostos.canonical_port('\\\\.\\COM12'), 'COM12')
        env = Path('checkout') / '.venv'
        self.assertEqual(hostos.venv_python(env), env / 'Scripts' / 'python.exe')
        self.assertEqual(hostos.venv_site_packages(env), env / 'Lib' / 'site-packages')
        with patch.dict(os.environ, LOCALAPPDATA=self.tmp.name, ProgramFiles=str(Path(self.tmp.name) / 'pf')):
            self.assertEqual(hostos.arduino_data_dir(), Path(self.tmp.name) / 'Arduino15')
            with patch.object(hostos.shutil, 'which', return_value='on-path'):
                self.assertEqual(hostos.arduino_cli(), 'on-path')
                bundled = Path(self.tmp.name) / 'Programs/Arduino IDE/resources/app/lib/backend/resources/arduino-cli.exe'
                bundled.parent.mkdir(parents=True)
                bundled.touch()
                self.assertEqual(hostos.arduino_cli(), str(bundled))

    def test_process_flags_wheel_and_permissions(self):
        flags = dict(DETACHED_PROCESS=0x8, CREATE_NEW_PROCESS_GROUP=0x200, CREATE_NO_WINDOW=0x08000000)
        with patch.multiple(hostos.subprocess, create=True, **flags):
            self.assertEqual(hostos.detached_kwargs(), dict(creationflags=0x208))
            self.assertEqual(hostos.quiet_kwargs(), dict(creationflags=0x08000000))
        self.assertEqual(hostos.wheel_units(SimpleNamespace(delta=-240)), -2)
        self.path.write_text('secret', encoding='utf-8')
        with patch.object(hostos.os, 'chmod', side_effect=AssertionError('no mode bits on Windows')):
            hostos.private_file(self.path)


class PosixBranchTests(unittest.TestCase):
    def test_mac_names(self):
        with patch.object(hostos, 'WINDOWS', False), patch.object(hostos, 'MAC', True):
            self.assertEqual(hostos.canonical_port('/dev/tty.usbmodem101'), '/dev/cu.usbmodem101')
            self.assertEqual(hostos.wheel_units(SimpleNamespace(delta=-3)), -3)
            self.assertEqual(hostos.detached_kwargs(), dict(start_new_session=True))
            self.assertEqual(hostos.quiet_kwargs(), {})


if __name__ == '__main__':
    unittest.main()
