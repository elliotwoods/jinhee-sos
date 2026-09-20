"""Exercise live PoolZone override/expiry; may turn a pool light on for a few seconds."""
import argparse
import json
from pathlib import Path
import time
import serial


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('port')
    args=parser.parse_args()
    evidence=[]
    with serial.Serial(args.port,115200,timeout=.05,write_timeout=.2,exclusive=True) as port:
        def send(command):
            evidence.append('> '+command); port.write((command+'\n').encode())
        def read_for(seconds, keepalive=False):
            end=time.monotonic()+seconds; next_ping=0; rows=[]
            while time.monotonic()<end:
                if keepalive and time.monotonic()>next_ping:
                    send('HOST PING'); next_ping=time.monotonic()+.35
                line=port.readline().decode(errors='replace').strip()
                if not line: continue
                evidence.append(line)
                try: d=json.loads(line)
                except ValueError: continue
                rows.append(d)
            return rows
        try:
            send('HOST DISARM'); send('?'); send('CAL GET')
            rows=read_for(1)
            cal=next(d for d in rows if d.get('type')=='calibration')
            before_path=Path(__file__).parent/'build/calibration-before-integration.json'
            if before_path.exists():
                before=json.loads(before_path.read_text())
                assert cal['ticks']==before['ticks'] and cal['anchors']==before['anchors'] and cal['saved']
            states=[d for d in rows if d.get('type')=='interaction']
            assert states and states[-1]['nfc'] and states[-1]['radio']
            assert not states[-1]['tag'], 'Remove NeoCube before the no-tag override test'
            assert not states[-1]['active'] and states[-1]['output']==0
            start=states[-1]['queued']
            send('HOST ARM')
            rows=read_for(2.5,keepalive=True)
            states=[d for d in rows if d.get('type')=='interaction']
            assert states[-1]['override'] and states[-1]['active']
            assert states[-1]['queued']-start>=10
            assert any(d['output']>0 for d in states), 'Place slider over a calibrated index for light-command verification'
            rows=read_for(2)
            state=[d for d in rows if d.get('type')=='interaction'][-1]
            assert not state['override'] and not state['active'] and state['output']==0
            send('HOST PING'); rows=read_for(.4)
            assert not [d for d in rows if d.get('type')=='interaction'][-1]['override']
            send('HOST ARM'); read_for(.3); send('HOST DISARM')
            rows=read_for(.4)
            assert not [d for d in rows if d.get('type')=='interaction'][-1]['override']
            assert any(line.startswith('FW: pool-') for line in evidence)
            print('PASS saved calibration, NFC/radio ready, tagless default OFF, armed light command + heartbeat, watchdog expiry, late-ping refusal, explicit disarm')
        finally:
            send('HOST DISARM')
            directory=Path(__file__).parent/'build'; directory.mkdir(exist_ok=True)
            (directory/'integration-hardware.log').write_text('\n'.join(evidence)+'\n')

if __name__=='__main__': main()
