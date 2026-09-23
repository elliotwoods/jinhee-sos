"""Long-running work off the owner thread: flashes, builds, syncs.

A job thread only ever sees plain data snapshotted before it starts and reports through
`emit(kind, value)`; the owner thread applies results. Kinds mirror flashing_station's Runner:
log, progress, stage, identity, result, plus done/failed added here.
"""
import paths  # noqa: F401
import queue
import threading
import time
import traceback
import uuid
from collections import deque

STAGES = ('sent', 'delivered', 'acknowledged', 'verified', 'failed')


class Job:
    def __init__(self, kind, target, title, hardware=False, device=None, cancellable=False, origin=None):
        self.id = uuid.uuid4().hex[:12]
        self.kind, self.target, self.title = kind, target, title
        self.hardware, self.device, self.cancellable, self.origin = hardware, device, cancellable, origin
        self.state = 'queued'          # queued | running | done | failed | cancelled
        self.stage = ''                # human stage text from the pipeline
        self.outcome = None            # dict(level=STAGES, text) set by the applier
        self.progress = None
        self.log = deque(maxlen=400)
        self.result = None
        self.error = None
        self.identity = None
        self.started_at = self.finished_at = None
        self.cancel = threading.Event()
        self.events = queue.Queue()
        self.thread = None
        self.writing = False           # an esptool write is in progress: never interrupt
        self.on_done = None
        self.quiet = False             # status checks: no 'Started' line in the timeline
        self.mute = False              # automatic updates: no timeline lines at all (the caller reports)

    def emit(self, kind, value=None):
        self.events.put((kind, value))

    def to_dict(self):
        return dict(id=self.id, kind=self.kind, target=self.target, title=self.title, hardware=self.hardware,
                    device=self.device, cancellable=self.cancellable, origin=self.origin, state=self.state,
                    stage=self.stage, outcome=self.outcome, progress=self.progress, log_tail=list(self.log)[-40:],
                    result=self.result, error=self.error, identity=self.identity, started_at=self.started_at,
                    finished_at=self.finished_at, writing=self.writing, quiet=self.quiet)


class JobRunner:
    """Owner-thread bookkeeping for jobs. `work(emit, cancel)` runs on a daemon thread."""

    def __init__(self, hub):
        self.hub = hub
        self.jobs = {}
        self.order = []

    def start(self, job, work, on_done=None):
        if job.hardware and any(j.hardware and j.state == 'running' and j.target == job.target for j in self.jobs.values()):
            raise ValueError('Another job is already using that port')
        if job.kind.startswith('build') and any(j.kind.startswith('build') and j.state == 'running' for j in self.jobs.values()):
            raise ValueError('Another firmware build is running; wait for it to finish')
        job.on_done = on_done
        job.state, job.started_at = 'running', self.hub.wall()
        self.jobs[job.id] = job
        self.order.append(job.id)
        while len(self.order) > 60:
            old = self.order.pop(0)
            if self.jobs.get(old) and self.jobs[old].state in ('done', 'failed', 'cancelled'):
                del self.jobs[old]
            else:
                self.order.append(old)
                break

        def run():
            try:
                result = work(job.emit, job.cancel)
                job.emit('done', result)
            except Exception as exc:
                job.emit('failed', dict(error=str(exc) or exc.__class__.__name__, traceback=traceback.format_exc()))

        job.thread = threading.Thread(target=run, name=f'job-{job.kind}', daemon=True)
        job.thread.start()
        if not (job.quiet or job.mute):
            self.hub.log(f'Started: {job.title}', 'info', job.device, source='job')
        self._sound('job_started', job)
        return job

    def _sound(self, hook, job):
        sounds = getattr(self.hub, 'sounds', None)   # sounds.py: the cube flasher's audio cues
        if sounds:
            getattr(sounds, hook)(job)

    def pump(self):
        """Apply queued job events on the owner thread."""
        for job in list(self.jobs.values()):
            if job.state != 'running':
                continue
            for _ in range(500):
                try:
                    kind, value = job.events.get_nowait()
                except queue.Empty:
                    break
                if kind == 'log':
                    job.log.append(str(value))
                    text = str(value)
                    job.writing = job.writing or ('write-flash' in text and text.startswith('$ '))
                    if text.startswith('Tool completed') or text.startswith('Hash of data verified') or 'Hard resetting' in text:
                        job.writing = False
                elif kind == 'progress':
                    job.progress = value
                elif kind == 'stage':
                    job.stage = str(value)
                    job.log.append(f'— {value}')
                    job.writing = False
                    self._sound('job_stage', job)
                elif kind == 'identity':
                    job.identity = value
                elif kind == 'result':
                    job.result = value
                elif kind in ('done', 'failed'):
                    job.finished_at = self.hub.wall()
                    job.writing = False
                    if kind == 'failed':
                        job.state, job.error = 'failed', value.get('error')
                        job.log.append('ERROR: ' + str(job.error))
                        job.outcome = job.outcome or dict(level='failed', text=str(job.error))
                    else:
                        job.state = 'cancelled' if job.cancel.is_set() else 'done'
                        if job.result is None:
                            job.result = value
                    try:
                        if job.on_done:
                            job.on_done(job)
                    except Exception as exc:
                        job.log.append(f'Applying the result failed: {exc}')
                        self.hub.log(f'{job.title}: applying the result failed: {exc}', 'bad', job.device)
                    level = 'ok' if job.state == 'done' else 'warn' if job.state == 'cancelled' else 'bad'
                    outcome = job.outcome or {}
                    if not job.mute and (not job.quiet or job.state != 'done'):
                            self.hub.log(f'{job.title}: {job.state}' + (f' · {outcome.get("text")}' if outcome.get('text') else ''),
                                     level, job.device, source='job')
                    self._sound('job_done', job)
                    self.hub.job_finished(job)
                    break
        self.hub.mark_dirty('jobs')

    def running(self):
        return [j for j in self.jobs.values() if j.state == 'running']

    def writing(self):
        return any(j.writing for j in self.running())

    def cancel(self, job_id):
        job = self.jobs.get(job_id)
        if not job or job.state != 'running':
            raise ValueError('That job is not running')
        if not job.cancellable:
            raise ValueError('This job cannot be interrupted safely; wait for it to finish')
        job.cancel.set()
        return job

    def snapshot(self):
        return [self.jobs[i].to_dict() for i in reversed(self.order) if i in self.jobs]
