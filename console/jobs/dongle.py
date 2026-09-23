"""Write the Workstation or the Mainshow controller firmware onto a spare ESP32-C3."""
import paths  # noqa: F401
import uuid

import dongle

from jobs.base import Job

# The relay dongle and General Radio targets became the Workstation: one firmware for every host job.
FIRMWARES = {'workstation': dongle.WORKSTATION, 'mainshow': dongle.MAINSHOW}


def flash_job(hub, device, which='workstation', force_build=False, force=False):
    firmware = FIRMWARES[which]
    known = dongle.known_boards(hub.db, hub.store.zones())
    if which == 'workstation':
        # A Workstation is a superset of the relay and the controller: converting either is allowed.
        known = dict(known, controllers=set())
    port = hub.port_dict(device)
    if device.mac and not force:
        reason = dongle.refusal(device.mac, known, firmware)
        if reason:
            raise ValueError(reason)
    folder = paths.CONSOLE / 'data' / 'dongle' / uuid.uuid4().hex
    job = Job(f'{which}.flash', device.key, f'Write {firmware.label} firmware ({firmware.version}) on {device.port}',
              hardware=True, device=device.id)
    hub.hold_port(device, job)

    def work(emit, cancel):
        return dongle.flash(port, known, folder, emit, force_build=force_build, firmware=firmware, force=force)

    def done(job):
        if job.state == 'done' and job.result:
            mac = str(job.result).upper()
            hub.db.set_role(mac, 'excluded')
            dongle.set_controller(hub.db, mac, firmware is dongle.MAINSHOW)
            if which == 'workstation':
                hub.record_workstation(mac)
            job.outcome = dict(level='verified', text=f'{firmware.label} written to {mac}; recorded as excluded from cube service')
            hub.mark_dirty('inventory')

    hub.jobs.start(job, work, done)
    return job
