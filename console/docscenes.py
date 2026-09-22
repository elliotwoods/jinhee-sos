"""Staged situations for the handover screenshots (and the in-process test that every one of them settles).

Each scenario stages the `docs` simulation (simdocs.install) into the state one handover step
describes, then says which route to open and which controls to outline. `console/tools/docshots.py`
drives these through the loopback API of a running `app.py --simulate --scenario docs`;
`tests/test_docscenes.py` runs the same setup/settled pairs in-process.

URL grammar understood by the page (web/lib/doc.js):
    #/<section>[/<id>[/<tab>]]?hl=<tokens>&open=<tokens>&dock=1&theme=light&still=1&explainers=1&search=<text>
`hl` tokens are data-doc names (`name`, `name*` prefix, or `css:<selector>`).
"""
import paths  # noqa: F401
import time
from urllib.parse import quote

import simdocs
import simulate
from jobs.base import Job

SCENARIOS = []


def scenario(id, chapter, step, en, kr, route, hl=(), open=(), dock=False, settle=8.0, size=None, search=None):
    def wrap(fn):
        SCENARIOS.append(dict(id=id, chapter=chapter, step=step, en=en, kr=kr, route=route, hl=list(hl), open=list(open), dock=dock,
                              settle=settle, size=size, search=search, setup=fn, settled=None))
        return fn
    return wrap


def settled(id):
    def wrap(fn):
        for s in SCENARIOS:
            if s['id'] == id:
                s['settled'] = fn
                return fn
        raise KeyError(id)
    return wrap


def by_id(id):
    for s in SCENARIOS:
        if s['id'] == id:
            return s
    raise KeyError(id)


# ---------------------------------------------------------------- helpers
def sim(hub):
    return hub._sim


def device(hub, key):
    """The Device for a fake board (by simdocs key) once the hub has identified it."""
    board = sim(hub)[key]
    for d in hub.devices.values():
        if d.port == board.port:
            return d
    raise LookupError(f'{board.port} is not on the rail yet')


def session(hub, key):
    return hub.sessions.get(device(hub, key).id)


def cmd(hub, name, **args):
    """Run a console command as the page would (confirming destructive kinds first, like the hold)."""
    import commands
    import commands_extra  # noqa: F401
    entry = commands.COMMANDS[name]
    token = hub.confirm(name, args)['token'] if entry['kind'] == 'destructive' else None
    return commands.run(hub, name, args, token=token)


def route(hub, s):
    """The final hash for a scenario, with device ids resolved and the doc query appended."""
    r = s['route']
    if callable(r):
        r = r(hub)
    query = []
    if s['hl']:
        query.append('hl=' + quote(','.join(s['hl']), safe=',:*.'))
    if s['open']:
        query.append('open=' + quote(','.join(s['open']), safe=',:*.'))
    if s['dock']:
        query.append('dock=1')
    if s['search']:
        query.append('search=' + quote(s['search']))
    query.append('still=1')
    return r + (('&' if '?' in r else '?') + '&'.join(query) if query else '')


def wait(hub, predicate, timeout=8.0, dt=0.02):
    """In-process settle (tests): tick the hub until the predicate holds."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        hub.tick()
        if predicate():
            return True
        time.sleep(dt)
    return predicate()


def base(hub):
    """Every chapter starts here: boards identified, sessions open, the station discovered its cubes,
    the published database is v32 and the sync status is 'up to date'."""
    sim(hub)['station'].hold_register = False
    ok = wait(hub, lambda: all(hub.sessions.get(device(hub, k).id) for k in ('station', 'plate', 'pool', 'radio', 'mainshow'))
              and hub.station_session().controller.connected, timeout=12)
    if not ok:
        raise RuntimeError('docs bench did not come up')
    cmd(hub, 'pairing.discover', device=device(hub, 'station').id)
    wait(hub, lambda: sim(hub)['known_mac'] in hub.station_session().controller.discovered, timeout=4)
    cmd(hub, 'zones.query', device=device(hub, 'station').id)
    wait(hub, lambda: len(hub.station_session().zones.snapshot().get('zones') or []) >= 3
         and all(r.get('in_range') for r in hub.station_session().zones.snapshot()['zones']), timeout=6)
    return True


def reset(hub):
    """Between scenarios of one chapter: stop what runs, release holds."""
    reset_register(hub)
    st = hub.station_session()
    if st and st.controller.mode:
        st.controller.stop()
    if st and st.zones.snapshot().get('walkaround'):
        cmd(hub, 'zones.walkaround', enabled=False, device=device(hub, 'station').id)   # Auto-update all ends with its chapter
    if st and st.zones.snapshot().get('publishing'):
        cmd(hub, 'zones.stop', device=device(hub, 'station').id)
    for key in ('station',):
        board = sim(hub)[key]
        board.hold_register = board.hold_publish = False
        board.pending_publish = None
        if board.pending_register:
            board.release_register(True)
    simdocs.docs_sync(hub, 'ok', web_version=32)     # C-5/C-6 change the sync status; every chapter starts synced
    hub.sync['password_known'] = True
    hub.sync['plan'] = None
    hub._sim['show_ready'] = False
    for key in ('plate', 'pool'):
        simdocs.doc_release(hub, device(hub, key).id)
        sess = session(hub, key)
        if sess and hasattr(sess, 'disarm'):
            sess.disarm()   # leases end with the chapter, as Esc/Stop would
    if session(hub, 'radio'):
        session(hub, 'radio').release_all() if hasattr(session(hub, 'radio'), 'release_all') else None
    simdocs.release_job(hub)
    wait(hub, lambda: not hub.jobs.running() and not (st and st.controller.mode), timeout=6)
    hub.jobs.jobs.clear()
    hub.jobs.order.clear()
    hub.mark_dirty('jobs')


def station_route(hub, tab='station'):
    return f'#/devices/{device(hub, "station").id}/{tab}'


def cube_route(hub, key='cube', tab='overview'):
    return f'#/devices/{device(hub, key).id}/{tab}'


def zone_route(hub, key, tab='monitor'):
    return f'#/devices/{device(hub, key).id}/{tab}'


def plate_behind(hub):
    """The plate holds the older v31 again (steps are replayable in any order) and every view knows it."""
    plate = sim(hub)['plate']
    plate.db_version, plate.db_count, plate.db_crc = 31, 32, 0x11E2A0F3
    cmd(hub, 'zones.query', device=device(hub, 'station').id)
    s = session(hub, 'plate')
    if s:
        s.last_report = 0.0   # re-read the `?` report now, so the USB evidence says v31 too
    wait(hub, lambda: any(r.get('mac') == plate.mac and int(r.get('db_version') or 0) == 31
                          for r in _station(hub).zones.snapshot().get('zones') or [])
         and ((session(hub, 'plate').snapshot().get('report') or {}).get('db_version') == 31), timeout=6)


def _station(hub):
    return hub.station_session()


# ---------------------------------------------------------------- 03 registration: the Register page
NEW_CUBE = dict(port='/dev/sim.cube-new', mac='A4:CF:12:34:56:9B', uid='04:A2:2B:1C:53:80:9B')


def reset_register(hub):
    """Register scenes end with their chapter: switch the workflow off, unplug the new cube, forget its number."""
    hub.settings['auto_register'] = False
    flow = hub.regflow
    flow.tick()   # switched off mid-flow: cancels and stops the station
    flow.clear()
    flow.history = []
    flow.was_enabled = False
    if any(d.port == NEW_CUBE['port'] for d in hub.devices.values()):
        hub.scanner.remove(NEW_CUBE['port'])
        wait(hub, lambda: not any(d.port == NEW_CUBE['port'] for d in hub.devices.values()), timeout=4)   # replug = a new identification
    if hub.db.get(NEW_CUBE['mac']):
        hub.db.unregister(NEW_CUBE['mac'], 'docs bench replay')   # the next replay is a new cube again
    hub.mark_dirty('register')


def register_route(hub):
    return '#/register'


@scenario('03-A1', 3, 1, 'Register: switch on "Register cubes as they are plugged in"', 'Register: "Register cubes as they are plugged in" 켜기',
          register_route, hl=['register.enable'])
def s03_a1(hub):
    hub.pinned_mac = None
    cmd(hub, 'register.enable', on=True)


@settled('03-A1')
def s03_a1_ok(hub):
    return hub.regflow.enabled and hub.regflow.step == 'idle'


@scenario('03-A2', 3, 2, 'A new cube plugged in: NEW NUMBER for its label, then scan its tag', '새 큐브 연결: 라벨용 새 번호, 이어서 태그 스캔',
          register_route, hl=['register.flow', 'station.banner'], dock=True)
def s03_a2(hub):
    s03_a1(hub)
    sim(hub)['station'].scan_clear()
    hub.scanner.add(simulate.FakeCube(NEW_CUBE['port'], NEW_CUBE['mac']))
    wait(hub, lambda: hub.regflow.armed, timeout=6)
    sim(hub)['station'].scan_clear()   # the reader is empty: READY TO SCAN


@settled('03-A2')
def s03_a2_ok(hub):
    f, c = hub.regflow, _station(hub).controller
    return f.mac == NEW_CUBE['mac'] and f.step == 'nfc' and f.armed and c.mode == 'repair' and c.phase == 'identifying' \
        and (c.feedback or {}).get('title', '').startswith('READY TO SCAN')


@scenario('03-A3', 3, 3, 'Registered and synced: unplug it and plug in the next cube', '등록 및 동기화 완료: 분리하고 다음 큐브 연결',
          register_route, hl=['register.flow'], dock=True)
def s03_a3(hub):
    s03_a2(hub)
    wait(hub, lambda: s03_a2_ok(hub), timeout=6)
    hub.sync['password_known'] = False   # hold the sync step: the bench never syncs with a web server
    sim(hub)['station'].scan(NEW_CUBE['uid'])
    wait(hub, lambda: _station(hub).controller.phase == 'removal', timeout=4)
    sim(hub)['station'].scan_clear()
    wait(hub, lambda: hub.regflow.step == 'sync' and 'Sign in' in hub.regflow.wait, timeout=4)
    job = Job('sync', 'web', 'Sync')
    hub.jobs.start(job, lambda emit, cancel: dict(zone_error=None))
    hub.sync['summary'] = 'Inventory ↑1 · zone database v33 published'
    hub.regflow.sync_job = job.id
    hub.sync['password_known'] = True


@settled('03-A3')
def s03_a3_ok(hub):
    return hub.regflow.step == 'done' and bool(hub.regflow.history)


# ---------------------------------------------------------------- 03 registration: from the cube panel
@scenario('03-1', 3, 1, 'Cube card after USB identification: the pinned cube, its number and tag', 'USB 식별 후 큐브 카드: 고정된 큐브, 번호와 태그',
          lambda hub: cube_route(hub, 'cube45'), hl=['cube.number', 'pairing.register'])
def s03_1(hub):
    hub.pinned_mac = device(hub, 'cube45').mac
    device(hub, 'cube45').pinned = True
    hub.mark_dirty('devices', 'inventory')


@settled('03-1')
def s03_1_ok(hub):
    return device(hub, 'cube45').pinned and hub.station_session().controller.connected


@scenario('03-2', 3, 2, 'Register (scan a tag)', '등록 (태그 스캔)',
          lambda hub: cube_route(hub, 'cube45'), hl=['pairing.register'], open=['pairing.register'])
def s03_2(hub):
    s03_1(hub)


@settled('03-2')
def s03_2_ok(hub):
    return s03_1_ok(hub)


@scenario('03-3', 3, 3, 'READY TO SCAN: the cube flashes, the station waits for a fresh tag', 'READY TO SCAN: 큐브가 점멸하고 스테이션이 새 태그를 기다림',
          lambda hub: station_route(hub), hl=['station.banner', 'pairing.stop'], dock=True)
def s03_3(hub):
    s03_1(hub)
    sim(hub)['station'].scan_clear()
    cmd(hub, 'pairing.register', mac=device(hub, 'cube45').mac, device=device(hub, 'station').id)


@settled('03-3')
def s03_3_ok(hub):
    c = _station(hub).controller
    return c.mode == 'repair' and c.phase == 'identifying'


@scenario('03-4', 3, 4, 'TAG DETECTED · REGISTERING: the mapping is being delivered over the radio', 'TAG DETECTED · REGISTERING: 매핑이 무선으로 전달되는 중',
          lambda hub: station_route(hub), hl=['station.banner', 'station.ladder'], dock=True)
def s03_4(hub):
    sim(hub)['station'].hold_register = True
    s03_3(hub)
    wait(hub, lambda: s03_3_ok(hub), timeout=4)
    sim(hub)['station'].scan('04:A2:2B:1C:53:80:45')


@settled('03-4')
def s03_4_ok(hub):
    c = _station(hub).controller
    return c.mode == 'repair' and c.phase == 'registering' and sim(hub)['station'].pending_register is not None


@scenario('03-5', 3, 5, 'REGISTERED: acknowledged by the cube; the row shows the committed tag', 'REGISTERED: 큐브가 확인 응답; 행에 확정 태그 표시',
          lambda hub: cube_route(hub, 'cube45'), hl=['cube.tag', 'cube.ladder'], dock=True)
def s03_5(hub):
    s03_4(hub)
    wait(hub, lambda: s03_4_ok(hub), timeout=4)
    sim(hub)['station'].release_register(True)
    wait(hub, lambda: _station(hub).controller.phase == 'removal', timeout=3)
    sim(hub)['station'].scan_clear()


@settled('03-5')
def s03_5_ok(hub):
    row = hub.db.get(device(hub, 'cube45').mac)
    return bool(row and row['uid'] == '04:A2:2B:1C:53:80:45' and not _station(hub).controller.mode)


# ---------------------------------------------------------------- 04 cube firmware
def _cube_stale(hub):
    d = device(hub, 'cube')
    sim(hub)['cube'].firmware = 'v1.3.9-USB'
    d.details = dict(d.details or {}, firmware='v1.3.9-USB')
    d.firmware = 'v1.3.9-USB'
    d.fw_status = dict(status='differs', reported='v1.3.9-USB', expected=hub.builds.get('cube', {}).get('version') or 'v1.4.1-USB.2',
                       text='Reported firmware v1.3.9-USB differs from the local build')
    hub.usb_firmware[d.mac] = d.fw_status
    hub.mark_dirty('devices')


@scenario('04-1', 4, 1, 'Cube › Firmware: the reported version differs from the local build', 'Cube › Firmware: 보고된 버전이 로컬 빌드와 다름',
          lambda hub: cube_route(hub, 'cube', 'firmware'), hl=['cube.fw.verdict', 'cube.flash_firmware'])
def s04_1(hub):
    _cube_stale(hub)


@settled('04-1')
def s04_1_ok(hub):
    return (device(hub, 'cube').fw_status or {}).get('status') == 'differs'


FLASH_STEPS = [('Backing up NVS', 10, '$ esptool read-flash 0x9000 0x5000 nvs-backup.bin'), ('Writing firmware', 35, '$ esptool write-flash 0x10000 neocore_usb.ino.bin'),
               (None, 55, 'Writing at 0x0004c000... (55 %)'), (None, 80, 'Hash of data verified.'), ('Checking the reboot', 92, 'Cube MAC: A4:CF:12:34:56:78'),
               (None, 100, 'FW: v1.4.1-USB.2 · READY')]


@scenario('04-2', 4, 2, 'Flashing: the job card shows the stage and progress; the port is held', '플래시 중: 작업 카드에 단계와 진행률 표시, 포트 점유',
          lambda hub: cube_route(hub, 'cube', 'firmware'), hl=['job:cube.flash'], dock=True)
def s04_2(hub):
    _cube_stale(hub)
    d = device(hub, 'cube')
    simdocs.scripted_job(hub, d, 'cube.flash', f'Flash cube {d.mac} with v1.4.1-USB.2', FLASH_STEPS,
                         dict(level='verified', text='Verified: reported v1.4.1-USB.2 after reboot'), hold_at=55)


@settled('04-2')
def s04_2_ok(hub):
    return any(j.kind == 'cube.flash' and j.state == 'running' and (j.progress or 0) >= 55 for j in hub.jobs.jobs.values())


def _cube_verified(hub):
    d = device(hub, 'cube')
    sim(hub)['cube'].firmware = 'v1.4.1-USB.2'
    d.details = dict(d.details or {}, firmware='v1.4.1-USB.2')
    d.firmware = 'v1.4.1-USB.2'
    d.fw_status = dict(status='current', reported='v1.4.1-USB.2', expected='v1.4.1-USB.2', text='Reported firmware matches the local build')
    hub.usb_firmware[d.mac] = d.fw_status
    try:
        ident = f'docs-{int(hub.wall())}'
        build = hub.builds.get('cube') or {}
        hub.db.start(ident, d.port, dict(version=build.get('version') or 'v1.4.1-USB.2', build_hash=build.get('build_hash') or 'simulated'), 'simulated.log')
        hub.db.update_run(ident, mac=d.mac, stage='reboot', result='success', detail='Verified: reported v1.4.1-USB.2 after reboot',
                          finished_at=time.strftime('%Y-%m-%d %H:%M:%S'))
    except Exception as exc:
        hub.log(f'docs: flash run not recorded: {exc}', 'warn')
    hub.mark_dirty('devices', 'inventory')


@scenario('04-3', 4, 3, 'Verified: the cube rebooted and reported the new version', '검증 완료: 큐브가 재부팅 후 새 버전을 보고함',
          lambda hub: cube_route(hub, 'cube', 'firmware'), hl=['job:cube.flash', 'cube.fw.verdict'], dock=True)
def s04_3(hub):
    _cube_stale(hub)
    d = device(hub, 'cube')
    simdocs.scripted_job(hub, d, 'cube.flash', f'Flash cube {d.mac} with v1.4.1-USB.2', FLASH_STEPS,
                         dict(level='verified', text='Verified: reported v1.4.1-USB.2 after reboot'), after=_cube_verified)


@settled('04-3')
def s04_3_ok(hub):
    return any(j.kind == 'cube.flash' and j.state == 'done' for j in hub.jobs.jobs.values()) and \
        (device(hub, 'cube').fw_status or {}).get('status') == 'current'


@scenario('04-4', 4, 4, 'Cube › History and Check boot', 'Cube › History 및 Check boot',
          lambda hub: cube_route(hub, 'cube', 'history'), hl=['cube.check_boot', 'cube.history'])
def s04_4(hub):
    _cube_verified(hub)


@settled('04-4')
def s04_4_ok(hub):
    return (device(hub, 'cube').fw_status or {}).get('status') == 'current'


# ---------------------------------------------------------------- 06 wireless database
@scenario('06-1', 6, 1, 'Zone relay: every zone in range with its database version and signal', 'Zone relay: 범위 내 모든 존과 데이터베이스 버전, 신호',
          lambda hub: station_route(hub, 'relay'), hl=['relay.table', 'zones.query'])
def s06_1(hub):
    pass


@settled('06-1')
def s06_1_ok(hub):
    return len(_station(hub).zones.snapshot().get('zones') or []) >= 2


@scenario('06-2', 6, 2, 'Update all: chunks are being sent to the zones that are behind', 'Update all: 뒤처진 존에 청크 전송 중',
          lambda hub: station_route(hub, 'relay'), hl=['relay.progress', 'zones.stop'], dock=True)
def s06_2(hub):
    plate_behind(hub)
    sim(hub)['station'].hold_publish = True
    cmd(hub, 'zones.update_all', device=device(hub, 'station').id)


@settled('06-2')
def s06_2_ok(hub):
    return bool((hub.sections.get('registry') or {}).get('publishing'))


@scenario('06-3', 6, 3, 'Database v32 confirmed on the plate', '플레이트에서 데이터베이스 v32 확인됨',
          lambda hub: station_route(hub, 'relay'), hl=['relay.table', 'relay.zone:14:63:93:C0:EC:14'], dock=True)
def s06_3(hub):
    plate_behind(hub)
    sim(hub)['station'].hold_publish = False
    cmd(hub, 'zones.update_all', device=device(hub, 'station').id)


@settled('06-3')
def s06_3_ok(hub):
    snap = _station(hub).zones.snapshot()
    z = next((r for r in snap.get('zones') or [] if r.get('mac') == '14:63:93:C0:EC:14'), {})
    return sim(hub)['plate'].db_version == 32 and int(z.get('db_version') or 0) == 32 and not snap.get('publishing')


@scenario('06-4', 6, 4, 'Auto-update all while walking the space', '공간을 걸으며 Auto-update all',
          lambda hub: station_route(hub, 'relay'), hl=['zones.walkaround'])
def s06_4(hub):
    cmd(hub, 'zones.walkaround', enabled=True, device=device(hub, 'station').id)


@settled('06-4')
def s06_4_ok(hub):
    return bool((hub.sections.get('registry') or {}).get('walkaround'))


# ---------------------------------------------------------------- 07 zone provisioning
@scenario('07-1', 7, 1, 'A blank board: Firmware & database with the provisioning form', '빈 보드: 프로비저닝 폼이 있는 Firmware & database',
          lambda hub: zone_route(hub, 'blank', 'firmware'), hl=['zone.fw.form', 'zone.flash'])
def s07_1(hub):
    pass


@settled('07-1')
def s07_1_ok(hub):
    return device(hub, 'blank').role == 'zone'


ZONE_STEPS = [('Building the zone image', 8, 'Using the built preshow-3.4.0 image (manifest verified)'), ('Writing firmware', 30, '$ esptool write-flash 0x10000 PreshowZone.ino.bin'),
              (None, 52, 'Writing at 0x00090000... (52 %)'), ('Writing configuration and database', 78, 'Zone config: type=1 point=2 name=Preshow 2 · database v32'),
              ('Reading back', 90, 'Hash of data verified.'), ('Waiting for the report', 100, 'ZONE: type=1 point=2 name=Preshow 2 · DB: version=32 · READY')]


@scenario('07-2', 7, 2, 'Flashing the zone: firmware, configuration and database in one job', '존 플래시: 펌웨어·설정·데이터베이스를 한 작업으로',
          lambda hub: zone_route(hub, 'blank', 'firmware'), hl=['job:zone.flash'], dock=True)
def s07_2(hub):
    d = device(hub, 'blank')
    simdocs.scripted_job(hub, d, 'zone.flash', 'Flash Preshow 2 (point 2) with preshow-3.4.0 + database v32', ZONE_STEPS,
                         dict(level='verified', text='Report matches: Preshow 2 · preshow-3.4.0 · database v32'), hold_at=52)


@settled('07-2')
def s07_2_ok(hub):
    return any(j.kind == 'zone.flash' and j.state == 'running' and (j.progress or 0) >= 52 for j in hub.jobs.jobs.values())


def _blank_provisioned(hub):
    b = sim(hub)['blank']
    p = sim(hub)['publication']
    b.zone_type, b.point, b.name, b.db_version, b.db_count, b.db_crc = 1, 2, 'Preshow 2', 32, p['count'], p['crc']


@scenario('07-3', 7, 3, 'Verified: the report after reboot matches what was written', '검증 완료: 재부팅 후 보고가 기록 내용과 일치',
          lambda hub: zone_route(hub, 'blank', 'firmware'), hl=['job:zone.flash', 'zone.fw.identity'], dock=True)
def s07_3(hub):
    d = device(hub, 'blank')
    simdocs.scripted_job(hub, d, 'zone.flash', 'Flash Preshow 2 (point 2) with preshow-3.4.0 + database v32', ZONE_STEPS,
                         dict(level='verified', text='Report matches: Preshow 2 · preshow-3.4.0 · database v32'), after=_blank_provisioned)


@settled('07-3')
def s07_3_ok(hub):
    return any(j.kind == 'zone.flash' and j.state == 'done' for j in hub.jobs.jobs.values()) and \
        (device(hub, 'blank').details or {}).get('name') == 'Preshow 2'


@scenario('07-4', 7, 4, 'Cube monitor: a tag was read and the cube found', '큐브 모니터: 태그를 읽고 큐브를 찾음',
          lambda hub: zone_route(hub, 'plate', 'monitor'), hl=['zone.monitor.ring', 'zone.monitor.card'])
def s07_4(hub):
    plate = sim(hub)['plate']
    plate.taps = [(0.0, '04:11:22:33:44:55:66')]
    plate.started = hub.clock()


@settled('07-4')
def s07_4_ok(hub):
    s = session(hub, 'plate')
    return bool(s and s.state.current and s.state.current.get('cube_id') == 12)


# ---------------------------------------------------------------- 08 preshow
@scenario('08-1', 8, 1, 'Cue test: take the lease, then press a POINT button', 'Cue test: 리스를 잡은 뒤 POINT 버튼을 누름',
          lambda hub: zone_route(hub, 'plate', 'cue'), hl=['preshow.arm', 'preshow.cue'])
def s08_1(hub):
    sim(hub)['plate'].media_mode = 'modern'
    d = device(hub, 'plate')
    simdocs.doc_hold(hub, d.id)
    cmd(hub, 'preshow.arm', device=d.id)


@settled('08-1')
def s08_1_ok(hub):
    s = session(hub, 'plate')
    return bool(s and s.armed)


@scenario('08-2', 8, 2, 'Point 2 ON, acknowledged by the media bridge', '포인트 2 ON, 미디어 브리지가 확인 응답',
          lambda hub: zone_route(hub, 'plate', 'cue'), hl=['preshow.state', 'preshow.cue'], dock=True)
def s08_2(hub):
    s08_1(hub)
    wait(hub, lambda: s08_1_ok(hub), timeout=4)
    cmd(hub, 'preshow.cue', on=True, point=2, device=device(hub, 'plate').id)


@settled('08-2')
def s08_2_ok(hub):
    s = session(hub, 'plate')
    return bool(s and (s.host or {}).get('state') == 'ON')


# ---------------------------------------------------------------- 10 pool
@scenario('10-1', 10, 1, 'Calibration: lease taken, the live reading and the band diagram', '캘리브레이션: 리스 획득, 실시간 값과 밴드 다이어그램',
          lambda hub: zone_route(hub, 'pool', 'calibration'), hl=['pool.arm', 'pool.bands'])
def s10_1(hub):
    d = device(hub, 'pool')
    simdocs.doc_hold(hub, d.id)
    cmd(hub, 'pool.arm', device=d.id)


@settled('10-1')
def s10_1_ok(hub):
    s = session(hub, 'pool')
    return bool(s and s.ready and s.arm_requested and (s.interaction or {}).get('override'))


@scenario('10-2', 10, 2, 'Capture control point 12 from the live reading', '실시간 값으로 제어점 12 캡처',
          lambda hub: zone_route(hub, 'pool', 'calibration'), hl=['pool.point:12'])
def s10_2(hub):
    s10_1(hub)
    wait(hub, lambda: s10_1_ok(hub), timeout=4)
    cmd(hub, 'pool.cal_set', index=12, mm=212.0, device=device(hub, 'pool').id)


@settled('10-2')
def s10_2_ok(hub):
    s = session(hub, 'pool')
    return bool(s and s.calibration and abs(s.calibration['ticks'][11] - 212.0) < 0.2 and not s.calibration.get('saved'))


@scenario('10-3', 10, 3, 'Apply & save: the board confirms with saved=true', 'Apply & save: 보드가 saved=true로 확인',
          lambda hub: zone_route(hub, 'pool', 'calibration'), hl=['pool.saved', 'pool.cal_save'], dock=True)
def s10_3(hub):
    s10_2(hub)
    wait(hub, lambda: s10_2_ok(hub), timeout=4)
    cmd(hub, 'pool.cal_save', device=device(hub, 'pool').id)


@settled('10-3')
def s10_3_ok(hub):
    s = session(hub, 'pool')
    return bool(s and s.calibration and s.calibration.get('saved') and abs(s.calibration['ticks'][11] - 212.0) < 0.2)


@scenario('10-4', 10, 4, 'Guided recording: hold the slider at the prompted tick', '가이드 녹화: 안내된 눈금에서 슬라이더 고정',
          lambda hub: zone_route(hub, 'pool', 'diagnostics'), hl=['pool.record', 'pool.record_reached'])
def s10_4(hub):
    s10_1(hub)
    wait(hub, lambda: s10_1_ok(hub), timeout=4)
    d = device(hub, 'pool')
    cmd(hub, 'pool.record_start', stride=4, hold=30.0, device=d.id)
    wait(hub, lambda: session(hub, 'pool').rec is not None, timeout=2)
    cmd(hub, 'pool.record_reached', device=d.id)


@settled('10-4')
def s10_4_ok(hub):
    s = session(hub, 'pool')
    return bool(s and s.rec and s.rec['state'] == 'hold' and len(s.rec['buffer']) >= 3)


# ---------------------------------------------------------------- 11 mainshow
@scenario('11-1', 11, 1, 'Show section: the controller, cube number and the two steps', 'Show 섹션: 컨트롤러, 큐브 번호와 두 단계',
          '#/show?cube=44', hl=['show.controller', 'show.cube', 'mainshow.ready', 'mainshow.trigger'])
def s11_1(hub):
    pass


@settled('11-1')
def s11_1_ok(hub):
    return hub.show_session() is not None


@scenario('11-2', 11, 2, '① Mainshow ready delivered: the cube turns neon', '① Mainshow ready 전달됨: 큐브가 네온으로',
          '#/show', hl=['mainshow.ready', 'show.ladder'], dock=True)
def s11_2(hub):
    if not sim(hub).get('show_ready'):
        cmd(hub, 'mainshow.ready', cube=44)
        sim(hub)['show_ready'] = True


@settled('11-2')
def s11_2_ok(hub):
    s = hub.show_session()
    if not s or not s.session.connected or s.session.pending:
        return False
    return any(e.get('kind') == 'log' and e.get('device') == s.device.id and 'delivered' in (e.get('text') or '') for e in list(hub.notable)[-30:])


@scenario('11-3', 11, 3, '② Trigger mainshow', '② Trigger mainshow',
          '#/show', hl=['mainshow.trigger'], open=['mainshow.trigger'])
def s11_3(hub):
    s11_2(hub)


@settled('11-3')
def s11_3_ok(hub):
    return s11_2_ok(hub)


@scenario('11-4', 11, 4, 'Show running: the clock counts the expected timeline', '쇼 진행 중: 시계가 예상 타임라인을 셈',
          '#/show', hl=['show.clock', 'mainshow.idle'], dock=True)
def s11_4(hub):
    s11_2(hub)
    wait(hub, lambda: s11_2_ok(hub), timeout=4)
    cmd(hub, 'mainshow.trigger', cube=44)


@settled('11-4')
def s11_4_ok(hub):
    s = hub.show_session()
    return bool(s and s.snapshot().get('show'))


# ---------------------------------------------------------------- 11 the Show editor
def seed_show(hub, version=5):
    """A published show (the working copy as version `version`) so the Cubes card offers Update all to vN."""
    import base64
    import showfile
    from show_registry import image_hash
    doc = hub.showedit.draft
    image = showfile.pack(doc)
    hub.showedit.registry.store.cache(dict(version=version, hash=image_hash(image), crc=showfile.crc32(image), length=len(image),
                                           image_b64=base64.b64encode(image).decode(), source=doc,
                                           published_at='2026-09-23T10:00:00+09:00', published_by='documentation pass'))
    hub.mark_dirty('showedit')


@scenario('11-5', 11, 5, 'Show editor: transport, timeline, the previewed cubes and Send to real cubes', 'Show editor: 트랜스포트, 타임라인, 미리보기 큐브와 Send to real cubes',
          '#/showedit', hl=['css:.show-transport', 'css:.show-cubes', 'show.publish'])
def s11_5(hub):
    seed_show(hub)


@settled('11-5')
def s11_5_ok(hub):
    return hub.showedit.registry.store.published()['version'] >= 5 and hub.showedit.relay() is not None


@scenario('11-6', 11, 6, 'Cubes: Query cubes, then Update all to the published version', 'Cubes: Query cubes 후 게시 버전으로 Update all',
          '#/showedit', hl=['show.query', 'show.update_all'])
def s11_6(hub):
    seed_show(hub)
    wait(hub, lambda: hub.showedit.relay() is not None, timeout=6)
    cmd(hub, 'show.query')


@settled('11-6')
def s11_6_ok(hub):
    return bool(hub.showedit.registry.cube_rows())


# ---------------------------------------------------------------- console-specific
@scenario('C-1', 0, 1, 'The console: device rail, attention panel, timeline dock', '콘솔: 장치 레일, Attention 패널, 타임라인 도크',
          '#/devices', hl=['rail', 'attention', 'topbar.sync'], dock=True)
def sC_1(hub):
    pass


@settled('C-1')
def sC_1_ok(hub):
    return len(hub.devices) >= 7


@scenario('C-2', 0, 2, 'Unknown tag on the plate, known here: Update database over USB', '플레이트에서 알 수 없는 태그, 여기서는 알려짐: USB로 데이터베이스 업데이트',
          lambda hub: zone_route(hub, 'plate', 'monitor'), hl=['attention.card:tag.known_zone_behind', 'attention.action:zone.update_db_usb'], settle=15)
def sC_2(hub):
    plate = sim(hub)['plate']
    plate_behind(hub)
    plate.taps = [(0.0, sim(hub)['known_uid'])]
    plate.started = hub.clock()


@settled('C-2')
def sC_2_ok(hub):
    return any(c['rule'] == 'tag.known_zone_behind' for c in (hub.sections.get('advisor') or {}).get('suggestions', []))


@scenario('C-3', 0, 3, 'A suggestion card menu: dismiss for this session', '제안 카드 메뉴: 이 세션 동안 무시',
          lambda hub: zone_route(hub, 'plate', 'monitor'), hl=['attention.menu:tag.known_zone_behind'], open=['attention.menu:tag.known_zone_behind'])
def sC_3(hub):
    sC_2(hub)


@settled('C-3')
def sC_3_ok(hub):
    return sC_2_ok(hub)


@scenario('C-4', 0, 4, 'Inventory › Cubes: every record, filter and search', 'Inventory › Cubes: 모든 레코드, 필터와 검색',
          '#/inventory/cubes', hl=['inventory.table', 'inventory.search'])
def sC_4(hub):
    pass


@settled('C-4')
def sC_4_ok(hub):
    return len((hub.sections.get('inventory') or {}).get('rows') or []) >= 2


@scenario('C-5', 0, 5, 'Sync ↑3 ↓2 and the Web sync plan', 'Sync ↑3 ↓2 및 Web sync 계획',
          '#/inventory/websync', hl=['websync.plan', 'topbar.sync'])
def sC_5(hub):
    simdocs.docs_sync(hub, 'local', up=3, down=2, inventory_up=2, inventory_down=2, zone_publish=True, web_version=31, local_version=32)
    hub.sync['plan'] = dict(checked_at=hub.wall(), upload=2, download=2, lost=[], notes=['Zone database: publish v33 (2 changed mappings)'],
                            rows=[dict(mac=sim(hub)['known_mac'], change='upload', local='#44 · 04:A2:2B:1C:53:80:01', web='#44 · (no tag)', after='#44 · 04:A2:2B:1C:53:80:01', decided=False),
                                  dict(mac=sim(hub)['cube45'].mac, change='upload', local='#45', web='—', after='#45', decided=False),
                                  dict(mac='34:85:18:00:00:12', change='download', local='—', web='#12 · 04:11:22:33:44:55:66', after='#12 · 04:11:22:33:44:55:66', decided=False),
                                  dict(mac='34:85:18:00:00:13', change='download', local='—', web='#13', after='#13', decided=False)])
    hub.mark_dirty('sync')


@settled('C-5')
def sC_5_ok(hub):
    return bool((hub.sections.get('sync') or {}).get('plan'))


@scenario('C-6', 0, 6, 'Sign in once: the web password is stored on this computer', '한 번만 로그인: 웹 비밀번호는 이 컴퓨터에 저장',
          '#/inventory/websync', hl=['sync.signin'], open=['sync.signin'])
def sC_6(hub):
    hub.sync['password_known'] = False
    simdocs.docs_sync(hub, 'signin', message='Sign in to the web inventory', password_known=False)


@settled('C-6')
def sC_6_ok(hub):
    return not hub.sync['password_known']


@scenario('C-7', 0, 7, 'General Radio: cubes and show verbs on one dongle', 'General Radio: 하나의 동글로 큐브와 쇼 명령',
          lambda hub: f'#/devices/{device(hub, "radio").id}/cubes?cube=44', hl=['radio.set_zone', 'radio.show_start'])
def sC_7(hub):
    pass


@settled('C-7')
def sC_7_ok(hub):
    s = session(hub, 'radio')
    return bool(s and s.controller.connected)


@scenario('C-8', 0, 8, 'General Radio: a pool lamp held under lease', 'General Radio: 리스로 유지되는 풀 램프',
          lambda hub: f'#/devices/{device(hub, "radio").id}/pool', hl=['radio.pool', 'radio.pool_release'])
def sC_8(hub):
    d = device(hub, 'radio')
    simdocs.doc_hold(hub, d.id)
    cmd(hub, 'radio.pool', member=7, device=d.id)


@settled('C-8')
def sC_8_ok(hub):
    s = session(hub, 'radio')
    return bool(s and s.snapshot().get('pool_held') == 7)


@scenario('C-9', 0, 9, 'This computer: USB intake, locks and builds', '이 컴퓨터: USB 인테이크, 잠금과 빌드',
          '#/devices/computer', hl=['computer.intake', 'usb.auto_cubes'])
def sC_9(hub):
    pass


@settled('C-9')
def sC_9_ok(hub):
    return True


def chapters():
    out = {}
    for s in SCENARIOS:
        out.setdefault(s['chapter'], []).append(s)
    return out


def run_setup(hub, id):
    s = by_id(id)
    reset(hub)
    s['setup'](hub)
    return True


def is_settled(hub, id):
    s = by_id(id)
    return bool(s['settled'](hub)) if s['settled'] else True
