"""Application-only updates for an already configured PoolZone; preserves all device data."""
import json
import re
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


def snapshot(port, timeout=4):
    text=''; calibration=None
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
    raise RuntimeError('No PoolZone report/calibration response. Connect to a configured PoolZone first.')


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


def flash(port_name, emit):
    folder=Path(__file__).parent/'build'/'firmware-runs'/uuid.uuid4().hex
    folder.mkdir(parents=True)
    runner=FlashRunner(emit,folder/'upload.log')
    selected=next((p for p in ports() if p['port']==port_name),None)
    if not selected or not selected['candidate']: raise RuntimeError('Select a connected ESP32 PoolZone board.')
    with PortLock(port_name):
        emit('stage','Checking PoolZone identity and calibration…')
        before,calibration=snapshot(port_name)
        check_identity(before,before['mac'])
        state, detail = status(before,calibration)
        emit('stage',detail)
        if state == 'current':
            return dict(port=port_name,version=before['firmware'],backup='',log=str(folder/'upload.log'),skipped=True)
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
            emit('stage',f'Flashing {manifest["version"]} · application only…')
            tool('write-flash','0x10000',folder/app['file'])
            emit('stage','Verifying firmware and preserved calibration/database…')
            tool('verify-flash','0x10000',folder/app['file'])
            for name,offset,size in [('nvs',0x9000,0x5000),('zone-data',0x210000,0x11000)]:
                path=folder/f'{name}-after.bin'
                tool('read-flash',hex(offset),hex(size),path)
                if path.read_bytes()!=backup[offset:offset+size]: raise RuntimeError(f'{name} changed unexpectedly; backup retained at {backup_path}')
        finally:
            if connected:
                try: tool('read-mac',after='watchdog-reset' if selected.get('native_usb') else 'hard-reset',timeout=15)
                except Exception as exc: runner.line('Reset: '+str(exc))
        emit('stage','Checking reboot and firmware version…')
        report=ZoneFlasher(folder/'unused.sqlite3',emit).boot_report(selected,runner)
        expected={k:before[k] for k in ('mac','channel','zone_type','point_id','name','db_version','db_count','db_crc')}
        expected['firmware']=manifest['version']
        if not report or any(report.get(k)!=v for k,v in expected.items()):
            raise RuntimeError('Flash verified, but boot/identity verification failed. See '+str(folder/'upload.log'))
        current=next((p for p in ports() if p['key']==selected['key']),None)
        if not current: raise RuntimeError('Firmware written but USB port did not return.')
        _,after=snapshot(current['port'])
        if after.get('build_id') != 'h'+manifest['source_hash']:
            raise RuntimeError('Firmware booted but build fingerprint does not match.')
        if any(after.get(k)!=calibration.get(k) for k in ('ticks','anchors')):
            raise RuntimeError('Firmware booted but calibration verification failed; backup retained.')
    result=dict(port=current['port'],version=manifest['version'],backup=str(backup_path),log=str(folder/'upload.log'))
    (folder/'result.json').write_text(json.dumps(result,indent=2))
    emit('stage','Firmware verified · calibration preserved · reconnecting…')
    return result
