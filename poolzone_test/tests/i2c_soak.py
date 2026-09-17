"""Live register-verified soak, mode fault recovery, and USB-monitor absence test."""
import json
import time
from pathlib import Path
import serial

ALL=(1<<23)-1
log=Path(__file__).resolve().parents[1]/'build/i2c-soak.log'

class Rig:
    def __init__(self):
        self.tx=serial.Serial('/dev/cu.usbmodem101',115200,timeout=0,write_timeout=1,exclusive=True)
        self.rx=serial.Serial('/dev/cu.usbmodem2101',115200,timeout=0,write_timeout=1,exclusive=True)
        self.buffers={'TX':b'','RX':b''}
        self.status={}; self.sender={}; self.events=[]
        self.started=time.monotonic(); self.ping=0
        self.log=log.open('w')
    def record(self,line):
        text=f'{time.monotonic()-self.started:8.3f} {line}'
        self.log.write(text+'\n'); self.log.flush()
        if line.startswith(('PASS','PHASE','RESULT','FAIL')): print(text,flush=True)
    def send(self,text): self.tx.write((text+'\n').encode())
    def read(self,duration=.05):
        end=time.monotonic()+duration
        while time.monotonic()<end:
            if time.monotonic()-self.ping>.3:
                self.send('PING'); self.ping=time.monotonic()
            for name,p in [('TX',self.tx),('RX',self.rx)]:
                if p is None: continue
                self.buffers[name]+=p.read(8192)
                while b'\n' in self.buffers[name]:
                    raw,self.buffers[name]=self.buffers[name].split(b'\n',1)
                    line=raw.decode(errors='replace').strip()
                    self.record(name+' '+line)
                    try: data=json.loads(line)
                    except ValueError:
                        if name=='RX': self.events.append(line)
                        continue
                    if name=='RX' and data.get('device')=='PoolCentralTest': self.status=data
                    elif name=='TX' and data.get('device')=='PoolRadioTest': self.sender=data
            time.sleep(.005)
    def wait(self, predicate, timeout=4):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            self.read()
            if predicate(self.status): return self.status
        raise AssertionError(f'Timed out; receiver state: {self.status}')
    def current(self):
        self.status={}; self.rx.write(b'STATUS\n')
        return self.wait(lambda s:s.get('version')==2)
    def check(self,members,timeout=3):
        mask=sum(1<<(m-1) for m in set(members) if m)
        self.status={}
        self.rx.write(b'STATUS\n')
        return self.wait(lambda s:s.get('desired')==mask and s.get('verified')==mask and s.get('known')==ALL and all(b['online'] and b['mode1']&0x7f==0x20 and b['mode2']==4 for b in s['boards']),timeout)
    def select(self,members):
        slots=list(members)+[0]*(6-len(members))
        self.send('SET '+' '.join(map(str,slots)))
        self.read(.20)
        return self.check(members)
    def close(self):
        self.send('OFF'); self.read(.4)
        self.tx.close()
        if self.rx:self.rx.close()
        self.log.close()

r=Rig()
try:
    r.send('OFF'); r.read(1)
    baseline=r.check([])
    assert baseline['channel']==2 and baseline['sda']==1 and baseline['scl']==1,baseline
    r.record('PASS both PCA9685 boards online with correct MODE1/MODE2; all 23 registers verified off')
    initial_errors=baseline['i2c_errors']; initial_mismatch=baseline['mismatches']
    r.record('PHASE repeated member toggles and six-slot patterns with register readback')
    for cycle in range(3):
        for member in range(1,24):
            r.select([member]); r.select([])
        for offset in range(10):
            r.select([1+(offset+i*4)%23 for i in range(6)])
        r.record(f'PASS soak cycle {cycle+1}/3; errors={r.status["i2c_errors"]}, mismatches={r.status["mismatches"]}')
    assert r.status['i2c_errors']==initial_errors and r.status['mismatches']==initial_mismatch,r.status
    assert not any('RADIO TIMEOUT' in e for e in r.events),r.events[-30:]
    r.record('PASS 138 individual ON/OFF transitions plus 30 six-slot patterns; no unexpected timeout, I2C error or mismatch')
    r.select([1,17,23])
    for address in [64,65]:
        before=r.current()
        r.record(f'PHASE inject sleep/AI-loss into PCA9685 {address:#x}')
        r.rx.write(f'TEST_SLEEP {address}\n'.encode())
        r.wait(lambda s:s.get('mismatches',0)>before['mismatches'] and s.get('recoveries',0)>before['recoveries'],5)
        r.check([1,17,23],5)
        r.record(f'PASS PCA9685 {address:#x} detected invalid mode and recovered requested outputs')
    before=r.current()
    r.rx.write(b'RECOVER\n')
    r.wait(lambda s:s.get('recoveries',0)>before['recoveries'])
    r.check([1,17,23])
    r.record('PASS explicit open-drain bus recovery + board reinitialization + output restore')
    r.record('PHASE 45 seconds wireless switching with receiver USB monitor closed')
    before=r.current()
    r.rx.close(); r.rx=None
    end=time.monotonic()+45; iteration=0
    while time.monotonic()<end:
        member=iteration%23+1
        r.send(f'SET {member} 0 0 0 0 0')
        r.read(.2)
        iteration+=1
    r.send('SET 2 16 17 23 0 0'); r.read(.3)
    r.rx=serial.Serial('/dev/cu.usbmodem2101',115200,timeout=0,write_timeout=1,exclusive=True)
    r.buffers['RX']=b''
    after=r.check([2,16,17,23],5)
    assert after['uptime_ms']>before['uptime_ms']+40000,after
    assert after['rx_packets']>before['rx_packets']+1400,after
    assert after['i2c_errors']==before['i2c_errors'],after
    assert after['mismatches']==before['mismatches'],after
    r.record(f'PASS USB monitor absent: {iteration} switches, rx delta={after["rx_packets"]-before["rx_packets"]}, log drops={after["log_drops"]}, no reboot or I2C error')
    r.select([])
    r.record('RESULT PASS all register checks, automatic PCA mode recovery, bus recovery and sustained wireless operation')
    r.record('FINAL '+json.dumps(r.status))
except Exception as e:
    r.record('FAIL '+repr(e))
    raise
finally:r.close()
