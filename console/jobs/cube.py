"""Cube firmware flash and boot check, through flashing_station's Flasher (NVS preserved)."""
import paths  # noqa: F401

from backend import Flasher, Runner
import core
import sightings

from jobs.base import Job


def flash_job(hub, device, manual=True):
    manifest = core.load_manifest()
    port = hub.port_dict(device)
    job = Job('cube.flash', device.key, f'Flash cube firmware {manifest["version"]} on {device.port}', hardware=True,
              device=device.id)
    hub.hold_port(device, job)
    flasher = Flasher(hub.database, job.emit)

    def work(emit, cancel):
        return flasher.execute(port, manifest, manual)

    def done(job):
        result = job.result or {}
        ui = result.get('ui_result') or ('failed' if job.error else 'unknown')
        detail = result.get('ui_detail') or job.error or ''
        level = {'success': 'verified', 'boot_unconfirmed': 'delivered', 'attention': 'delivered'}.get(ui, 'failed')
        job.outcome = dict(level=level, text=f'{ui}: {detail}' if detail else ui)
        mac = result.get('mac') or (job.identity or {}).get('mac')
        if mac:
            sightings.record(hub.db.conn, mac, 'usb_flash', f'{ui} {manifest["version"]}')
        hub.mark_dirty('inventory')

    hub.jobs.start(job, work, done)
    return job


def boot_check_job(hub, device):
    if not device.mac:
        raise ValueError('The cube has no known MAC yet; identify it first')
    manifest = core.load_manifest()
    port = hub.port_dict(device)
    job = Job('cube.boot', device.key, f'Check cube boot on {device.port}', hardware=True, device=device.id)
    hub.hold_port(device, job)
    flasher = Flasher(hub.database, job.emit)

    def work(emit, cancel):
        return flasher.boot(port, device.mac, manifest['version'], Runner(emit))

    def done(job):
        ok = job.result is True
        job.outcome = dict(level='verified' if ok else 'failed',
                           text='Boot confirmed: version, MAC, channel 2 and READY all matched' if ok else
                           'No matching boot response (unverified, not necessarily wrong)')

    hub.jobs.start(job, work, done)
    return job
