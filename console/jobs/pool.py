"""PoolZone firmware update and radio-id assignment through zones/calibration/firmware.py."""
import paths  # noqa: F401

import firmware as pool_firmware

from jobs.base import Job


def flash_job(hub, device, database_only=False):
    port_name = device.port
    title = ('Update pool radio database' if database_only else 'Update pool radio firmware') + f' on {port_name}'
    job = Job('pool.db' if database_only else 'pool.flash', device.key, title, hardware=True, device=device.id)
    hub.hold_port(device, job)

    def work(emit, cancel):
        return pool_firmware.flash(port_name, emit, database_only=database_only)

    def done(job):
        if job.state == 'done':
            job.outcome = dict(level='verified', text=str(job.result) if job.result else 'done')
        hub.mark_dirty('inventory', 'registry')

    hub.jobs.start(job, work, done)
    return job


def assign_radio_id_job(hub, device, new_id, force=False):
    port_name = device.port
    job = Job('pool.radio_id', device.key, f'Assign pool radio id {int(new_id)} on {port_name}', hardware=True, device=device.id)
    hub.hold_port(device, job)

    def work(emit, cancel):
        return pool_firmware.assign_radio_id(port_name, int(new_id), emit, force=bool(force))

    def done(job):
        if job.state == 'done':
            job.outcome = dict(level='verified', text=str(job.result) if job.result else f'radio id {int(new_id)}')
        hub.mark_dirty('inventory', 'registry')

    hub.jobs.start(job, work, done)
    return job
