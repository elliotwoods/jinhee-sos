#!/usr/bin/env python3
"""Guided PoolZone slider recording, calibration extraction and filter auto-tuning.

Pure functions: no Tk, no serial. The GUI drives `plan_steps` and collects samples;
everything else runs offline against a saved recording, so a tune can be re-derived
without the hardware present.

`simulate` mirrors the firmware pipeline in PoolZone.ino/SliderTuning.h. Keep the two
in step: it is what justifies a parameter set before anything is written to flash.
"""
import json
import math
import time
from pathlib import Path

TICKS = 23

# Firmware defaults, mirroring SliderTuning.h. Values are what TUNE SET accepts.
DEFAULTS = dict(mincutoff=0.8, beta=0.03, dcutoff=1.0, enter=0.33, exit=0.45,
                confirm=50, release=120, dropout=400, budget=20, interval=0, median=3)
# key -> (label, is_integer, low, high)
FIELDS = {
    'mincutoff': ('Min cutoff (Hz)', False, 0.05, 20.0),
    'beta': ('Beta (Hz per mm/s)', False, 0.0, 5.0),
    'dcutoff': ('Derivative cutoff (Hz)', False, 0.05, 20.0),
    'enter': ('Enter window (fraction)', False, 0.05, 0.5),
    'exit': ('Exit window (fraction)', False, 0.05, 0.9),
    'confirm': ('Confirm (ms)', True, 0, 1000),
    'release': ('Release (ms)', True, 0, 1000),
    'dropout': ('Dropout tolerance (ms)', True, 50, 1000),
    'budget': ('Sensor timing budget (ms)', True, 10, 200),
    'interval': ('Inter-measurement (ms)', True, 0, 1000),
    'median': ('Median window (samples)', True, 1, 9),
}
# Matches SliderTuning::valid(); the firmware rejects anything else.
JSON_KEYS = dict(mincutoff='min_cutoff_hz', beta='beta', dcutoff='derivative_cutoff_hz',
                 enter='enter_frac', exit='exit_frac', confirm='confirm_ms',
                 release='release_ms', dropout='dropout_ms', budget='timing_budget_ms',
                 interval='interval_ms', median='median_window')


def valid(tuning):
    """Mirror of SliderTuning::valid(). Returns a reason, or None when acceptable."""
    for key, (label, whole, low, high) in FIELDS.items():
        value = tuning.get(key)
        if value is None or not isinstance(value, (int, float)) or not math.isfinite(value):
            return f'{label} is missing or not a number'
        if not low <= value <= high:
            return f'{label} must be {low}–{high}'
        if whole and int(value) != value:
            return f'{label} must be a whole number'
    if tuning['exit'] < tuning['enter']:
        return 'Exit window must be at least the enter window, or the hysteresis inverts'
    if tuning['interval'] and tuning['interval'] <= tuning['budget']:
        return 'Inter-measurement must be 0 or above the timing budget'
    if tuning['median'] % 2 == 0:
        return 'Median window must be odd'
    return None


def plan_steps(stride=4, hold=5.0, ticks=TICKS):
    """Ticks to visit: both endpoints plus every `stride`th between them.

    Endpoints bound the whole slider, so they are always included even when the stride
    does not land on the last tick.

    There is no move deadline: the operator confirms arrival at each tick, and only the
    hold is timed. A fixed countdown would silently record a half-finished move as if it
    were a settled position, which is exactly the data that poisons a calibration.
    """
    if stride < 1 or ticks < 2:
        raise ValueError('Stride must be at least 1.')
    if hold <= 0:
        raise ValueError('Hold time must be positive.')
    visited = list(range(1, ticks + 1, stride))
    if visited[-1] != ticks:
        visited.append(ticks)
    return [dict(tick=t, hold=float(hold)) for t in visited]


def plan_duration(steps, move_estimate=3.0):
    """Rough wall-clock estimate. The move time is operator-paced, so it is a guess."""
    return sum(s['hold'] + move_estimate for s in steps)


# ---------------------------------------------------------------- analysis

def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    if not n:
        raise ValueError('No samples.')
    return ordered[n//2] if n % 2 else (ordered[n//2 - 1] + ordered[n//2]) / 2


def _mad(values, centre):
    """Median absolute deviation, scaled to be comparable with a standard deviation."""
    return 1.4826 * _median([abs(v - centre) for v in values])


def _high_frequency_sigma(values):
    """Noise sigma from successive differences.

    This is what the filter actually attenuates, and unlike the spread about the mean
    it is not inflated by slow drift, so it stays usable on a step the operator was
    still adjusting. For white noise the differences have sigma*sqrt(2).
    """
    diffs = [b - a for a, b in zip(values, values[1:])]
    if not diffs:
        return 0.0
    return _mad(diffs, 0.0) / math.sqrt(2)


def _runs(flags):
    """Lengths of consecutive True runs."""
    out, current = [], 0
    for flag in flags:
        if flag:
            current += 1
        elif current:
            out.append(current)
            current = 0
    if current:
        out.append(current)
    return out


def analyse(recording):
    """Per-step distance and noise from the hold windows only.

    A step whose hold window is not stationary is flagged rather than silently folded
    into the calibration: a fumbled move would otherwise poison a tick.
    """
    steps = []
    for step in recording['steps']:
        samples = [s for s in step['samples'] if s.get('t') is not None]
        hold = [s for s in samples if s['t'] >= step['hold_from']]
        good = [s for s in hold if s.get('mm') is not None]
        entry = dict(tick=step['tick'], samples=len(hold), valid=len(good), warnings=[])
        if len(good) < 5:
            entry['warnings'].append('Too few valid readings to trust this tick.')
            entry.update(mm=None, noise=None, span=None, drift=None)
            steps.append(entry)
            continue
        values = [s['mm'] for s in good]
        centre = _median(values)
        noise = _high_frequency_sigma(values)
        # Compare the two halves of the hold: a real drift shows as a shifted median.
        half = len(values) // 2
        drift = abs(_median(values[:half]) - _median(values[half:])) if half >= 2 else 0.0
        entry.update(mm=round(centre, 2), noise=round(noise, 3),
                     span=round(max(values) - min(values), 2), drift=round(drift, 2))
        if drift > max(3 * noise, 1.0) + 0.5:
            entry['warnings'].append('Slider was still moving during the hold; re-record this step.')
        if len(good) < len(hold) * 0.8:
            entry['warnings'].append('Many invalid readings here; check sensor aim and ambient light.')
        steps.append(entry)

    usable = [s for s in steps if s['mm'] is not None]
    if len(usable) < 2:
        raise ValueError('Need at least two usable steps; re-record.')

    # Invalid-reading run lengths across the whole recording, in milliseconds.
    every = [s for step in recording['steps'] for s in step['samples']]
    every.sort(key=lambda s: s['t'])
    period = _sample_period(every)
    dropout_runs = [n * period for n in _runs([s.get('mm') is None for s in every])]

    # Peak speed before each confirmed hold: how fast the operator actually moves.
    speeds = []
    for step in recording['steps']:
        moving = [s for s in step['samples'] if s.get('mm') is not None and s['t'] < step['hold_from']]
        for a, b in zip(moving, moving[1:]):
            dt = (b['t'] - a['t']) / 1000.0
            if dt > 0:
                speeds.append(abs(b['mm'] - a['mm']) / dt)
    speeds.sort()

    ticks = interpolate_ticks({s['tick']: s['mm'] for s in usable})
    gaps = [abs(b - a) for a, b in zip(ticks, ticks[1:])]
    return dict(
        steps=steps,
        ticks=ticks,
        points={s['tick']: s['mm'] for s in usable},
        min_gap=round(min(gaps), 2),
        noise=round(max((s['noise'] for s in usable), default=0.0), 3),
        sample_period_ms=round(period, 1),
        dropout_runs_ms=[round(v) for v in dropout_runs],
        worst_dropout_ms=round(max(dropout_runs, default=0.0)),
        move_speed=round(speeds[int(len(speeds)*0.9)] if speeds else 0.0, 1),
        outlier_rate=_outlier_rate(recording),
        warnings=[f"Tick {s['tick']}: {w}" for s in steps for w in s['warnings']],
    )


def _sample_period(samples):
    deltas = [b['t'] - a['t'] for a, b in zip(samples, samples[1:]) if 0 < b['t'] - a['t'] < 500]
    return _median(deltas) if deltas else 20.0


def _outlier_rate(recording):
    """Fraction of hold-window readings far from their local median.

    These are the spikes a median prefilter removes and an EMA cannot.
    """
    total = flagged = 0
    for step in recording['steps']:
        values = [s['mm'] for s in step['samples']
                  if s.get('mm') is not None and s['t'] >= step['hold_from']]
        if len(values) < 5:
            continue
        centre = _median(values)
        scale = _high_frequency_sigma(values) or 0.5
        total += len(values)
        flagged += sum(1 for v in values if abs(v - centre) > 5 * scale)
    return round(flagged / total, 4) if total else 0.0


def interpolate_ticks(points):
    """Linear interpolation between control points; endpoints must be present."""
    ordered = sorted(points.items())
    if not ordered or ordered[0][0] != 1 or ordered[-1][0] != TICKS:
        raise ValueError(f'Control points at ticks 1 and {TICKS} are required.')
    result = [0.0] * TICKS
    for (a, av), (b, bv) in zip(ordered, ordered[1:]):
        for i in range(a, b + 1):
            result[i-1] = round(av + (bv - av) * (i - a) / (b - a), 2)
    return result


# ---------------------------------------------------------------- simulation

class _OneEuro:
    """Mirror of OneEuroFilter in zones/firmware/PoolZone/OneEuroFilter.h."""

    def __init__(self, mincutoff, beta, dcutoff, gap_ms):
        self.mincutoff, self.beta, self.dcutoff, self.gap = mincutoff, beta, dcutoff, gap_ms
        self.ready = False
        self.t = self.raw = self.value = self.speed = 0.0

    @staticmethod
    def _alpha(cutoff, dt):
        r = 2 * math.pi * cutoff * dt
        return r / (1 + r)

    def reset(self):
        self.ready = False

    def update(self, raw, now):
        elapsed = now - self.t
        if not self.ready or elapsed > self.gap:
            self.ready = True
            self.t, self.raw, self.value, self.speed = now, raw, raw, 0.0
            return raw
        if elapsed <= 0:
            return self.value
        dt = elapsed / 1000.0
        derivative = (raw - self.raw) / dt
        self.speed += self._alpha(self.dcutoff, dt) * (derivative - self.speed)
        cutoff = self.mincutoff + self.beta * abs(self.speed)
        self.value += self._alpha(cutoff, dt) * (raw - self.value)
        self.raw, self.t = raw, now
        return self.value


class _Median:
    """Mirror of MedianFilter in zones/firmware/PoolZone/OneEuroFilter.h."""

    def __init__(self, window):
        self.window = max(1, min(9, window | 1))
        self.ring = []

    def reset(self):
        self.ring = []

    def update(self, raw):
        if self.window <= 1:
            return raw
        self.ring.append(raw)
        if len(self.ring) > self.window:
            self.ring.pop(0)
        return _median(self.ring)


def _window(ticks, index, distance, frac):
    """Mirror of SliderCalibration::window()."""
    direction = 1 if (distance - ticks[index]) * (ticks[-1] - ticks[0]) >= 0 else -1
    neighbour = min(max(index + direction, 0), TICKS - 1)
    if neighbour == index:
        neighbour = index - 1 if index else 1
    return abs(ticks[neighbour] - ticks[index]) * frac


def select(ticks, distance, held, enter, exit_):
    """Mirror of SliderCalibration::select(): the held member is tested first."""
    if distance is None or not math.isfinite(distance):
        return -1
    enter = 0.33 if not 0 < enter <= 0.5 else enter
    exit_ = max(enter, min(0.9, exit_))
    if 1 <= held <= TICKS and abs(distance - ticks[held-1]) <= _window(ticks, held-1, distance, exit_) + 1e-4:
        return held
    nearest = min(range(TICKS), key=lambda i: abs(distance - ticks[i]))
    return nearest + 1 if abs(distance - ticks[nearest]) <= _window(ticks, nearest, distance, enter) + 1e-4 else -1


def simulate(recording, tuning, ticks=None):
    """Replay recorded raw samples through the firmware pipeline.

    Reports the two objectives that matter, because they trade against each other:
    flicker (index changes while the slider is held still) and latency (how long after
    the slider stops the correct member is confirmed).
    """
    ticks = ticks or analyse(recording)['ticks']
    median = _Median(int(tuning['median']))
    euro = _OneEuro(tuning['mincutoff'], tuning['beta'], tuning['dcutoff'], tuning['dropout'])
    confirmed, candidate, candidate_since, last_good = -1, -1, 0, None
    flicker, settles, missed = 0, [], 0

    for step in recording['steps']:
        target = step['tick']
        settled_at = None
        for sample in sorted(step['samples'], key=lambda s: s['t']):
            now, mm = sample['t'], sample.get('mm')
            before = confirmed
            if mm is None:
                # Dropout tolerance: hold the member unless the gap exceeds dropoutMs.
                if last_good is None or now - last_good > tuning['dropout']:
                    euro.reset(); median.reset()
                    confirmed = candidate = -1
                    candidate_since = now
            else:
                last_good = now
                value = euro.update(median.update(mm), now)
                member = select(ticks, value, confirmed, tuning['enter'], tuning['exit'])
                if member != candidate:
                    candidate, candidate_since = member, now
                held = now - candidate_since
                if confirmed >= 1 and candidate != confirmed and held >= tuning['release']:
                    confirmed = -1
                if confirmed < 1 and candidate >= 1 and held >= tuning['confirm']:
                    confirmed = candidate
            if now >= step['hold_from']:
                if settled_at is None:
                    # Arriving at the target is expected, not flicker.
                    if confirmed == target:
                        settled_at = now
                elif confirmed != before:
                    # Any change after the slider had already settled is flicker.
                    flicker += 1
        if settled_at is None:
            missed += 1
        else:
            settles.append(settled_at - step['hold_from'])

    return dict(flicker=flicker, missed=missed,
                settle_ms=round(max(settles), 1) if settles else None,
                settle_median_ms=round(_median(settles), 1) if settles else None)


# ---------------------------------------------------------------- recommendation

def _filtered_noise(sigma, cutoff, period_ms, median_window):
    """Steady-state noise out of median + EMA, in mm.

    At rest the One Euro cutoff sits at its minimum, so the EMA identity
    sigma_out = sigma_in * sqrt(a / (2 - a)) applies. A median of w samples reduces
    Gaussian noise by roughly sqrt(2/(pi*w)) * sqrt(w) -> use the standard
    sigma * sqrt(pi/(2*w)) approximation for the median of w samples.
    """
    if median_window > 1:
        sigma *= math.sqrt(math.pi / (2 * median_window))
    dt = period_ms / 1000.0
    r = 2 * math.pi * cutoff * dt
    a = r / (1 + r)
    return sigma * math.sqrt(a / (2 - a))


def recommend(analysis, settle_budget_ms=300, current=None):
    """Pick parameters that stop flicker without exceeding the settling budget.

    This is a constrained choice, not noise minimisation: smoothing trades directly
    against responsiveness, so the returned notes say what was traded and why.
    """
    base = dict(current or DEFAULTS)
    out = dict(base)
    notes, unmet = [], []
    period = analysis['sample_period_ms']
    half_gap = analysis['min_gap'] / 2.0
    sigma = analysis['noise']

    # Median window: only worth its group delay if real outliers are present.
    rate = analysis['outlier_rate']
    out['median'] = 5 if rate > 0.01 else (3 if rate > 0.001 else 1)
    delay = (out['median'] - 1) / 2 * period
    notes.append(f"Median {out['median']}: {rate*100:.2f}% of held readings were outliers "
                 f"({delay:.0f} ms group delay).")

    # Enter window stays at the firmware default unless the ticks are unusually tight.
    out['enter'] = DEFAULTS['enter']

    # Minimum cutoff: filtered noise must fit well inside the acceptance window, but a
    # lower cutoff costs settling time. Walk candidates from responsive to smooth.
    target = half_gap * out['enter'] / 3.0  # 3 sigma inside the enter window
    chosen = None
    for cutoff in [2.0, 1.5, 1.2, 1.0, 0.8, 0.6, 0.5, 0.4, 0.3, 0.25, 0.2, 0.15, 0.1]:
        if _filtered_noise(sigma, cutoff, period, out['median']) <= target:
            chosen = cutoff
            break
    if chosen is None:
        chosen = 0.1
        unmet.append('Sensor noise is too large for the tick spacing even at the '
                     'lowest cutoff. Improve the sensor mounting or raise the timing budget.')
    out['mincutoff'] = chosen
    residual = _filtered_noise(sigma, chosen, period, out['median'])
    notes.append(f"Min cutoff {chosen} Hz: {sigma:.2f} mm raw noise becomes "
                 f"{residual:.2f} mm filtered, against a {half_gap*out['enter']:.2f} mm window.")

    # Beta: keep the cutoff responsive at the speed the operator actually moves.
    speed = analysis['move_speed']
    if speed > 20:
        out['beta'] = round(min(1.0, max(0.005, (6.0 - chosen) / speed)), 4)
        notes.append(f"Beta {out['beta']}: reaches ~6 Hz at the observed {speed:.0f} mm/s move speed.")
    else:
        out['beta'] = DEFAULTS['beta']
        notes.append('Beta left at the default: no clear movement was recorded.')

    # Exit window: noise must not be able to push a held member back out.
    margin = 3 * residual / half_gap if half_gap else 0
    out['exit'] = round(min(0.9, max(out['enter'] + 0.05, out['enter'] + margin)), 3)
    notes.append(f"Exit {out['exit']}: {3*residual:.2f} mm of filtered noise cannot leave "
                 f"a held member's window.")

    # Dropout tolerance from the worst invalid run actually observed.
    worst = analysis['worst_dropout_ms']
    out['dropout'] = int(min(1000, max(200, round(worst * 1.5 / 50) * 50))) if worst else DEFAULTS['dropout']
    notes.append(f"Dropout {out['dropout']} ms: worst observed run of invalid readings was {worst:.0f} ms.")

    # Confirm/release must both outlast the filter's residual wobble.
    out['confirm'] = DEFAULTS['confirm']
    out['release'] = int(max(DEFAULTS['release'], round(4 * period / 10) * 10))
    notes.append(f"Release {out['release']} ms: a held member survives several noisy samples.")

    if analysis['warnings']:
        unmet.extend(analysis['warnings'])
    return dict(tuning=out, notes=notes, warnings=unmet, settle_budget_ms=settle_budget_ms)


def fit_budget(recording, analysis, recommended, settle_budget_ms=300):
    """Relax smoothing until the settling budget is met, and say what was given up.

    Returns the chosen tuning plus the frontier that was explored, so an impossible
    combination is reported rather than silently smoothed into an unusable interaction.
    """
    ticks = analysis['ticks']
    frontier = []
    cutoffs = sorted({recommended['mincutoff'], 0.1, 0.15, 0.2, 0.25, 0.3, 0.4,
                      0.5, 0.6, 0.8, 1.0, 1.5, 2.0})
    for cutoff in cutoffs:
        trial = dict(recommended, mincutoff=cutoff)
        result = simulate(recording, trial, ticks)
        within = (result['settle_ms'] is not None and not result['missed']
                  and result['settle_ms'] <= settle_budget_ms)
        frontier.append(dict(mincutoff=cutoff, within_budget=within, **result))

    # Least flicker among the options that meet the settling budget, tie-broken by the
    # faster settle. Minimising flicker alone would always pick the heaviest smoothing.
    affordable = [f for f in frontier if f['within_budget']]
    pool = affordable or frontier
    best = min(pool, key=lambda f: (f['flicker'], f['settle_ms'] if f['settle_ms'] is not None else 1e9))
    chosen = dict(recommended, mincutoff=best['mincutoff'])
    return dict(tuning=chosen, frontier=frontier, best=best,
                met=bool(affordable) and best['flicker'] == 0,
                budget_met=bool(affordable), settle_budget_ms=settle_budget_ms)


# ---------------------------------------------------------------- storage

def save(recording, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"recording-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(recording, indent=2), encoding='utf-8')
    return path


def load(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if 'steps' not in data:
        raise ValueError('Not a PoolZone recording.')
    return data
