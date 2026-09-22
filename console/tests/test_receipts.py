"""cube.recover_receipts imports a saved receipt for a run whose database save failed."""
import json
import tempfile
import unittest
from pathlib import Path

import support
import commands
import commands_extra


class ReceiptsTest(unittest.TestCase):
    def setUp(self):
        self.hub = support.simulated_hub()
        self.runs = Path(tempfile.mkdtemp(prefix='nct-receipts-')) 
        self.previous = commands_extra.RUNS
        commands_extra.RUNS = self.runs

    def tearDown(self):
        commands_extra.RUNS = self.previous
        self.hub.shutdown(force=True)

    def test_recovers_only_runs_still_marked_running(self):
        db = self.hub.db
        manifest = dict(version='v1.4.1-USB.2', build_hash='abc')
        db.start('run-1', '/dev/sim.cube', manifest, 'log')
        db.start('run-2', '/dev/sim.cube', manifest, 'log')
        db.update_run('run-2', result='failed', detail='esptool failed')
        for ident, result in (('run-1', 'success'), ('run-2', 'success'), ('run-x', 'success')):
            folder = self.runs / ident
            folder.mkdir()
            (folder / 'receipt.json').write_text(json.dumps(dict(id=ident, result=result, detail='Verified after reboot',
                                                                  finished_at='2026-09-23 10:00:00')), encoding='utf-8')
        out = commands.run(self.hub, 'cube.recover_receipts', {})
        self.assertEqual(out['recovered'], 2, out)   # run-1 (running) and run-2 (failed → the receipt says success)
        rows = {r[0]: r[1] for r in db.conn.execute('SELECT id, result FROM flash_runs')}
        self.assertEqual(rows['run-1'], 'success')
        self.assertEqual(rows['run-2'], 'success')
        self.assertNotIn('run-x', rows)
        again = commands.run(self.hub, 'cube.recover_receipts', {})
        self.assertEqual(again['recovered'], 0)


if __name__ == '__main__':
    unittest.main()
