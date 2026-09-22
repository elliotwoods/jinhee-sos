"""One hardware owner. Subprocess output and serial telemetry become UI events."""
import json
import os
import queue
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
import serial
from serial.tools import list_ports
from core import ROOT, Store, PortLock, atomic_json, timestamp, PROTECTED, digest
import hostos

TOOL_ENTRY = Path(__file__).resolve().with_name('esptool_entry.py')

def tool_command():
    return [sys.executable, '-u', str(TOOL_ENTRY)]

MAC_RE = re.compile(r'(?i)MAC:\s*([0-9a-f]{2}(?::[0-9a-f]{2}){5})')

def ports():
    result=[]
    for p in list_ports.comports():
        if '/tty.' in p.device: continue
        result.append(dict(port=p.device, key=p.serial_number or p.location or p.device,
            description=p.description, candidate=p.vid in {0x303a,0x10c4,0x1a86,0x0403} and (p.serial_number or '').upper() not in PROTECTED,
            serial=p.serial_number, location=p.location, native_usb=p.vid==0x303a and p.pid==0x1001))
    return result

def validate_partition(data):
    if data == b'\xff'*len(data): return 'Blank flash'
    records=[]
    for i in range(0,len(data),32):
        chunk=data[i:i+32]
        if len(chunk)<32 or chunk[:2] in (b'\xff\xff', b'\xeb\xeb'): break
        magic,kind,sub,offset,size,label,flags=struct.unpack('<HBBII16sI',chunk)
        if magic!=0x50aa: raise ValueError('Unrecognized partition table; preserving flash, no upload')
        records.append((kind,sub,offset,size,label.rstrip(b'\0')))
    nvs=[r for r in records if r[0:2]==(1,2)]
    if len(nvs)!=1 or nvs[0][2:4]!=(0x9000,0x5000):
        raise ValueError('Incompatible NVS layout; no upload performed')
    return 'Compatible NVS layout'

class Runner:
    def __init__(self, emit, logfile=None): self.emit,self.logfile=emit,logfile
    def line(self,line):
        if self.logfile:
            with self.logfile.open('a',encoding='utf-8') as f: f.write(line+'\n')
        self.emit('log',line)
        m=re.search(r'(\d+(?:\.\d+)?)\s*%',line)
        if m: self.emit('progress',float(m[1]))
    def __call__(self,args,timeout=90):
        started=time.monotonic()
        self.line('$ '+' '.join(map(str,args)))
        env=os.environ.copy()
        for key in ('PYTHONHOME','PYTHONEXECUTABLE','__PYVENV_LAUNCHER__'):
            env.pop(key,None)
        env['PYTHONUTF8']='1'  # the tool's output is decoded as UTF-8 below, whatever the console codepage
        p=subprocess.Popen(list(map(str,args)),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                           text=True,encoding='utf-8',errors='replace',bufsize=1,env=env,cwd=str(TOOL_ENTRY.parent),
                           **hostos.quiet_kwargs())
        q=queue.Queue()
        def read():
            for line in p.stdout: q.put(line.rstrip())
            q.put(None)
        threading.Thread(target=read,daemon=True).start()
        lines=[]; deadline=time.monotonic()+timeout
        try:
            while True:
                if time.monotonic()>deadline: raise TimeoutError('Tool timed out; reconnect and retry manually')
                try: line=q.get(timeout=.1)
                except queue.Empty: continue
                if line is None: break
                lines.append(line); self.line(line)
            code=p.wait(timeout=3)
            if any('No module named' in line for line in lines):
                raise RuntimeError('Flashing tool could not load its Python dependencies: '+ '\n'.join(lines[-8:]))
            if code: raise RuntimeError('\n'.join(lines[-8:]) or f'Tool exited {code}')
        except BaseException:
            p.kill();p.wait();raise
        finally: p.stdout.close()
        self.line(f'Tool completed in {time.monotonic()-started:.2f}s')
        return '\n'.join(lines)

class Flasher:
    def __init__(self, database, emit): self.database,self.emit=database,emit
    def execute(self, port, manifest, manual=False, session_start=None):
        ident=uuid.uuid4().hex
        folder=ROOT/'data'/'runs'/ident;folder.mkdir(parents=True)
        log=folder/'upload.log'; runner=Runner(self.emit,log)
        db=Store(self.database); mac=None; result='failed';detail=''; written=False
        record=dict(id=ident,port=port['port'],version=manifest['version'],build_hash=manifest['build_hash'],log_path=str(log))
        def stage(name):
            db.update_run(ident,stage=name)
            self.emit('stage',name)
        try:
            db.start(ident,port['port'],manifest,log)
            # Freeze the checked build for this attempt, independent of later rebuilds.
            for segment in manifest['segments']:
                target=folder/segment['file']
                shutil.copyfile(ROOT/'build'/segment['file'], target)
                if digest(target) != segment['sha256']:
                    raise RuntimeError('Firmware changed during preparation; rebuild and retry')
            usb_mac = (port.get('serial') or '').upper()
            if usb_mac and db.protected(usb_mac):
                raise RuntimeError('Protected registration station USB identity; serial port was not opened')
            with PortLock(port['port']):
                stage('Check flashing tool')
                tool_version=runner(tool_command()+['version'],timeout=10)
                if '5.3.1' not in tool_version:
                    raise RuntimeError('Flashing tool did not start correctly; expected esptool 5.3.1. '+tool_version[-500:])
                connected = False
                def tool(*args,after='no-reset-stub',timeout=120):
                    nonlocal connected
                    current = next((p for p in ports() if p['port']==port['port']), None)
                    if current is None:
                        raise RuntimeError('USB device disconnected; reconnect and retry manually')
                    if db.protected((current.get('serial') or '').upper()):
                        raise RuntimeError('Protected registration station; serial port was not opened')
                    if current['key'] != port['key']:
                        raise RuntimeError('USB identity changed; upload stopped')
                    before = 'no-reset' if connected else 'default-reset'
                    output = runner(tool_command()+['--chip','esp32c3','--port',port['port'],'--baud','460800',
                                     '--before',before,'--after',after,*args],timeout)
                    connected = True
                    return output
                stage('Identify')
                identity=tool('flash-id')
                match=MAC_RE.search(identity)
                if not match: raise RuntimeError('ESP32 bootloader did not report a MAC; no firmware was written. Check the tool log and USB connection.')
                mac=match[1].upper();record['mac']=mac;db.update_run(ident,mac=mac)
                native_usb = 'USB-Serial/JTAG' in identity
                port = dict(port, native_usb=native_usb)
                reset_mode = 'watchdog-reset' if native_usb else 'hard-reset'
                self.emit('identity',dict(mac=mac,chip='ESP32-C3',flash='4 MB',port=port['port']))
                if db.protected(mac): raise RuntimeError('Protected station/reader MAC: upload blocked')
                if not manual and session_start and db.conn.execute(
                    "SELECT 1 FROM flash_runs WHERE mac=? AND started_at>=? AND id<>? AND result NOT IN ('success','skipped','running')",
                    (mac,session_start,ident)).fetchone():
                    raise RuntimeError('Earlier attempt needs attention; select Manual Retry')
                if not re.search(r'Detected flash size:\s*4\s*MB',identity,re.I):
                    raise RuntimeError('Requires a 4 MB XIAO ESP32-C3')
                if not manual and db.seen(mac,manifest['build_hash']):
                    result='skipped'; detail='This MAC already completed this firmware build'
                    tool('read-mac',after=reset_mode)
                else:
                    row=db.reserve(mac,source='usb_flash');self.emit('device',row)
                    stage('Back up registration')
                    table=folder/'partitions.bin';nvs=folder/'nvs.bin'
                    backup=folder/'registration-region.bin'
                    tool('read-flash','0x8000','0x6000',backup)
                    raw=backup.read_bytes()
                    table.write_bytes(raw[:0x1000]);nvs.write_bytes(raw[0x1000:])
                    runner.line(validate_partition(table.read_bytes()))
                    if nvs.stat().st_size != 0x5000:
                        raise RuntimeError('Incomplete NVS backup; upload blocked')
                    stage('Write and verify')
                    args=['write-flash','--flash-mode','dio','--flash-freq','80m','--flash-size','4MB']
                    for segment in manifest['segments']:
                        args += [hex(segment['offset']), folder/segment['file']]
                    tool(*args,timeout=180)
                    written=True
                    stage('Check preserved registration')
                    after=folder/'nvs-after.bin';tool('read-flash','0x9000','0x5000',after,after=reset_mode)
                    if after.read_bytes()!=nvs.read_bytes(): raise RuntimeError('Registration storage changed unexpectedly; backup retained')
                    stage('Confirm boot')
                    if self.boot(port,mac,manifest['version'],runner):
                        result='success';detail='Firmware verified · boot confirmed · registration preserved'
                    else:
                        result='boot_unconfirmed';detail='Firmware verified; boot not confirmed. Use Check boot, without reflashing.'
            record.update(result=result,detail=detail,finished_at=timestamp())
            # Durable independent receipt permits DB recovery without another write to hardware.
            atomic_json(folder/'receipt.json',record)
            db.update_run(ident,result=result,detail=detail,finished_at=record['finished_at'],stage='Complete')
        except Exception as exc:
            detail=str(exc); result='failed' if not written else 'attention'
            record.update(result=result,detail=detail,finished_at=timestamp(),written=written)
            receipt=folder/'receipt.json'
            if receipt.exists():
                record=json.loads(receipt.read_text(encoding='utf-8'));result='save_failed';detail='Hardware result saved locally; database save failed: '+str(exc)
            else: atomic_json(receipt,record)
            runner.line(detail)
            try: db.update_run(ident,result=result,detail=detail,finished_at=timestamp())
            except Exception: pass
        finally:
            db.close()
        return dict(**record,ui_result=result,ui_detail=detail)

    def boot(self, original, mac, version, runner):
        db = Store(self.database)
        try:
            protected = {m for m,role in db.roles().items() if role=='excluded'} | PROTECTED
        finally:
            db.close()
        if (original.get('serial') or '').upper() in protected or mac in protected:
            raise RuntimeError('Protected registration station; serial port was not opened')
        deadline=time.monotonic()+12; text='';last_error=None
        while time.monotonic()<deadline:
            candidates=[p for p in ports() if p['key']==original['key']]
            if not candidates:
                time.sleep(.3);continue
            path=candidates[0]['port']
            try:
                if candidates and (candidates[0].get('serial') or '').upper() in protected:
                    raise RuntimeError('Protected registration station; serial port was not opened')
                conn = serial.Serial(port=None,baudrate=115200,timeout=.2,exclusive=True)
                native_usb = original.get('native_usb',False)
                conn.dtr = not native_usb; conn.rts = not native_usb; conn.port = path
                conn.open()
                if not native_usb:
                    conn.rts = False; conn.dtr = False
                with conn:
                    while time.monotonic()<deadline:
                        conn.write(b'?')
                        line=conn.read(4096).decode(errors='replace')
                        if line: runner.line(line.rstrip());text+=line
                        if f'FW: {version}' in text and f'Cube MAC: {mac}' in text and 'ESP-NOW CHANNEL: 2' in text and 'Cube READY' in text:
                            return True
            except (OSError,serial.SerialException) as exc:
                if str(exc)!=last_error:runner.line('Waiting for USB boot: '+str(exc));last_error=str(exc)
                time.sleep(.2)
        return False
