"""Main show publish/pull as jobs (network calls never run on the owner thread)."""
import paths  # noqa: F401

import show_publish
import web_client
from web_client import client_name

from jobs.base import Job
from jobs.sync import client


def show_pull_job(hub):
    job = Job('show.pull', 'web', 'Pull the published main show')
    database = hub.database

    def work(emit, cancel):
        published, status = show_publish.pull(database, client(hub))
        return dict(published=published, status=status)

    def done(job):
        hub.mark_dirty('showedit')
        if job.state == 'done':
            p = job.result['published']
            text = {'none': 'No show published on the web yet', 'current': f'Show v{p["version"]} is already here',
                    'updated': f'Pulled show v{p["version"]}'}[job.result['status']]
            job.outcome = dict(level='verified', text=text)
            hub.log(text, 'ok', source='show')

    hub.jobs.start(job, work, done)
    return job


def show_publish_job(hub, doc):
    if not web_client.load_password():
        raise ValueError('Enter the web inventory password first (Sync › sign in)')
    job = Job('show.publish', 'web', 'Publish the main show')
    database = hub.database
    seen = (hub.showedit.registry.store.highest_seen(),)

    def work(emit, cancel):
        return show_publish.publish(database, client(hub), client_name('NCT Console'), doc, seen_versions=seen)

    def done(job):
        hub.mark_dirty('showedit')
        if job.state == 'done':
            p = job.result['published']
            text = f'Show v{p["version"]} published' if job.result['changed'] else f'Unchanged: show v{p["version"]} is already published'
            job.outcome = dict(level='verified', text=text)
            hub.log(text + '. Cubes take it from Update all (a General Radio) and keep their show until then.', 'ok', source='show')

    hub.jobs.start(job, work, done)
    return job
