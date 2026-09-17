"""Explicit hardware test: briefly lights members 1, 16, 17, 23, then releases."""
import json
import sys
import time
import serial

with serial.Serial(sys.argv[1], 115200, timeout=0.1, write_timeout=1) as port:
    def wait_for(predicate, timeout=3):
        end = time.monotonic()+timeout
        while time.monotonic()<end:
            line = port.readline().decode(errors='replace').strip()
            try: data = json.loads(line)
            except ValueError: continue
            if predicate(data): return data
        raise AssertionError('Expected bridge state not received')
    def send(text): port.write((text+'\n').encode())
    try:
        send('OFF'); send('STATUS')
        initial = wait_for(lambda s: s.get('device')=='PoolRadioTest' and s['ready'])
        assert initial['channel']==2, initial
        send('SET 1 16 17 23 0 0')
        active = wait_for(lambda s:s.get('members')==[1,16,17,23,0,0])
        send('SET 24 0 0 0 0 0')
        send('STATUS')
        unchanged = wait_for(lambda s:s.get('members')==[1,16,17,23,0,0])
        cleared = wait_for(lambda s:s.get('members')==[0]*6 and not s['armed'], 4)
        assert cleared['queued']>initial['queued']
        assert cleared['errors']==0, cleared
        print('PASS identity, channel 2, member boundaries, malformed-command rejection, USB watchdog, queued ESP-NOW sends')
        print(json.dumps(cleared))
    finally: send('OFF')
