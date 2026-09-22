"""Every explanation the front end asks for exists, with a valid tone."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import paths  # noqa: E402,F401
import uitext as console_copy  # noqa: E402

WEB = Path(__file__).resolve().parents[1] / 'web'


class CopyTests(unittest.TestCase):
    def test_panels_referenced_exist(self):
        used = set()
        for path in WEB.rglob('*.js'):
            used.update(re.findall(r'Explainer\}\s+id="([\w.]+)"', path.read_text(encoding='utf-8')))
        self.assertTrue(used)
        missing = used - set(console_copy.PANELS)
        self.assertFalse(missing, f'Explainer ids without copy: {sorted(missing)}')

    def test_status_keys_referenced_exist(self):
        used = set()
        for path in WEB.rglob('*.js'):
            used.update(re.findall(r'status="([\w.]+)"', path.read_text(encoding='utf-8')))
        missing = used - set(console_copy.STATUS)
        self.assertFalse(missing, f'status keys without copy: {sorted(missing)}')

    def test_tones_and_text(self):
        for key, entry in console_copy.STATUS.items():
            self.assertIn(entry['tone'], console_copy.TONES, key)
            self.assertTrue(entry['label'] and entry['tip'], key)
        for key, entry in console_copy.PANELS.items():
            self.assertTrue(entry['title'] and entry['what'] and entry['check'], key)
        self.assertEqual(set(console_copy.LADDER), {'sent', 'delivered', 'acknowledged', 'verified', 'failed'})
        self.assertNotIn('acknowledged', console_copy.LADDER['delivered'].lower().replace('no application acknowledgment', ''))

    def test_every_physical_command_has_tooltip_copy(self):
        import commands, commands_extra, commands_show  # noqa: F401  (registers every command)
        for name, spec in commands.COMMANDS.items():
            if spec['kind'] == 'safe':
                continue
            entry = console_copy.ACTIONS.get(name)
            self.assertTrue(entry, f'{name} ({spec["kind"]}) has no ACTIONS tooltip copy')
            self.assertTrue(entry.get('what') and entry.get('hazard'), f'{name} needs what + hazard')
        for name, entry in console_copy.ACTIONS.items():
            self.assertTrue(entry.get('label') and entry.get('what'), name)
            self.assertLessEqual(set(entry), {'label', 'what', 'hazard', 'needs', 'disabled'}, name)

    def test_no_arm_step_left_in_operator_text(self):
        # HOST ARM / pool.arm / preshow.arm are the device lease protocol, not a UI step.
        pattern = re.compile(r'\b(Arm:|Go:|ArmButton|arm step|armed button|click Arm)')
        for path in list(WEB.rglob('*.js')) + [WEB.parent / 'uitext.py']:
            if 'vendor' in path.parts:
                continue
            hits = pattern.findall(path.read_text(encoding='utf-8'))
            self.assertFalse(hits, f'{path.name}: {hits}')

    def test_as_dict_is_json(self):
        import json
        json.dumps(console_copy.as_dict())

    def test_korean_copy_is_not_stale(self):
        # A reworded English text needs its Korean revisited; then `python console/uitext_ko.py --stamp`.
        import uitext_ko
        self.assertEqual(uitext_ko.stale(), [], 'English changed since the Korean was written (uitext_ko.py)')

    def test_korean_copy_covers_every_entry(self):
        # The EN/KR switch lays uitext_ko over uitext: same keys, translatable fields only, nothing missing.
        import uitext_ko
        text_fields = dict(panels={'title', 'what', 'check'}, status={'label', 'tip'}, actions={'label', 'what', 'hazard', 'needs', 'disabled'})
        for group, fields in text_fields.items():
            en, ko = getattr(console_copy, group.upper()), getattr(uitext_ko, group.upper())
            self.assertEqual(set(ko), set(en), f'{group}: keys differ from uitext')
            for key, entry in ko.items():
                self.assertEqual(set(entry), set(en[key]) & fields, f'{group}.{key}: fields differ')
                self.assertTrue(all(v.strip() for v in entry.values()), f'{group}.{key}: empty text')
        for group in ('LADDER', 'GLOSSARY'):
            en, ko = getattr(console_copy, group), getattr(uitext_ko, group)
            self.assertEqual(set(ko), set(en), group)
            self.assertTrue(all(v.strip() for v in ko.values()), group)


if __name__ == '__main__':
    unittest.main()
