"""Hardware E2E: bridge USB -> ESP-NOW -> central FRAME logs.

Close the GUI first. Does not reflash either board. Leaves all slots off.
Usage: python e2e_check.py SENDER_PORT CENTRAL_PORT
"""
import argparse
import json
import time
from pathlib import Path
import serial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sender')
    parser.add_argument('central')
    args = parser.parse_args()
    output = Path(__file__).resolve().parents[1] / 'build' / 'e2e-latest.log'
    output.parent.mkdir(exist_ok=True)
    with output.open('w') as log, serial.Serial(args.sender, 115200, timeout=0, write_timeout=1, exclusive=True) as tx, serial.Serial(args.central, 115200, timeout=0, exclusive=True) as rx:
        buffers = {'TX': b'', 'RX': b''}
        frames = set()
        events = []
        status = {}
        i2c_errors = []
        last_ping = 0
        start = time.monotonic()

        def record(text):
            line = f'{time.monotonic()-start:8.3f} {text}'
            print(line, flush=True)
            log.write(line+'\n')
            log.flush()

        def send(command):
            tx.write((command+'\n').encode())
            if command != 'PING': record('COMMAND '+command)

        def pump(duration, ping=True):
            nonlocal last_ping, status
            end = time.monotonic()+duration
            while time.monotonic()<end:
                if ping and time.monotonic()-last_ping > .3:
                    send('PING'); last_ping = time.monotonic()
                for label, port in [('TX',tx), ('RX',rx)]:
                    buffers[label] += port.read(4096)
                    while b'\n' in buffers[label]:
                        raw, buffers[label] = buffers[label].split(b'\n',1)
                        line = raw.decode(errors='replace').strip()
                        if not line: continue
                        record(label+' '+line)
                        if label == 'TX':
                            try: status = json.loads(line)
                            except ValueError: pass
                        else:
                            events.append(line)
                            if 'I2C ERROR' in line: i2c_errors.append(line)
                            parts = line.split()
                            if len(parts)==3 and parts[0]=='FRAME' and parts[1].isdigit():
                                member=int(parts[1])
                                if parts[2]=='ON': frames.add(member)
                                elif parts[2]=='OFF': frames.discard(member)
                time.sleep(.005)

        def expect(expected, required, timeout=2.5, ping=True):
            end = time.monotonic()+timeout
            while time.monotonic()<end:
                pump(.03,ping)
                if frames == set(expected) and all(e in events for e in required): return
            raise AssertionError(f'Expected frames {sorted(expected)} and events {required}; got frames {sorted(frames)}, events {events}')

        try:
            record(f'PORTS sender={args.sender} central={args.central}')
            send('OFF'); send('STATUS'); pump(1)
            assert status.get('device')=='PoolRadioTest' and status.get('ready'), status
            assert status['channel']==2, status
            initial_errors=status['errors']
            events.clear()
            for member in range(1,24):
                events.clear()
                send(f'SET {member} 0 0 0 0 0')
                expect({member},[f'RADIO 1 -> MEMBER {member}', f'FRAME {member} ON'])
                events.clear()
                send('OFF')
                expect(set(),[f'FRAME {member} OFF'])
            record('PASS all 23 individual light ON/OFF commands received by central')
            events.clear()
            selected=[1,5,9,13,17,23]
            send('SET '+' '.join(map(str,selected)))
            expect(selected,[f'RADIO {i+1} -> MEMBER {m}' for i,m in enumerate(selected)]+[f'FRAME {m} ON' for m in selected])
            pump(2)
            assert frames==set(selected), frames
            assert not any('TIMEOUT' in e or e.endswith(' OFF') for e in events), events
            record('PASS all six radio slots and sustained heartbeat')
            events.clear()
            send('OFF')
            expect(set(),[f'FRAME {m} OFF' for m in selected])
            record('PASS all-off release received by central')
            events.clear()
            send('SET 23 0 0 0 0 0')
            expect({23},['FRAME 23 ON'])
            events.clear()
            expect(set(),['FRAME 23 OFF'],timeout=3,ping=False)
            assert not status.get('armed'),status
            assert status['errors']==initial_errors,status
            record('PASS host-watchdog release received by central; no new send errors')
            record('RESULT PASS: USB -> ESP-NOW channel 2 -> central frame ON/OFF handler.')
            record(f'I2C write errors observed during test: {len(i2c_errors)}. Physical light emission not measured.')
        finally:
            send('OFF')
            pump(.3)


if __name__=='__main__': main()
