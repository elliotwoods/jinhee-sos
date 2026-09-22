"""Firmware builds (arduino-cli) and the flashing-tool check. No uploads."""
import paths  # noqa: F401

from backend import Runner, tool_command
import build as cube_build
import dongle
import zone_build

from jobs.base import Job


def cube_build_job(hub):
    job = Job('build.cube', 'build', 'Build the cube firmware')

    def work(emit, cancel):
        runner = Runner(emit)
        return cube_build.build(lambda args, timeout=900: runner(args, timeout))

    def done(job):
        hub.refresh_builds()
        if job.state == 'done':
            job.outcome = dict(level='verified', text='Cube build manifest updated')

    hub.jobs.start(job, work, done)
    return job


def zone_build_job(hub, sketch):
    if sketch not in zone_build.SKETCHES:
        raise ValueError(f'Unknown zone sketch {sketch}')
    job = Job('build.zone', 'build', f'Build {sketch}')

    def work(emit, cancel):
        runner = Runner(emit)
        return zone_build.build(sketch, lambda args, timeout=900: runner(args, timeout))

    def done(job):
        hub.refresh_builds()
        if job.state == 'done':
            job.outcome = dict(level='verified', text=f'{sketch} built: {job.result.get("version") if isinstance(job.result, dict) else ""}')

    hub.jobs.start(job, work, done)
    return job


def dongle_build_job(hub, which='dongle'):
    from jobs.dongle import FIRMWARES
    if which not in FIRMWARES:
        raise ValueError('firmware must be dongle, mainshow or general')
    firmware = FIRMWARES[which]
    job = Job('build.dongle', 'build', f'Build the {firmware.label} firmware')

    def work(emit, cancel):
        dongle.build(Runner(emit), firmware)
        return firmware.version

    def done(job):
        hub.refresh_builds()
        if job.state == 'done':
            job.outcome = dict(level='verified', text=f'{firmware.label} {firmware.version} built')

    hub.jobs.start(job, work, done)
    return job


def tools_job(hub):
    job = Job('tools.check', 'tools', 'Check the flashing tool')
    job.quiet = True

    def work(emit, cancel):
        text = Runner(emit)(tool_command() + ['version'], timeout=30)
        return dict(esptool_ok='5.3.1' in text, esptool_text=text.strip().splitlines()[-1] if text.strip() else '')

    def done(job):
        tools = hub.builds.setdefault('tools', {})
        if job.state == 'done':
            tools.update(job.result)
        else:
            tools.update(esptool_ok=False, esptool_text=job.error)
        hub.mark_dirty('builds')

    hub.jobs.start(job, work, done)
    return job
