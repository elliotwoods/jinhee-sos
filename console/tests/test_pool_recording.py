"""Guided recording on a PoolZone radio: plan → reached → hold → analysis/proposal (simulated samples)."""
import unittest

import support  # noqa: F401

import docscenes


class PoolRecordingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hub = support.docs_hub()
        docscenes.base(cls.hub)

    @classmethod
    def tearDownClass(cls):
        cls.hub.shutdown(force=True)

    def session(self):
        return docscenes.session(self.hub, 'pool')

    def test_recording_flow(self):
        hub = self.hub
        d = docscenes.device(hub, 'pool')
        docscenes.wait(hub, lambda: self.session() and self.session().ready, timeout=6)
        s = self.session()
        with self.assertRaises(ValueError):
            s.record_reached()
        plan = docscenes.cmd(hub, 'pool.record_start', stride=22, hold=0.3, device=d.id)
        self.assertEqual(plan['steps'], [1, 23])
        self.assertEqual(s.rec['state'], 'move')
        self.assertTrue(hub._sim['pool'].raw_stream)
        for _ in range(2):
            docscenes.wait(hub, lambda: s.rec and s.rec['state'] == 'move', timeout=3)
            docscenes.cmd(hub, 'pool.record_reached', device=d.id)
            self.assertEqual(s.rec['state'], 'hold')
            docscenes.wait(hub, lambda: not s.rec or s.rec['state'] == 'move', timeout=3)
        self.assertIsNone(s.rec)
        self.assertFalse(hub._sim['pool'].raw_stream)
        self.assertIsNotNone(s.recording)
        self.assertEqual(len(s.recording['steps']), 2)
        self.assertTrue(all(step['samples'] for step in s.recording['steps']), 'each hold collected raw samples')
        snap = s.snapshot()['recording']
        self.assertFalse(snap['live'])
        self.assertTrue(snap['has_recording'])
        self.assertIn('Recording', snap['note'])
        # The fixed-distance fake gives identical readings at both ticks, so the analysis rightly refuses a proposal
        # or produces one; either way the session says which in its note and never raises.
        if s.proposal:
            applied = docscenes.cmd(hub, 'pool.record_apply', save=False, points=False, device=d.id)
            self.assertTrue(applied['tuning'])

    def test_abort_turns_raw_off(self):
        hub = self.hub
        d = docscenes.device(hub, 'pool')
        s = self.session()
        docscenes.cmd(hub, 'pool.record_start', stride=4, hold=5, device=d.id)
        self.assertTrue(hub._sim['pool'].raw_stream)
        docscenes.cmd(hub, 'pool.record_abort', device=d.id)
        self.assertIsNone(s.rec)
        support.run_ticks(hub, 5)
        self.assertFalse(hub._sim['pool'].raw_stream)


if __name__ == '__main__':
    unittest.main()
