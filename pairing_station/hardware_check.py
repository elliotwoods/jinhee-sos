#!/usr/bin/env python3
"""Read-only station handshake + repeated discovery; never registers or flashes cubes."""
import argparse
import json
import time
from transport import Transport
import queue

parser=argparse.ArgumentParser()
parser.add_argument('--port',default='/dev/cu.usbmodem101')
parser.add_argument('--seconds',type=int,default=10)
args=parser.parse_args()
link=Transport()
link.open(args.port)
start=time.monotonic();last_ping=last_discovery=0
ready=False;devices=set();hello=None
try:
    link.send(dict(cmd='hello',id='check-hello'))
    while time.monotonic()-start<args.seconds:
        now=time.monotonic()
        if ready and now-last_ping>1:
            link.send(dict(cmd='ping',id='check-ping'));last_ping=now
        if ready and now-last_discovery>2:
            link.send(dict(cmd='discover',id='check-discover'));last_discovery=now
        try: event=link.inbox.get(timeout=.1)
        except queue.Empty: continue
        if event.get('event')=='hello':
            hello=event;ready=bool(event.get('radio_ok'));print(json.dumps(event),flush=True)
        elif event.get('event')=='device':
            devices.add(event['mac']);print(json.dumps(event),flush=True)
        elif event.get('event') not in ('pong','radio','discover_sent'):
            print(json.dumps(event),flush=True)
    print(json.dumps(dict(station=hello,discovered=sorted(devices))),flush=True)
finally:
    link.close()
