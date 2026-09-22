"""Guided cube flashing over USB: plug cubes in one after another; each gets the firmware and the show.

Switched on from the Flash page (off at every launch, like the Tk flasher's Arm Auto: automatic flash
intake is never left armed across a restart). While on, the cube side of Intake (intake.py, the Tk
flasher's core.Scheduler) picks each newly plugged candidate port once and hands it to `begin`, which
runs one `cube.flash` job (jobs/cube.py → flashing_station Flasher.execute):
  1. usb       a candidate port appeared (a cube that cannot answer "?" is still flashable)
  2. firmware  NVS backed up, firmware written and verified, NVS unchanged; skipped when this MAC already
               completed this build (the Tk auto rule)
  3. show      the published main show: NVS read over USB; when older, missing or damaged it is rewritten
               with every other value kept, read back, and the cube must report it from NVS. Runs even
               when the firmware was skipped
Only USB: nothing here uses the radio. Runs on the owner thread (Hub.tick, Intake.tick) and never blocks.
A failure waits for Retry (which rewrites the firmware, as the Tk flasher's Manual Retry) or the next cube.
"""
import paths  # noqa: F401

import core

from jobs import cube as cube_jobs

STEPS = ('usb', 'firmware', 'show')
SHOW_STAGES = ('Check show', 'Write show')
HISTORY = 20


class FlashFlow:
    def __init__(self, hub):
        self.hub = hub
        self.enabled = False
        self.session_start = None      # flash_runs after this belong to this session (Tk "needs attention" rule)
        self.history = []              # newest first: dict(mac, number, result, firmware, show, at, detail)
        self.notice = None
        self.notices = 0
        self.clear()

    # ---------------------------------------------------------------- state
    def clear(self):
        self.key = self.port = self.device_id = self.mac = None
        self.step = 'idle'             # idle | firmware | show | done | failed
        self.job = None
        self.show = None               # dict(version, crc) sent with the job
        self.result = None             # the Flasher's record once finished
        self.error = ''
        self.failed_step = None
        self.started_at = None

    def say(self, text, tone='info'):
        self.notices += 1
        self.notice = dict(id=self.notices, text=text, tone=tone)
        self.hub.log(text, 'ok' if tone == 'ok' else 'warn' if tone in ('warn', 'bad') else 'info', self.device_id,
                     source='flash')
        self.hub.mark_dirty('flash')

    def number(self):
        row = self.hub.db.get(self.mac) if self.mac else None
        return row['cube_id'] if row else None

    def label(self):
        number = self.number()
        if number is not None:
            return f'#{number} ({self.mac})'
        return self.mac or self.port or 'the cube'

    def record(self, result):
        r = self.result or {}
        self.history = [h for h in self.history if not (self.mac and h['mac'] == self.mac)]
        self.history.insert(0, dict(mac=self.mac, number=self.number(), port=self.port, result=result,
                                    firmware=r.get('ui_result'), version=r.get('version'),
                                    show=r.get('show_result'), show_version=r.get('show_version'),
                                    at=self.hub.wall(), detail=self.error or r.get('ui_detail') or ''))
        del self.history[HISTORY:]
        self.hub.mark_dirty('flash')

    # ---------------------------------------------------------------- entry points
    def enable(self, on):
        on = bool(on)
        self.hub.intake.arm_cubes(on)      # refuses (ValueError) when the cube build has an error
        if on and not self.enabled:
            self.session_start = core.timestamp()
        self.enabled = on
        self.hub.mark_dirty('flash')

    def begin(self, device):
        """Intake picked this newly plugged candidate port: flash it (firmware, then the show)."""
        self.clear()
        self.key, self.port, self.device_id, self.mac = device.key, device.port, device.id, device.mac
        self.started_at = self.hub.wall()
        self._start(manual=False)

    def retry(self):
        if self.step != 'failed':
            raise ValueError('Nothing to retry')
        device = self.hub.devices.get(self.key)
        if not device:
            raise ValueError('Plug the cube back in first')
        self.port, self.device_id = device.port, device.id
        self.error, self.failed_step, self.result = '', None, None
        self._start(manual=True)

    def _start(self, manual):
        device = self.hub.devices[self.key]
        show = cube_jobs.published_show(self.hub)
        self.show = dict(version=show['version'], crc=show['crc']) if show else None
        self.step = 'firmware'
        try:
            self.job = cube_jobs.flash_job(self.hub, device, manual=manual, show=show, session_start=self.session_start).id
        except Exception as exc:
            self.job = None
            self.fail(str(exc))
            raise
        self.hub.mark_dirty('flash')

    def fail(self, text):
        self.failed_step = self.step if self.step in STEPS else self.failed_step
        self.step, self.error = 'failed', text
        self.say(f'Flashing {self.label()} stopped: {text}', 'bad')
        self.record('failed')

    def holds(self, mac, device=None):
        """True while this flow is flashing the cube with this MAC, or will take its port (`device`) next,
        so the Register page waits for it. During the job the port is held and may not show as a cube."""
        if self.step in ('firmware', 'show') and mac and self.mac == mac:
            return True
        if not self.enabled or device is None:
            return False
        if self.key == device.key and self.step in ('firmware', 'show'):
            return True
        return device.key not in self.hub.intake.cubes.attempted and bool(self.hub.port_dict(device).get('candidate'))

    # ---------------------------------------------------------------- tick
    def tick(self):
        if self.step not in ('firmware', 'show'):
            return
        job = self.hub.jobs.jobs.get(self.job)
        if job is None:
            return self.fail('The flash job was lost')
        if job.state in ('queued', 'running'):
            step = 'show' if job.stage in SHOW_STAGES else 'firmware'
            if step != self.step:
                self.step = step
            self.hub.mark_dirty('flash')
            return
        self.result = job.result if isinstance(job.result, dict) else None
        r = self.result or {}
        self.mac = r.get('mac') or self.mac
        ui = r.get('ui_result')
        if ui not in ('success', 'skipped'):
            self.step = 'show' if job.stage in SHOW_STAGES else self.step
            return self.fail(r.get('ui_detail') or job.error or 'The flash job failed')
        self.step = 'done'
        if ui == 'success':
            firmware = f'firmware {r.get("version")} written and verified'
        else:
            firmware = f'firmware {r.get("version")} already on this cube'
        show = {None: 'no published show; the built-in show is kept',
                'current': f'show v{r.get("show_version")} already current',
                'written': f'show v{r.get("show_version")} written and confirmed by the cube',
                'newer': f'show v{r.get("show_version")} on the cube is newer than the published one; kept',
                'unsupported': 'firmware too old for a stored show'}[r.get('show_result') if self.show else None]
        self.say(f'Cube {self.label()}: {firmware}, {show}. Unplug it and plug in the next cube.',
                 'warn' if r.get('show_result') in ('newer', 'unsupported') else 'ok')
        self.record('flashed')

    # ---------------------------------------------------------------- UI
    def job_view(self):
        job = self.hub.jobs.jobs.get(self.job) if self.job else None
        if not job:
            return None
        return dict(id=job.id, state=job.state, stage=job.stage, progress=job.progress, title=job.title)

    def snapshot(self):
        intake = self.hub.intake
        builds = self.hub.builds.get('cube', {})
        return dict(enabled=self.enabled, step=self.step, key=self.key, port=self.port, device=self.device_id,
                    mac=self.mac, number=self.number(), error=self.error, failed_step=self.failed_step,
                    show=self.show, published=cube_jobs.published_show_summary(self.hub),
                    firmware=dict(version=builds.get('version'), error=builds.get('error')),
                    job=self.job_view(), result={k: v for k, v in (self.result or {}).items()
                                                 if k in ('ui_result', 'ui_detail', 'version', 'show_result', 'show_version')},
                    attempted=len(intake.cubes.attempted), notice=self.notice, history=list(self.history),
                    steps=list(STEPS))
