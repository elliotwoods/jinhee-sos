"""Every documentation scenario stages and settles in-process (the same code docshots.py drives over the API)."""
import unittest

import support  # noqa: F401

import docscenes
import simdocs


class DocScenesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hub = support.docs_hub()
        docscenes.base(cls.hub)

    @classmethod
    def tearDownClass(cls):
        cls.hub.shutdown(force=True)

    def test_every_scenario_settles(self):
        failures = []
        for s in docscenes.SCENARIOS:
            with self.subTest(scenario=s['id']):
                docscenes.run_setup(self.hub, s['id'])
                ok = docscenes.wait(self.hub, lambda: docscenes.is_settled(self.hub, s['id']), timeout=s['settle'])
                if not ok:
                    failures.append(s['id'])
                    rules = [c['rule'] for c in (self.hub.sections.get('advisor') or {}).get('suggestions', [])]
                    recent = [e.get('text') for e in list(self.hub.notable)[-8:]]
                    self.fail(f'{s["id"]} did not settle · advisor {rules} · recent {recent}')
                route = docscenes.route(self.hub, s)
                self.assertTrue(route.startswith('#/'), route)
                self.assertIn('still=1', route)
        self.assertEqual(failures, [])

    def test_ids_unique_and_ordered(self):
        ids = [s['id'] for s in docscenes.SCENARIOS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(s['settled'] for s in docscenes.SCENARIOS), 'every scenario needs a settled predicate')

    def test_bench_boards(self):
        sim = self.hub._sim
        for key in ('station', 'plate', 'pool', 'blank', 'cube', 'cube45', 'radio', 'mainshow'):
            self.assertIn(key, sim)
        self.assertIsInstance(sim['station'], simdocs.DocStation)
        self.assertEqual(self.hub.store.published()['version'], 32)


if __name__ == '__main__':
    unittest.main()
