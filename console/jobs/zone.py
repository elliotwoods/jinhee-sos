"""Zone board jobs through zones/flasher: full flash, database-only update over USB, bootloader
detection (reboots), and a plain `?` report check."""
import paths  # noqa: F401
import time

from backend import Runner
from zone_flash import ZoneFlasher
import zone_build
import zone_detect
import zonedb

from jobs.base import Job


def _outcome_from_record(record):
    result = (record or {}).get('result', 'failed')
    level = {'success': 'verified', 'boot_unconfirmed': 'delivered', 'attention': 'delivered', 'skipped': 'sent'}.get(result, 'failed')
    return dict(level=level, text=f'{result}: {(record or {}).get("detail", "")}'.strip(': '))


def flash_job(hub, device, profile, point, name, params=(), rx_gain=zonedb.RX_GAIN_DEFAULT, force=False):
    if profile not in zone_build.PROFILES:
        raise ValueError('Choose a zone profile')
    zone_build.load_manifest(zone_build.PROFILES[profile]['sketch'])
    port = hub.port_dict(device)
    job = Job('zone.flash', device.key, f'Flash {zone_build.PROFILES[profile]["label"]} "{name}" on {device.port}',
              hardware=True, device=device.id)
    hub.hold_port(device, job)
    flasher = ZoneFlasher(hub.database, job.emit)

    def work(emit, cancel):
        return flasher.execute(port, profile, int(point), name, params or (), force=bool(force), rx_gain=rx_gain)

    def done(job):
        job.outcome = _outcome_from_record(job.result)
        hub.mark_dirty('inventory', 'registry')

    hub.jobs.start(job, work, done)
    return job


def update_db_job(hub, device):
    mac = device.mac or (device.details or {}).get('mac')
    if not mac:
        raise ValueError('The board has no known MAC; identify it again before updating its database')
    publication = hub.store.current()   # raises the operator-readable reason when nothing is publishable
    if getattr(hub, 'fake_zone_db', None):   # --simulate: no esptool (simulate.fake_zone_db)
        return hub.fake_zone_db(hub, device, publication)
    port = hub.port_dict(device)
    job = Job('zone.db_usb', device.key, f'Update zone database over USB on {device.port}', hardware=True, device=device.id)
    hub.hold_port(device, job)
    flasher = ZoneFlasher(hub.database, job.emit)

    def work(emit, cancel):
        return flasher.update_database(port, mac)

    def done(job):
        job.outcome = _outcome_from_record(job.result)
        hub.mark_dirty('inventory', 'registry')

    hub.jobs.start(job, work, done)
    return job


def detect_job(hub, device):
    port = hub.port_dict(device)
    job = Job('zone.detect', device.key, f'Identify board on {device.port} (bootloader read, reboots it)', hardware=True,
              device=device.id)
    hub.hold_port(device, job)
    flasher = ZoneFlasher(hub.database, job.emit)

    def work(emit, cancel):
        return flasher.detect(port)

    def done(job):
        if job.state == 'done' and isinstance(job.result, dict):
            device.detection = job.result
            label = job.result.get('label')
            job.outcome = dict(level='verified', text=f'{label} · {job.result.get("source")}')
            if job.result.get('mac'):
                device.mac = job.result['mac'].upper()
            hub.mark_dirty('devices')

    hub.jobs.start(job, work, done)
    return job


def report_job(hub, device):
    port = hub.port_dict(device)
    job = Job('zone.report', device.key, f'Read the zone report on {device.port}', hardware=True, device=device.id)
    hub.hold_port(device, job)
    flasher = ZoneFlasher(hub.database, job.emit)

    def work(emit, cancel):
        return flasher.boot_report(port, Runner(emit), timeout=6)

    def done(job):
        report = job.result
        if report:
            device.details = dict(report)
            device.firmware = report.get('firmware')
            device.mac = report.get('mac') or device.mac
            state = zone_detect.database_state(zone_detect.from_report(report), hub.store.published())
            job.outcome = dict(level='verified', text=f'{report.get("name") or "unconfigured"} · {report["firmware"]} · '
                                                      f'database v{report["db_version"]} ({state})')
            hub.zone_report(device, report, {})
        else:
            job.outcome = dict(level='failed', text='No zone report (not answering "?")')

    hub.jobs.start(job, work, done)
    return job
