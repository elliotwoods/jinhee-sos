"""A PoolZone slider radio on USB: zone console + calibration/tuning console + leased override.

The lease (HOST PING every 0.35 s) is driven from tick() and only while the UI has touched the
override within 0.6 s, so a closed window or a stalled front end lets the override lapse.
"""
import paths  # noqa: F401
import json
import math
import time
from collections import deque

import recording as rec

from sessions.zone_console import ZoneConsoleSession


class PoolRadioSession(ZoneConsoleSession):
    kind = 'pool'
    PING, TOUCH, PENDING_TIMEOUT = 0.35, 0.6, 2.0

    def __init__(self, hub, device):
        super().__init__(hub, device)
        self.interaction = {}
        self.calibration = None
        self.tuning = None
        self.tuning_saved = False
        self.tuning_defaults = None
        self.tune_supported = None
        self.tune_attempts = 0
        self.raw = None
        self.samples = deque(maxlen=400)   # (t, raw_mm, filtered_mm, index)
        self.last_sample = self.last_interaction = self.last_query = self.last_ping = 0.0
        self.arm_requested = False
        self.arm_at = 0.0
        self.last_touch = 0.0
        self.queue = deque()
        self.pending = None
        self.note = ''
        self.ready = False
        self.rec = None            # live recording: dict(state move|hold, steps, step, buffer, phase_at, hold_from, data, started)
        self.recording = None      # finished recording (rec.save format)
        self.analysis = None
        self.proposal = None
        self.rec_note = ''
        self.rec_path = None

    def open(self):
        super().open()
        self.send('HOST DISARM')
        self.send('CAL GET')

    def close(self, reason='closed'):
        self.arm_requested = False
        if self.transport.is_open:
            self.transport.close(farewell='HOST DISARM')
        super().close(reason)

    def stop_active(self):
        self.arm_requested = False
        if self.transport.is_open:
            self.send('HOST DISARM')
            self.send('stop')

    # ---- override lease ----
    def arm(self):
        if not self.ready:
            raise ValueError('The radio has not reported its calibration yet')
        self.arm_requested = True
        self.arm_at = self.last_touch = self.clock()
        self.send('HOST ARM')

    def touch(self):
        self.last_touch = self.clock()
        return bool(self.interaction.get('override'))

    def disarm(self):
        self.arm_requested = False
        if self.transport.is_open:
            self.send('HOST DISARM')

    # ---- queued CAL / TUNE commands (one in flight, 2 s timeout) ----
    def enqueue(self, *commands):
        self.queue.extend(commands)

    def cal_set(self, index, mm):
        index, mm = int(index), float(mm)
        if not 1 <= index <= 23 or not 10 <= mm <= 1000:
            raise ValueError('Control point index 1-23, distance 10-1000 mm')
        self.enqueue(f'CAL SET {index} {mm:.1f}')

    def cal_save(self):
        self.enqueue('CAL SAVE', 'CAL GET')

    def cal_load(self):
        self.enqueue('CAL LOAD', 'CAL GET')

    def cal_anchors(self, mask):
        self.enqueue(f'CAL ANCHORS {int(mask)}', 'CAL GET')

    def format_field(self, key, value):
        return str(int(value)) if rec.FIELDS[key][1] else f'{float(value):g}'

    def tune_apply(self, values, save):
        reason = rec.valid(values)
        if reason:
            raise ValueError(reason)
        current = self.tuning or {}
        commands = [f'TUNE SET {k} {self.format_field(k, v)}' for k, v in values.items()
                    if current.get(k) is None or abs(float(current[k]) - float(v)) > 1e-6]
        if save:
            commands.append('TUNE SAVE')
        if not commands:
            raise ValueError('Tuning already matches the device')
        self.enqueue(*commands)
        self.note = f'Applying {len(commands)} tuning command(s)…'

    def tune_load(self):
        self.enqueue('TUNE LOAD')

    def tune_defaults(self):
        self.enqueue('TUNE DEFAULTS')

    def raw_mode(self, on):
        self.enqueue('RAW ON' if on else 'RAW OFF')

    # ---- telemetry ----
    def handle(self, line):
        if line.startswith('{'):
            try:
                data = json.loads(line)
            except ValueError:
                return super().handle(line)
            if isinstance(data, dict) and data.get('device') == 'PoolZoneCalibration':
                self.absorb(data)
                self.last_rx = self.clock()
                return
        super().handle(line)

    def absorb(self, data):
        now = self.clock()
        kind = data.get('type')
        if kind == 'interaction':
            self.interaction = data
            self.last_interaction = now
            if not data.get('override') and now - self.arm_at > 0.75:
                self.arm_requested = False   # the board dropped the lease (or refused it): stop pretending
        elif kind == 'calibration':
            self.calibration = data
            self.ready = True
            if self.pending and self.pending[0].startswith('CAL'):
                self.pending = None
        elif kind == 'tuning':
            self.absorb_tuning(data)
        elif kind == 'sample':
            # {"type":"sample","sensor":true,"distance":<mm filtered>,"raw_distance":<mm>,"index":<1-23|-1>}
            self.last_sample = now
            value = data.get('distance')
            valid = data.get('sensor') is True and isinstance(value, (int, float)) and math.isfinite(value) and 10 <= value <= 1000
            index = data.get('index', -1)
            index = index if valid and isinstance(index, int) and 1 <= index <= 23 else -1
            raw = data.get('raw_distance', value)
            raw = raw if valid and isinstance(raw, (int, float)) and math.isfinite(raw) and 10 <= raw <= 1000 else None
            self.raw = dict(distance=value if valid else None, raw_distance=raw, index=index, sensor=data.get('sensor'))
            self.samples.append((now, raw, value if valid else None, index))
        elif kind == 'raw':
            # {"type":"raw","t":<ms>,"mm":<mm|null>,"st":<state>} streamed while RAW ON (guided recording)
            if self.rec is not None and isinstance(data.get('t'), (int, float)):
                mm = data.get('mm')
                mm = mm if isinstance(mm, (int, float)) and math.isfinite(mm) else None
                self.rec['buffer'].append(dict(t=int(data['t']), mm=mm, st=data.get('st', 0)))
        elif kind == 'host':
            self.interaction = dict(self.interaction, **data)

    def absorb_tuning(self, data):
        values = {}
        for key, name in rec.JSON_KEYS.items():
            value = data.get(name)
            if type(value) in (int, float) and math.isfinite(value):
                values[key] = int(value) if rec.FIELDS[key][1] else float(value)
        if len(values) != len(rec.JSON_KEYS):
            return
        self.tune_supported = True
        self.tuning, self.tuning_saved = values, bool(data.get('saved'))
        defaults = data.get('defaults')
        if isinstance(defaults, dict):
            self.tuning_defaults = {k: defaults.get(n) for k, n in rec.JSON_KEYS.items()}
        if self.pending and self.pending[0].startswith('TUNE'):
            cmd = self.pending[0]
            if cmd.startswith('TUNE SET '):
                _, _, key, value = cmd.split()
                got = values.get(key)
                if got is None or abs(float(got) - float(value)) > max(1e-4, abs(float(value)) * 1e-3):
                    self.note = f'Device did not accept {key}; tuning left unchanged'
                    self.queue.clear()
            elif cmd == 'TUNE SAVE':
                self.note = 'Tuning saved to device flash and verified' if self.tuning_saved else \
                    'Tuning save was not confirmed by the device'
                if not self.tuning_saved:
                    self.queue.clear()
            self.pending = None

    # ---- guided recording (the calibration app's Start guided recording / Reached this position) ----
    def record_start(self, stride=4, hold=5.0):
        if not self.ready:
            raise ValueError('Connect to a PoolZone first (no calibration report yet)')
        if self.tune_supported is False:
            raise ValueError('This firmware has no tuning support; update the board to pool-2.8.0 or newer first')
        if self.rec is not None:
            raise ValueError('A recording is already running')
        steps = rec.plan_steps(int(stride), float(hold))
        now = self.clock()
        self.rec = dict(state='move', steps=steps, step=0, buffer=[], phase_at=now, hold_from=0, data=[], started=now)
        self.recording = self.analysis = self.proposal = None
        self.rec_note = f'Recording started · {len(steps)} positions'
        self.send('RAW ON')
        return dict(steps=[s['tick'] for s in steps])

    def record_reached(self):
        """The operator confirms the slider is at the prompted tick; only the hold that follows is measured."""
        if self.rec is None or self.rec['state'] != 'move':
            raise ValueError('Nothing is waiting for a position')
        self.rec['state'] = 'hold'
        self.rec['phase_at'] = self.clock()
        self.rec['hold_from'] = self.rec['buffer'][-1]['t'] if self.rec['buffer'] else 0

    def record_abort(self, reason='Recording aborted'):
        if self.rec is None:
            return
        self.rec = None
        if self.transport.is_open:
            self.send('RAW OFF')
        self.rec_note = reason

    def _record_advance(self, now):
        r = self.rec
        if r is None:
            return
        if not self.transport.is_open:
            self.record_abort('Disconnected during recording')
            return
        if r['state'] != 'hold':
            return
        step = r['steps'][r['step']]
        if step['hold'] - (now - r['phase_at']) > 0:
            return
        r['data'].append(dict(tick=step['tick'], hold_from=r['hold_from'], samples=r['buffer']))
        r['buffer'] = []
        r['step'] += 1
        if r['step'] >= len(r['steps']):
            self._record_finish()
            return
        r['state'], r['phase_at'] = 'move', now

    def _record_finish(self):
        data = self.rec['data']
        self.rec = None
        self.send('RAW OFF')
        self.recording = dict(steps=data, ticks=23, created=time.strftime('%Y-%m-%d %H:%M:%S'),
                              firmware=(self.state.zone or {}).get('firmware'))
        try:
            self.analysis = rec.analyse(self.recording)
            proposal = rec.recommend(self.analysis, current=self.tuning)
            fitted = rec.fit_budget(self.recording, self.analysis, proposal['tuning'])
            proposal['tuning'] = fitted['tuning']
            proposal['fit'] = fitted
            proposal['before'] = rec.simulate(self.recording, self.tuning or rec.DEFAULTS, self.analysis['ticks'])
            proposal['after'] = rec.simulate(self.recording, fitted['tuning'], self.analysis['ticks'])
            self.proposal = proposal
            self.rec_note = 'Recording analysed: review the proposal, then apply it live or save it'
        except ValueError as exc:
            self.analysis = self.proposal = None
            self.rec_note = f'Recording unusable: {exc}'
        try:
            self.rec_path = str(rec.save(self.recording, paths.CONSOLE / 'data' / 'recordings'))
        except Exception as exc:
            self.rec_path = None
            self.hub.log(f'Recording not saved to disk: {exc}', 'warn', self.device.id)
        self.hub.log(self.rec_note, 'ok' if self.proposal else 'warn', self.device.id, source='pool')

    def record_apply(self, save=False, points=False):
        """Apply the recommended tuning (live, or saved to flash) and optionally the measured control points."""
        if not self.proposal:
            raise ValueError('No recording proposal to apply')
        self.tune_apply(dict(self.proposal['tuning']), bool(save))
        applied = dict(tuning=True, points=0)
        if points and self.analysis:
            for index, mm in enumerate(self.analysis.get('ticks') or []):
                if isinstance(mm, (int, float)) and 10 <= mm <= 1000:
                    self.enqueue(f'CAL SET {index + 1} {mm:.1f}')
                    applied['points'] += 1
            if applied['points'] and save:
                self.enqueue('CAL SAVE', 'CAL GET')
        return applied

    def tick(self, now):
        super().tick(now)
        self._record_advance(now)
        if not self.transport.is_open:
            return
        if not self.ready and now - self.last_query > 1:
            self.last_query = now
            self.send('CAL GET')
        elif self.ready and self.tuning is None and self.tune_supported is None and now - self.last_query > 1:
            self.last_query = now
            self.tune_attempts += 1
            if self.tune_attempts > 3:
                self.tune_supported = False   # firmware before pool-2.8.0 has no TUNE command
            else:
                self.send('TUNE GET')
        if self.pending and now - self.pending[1] > self.PENDING_TIMEOUT:
            self.pending = None
            self.queue.clear()
            self.note = 'Command timed out; the save is unconfirmed. Reconnect to inspect the device state.'
        if self.ready and self.queue and not self.pending:
            cmd = self.queue.popleft()
            self.send(cmd)
            self.pending = (cmd, now) if cmd.startswith(('CAL SAVE', 'CAL LOAD', 'CAL SET', 'CAL ANCHORS', 'TUNE')) else None
        if self.arm_requested:
            if now - self.last_touch > self.TOUCH or (self.last_sample and now - self.last_sample > self.TOUCH):
                self.arm_requested = False
                self.send('HOST DISARM')
            elif self.interaction.get('override') and now - self.last_ping >= self.PING:
                self.last_ping = now
                self.send('HOST PING')

    def snapshot(self):
        base = super().snapshot()
        now = self.clock()
        stale = not self.last_sample or now - self.last_sample > self.TOUCH
        return dict(base, kind='pool', interaction=self.interaction, calibration=self.calibration, tuning=self.tuning,
                    tuning_saved=self.tuning_saved, tuning_defaults=self.tuning_defaults, tune_supported=self.tune_supported,
                    ready=self.ready, armed=self.arm_requested and bool(self.interaction.get('override')),
                    arm_requested=self.arm_requested, note=self.note, pending=self.pending[0] if self.pending else None,
                    queued=len(self.queue), sample=None if stale else self.raw,
                    samples=[list(s) for s in list(self.samples)[-120:]], fields=rec.FIELDS, json_keys=rec.JSON_KEYS,
                    recording=self._recording_snapshot(now))

    def _recording_snapshot(self, now):
        r = self.rec
        live = None
        if r is not None:
            step = r['steps'][r['step']]
            live = dict(state=r['state'], step=r['step'] + 1, total=len(r['steps']), tick=step['tick'], hold=step['hold'],
                        remaining=max(0.0, round(step['hold'] - (now - r['phase_at']), 1)) if r['state'] == 'hold' else None,
                        samples=len(r['buffer']), ticks=[s['tick'] for s in r['steps']])
        analysis = None
        if self.analysis:
            analysis = dict(ticks=self.analysis.get('ticks'),
                            steps=[{k: v for k, v in step.items() if k in ('tick', 'samples', 'valid', 'warnings', 'mm', 'sigma', 'noise', 'median')}
                                   for step in self.analysis.get('steps', [])],
                            warnings=self.analysis.get('warnings'))
        proposal = None
        if self.proposal:
            p = self.proposal
            proposal = dict(tuning=p.get('tuning'), before=p.get('before'), after=p.get('after'), fit=p.get('fit'),
                            reasons=p.get('reasons') or p.get('notes'))
        return dict(live=live, note=self.rec_note, analysis=analysis, proposal=proposal, path=self.rec_path,
                    has_recording=self.recording is not None)
