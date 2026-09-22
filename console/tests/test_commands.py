import unittest

import support  # noqa: F401
import commands
import commands_extra  # noqa: F401


class CatalogueTests(unittest.TestCase):
    def test_every_command_has_a_kind(self):
        for name, spec in commands.COMMANDS.items():
            self.assertIn(spec['kind'], ('safe', 'hardware', 'destructive'), name)

    def test_flash_and_show_commands_are_not_safe(self):
        for name in ('cube.flash_firmware', 'zone.flash', 'zone.update_db_usb', 'dongle.flash', 'zones.update', 'pairing.register',
                     'mainshow.trigger', 'pool.cal_save', 'preshow.cue', 'pooltest.toggle', 'usb.auto_cubes'):
            self.assertNotEqual(commands.COMMANDS[name]['kind'], 'safe', name)
        for name in ('zone.flash_force', 'mainshow.trigger_all', 'inventory.unregister'):
            self.assertEqual(commands.COMMANDS[name]['kind'], 'destructive', name)

    def test_unknown_command(self):
        with self.assertRaises(ValueError):
            commands.run(None, 'no.such', {})

    def test_dongle_flash_targets_are_workstation_or_mainshow(self):
        # The relay dongle and General Radio targets became the Workstation; the old names are refused before any device lookup.
        for old in ('general', 'dongle'):
            with self.assertRaisesRegex(ValueError, 'workstation or mainshow'):
                commands.run(None, 'dongle.flash', dict(device='x', firmware=old))


if __name__ == '__main__':
    unittest.main()
