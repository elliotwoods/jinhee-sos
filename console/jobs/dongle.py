"""Write the pairing-station relay or the Mainshow controller firmware onto a spare ESP32-C3."""
import paths  # noqa: F401
import uuid

import dongle

from jobs.base import Job

# The General Radio is built like the Mainshow controller (NeoPixel from live files/libraries, the zone
# protocol headers), on the same board recipe. It replaces a relay or a controller on any spare ESP32-C3.
GENERAL = dongle.Firmware('General Radio', 'general-radio-1.0.0', paths.ROOT / 'zones/firmware/GeneralRadio',
                          paths.ROOT / 'zones/build/GeneralRadio',
                          (paths.ROOT / 'zones/firmware/libraries', paths.ROOT / 'live files/libraries'))
FIRMWARES = {'dongle': dongle.PAIRING, 'mainshow': dongle.MAINSHOW, 'general': GENERAL}


def flash_job(hub, device, which='dongle', force_build=False):
    firmware = FIRMWARES[which]
    known = dongle.known_boards(hub.db, hub.store.zones())
    if which == 'general':
        # A General Radio is a superset of the relay and the controller: converting either is allowed.
        known = dict(known, controllers=set())
    port = hub.port_dict(device)
    if device.mac:
        reason = dongle.refusal(device.mac, known, firmware)
        if reason:
            raise ValueError(reason)
    folder = paths.CONSOLE / 'data' / 'dongle' / uuid.uuid4().hex
    job = Job(f'{which}.flash', device.key, f'Write {firmware.label} firmware ({firmware.version}) on {device.port}',
              hardware=True, device=device.id)
    hub.hold_port(device, job)

    def work(emit, cancel):
        return dongle.flash(port, known, folder, emit, force_build=force_build, firmware=firmware)

    def done(job):
        if job.state == 'done' and job.result:
            mac = str(job.result).upper()
            hub.db.set_role(mac, 'excluded')
            dongle.set_controller(hub.db, mac, firmware is dongle.MAINSHOW)
            if which == 'general':
                hub.record_general_radio(mac)
            job.outcome = dict(level='verified', text=f'{firmware.label} written to {mac}; recorded as excluded from cube service')
            hub.mark_dirty('inventory')

    hub.jobs.start(job, work, done)
    return job
