import unittest

import support
import hostos
from locks import AlreadyOpen, InstanceLocks, instance_locks


class LockTests(unittest.TestCase):
    def test_console_takes_every_old_app_lock(self):
        database = support.temp_database()
        database.parent.mkdir(parents=True, exist_ok=True)
        locks = InstanceLocks(database)
        try:
            for suffix in ('.lock', '.flasher.lock', '.zonedb.lock', '.mainshow.lock', '.console.lock'):
                handle = database.with_suffix(suffix).open('a')
                with self.assertRaises(BlockingIOError, msg=suffix):
                    hostos.lock_file(handle)
                handle.close()
        finally:
            locks.close()
        handle = database.with_suffix('.lock').open('a')
        hostos.lock_file(handle)  # released after close
        handle.close()

    def test_refusal_names_the_app(self):
        database = support.temp_database()
        database.parent.mkdir(parents=True, exist_ok=True)
        other = database.with_suffix('.zonedb.lock').open('a')
        hostos.lock_file(other)
        try:
            with self.assertRaises(AlreadyOpen) as ctx:
                InstanceLocks(database)
            self.assertIn('Zone Database Manager', str(ctx.exception))
            # nothing stays held after a refusal
            probe = database.with_suffix('.lock').open('a')
            hostos.lock_file(probe)
            probe.close()
        finally:
            other.close()

    def test_probe_reports_held_locks_without_holding(self):
        database = support.temp_database()
        database.parent.mkdir(parents=True, exist_ok=True)
        other = database.with_suffix('.flasher.lock').open('a')
        hostos.lock_file(other)
        try:
            held = instance_locks(database)
            self.assertTrue(held['.flasher.lock'])
            self.assertFalse(held['.lock'])
            self.assertNotIn('.console.lock', held)
        finally:
            other.close()
        self.assertFalse(instance_locks(database)['.flasher.lock'])

    def test_console_does_not_report_its_own_locks(self):
        """With flock, a second handle in the same process conflicts with its own lock: the hub must skip what it holds."""
        database = support.temp_database()
        database.parent.mkdir(parents=True, exist_ok=True)
        own = InstanceLocks(database)
        try:
            self.assertTrue(instance_locks(database)['.lock'], 'the probe alone sees the console\'s own lock as held')
            probed = instance_locks(database, skip=('.console.lock',) + tuple(own.held))
            self.assertEqual(probed, {})
        finally:
            own.close()


if __name__ == '__main__':
    unittest.main()
