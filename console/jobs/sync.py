"""Web sync and zone-database publish/pull as jobs (network calls never run on the owner thread)."""
import paths  # noqa: F401

import sync_all
import web_client
import web_sync
import zone_publish
from sync_widget import summary as sync_summary
from web_client import Unauthorized, Unreachable, WebClient, client_name
from web_sync import SyncBusy

from jobs.base import Job
from locks import SUFFIXES


def client(hub, password=web_client.STORED):
    return WebClient(password=password, client=client_name('NCT Console'))


def status_job(hub):
    job = Job('sync.status', 'web', 'Check web sync status')
    database = hub.database

    def work(emit, cancel):
        return sync_all.status(database, client(hub))

    def done(job):
        if job.state == 'done' and isinstance(job.result, dict):
            hub.sync['status'] = job.result
            hub.sync['checked_at'] = hub.wall()
        elif job.error:
            hub.sync['status'] = dict(state='error', message=job.error)
        hub.sync['password_known'] = bool(web_client.load_password())
        hub.mark_dirty('sync')

    job.quiet = True
    hub.jobs.start(job, work, done)
    return job


def sync_job(hub, upload=True, download=True):
    if hub.sync['busy']:
        raise ValueError('A sync is already running')
    if not web_client.load_password():
        raise ValueError('Enter the web inventory password first (Sync › sign in)')
    job = Job('sync', 'web', 'Sync inventory and zone database')
    database, held = hub.database, SUFFIXES
    apply_ok = hub.idle_flag.is_set
    seen_versions = (hub.store.highest_seen(),)
    hub.sync['busy'] = True
    hub.mark_dirty('sync')

    def work(emit, cancel):
        emit('stage', 'Uploading, downloading and publishing')
        if upload and download:
            return sync_all.sync(database, client(hub), client_name('NCT Console'), held=held, apply_ok=apply_ok,
                                 seen_versions=seen_versions)
        result = web_sync.run(database, client(hub), client_name('NCT Console'), upload=upload, download=download,
                              held=held, apply_ok=apply_ok)
        return dict(sync=result, zone=None, blocked=None, zone_error=None)

    def done(job):
        hub.sync['busy'] = False
        if job.state == 'done':
            hub.sync['last_result'] = job.result
            hub.sync['summary'] = sync_summary(job.result or {})
            hub.sync['last_error'] = None
            job.outcome = dict(level='verified', text=hub.sync['summary'] or 'Synced')
            hub.log('Sync finished' + (': ' + hub.sync['summary'] if hub.sync['summary'] else ''), 'ok', source='sync')
        else:
            error = job.error or ''
            kind = 'other'
            if 'password' in error.lower() or 'unauthorized' in error.lower() or '401' in error:
                kind = 'unauthorized'
                web_client.forget_password()
            elif 'syncing right now' in error or 'SyncBusy' in error:
                kind = 'busy'
            elif 'unreachable' in error.lower():
                kind = 'unreachable'
            elif 'interrupted' in error.lower():
                kind = 'after_push'
            hub.sync['last_error'] = dict(kind=kind, text=error)
        hub.sync['password_known'] = bool(web_client.load_password())
        hub.mark_dirty('sync', 'inventory', 'registry')
        status_job(hub)

    hub.jobs.start(job, work, done)
    return job


def signin_job(hub, password):
    password = (password or '').strip()
    if not password:
        raise ValueError('Enter the web inventory password')
    job = Job('sync.signin', 'web', 'Check the web inventory password')

    def work(emit, cancel):
        client(hub, password=password).head()
        web_client.save_password(password)
        return True

    def done(job):
        if job.state == 'done':
            hub.sync['password_known'] = True
            hub.sync['last_error'] = None
            hub.log('Web inventory password accepted and stored on this computer', 'ok', source='sync')
            status_job(hub)
        else:
            hub.sync['last_error'] = dict(kind='unauthorized', text=job.error)
        hub.mark_dirty('sync')

    hub.jobs.start(job, work, done)
    return job


def zone_pull_job(hub):
    job = Job('zone.pull', 'web', 'Pull the published zone database')
    database = hub.database

    def work(emit, cancel):
        return zone_publish.pull(database, client(hub))

    def done(job):
        hub.mark_dirty('inventory', 'registry')
        if job.state == 'done':
            job.outcome = dict(level='verified', text=str(job.result))
        status_job(hub)

    hub.jobs.start(job, work, done)
    return job


def zone_publish_job(hub):
    job = Job('zone.publish', 'web', 'Publish the zone database')
    database = hub.database
    seen = (hub.store.highest_seen(),)

    def work(emit, cancel):
        return zone_publish.publish(database, client(hub), client_name('NCT Console'), seen_versions=seen)

    def done(job):
        hub.mark_dirty('inventory', 'registry')
        if job.state == 'done':
            job.outcome = dict(level='verified', text=str(job.result))
        status_job(hub)

    hub.jobs.start(job, work, done)
    return job


def check_job(hub):
    """What a Sync would move, record by record, without writing anything (web_sync.check)."""
    if not web_client.load_password():
        raise ValueError('Enter the web inventory password first (Sync › sign in)')
    job = Job('sync.check', 'web', 'Check what a Sync would move')
    database = hub.database

    def work(emit, cancel):
        result = web_sync.check(database, client(hub))
        local, remote, merged = result['local'], result['remote'], result['merged']
        rows = []
        for mac in sorted(set(result['upload']) | set(result['download'])):
            change = 'both' if mac in result['upload'] and mac in result['download'] else 'upload' if mac in result['upload'] else 'download'
            rows.append(dict(mac=mac, change=change, local=local.get(mac), web=remote.get(mac), after=merged.get(mac),
                             decided=mac in result['auto_resolved']))
        return dict(rows=rows, upload=len(result['upload']), download=len(result['download']), lost=result['lost'],
                    notes=result.get('notes'), revision=result['revision'], sightings=result.get('sightings'))

    def done(job):
        if job.state == 'done':
            hub.sync['plan'] = dict(job.result, checked_at=hub.wall())
            hub.sync['last_error'] = None
            job.outcome = dict(level='verified', text=f'{job.result["upload"]} to upload · {job.result["download"]} to download')
        else:
            hub.sync['last_error'] = dict(kind='other', text=job.error)
        hub.mark_dirty('sync')

    hub.jobs.start(job, work, done)
    return job
