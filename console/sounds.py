"""Audio cues for USB cube flashing: the Tk cube flasher's sounds (flashing_station/audio.py), same tones and moments.

  connected  a new candidate USB port appeared while the Flash page is on
  start      a cube flash job started
  tick       each pipeline stage, and every 4 s while a flash runs (so a long write is audibly alive)
  success    flashed and verified (or, firmware already current, the show written and confirmed)
  tick       firmware already current and nothing written (the Tk "skipped")
  failure    anything else, including boot unconfirmed and a failed boot check

Switched by the `audio` setting (Settings › Behaviour). Never plays in a simulation: tests and documentation
screenshots stay silent. Owner thread only; Audio.play starts afplay/winsound and returns at once.
"""
import paths  # noqa: F401

KINDS = ('cube.flash', 'cube.boot')
HEARTBEAT_S = 4.0


class Sounds:
    def __init__(self, hub):
        self.hub = hub
        self.audio = None
        self.last_tick = 0.0
        self.ports = None          # candidate port keys seen last tick (None until the first tick)

    @property
    def enabled(self):
        return bool(self.hub.settings.get('audio')) and not self.hub.simulate

    def play(self, name, force=False):
        if not (self.enabled or force):
            return
        try:
            if self.audio is None:
                from audio import Audio   # flashing_station/audio.py; writes its WAV files on first use
                self.audio = Audio()
            self.audio.play(name)
        except Exception as exc:   # sound is a convenience: never let it break a flash
            self.hub.log(f'Audio cue failed: {exc}', 'warn', source='audio')

    # ---------------------------------------------------------------- job hooks (JobRunner)
    def job_started(self, job):
        if job.kind == 'cube.flash':
            self.last_tick = self.hub.clock()
            self.play('start')

    def job_stage(self, job):
        if job.kind in KINDS:
            self.play('tick')

    def job_done(self, job):
        if job.kind not in KINDS:
            return
        if job.kind == 'cube.boot':
            return self.play('success' if job.state == 'done' and job.result is True else 'failure')
        result = job.result if isinstance(job.result, dict) else {}
        ui = result.get('ui_result') if job.state == 'done' else None
        if ui == 'success' or (ui == 'skipped' and result.get('show_result') == 'written'):
            self.play('success')
        elif ui == 'skipped':
            self.play('tick')
        else:
            self.play('failure')

    # ---------------------------------------------------------------- hub tick
    def tick(self, now):
        flashing = any(j.kind == 'cube.flash' for j in self.hub.jobs.running())
        if flashing and now - self.last_tick > HEARTBEAT_S:
            self.last_tick = now
            self.play('tick')
        keys = {d.key for d in self.hub.devices.values() if d.candidate}
        flash = getattr(self.hub, 'flashflow', None)
        if self.ports is not None and keys - self.ports and flash and flash.enabled:
            self.play('connected')
        self.ports = keys
