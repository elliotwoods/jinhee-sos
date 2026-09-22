"""`sync.check` builds the record-by-record plan against a fake web inventory (nothing is written)."""
import sys
import unittest
from pathlib import Path

import support  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'pairing_station' / 'tests'))
from fake_web_inventory import FakeWebInventory  # noqa: E402

import web_client  # noqa: E402

import commands  # noqa: E402
import commands_extra  # noqa: E402,F401


class SyncCheckTest(unittest.TestCase):
    def setUp(self):
        self.server = FakeWebInventory()
        import jobs.sync as sync_jobs
        self.sync_jobs, self.previous_client = sync_jobs, sync_jobs.client
        sync_jobs.client = lambda hub, password=web_client.STORED: web_client.WebClient(server=self.server.url, password='test-password',
                                                                                        client='NCT Console test')
        self.hub = support.simulated_hub()

    def tearDown(self):
        self.hub.shutdown(force=True)
        self.server.close()
        self.sync_jobs.client = self.previous_client

    def test_plan_lists_local_upload(self):
        commands.run(self.hub, 'sync.check', {})
        ok = support.tick_until(self.hub, lambda: self.hub.sync.get('plan') is not None, timeout=15)
        self.assertTrue(ok, self.hub.sync.get('last_error'))
        plan = self.hub.sync['plan']
        self.assertGreaterEqual(plan['upload'], 1, plan)
        macs = {row['mac'] for row in plan['rows']}
        self.assertIn(self.hub._sim['known_mac'], macs)
        self.assertTrue(all(row['change'] in ('upload', 'download', 'both') for row in plan['rows']))
        self.assertIn('plan', support.section(self.hub, 'sync'))
        commands.run(self.hub, 'sync.plan_clear', {})
        self.assertIsNone(self.hub.sync['plan'])


if __name__ == '__main__':
    unittest.main()
