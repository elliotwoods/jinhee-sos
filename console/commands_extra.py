"""Commands added by the handover verification pass (registered into commands.COMMANDS).

Kept in their own module so the file the General Radio work edits (commands.py) is untouched.
"""
import paths  # noqa: F401
import json

from commands import command, _job
from jobs import sync as sync_jobs

RUNS = paths.ROOT / 'flashing_station' / 'data' / 'runs'


@command('cube.recover_receipts')
def cube_recover_receipts(hub):
    """Import completed cube-flash receipts whose database save failed (flashing_station/data/runs/*/receipt.json)."""
    recovered, errors = 0, []
    for receipt in sorted(RUNS.glob('*/receipt.json')):
        try:
            r = json.loads(receipt.read_text(encoding='utf-8'))
            current = hub.db.conn.execute('SELECT result FROM flash_runs WHERE id=?', (r['id'],)).fetchone()
            if not current or current[0] == r['result'] or current[0] == 'success':
                continue
            hub.db.update_run(r['id'], result=r['result'], detail=r.get('detail', ''), finished_at=r.get('finished_at'))
            recovered += 1
        except Exception as exc:
            errors.append(f'{receipt.parent.name}: {exc}')
    hub.mark_dirty('inventory')
    hub.log(f'Receipt recovery: {recovered} saved hardware result(s) imported' + (f'; {len(errors)} unreadable' if errors else ''),
            'ok' if recovered else 'info', source='flash')
    return dict(recovered=recovered, errors=errors)


@command('sync.check')
def sync_check(hub):
    """Compare local, web and baseline without writing: the record-by-record plan of the next Sync."""
    return _job(sync_jobs.check_job(hub))


@command('sync.plan_clear')
def sync_plan_clear(hub):
    hub.sync['plan'] = None
    hub.mark_dirty('sync')
    return True


def _pool(hub, device):
    return hub.session_for(device, ('pool',))


@command('pool.record_start', 'hardware')
def pool_record_start(hub, device, stride=4, hold=5.0):
    """Start guided recording: the radio streams raw samples (RAW ON); the page prompts each tick to move to."""
    return _pool(hub, device).record_start(stride, hold)


@command('pool.record_reached')
def pool_record_reached(hub, device):
    """Reached this position: start the hold measurement for the prompted tick."""
    _pool(hub, device).record_reached()
    return True


@command('pool.record_abort')
def pool_record_abort(hub, device):
    _pool(hub, device).record_abort()
    return True


@command('pool.record_apply', 'hardware')
def pool_record_apply(hub, device, save=False, points=False):
    """Apply the recording's recommended tuning (live or saved) and optionally its measured control points."""
    return _pool(hub, device).record_apply(bool(save), bool(points))
