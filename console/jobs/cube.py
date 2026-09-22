"""Cube firmware flash and boot check, through flashing_station's Flasher (NVS preserved)."""
import paths  # noqa: F401

from backend import Flasher, Runner
import core
import sightings

from jobs.base import Job


def published_show(hub):
    """The published main show as the Flasher's `show` argument, or None when none is published here."""
    editor = getattr(hub, 'showedit', None)
    if editor is None:
        return None
    try:
        publication = editor.registry.store.current()
    except ValueError:
        return None
    return dict(version=publication.version, crc=publication.crc, image=publication.image)


def simulated_manifest():
    """The local cube build when it is current; otherwise a stand-in, so a simulation never needs a rebuild."""
    try:
        return core.load_manifest()
    except (ValueError, OSError, KeyError):
        return dict(version=core.VERSION, build_hash='simulated-' + core.VERSION, segments=[])


def published_show_summary(hub):
    show = published_show(hub)
    return dict(version=show['version'], crc=show['crc'], length=len(show['image'])) if show else None


def flash_job(hub, device, manual=True, show=None, session_start=None, show_only=None):
    """Flash the cube firmware and, with `show`, bring the show in its NVS up to that one (Flasher.execute).
    `show_only` (the firmware version the cube reported) writes just the show."""
    fake = getattr(hub, 'fake_cube_flash', None)   # --simulate: no esptool (simulate.fake_cube_flash)
    manifest = simulated_manifest() if fake else core.load_manifest()
    port = hub.port_dict(device)
    if show_only:
        title = f'Update the show in cube NVS to v{show["version"]} on {device.port}'
    else:
        title = f'Flash cube firmware {manifest["version"]}' + (f' and show v{show["version"]}' if show else '') + f' on {device.port}'
    job = Job('cube.flash', device.key, title, hardware=True, device=device.id)
    hub.hold_port(device, job)
    flasher = Flasher(hub.database, job.emit)

    def work(emit, cancel):
        if fake:
            return fake(device.port, manifest, manual, show, emit, show_only=show_only)
        return flasher.execute(port, manifest, manual, session_start=session_start, show=show, show_only=show_only)

    def done(job):
        result = job.result or {}
        ui = result.get('ui_result') or ('failed' if job.error else 'unknown')
        detail = result.get('ui_detail') or job.error or ''
        level = {'success': 'verified', 'boot_unconfirmed': 'delivered', 'attention': 'delivered',
                 # firmware already on this MAC: verified only when this run wrote a show and saw it report it
                 'skipped': 'verified' if result.get('show_result') == 'written' else 'acknowledged'}.get(ui, 'failed')
        job.outcome = dict(level=level, text=f'{ui}: {detail}' if detail else ui)
        mac = result.get('mac') or (job.identity or {}).get('mac')
        if mac:
            sightings.record(hub.db.conn, mac, 'usb_flash', f'{ui} {manifest["version"]}'
                             + (f' show {result["show_result"]} v{result.get("show_version")}' if result.get('show_result') else ''))
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
