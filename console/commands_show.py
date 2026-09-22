"""Show editor and wireless show-update commands (registered into commands.COMMANDS).

A separate module, like commands_extra.py, so the show work does not edit commands.py.
Anything that transmits to cubes is hardware-kind (marked in the UI); publishing only talks to the web.
"""
import paths  # noqa: F401

from commands import command, _job
from jobs import show as show_jobs
import showedit


def _editor(hub):
    return hub.showedit


@command('show.save')
def show_save(hub, doc):
    """Validate and keep the editor's working copy (this computer only)."""
    return _editor(hub).save(doc)


@command('show.import')
def show_import(hub, text):
    """Replace the working copy with pasted show JSON."""
    return _editor(hub).save(showedit.draft_from_json(text))


@command('show.revert')
def show_revert(hub, source):
    """Replace the working copy with the published show ('published') or the cube's compiled-in default ('default')."""
    return _editor(hub).revert(source)


@command('show.pull')
def show_pull(hub):
    return _job(show_jobs.show_pull_job(hub))


@command('show.publish')
def show_publish(hub):
    """Publish the working copy on the web as the next show version (cubes are not touched)."""
    return _job(show_jobs.show_publish_job(hub, _editor(hub).draft))


@command('show.query', 'hardware')
def show_query(hub):
    """Ask every cube in range which show it holds (broadcast SHOW_QUERY)."""
    if not _editor(hub).relay():
        raise ValueError('Connect a General Radio (general-radio-1.1.0 or later) to query cube shows')
    return _editor(hub).registry.query()


@command('show.update_all', 'hardware')
def show_update_all(hub):
    """Send the published show to every cube heard recently, until each confirms it."""
    editor = _editor(hub)
    if not editor.relay():
        raise ValueError('Connect a General Radio (general-radio-1.1.0 or later) to update cube shows')
    p = editor.registry.publish()
    return dict(version=p.version, expected=len(editor.registry.expected))


@command('show.update_selected', 'hardware')
def show_update_selected(hub, macs):
    """Send the published show until the given cubes confirm it (a broadcast: other older cubes take it too)."""
    editor = _editor(hub)
    if not editor.relay():
        raise ValueError('Connect a General Radio (general-radio-1.1.0 or later) to update cube shows')
    macs = sorted({str(m).upper() for m in macs or ()})
    if not macs:
        raise ValueError('Tick the cubes to update first')
    p = editor.registry.publish(expected=macs)
    return dict(version=p.version, expected=len(macs))


@command('show.update', 'hardware')
def show_update(hub, mac):
    """Send the published show to one cube (never forced: a cube never goes back a version)."""
    editor = _editor(hub)
    if not editor.relay():
        raise ValueError('Connect a General Radio (general-radio-1.1.0 or later) to update cube shows')
    return dict(version=editor.registry.update(mac.upper()).version)


@command('show.auto_update', 'hardware')
def show_auto_update(hub, enabled):
    """Walk-around mode: any cube in range on an older show is updated automatically (the persisted
    `auto_show` setting, applied by hub.apply_auto_modes)."""
    _editor(hub)
    hub.settings['auto_show'] = bool(enabled)
    hub.save_settings()
    hub.apply_auto_modes()
    hub.mark_dirty('showedit')
    return bool(enabled)


@command('show.stop')
def show_stop(hub):
    """Stop sending the show (cubes keep whatever they committed)."""
    _editor(hub).registry.stop('Show update stopped by the operator')
    hub.mark_dirty('showedit')
    return True


@command('show.push_config', 'hardware')
def show_push_config(hub):
    """Tell the Mainshow controller the published show's length (bounds its timecode)."""
    return _editor(hub).push_config()


@command('show.live', 'hardware')
def show_live(hub, entries, lease_ms=600):
    """Mirror the editor's preview on real cubes: broadcast SHOW_LIVE with each cube number's colour.

    `entries` = [[cube_number, [r, g, b]], ...] in cube levels 0-100. Cubes on firmware v1.7.0+ show the
    colour for `lease_ms`, then fall back; a cube playing a show ignores it. Rate limited, held during a
    show update or a running show, fire-and-forget (no acknowledgment).
    """
    return _editor(hub).live(entries, lease_ms)
