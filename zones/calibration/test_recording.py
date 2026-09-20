"""Recording plan, analysis, auto-tuning and the firmware-mirroring simulator."""
import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recording


def synthetic(noise=1.0, spikes=0.0, dropouts=0, period=20, ticks=None,
              stride=4, settle=3.0, hold=5.0, seed=1):
    """`settle` models the operator-paced move that precedes each confirmed hold."""
    """A recording of a slider parked at each planned tick, with known noise."""
    rng = random.Random(seed)
    ticks = ticks or [383 - (383-43)*i/22 for i in range(23)]
    steps, now = [], 0.0
    previous = ticks[0]
    for step in recording.plan_steps(stride, hold):
        target = ticks[step['tick']-1]
        samples = []
        settle_end = now + settle*1000
        hold_end = settle_end + step['hold']*1000
        t = now
        while t < hold_end:
            if t < settle_end:  # linear move from the previous tick
                mm = previous + (target-previous) * (t-now) / max(1.0, settle_end-now)
            else:
                mm = target
            value = mm + rng.gauss(0, noise)
            if spikes and rng.random() < spikes:
                value += rng.choice([-1, 1]) * rng.uniform(20, 60)
            samples.append(dict(t=round(t), mm=round(value, 2), st=0))
            t += period
        for _ in range(dropouts):  # a burst of invalid readings inside the hold
            index = rng.randrange(len(samples)//2, len(samples))
            samples[index] = dict(t=samples[index]['t'], mm=None, st=4)
        steps.append(dict(tick=step['tick'], samples=samples, hold_from=round(settle_end)))
        now, previous = hold_end, target
    return dict(steps=steps, ticks=23, created='test')


class PlanTest(unittest.TestCase):
    def test_endpoints_always_included(self):
        self.assertEqual([s['tick'] for s in recording.plan_steps(4)], [1, 5, 9, 13, 17, 21, 23])
        self.assertEqual([s['tick'] for s in recording.plan_steps(5)], [1, 6, 11, 16, 21, 23])
        self.assertEqual([s['tick'] for s in recording.plan_steps(1)], list(range(1, 24)))
        self.assertEqual([s['tick'] for s in recording.plan_steps(11)], [1, 12, 23])

    def test_duration_is_an_estimate_since_moves_are_operator_paced(self):
        self.assertEqual(recording.plan_duration(recording.plan_steps(4)), 56.0)
        self.assertEqual(recording.plan_duration(recording.plan_steps(4), move_estimate=0), 35.0)

    def test_rejects_an_impossible_plan(self):
        for bad in (dict(stride=0), dict(hold=-1), dict(hold=0)):
            with self.assertRaises(ValueError):
                recording.plan_steps(**bad)

    def test_steps_carry_no_move_deadline(self):
        # Arrival is confirmed by the operator, so nothing in the plan may time the move.
        for step in recording.plan_steps(4):
            self.assertNotIn('settle', step)


class ValidationTest(unittest.TestCase):
    def test_defaults_are_accepted(self):
        self.assertIsNone(recording.valid(recording.DEFAULTS))

    def test_mirrors_the_firmware_limits(self):
        for key, value in [('budget', 5), ('budget', 201), ('median', 4), ('median', 0),
                           ('enter', 0.6), ('exit', 0.95), ('dropout', 10),
                           ('mincutoff', 0.0), ('confirm', 5000)]:
            self.assertIsNotNone(recording.valid(dict(recording.DEFAULTS, **{key: value})),
                                 f'{key}={value} should be rejected')
        self.assertIsNotNone(recording.valid(dict(recording.DEFAULTS, exit=0.2, enter=0.33)))
        self.assertIsNotNone(recording.valid(dict(recording.DEFAULTS, interval=20, budget=20)))
        self.assertIsNone(recording.valid(dict(recording.DEFAULTS, interval=21, budget=20)))
        self.assertIsNotNone(recording.valid(dict(recording.DEFAULTS, mincutoff=float('nan'))))


class AnalysisTest(unittest.TestCase):
    def test_recovers_the_tick_positions(self):
        report = recording.analyse(synthetic(noise=1.0))
        expected = [383 - (383-43)*i/22 for i in range(23)]
        for got, want in zip(report['ticks'], expected):
            self.assertLess(abs(got-want), 1.5)
        self.assertEqual(len(report['ticks']), 23)
        self.assertFalse(report['warnings'])
        self.assertAlmostEqual(report['sample_period_ms'], 20, delta=1)

    def test_measures_noise_and_outliers(self):
        quiet = recording.analyse(synthetic(noise=0.5))
        noisy = recording.analyse(synthetic(noise=4.0))
        self.assertLess(quiet['noise'], noisy['noise'])
        self.assertGreater(recording.analyse(synthetic(spikes=0.05))['outlier_rate'],
                           recording.analyse(synthetic(spikes=0.0))['outlier_rate'])

    def test_reports_dropout_runs(self):
        report = recording.analyse(synthetic(dropouts=6))
        self.assertGreater(report['worst_dropout_ms'], 0)
        self.assertTrue(report['dropout_runs_ms'])

    def test_flags_a_step_that_never_settled(self):
        data = synthetic(noise=0.5)
        drifting = data['steps'][2]
        for i, sample in enumerate(drifting['samples']):
            if sample['t'] >= drifting['hold_from'] and sample['mm'] is not None:
                sample['mm'] += i * 0.5  # never actually came to rest
        report = recording.analyse(data)
        self.assertTrue(any('still moving' in w for w in report['warnings']))

    def test_rejects_an_unusable_recording(self):
        with self.assertRaises(ValueError):
            recording.analyse(dict(steps=[]))


class SelectTest(unittest.TestCase):
    ticks = [100 + 10*i for i in range(23)]

    def test_matches_the_firmware_hysteresis(self):
        self.assertEqual(recording.select(self.ticks, 104.0, -1, .33, .45), -1)
        self.assertEqual(recording.select(self.ticks, 104.0, 1, .33, .45), 1)
        # An exit fraction above 0.5 must genuinely widen, not silently cap.
        self.assertEqual(recording.select(self.ticks, 107.0, 1, .33, .8), 1)
        self.assertEqual(recording.select(self.ticks, 107.0, -1, .33, .8), 2)

    def test_a_held_member_is_always_releasable(self):
        for frac in (0.5, 0.8, 0.9, 5.0):
            self.assertEqual(recording.select(self.ticks, 110.0, 1, .33, frac), 2)

    def test_equal_fractions_reproduce_the_plain_mapping(self):
        for held in range(-1, 24):
            for step in range(0, 2400):
                mm = 90 + step * 0.1
                self.assertEqual(recording.select(self.ticks, mm, held, .33, .33),
                                 recording.select(self.ticks, mm, -1, .33, .33))


class SimulateTest(unittest.TestCase):
    def test_quiet_slider_never_flickers(self):
        data = synthetic(noise=0.3)
        result = recording.simulate(data, recording.DEFAULTS)
        self.assertEqual(result['flicker'], 0)
        self.assertEqual(result['missed'], 0)

    def test_tuning_removes_flicker_that_a_fast_filter_leaves(self):
        # Noise comparable to the acceptance window, with the filter effectively off.
        data = synthetic(noise=3.5, seed=7)
        analysis = recording.analyse(data)
        loose = dict(recording.DEFAULTS, mincutoff=20.0, median=1, exit=0.33, release=0)
        before = recording.simulate(data, loose, analysis['ticks'])
        fitted = recording.fit_budget(data, analysis, recording.recommend(analysis)['tuning'])
        after = recording.simulate(data, fitted['tuning'], analysis['ticks'])
        self.assertGreater(before['flicker'], 10)
        # The whole point: no output changes once the slider has settled.
        self.assertEqual(after['flicker'], 0)
        self.assertTrue(fitted['met'])
        self.assertLessEqual(after['settle_ms'], 300)

    def test_dropouts_do_not_drop_the_member(self):
        data = synthetic(noise=0.3, dropouts=4)
        tolerant = dict(recording.DEFAULTS, dropout=400)
        intolerant = dict(recording.DEFAULTS, dropout=50)
        self.assertLessEqual(recording.simulate(data, tolerant)['flicker'],
                             recording.simulate(data, intolerant)['flicker'])

    def test_reports_settling_latency(self):
        result = recording.simulate(synthetic(noise=0.5), recording.DEFAULTS)
        self.assertIsNotNone(result['settle_ms'])
        self.assertGreaterEqual(result['settle_ms'], 0)


class RecommendTest(unittest.TestCase):
    def test_noisier_input_gets_more_smoothing(self):
        quiet = recording.recommend(recording.analyse(synthetic(noise=0.3)))['tuning']
        noisy = recording.recommend(recording.analyse(synthetic(noise=5.0)))['tuning']
        self.assertLessEqual(noisy['mincutoff'], quiet['mincutoff'])

    def test_median_only_when_outliers_are_present(self):
        clean = recording.recommend(recording.analyse(synthetic(spikes=0.0)))['tuning']
        spiky = recording.recommend(recording.analyse(synthetic(spikes=0.05)))['tuning']
        self.assertEqual(clean['median'], 1)
        self.assertGreater(spiky['median'], 1)

    def test_recommendations_are_always_firmware_valid(self):
        for noise in (0.2, 1.0, 3.0, 8.0, 20.0):
            result = recording.recommend(recording.analyse(synthetic(noise=noise)))
            self.assertIsNone(recording.valid(result['tuning']), f'noise={noise}')
            self.assertTrue(result['notes'])

    def test_impossible_noise_is_reported_not_hidden(self):
        result = recording.recommend(recording.analyse(synthetic(noise=40.0)))
        self.assertTrue(any('too large' in w for w in result['warnings']))

    def test_exit_exceeds_enter_so_hysteresis_is_real(self):
        tuning = recording.recommend(recording.analyse(synthetic(noise=2.0)))['tuning']
        self.assertGreater(tuning['exit'], tuning['enter'])

    def test_fit_budget_reports_the_frontier(self):
        data = synthetic(noise=2.0)
        analysis = recording.analyse(data)
        fitted = recording.fit_budget(data, analysis, recording.recommend(analysis)['tuning'])
        self.assertTrue(fitted['frontier'])
        self.assertIsNone(recording.valid(fitted['tuning']))
        self.assertIn('met', fitted)


class StorageTest(unittest.TestCase):
    def test_round_trip(self):
        import tempfile
        data = synthetic(noise=0.5)
        with tempfile.TemporaryDirectory() as folder:
            path = recording.save(data, folder)
            self.assertEqual(recording.load(path)['steps'][0]['tick'], 1)
        with self.assertRaises(ValueError):
            import json
            with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as handle:
                json.dump({'nope': 1}, handle)
            recording.load(handle.name)


if __name__ == '__main__':
    unittest.main()
