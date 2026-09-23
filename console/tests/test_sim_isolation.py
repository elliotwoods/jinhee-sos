"""Simulations and tests must never write the shared Git inventory (ROOT/inventory/devices).

A Windows computer once found simulator MACs (A4:CF:12:34:56:78 ...) there. They came from the real
web inventory (a pre-guard simulated Sync uploaded them) through the machine's real database and
scripts/sync_inventory.py, not from a console simulation. This guards the console side of that path:
simulated hubs keep their database in a temporary folder and nothing in the console writes the Git
inventory folder.
"""
import re
import unittest
from pathlib import Path

from support import docs_hub, run_ticks, simulated_hub

import paths

INVENTORY = paths.ROOT / 'inventory' / 'devices'


def snapshot():
    if not INVENTORY.is_dir():
        return {}
    return {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in INVENTORY.iterdir()}


class SimulationLeavesGitInventoryAlone(unittest.TestCase):

    def setUp(self):
        self.before = snapshot()

    def check(self, hub):
        try:
            self.assertNotIn(paths.ROOT.resolve(), Path(hub.database).resolve().parents,
                             'a simulated hub must use a temporary database')
            run_ticks(hub, 60)
        finally:
            hub.shutdown(force=True)
        self.assertEqual(snapshot(), self.before, 'the simulation changed inventory/devices')

    def test_default_simulation(self):
        self.check(simulated_hub())

    def test_docs_simulation(self):
        self.check(docs_hub())

    def test_console_never_runs_git_inventory_sync(self):
        # The only writer of inventory/devices is inventory_sync.sync (scripts/sync_inventory.py). The console
        # must not call it: its simulated and test hubs would export whatever their database holds.
        pattern = re.compile(r'inventory_sync\s+import[^\n]*\bsync\b|inventory_sync\.sync\(|sync_inventory|inventory[\'"]?\s*/\s*[\'"]?devices')
        for path in paths.CONSOLE.rglob('*.py'):
            if 'tests' in path.relative_to(paths.CONSOLE).parts:
                continue
            text = path.read_text(encoding='utf-8')
            self.assertIsNone(pattern.search(text), f'{path.relative_to(paths.ROOT)} touches the Git inventory')


if __name__ == '__main__':
    unittest.main()
