"""PoolZone firmware + cube database updates; preserves calibration and zone identity."""
import json
import re
import sqlite3
from pathlib import Path
import shutil
import sys
import time
import uuid

import serial
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'flasher'))
sys.path.insert(0,str(ROOT.parent/'pairing_station'))
from port_lock import PortLock
from zone_flash import Runner, tool_command, ports, parse_report, MAC_RE, ZoneFlasher
import zone_build
from zone_flash import DEFAULT_DATABASE, Database, ZoneStore, zonedb


ANSI = re.compile(r'\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))')

def clean_output(text):
    text=ANSI.sub('',str(text))
    return ''.join(c for c in text if c in '\n\t' or ord(c)>=32).strip()

class FlashRunner(Runner):
    def __init__(self, emit, logfile):
        super().__init__(emit,logfile)
        self.errors=[]
    def line(self,line):
        line=clean_output(line)
        if re.search(r'(?:fatal error:|error:|A fatal error|Error:)',line,re.I): self.errors.append(line)
        if line: super().line(line)
    def __call__(self,args,timeout=90):
        self.errors=[]
        try: return super().__call__(args,timeout)
        except Exception as exc:
            useful=self.errors[0] if self.errors else clean_output(str(exc)).split('\n')[0]
            raise RuntimeError(useful[:300]+' — full details in the log below.') from exc


def ensure_build(runner,emit):
    try:
        manifest=zone_build.load_manifest('PoolZone')
    except (ValueError,OSError,KeyError,TypeError) as exc:
        emit('stage','Building firmware: '+str(exc))
        zone_build.build('PoolZone',runner)
        return zone_build.load_manifest('PoolZone')
    emit('stage',f'Using existing verified build {manifest["version"]} · no compilation needed')
    return manifest


def snapshot(port, timeout=4, require_calibration=True):
    text=''; calibration=None; report=None
    with serial.Serial(port,115200,timeout=.1,write_timeout=.3,exclusive=True) as conn:
        conn.write(b'HOST DISARM\n?\nCAL GET\n')
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            line=conn.readline().decode(errors='replace').strip()
            text+=line+'\n'
            try: data=json.loads(line)
            except ValueError: data=None
            if isinstance(data,dict) and data.get('device')=='PoolZoneCalibration' and data.get('type')=='calibration': calibration=data
            report=parse_report(text)
            if report and calibration is not None: return report, calibration
    if report and not require_calibration:
        return report, calibration
    raise RuntimeError('No PoolZone report/calibration response. Connect to a configured PoolZone first.')


def verify_calibration(before, after):
    if before is not None and any(after.get(k)!=before.get(k) for k in ('ticks','anchors')):
        raise RuntimeError('Firmware booted but calibration verification failed; backup retained.')


def check_identity(report, bootloader_mac):
    if not report['firmware'].startswith('pool-') or report.get('zone_type')!=3:
        raise RuntimeError('Selected board is not configured as PoolZone; no firmware written.')
    if report['mac'].upper()!=bootloader_mac.upper():
        raise RuntimeError('Board identity changed; no firmware written.')


def check_layout(backup, table):
    if len(backup)!=0x400000: raise RuntimeError('Incomplete full-flash backup; no firmware written.')
    if backup[0x8000:0x8000+len(table)]!=table:
        raise RuntimeError('Partition layout differs. Use Zone Flasher for initial setup/migration; no firmware written.')


def status(report, calibration):
    if not report:
        return 'unknown', 'Detecting firmware on the connected USB line…'
    if not report.get('firmware','').startswith('pool-') or report.get('zone_type')!=3:
        return 'unsupported', f'Detected {report.get("firmware","unknown")}: not a configured PoolZone. Use Zone Flasher for setup.'
    version=zone_build.firmware_version('PoolZone')
    expected='h'+zone_build.source_hash('PoolZone')
    installed=(calibration or {}).get('build_id')
    if installed==expected and report['firmware']==version:
        return 'current', f'Up to date · {version} · build {expected[1:11]}'
    if not installed or installed=='unknown':
        return 'update', f'Update available · installed {report["firmware"]} (build fingerprint unavailable) → local {version}'
    return 'update', f'Update available · installed {report["firmware"]} / {installed[1:11]} → local {version} / {expected[1:11]}'


def local_database(publish=False, path=DEFAULT_DATABASE):
    path=Path(path)
    if not path.is_file(): raise RuntimeError('Pairing database is missing; refusing to replace cube mappings.')
    if publish:
        db=Database(path,recover_pending=False)
        try: return ZoneStore(db).publish()
        finally: db.close()
    # Read-only preview: checking versions must not publish or modify the master database.
    conn=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.3)
    try:
        conn.row_factory=sqlite3.Row
        with conn:
            conn.execute('BEGIN')
            rows=[dict(r) for r in conn.execute("SELECT d.* FROM devices d LEFT JOIN device_roles r ON r.mac=d.mac WHERE COALESCE(r.role,'auto')!='excluded'")]
            meta=dict(conn.execute('SELECT key,value FROM metadata'))
        records=zonedb.records_from_rows(rows)
        version=int(meta.get('zone_db_version',0))
        if zonedb.content_hash(records)!=meta.get('zone_db_hash'): version+=1
        return zonedb.Publication(version,records)
    finally: conn.close()


def database_status(report, publication):
    target=f'Local v{publication.version} · {publication.count} cubes'
    if not report: return 'unknown', 'Board database: waiting · '+target
    installed=f'Board v{report.get("db_version",0)} · {report.get("db_count",0)} cubes · CRC {report.get("db_crc",0):08X}'
    matches=all(report.get(k)==v for k,v in dict(db_version=publication.version,db_count=publication.count,db_crc=publication.crc).items())
    if matches: return 'current', installed+' · in sync with '+target
    if report.get('db_version',0)>publication.version:
        return 'ahead', installed+' · newer than '+target+'; check the master database before updating'
    return 'update', installed+' · needs '+target


def database_plan(backup, publication):
    slots=[zonedb.parse_slot(backup[o:o+0x8000]) for o in (0x211000,0x219000)]
    valid=[i for i in range(2) if slots[i]]
    active=max(valid,key=lambda i:(slots[i]['version'],slots[i]['generation'],-i)) if valid else None
    current=slots[active] if active is not None else None
    if current and current['version']>publication.version:
        raise RuntimeError('Board database is newer than the local master; refusing a database rollback.')
    if current and (current['version'],current['count'],current['crc'])==(publication.version,publication.count,publication.crc): return None
    inactive=1-active if active is not None else 0
    generation=max((s['generation'] for s in slots if s),default=0)+1
    image=zonedb.slot_image(publication.records,publication.version,generation).ljust(0x8000,b'\xff')
    if len(image)!=0x8000: raise RuntimeError('Cube database exceeds slot capacity.')
    return (0x211000,0x219000)[inactive],image


def record_zone_status(report, source='poolzone-calibration', detail=None):
    """Write this board's row in the shared zones table.

    Previously this happened only as a side effect of a flash, so a board that was
    merely inspected or tuned never appeared in the registry.
    """
    if not report or not report.get('mac'): raise RuntimeError('No board report to record.')
    db=Database(DEFAULT_DATABASE,recover_pending=False)
    try:
        store=ZoneStore(db)
        store.seen(report['mac'],report,source=source)
        if detail:
            with store.conn: store.conn.execute('UPDATE zones SET detail=? WHERE mac=?',(detail[:400],report['mac']))
    finally: db.close()
    return report['mac']


POOL_POINTS = zone_build.PROFILES['pool']['points']
POOL_ZONE_TYPE = zone_build.PROFILES['pool']['zone_type']


def pool_radios():
    """Every pool board the registry knows, newest sighting first."""
    db=Database(DEFAULT_DATABASE,recover_pending=False)
    try:
        rows=ZoneStore(db).conn.execute(
            'SELECT mac,name,point_id,firmware,last_seen FROM zones WHERE zone_type=? ORDER BY point_id,mac',
            (POOL_ZONE_TYPE,)).fetchall()
    finally: db.close()
    return [dict(mac=r[0],name=r[1],point_id=r[2],firmware=r[3],last_seen=r[4]) for r in rows]


def radio_id_conflicts(mac, point_id, radios=None):
    """Other boards already using this radio id.

    Two sliders sharing an id land in the same slot at the central and contradict each
    other about what that id is doing, which reaches the lamps as unexplained flicker.
    """
    radios=pool_radios() if radios is None else radios
    return [r for r in radios if r['point_id']==point_id and (r['mac'] or '').upper()!=(mac or '').upper()]


def suggest_radio_id(mac, radios=None):
    """Lowest id no other board is using, or None when all six are taken."""
    radios=pool_radios() if radios is None else radios
    return next((p for p in POOL_POINTS if not radio_id_conflicts(mac,p,radios)),None)


def assign_radio_id(port_name, new_id, emit, force=False):
    """Rewrite just this board's zcfg identity, preserving firmware, calibration and database.

    Only the 4 KiB zcfg sector is written. NVS (where the slider calibration and tuning
    live) and both database slots are read before and after and must be byte-identical.
    """
    if new_id not in POOL_POINTS:
        raise RuntimeError(f'Radio ID must be one of {", ".join(str(p) for p in POOL_POINTS)}.')
    folder=Path(__file__).parent/'build'/'radio-id-runs'/uuid.uuid4().hex
    folder.mkdir(parents=True)
    runner=FlashRunner(emit,folder/'assign.log')
    selected=next((p for p in ports() if p['port']==port_name),None)
    if not selected or not selected['candidate']: raise RuntimeError('Select a connected ESP32 PoolZone board.')
    partitions=zone_build.parse_partitions(ROOT/'firmware/PoolZone/partitions.csv')
    zcfg,zdb_a,zdb_b=partitions['zcfg'],partitions['zdb_a'],partitions['zdb_b']
    nvs=partitions['nvs']
    with PortLock(port_name):
        emit('stage','Checking PoolZone identity…')
        before,_=snapshot(port_name,require_calibration=False)
        check_identity(before,before['mac'])
        if before.get('point_id')==new_id:
            return dict(mac=before['mac'],point_id=new_id,name=before.get('name'),skipped=True,log=str(folder/'assign.log'))
        conflicts=radio_id_conflicts(before['mac'],new_id)
        if conflicts and not force:
            who=', '.join(f"{c['name'] or 'unnamed'} ({c['mac']})" for c in conflicts)
            raise RuntimeError(f'Radio ID {new_id} is already used by {who}. Give that board a different ID first, '
                               'or re-run with override if it has been retired.')
        name=zone_build.PROFILES['pool']['name'].format(point=new_id)
        connected=False
        def tool(*args,after='no-reset-stub',timeout=90):
            nonlocal connected
            current=next((p for p in ports() if p['port']==port_name),None)
            if not current or current['key']!=selected['key']: raise RuntimeError('USB board disconnected or changed; nothing written.')
            result=runner(tool_command()+['--chip','esp32c3','--port',port_name,'--baud','460800','--before',
                         'no-reset' if connected else 'default-reset','--after',after,*args],timeout)
            connected=True
            return result
        try:
            identity=tool('read-mac')
            match=MAC_RE.search(identity)
            if not match: raise RuntimeError('Bootloader did not report board identity.')
            check_identity(before,match[1])
            emit('stage','Reading current identity and protected regions…')
            current_path=folder/'zcfg-before.bin'
            tool('read-flash',hex(zcfg['offset']),hex(zcfg['size']),current_path)
            current=current_path.read_bytes()
            parsed=zonedb.parse_config(current)
            # Proves we are reading the identity sector and not some other part of flash.
            if not parsed or parsed['zone_type']!=POOL_ZONE_TYPE or parsed['point_id']!=before.get('point_id'):
                raise RuntimeError('Zone identity sector does not match the board report; nothing written. '
                                   'Use the Zone Flasher for initial setup or migration.')
            params=zonedb.parse_params(current)
            protected={}
            for label,part in (('nvs',nvs),('zdb_a',zdb_a),('zdb_b',zdb_b)):
                path=folder/f'{label}-before.bin'
                tool('read-flash',hex(part['offset']),hex(part['size']),path)
                protected[label]=(part,path.read_bytes())
            image=zonedb.zcfg_image(POOL_ZONE_TYPE,new_id,name,params).ljust(zcfg['size'],b'\xff')
            target=folder/'zcfg-after.bin'; target.write_bytes(image)
            emit('stage',f'Assigning radio ID {new_id} ({name})…')
            tool('write-flash',hex(zcfg['offset']),target)
            tool('verify-flash',hex(zcfg['offset']),target)
            emit('stage','Verifying calibration and database were untouched…')
            for label,(part,expected) in protected.items():
                path=folder/f'{label}-after.bin'
                tool('read-flash',hex(part['offset']),hex(part['size']),path)
                if path.read_bytes()!=expected:
                    raise RuntimeError(f'{label} changed unexpectedly; previous identity kept at {current_path}')
        finally:
            if connected:
                try: tool('read-mac',after='watchdog-reset' if selected.get('native_usb') else 'hard-reset',timeout=15)
                except Exception as exc: runner.line('Reset: '+str(exc))
        emit('stage','Checking reboot and new identity…')
        report=ZoneFlasher(folder/'unused.sqlite3',emit).boot_report(selected,runner)
        expected={k:before[k] for k in ('mac','channel','zone_type','firmware','db_version','db_count','db_crc')}
        expected.update(point_id=new_id,name=name)
        if not report or any(report.get(k)!=v for k,v in expected.items()):
            raise RuntimeError('Identity written, but boot verification failed. See '+str(folder/'assign.log'))
    record_zone_status(report,source='poolzone-radio-id')
    return dict(mac=report['mac'],point_id=new_id,name=name,previous=before.get('point_id'),
                backup=str(current_path),log=str(folder/'assign.log'),skipped=False)


def flash(port_name, emit, database_only=False):
    folder=Path(__file__).parent/'build'/'firmware-runs'/uuid.uuid4().hex
    folder.mkdir(parents=True)
    runner=FlashRunner(emit,folder/'upload.log')
    selected=next((p for p in ports() if p['port']==port_name),None)
    if not selected or not selected['candidate']: raise RuntimeError('Select a connected ESP32 PoolZone board.')
    with PortLock(port_name):
        emit('stage','Checking PoolZone identity and calibration…')
        before,calibration=snapshot(port_name,require_calibration=False)
        check_identity(before,before['mac'])
        if calibration is None:
            emit('log','Legacy firmware has no calibration response. Full flash will be backed up; NVS remains unchanged and cube database updates are verified before reboot.')
        state, detail = status(before,calibration)
        emit('stage',detail)
        publication=local_database(publish=True)
        db_state, db_detail=database_status(before,publication)
        emit('stage',db_detail)
        if db_state=='ahead': raise RuntimeError(db_detail)
        if database_only:
            # Leave a current application alone; only the A/B database slot is rewritten.
            if db_state != 'update': raise RuntimeError('Cube database is already current on this board.')
            state = 'current'
        if state == 'current' and db_state=='current':
            return dict(port=port_name,version=before['firmware'],db_version=publication.version,db_count=publication.count,backup='',log=str(folder/'upload.log'),skipped=True)
        manifest=ensure_build(runner,emit)
        # Freeze checked artifacts so another build cannot change this upload mid-flight.
        for segment in manifest['segments']:
            target=folder/segment['file']
            shutil.copyfile(zone_build.build_dir('PoolZone')/segment['file'],target)
            if zone_build.digest(target)!=segment['sha256']: raise RuntimeError('Build changed while preparing upload.')
        (folder/'before.json').write_text(json.dumps(dict(report=before,calibration=calibration),indent=2))
        connected=False
        def tool(*args,after='no-reset-stub',timeout=180):
            nonlocal connected
            current=next((p for p in ports() if p['port']==port_name),None)
            if not current or current['key']!=selected['key']: raise RuntimeError('USB board disconnected or changed; upload stopped.')
            result=runner(tool_command()+['--chip','esp32c3','--port',port_name,'--baud','460800','--before',
                         'no-reset' if connected else 'default-reset','--after',after,*args],timeout)
            connected=True
            return result
        try:
            identity=tool('read-mac')
            match=MAC_RE.search(identity)
            if not match: raise RuntimeError('Bootloader did not report board identity.')
            check_identity(before,match[1])
            emit('stage','Backing up full flash…')
            backup_path=folder/'backup.bin'
            tool('read-flash','0','0x400000',backup_path,timeout=240)
            backup=backup_path.read_bytes()
            table=(folder/'PoolZone.ino.partitions.bin').read_bytes()
            check_layout(backup,table)
            app=next(s for s in manifest['segments'] if s['file']=='PoolZone.ino.bin')
            if app['offset']!=0x10000 or app['size']>0x200000: raise RuntimeError('Unexpected application layout.')
            if state != 'current':
                emit('stage',f'Flashing {manifest["version"]}…')
                tool('write-flash','0x10000',folder/app['file'])
            emit('stage','Verifying firmware and preserved calibration/database…')
            if not database_only:
                tool('verify-flash','0x10000',folder/app['file'])
            expected_flash=bytearray(backup)
            plan=database_plan(backup,publication)
            if plan:
                offset,image=plan
                emit('stage',f'Updating cube database v{publication.version} · {publication.count} mappings…')
                # Keep the active slot intact. Stage records with an invalid header, then
                # commit the first sector (header + first records) only after verification.
                staged=folder/'database-staged.bin'; staged.write_bytes(b'\xff'*24+image[24:])
                committed=folder/'database.bin'; committed.write_bytes(image)
                header=folder/'database-commit-sector.bin'; header.write_bytes(image[:0x1000])
                tool('write-flash',hex(offset),staged)
                tool('verify-flash',hex(offset),staged)
                tool('write-flash',hex(offset),header)
                tool('verify-flash',hex(offset),committed)
                expected_flash[offset:offset+0x8000]=image
            for name,offset,size in [('nvs',0x9000,0x5000),('zone-data',0x210000,0x11000)]:
                path=folder/f'{name}-after.bin'
                tool('read-flash',hex(offset),hex(size),path)
                if path.read_bytes()!=expected_flash[offset:offset+size]: raise RuntimeError(f'{name} changed unexpectedly; backup retained at {backup_path}')
        finally:
            if connected:
                try: tool('read-mac',after='watchdog-reset' if selected.get('native_usb') else 'hard-reset',timeout=15)
                except Exception as exc: runner.line('Reset: '+str(exc))
        emit('stage','Checking reboot and firmware version…')
        report=ZoneFlasher(folder/'unused.sqlite3',emit).boot_report(selected,runner)
        expected={k:before[k] for k in ('mac','channel','zone_type','point_id','name')}
        expected.update(firmware=before['firmware'] if database_only else manifest['version'],
                        db_version=publication.version,db_count=publication.count,db_crc=publication.crc)
        if not report or any(report.get(k)!=v for k,v in expected.items()):
            raise RuntimeError('Flash verified, but boot/identity verification failed. See '+str(folder/'upload.log'))
        current=next((p for p in ports() if p['key']==selected['key']),None)
        if not current: raise RuntimeError('Firmware written but USB port did not return.')
        # A database-only update leaves the original firmware running, so a legacy board
        # still will not answer CAL GET afterwards; only require what we expect to get.
        _,after=snapshot(current['port'],require_calibration=True if not database_only else calibration is not None)
        if not database_only and after.get('build_id') != 'h'+manifest['source_hash']:
            raise RuntimeError('Firmware booted but build fingerprint does not match.')
        # A legacy board has no calibration to compare; verify_calibration tolerates None.
        verify_calibration(calibration,after)
    record_zone_status(report,source='poolzone-database' if database_only else 'poolzone-flash')
    # A database-only update does not change the application; report what is running.
    result=dict(port=current['port'],version=before['firmware'] if database_only else manifest['version'],
                db_version=publication.version,db_count=publication.count,backup=str(backup_path),log=str(folder/'upload.log'))
    (folder/'result.json').write_text(json.dumps(result,indent=2))
    emit('stage',('Cube database verified · firmware and calibration untouched · reconnecting…'
                  if database_only else
                  'Firmware and cube database verified · NVS preserved · reconnecting…'))
    return result
