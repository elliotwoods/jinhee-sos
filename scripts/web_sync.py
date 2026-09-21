#!/usr/bin/env python3
"""Headless web inventory sync: `status` or `sync`. Uses the stored password (asks once and saves it).

`sync` never needs a decision: when two computers changed the same device the newest change wins;
what was decided, and what a device on this computer gave up, is printed.
"""
import argparse
from getpass import getpass
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'pairing_station'))
import web_client
from web_client import DEFAULT_DATASET, DEFAULT_SERVER, WebClient, WebError
import web_status
import web_sync


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('status', 'sync'))
    parser.add_argument('--database', type=Path, default=ROOT/'pairing_station/data/devices.sqlite3')
    parser.add_argument('--server', default=DEFAULT_SERVER)
    parser.add_argument('--dataset', default=DEFAULT_DATASET)
    args = parser.parse_args()
    client = WebClient(args.server, dataset=args.dataset, client=web_client.client_name('CLI'))
    prompted = not client.password
    if prompted:
        client.password = getpass('Web inventory password (stored on this computer): ')
    try:
        if args.command == 'status':
            print(web_status.summarize(args.database, client)[1])
            if prompted:
                client.head()
                web_client.save_password(client.password)
            return
        result = web_sync.run(args.database, client, web_client.client_name('CLI'))
        if prompted:
            web_client.save_password(client.password)
        for line in [note['text'] for note in result['notes']] + [entry['text'] for entry in result['lost']]:
            print('Decided: ' + line)
        print(f"Revision {result['revision']}: uploaded {len(result['uploaded'])}, "
              f"applied {len(result['download']) if result['applied'] else 0}, waiting {result['unapplied']}.")
        if result.get('sightings') is not None:
            print(f"Reported last-seen data for {result['sightings']} cubes.")
        if result['unapplied']:
            print('Close the pairing and flashing apps, then sync again to apply the waiting web changes.')
    except web_client.Unauthorized as exc:
        web_client.forget_password()
        raise SystemExit('Web sync stopped: ' + str(exc) + ' (stored password cleared; run again to enter it)')
    except web_sync.SyncBusy as exc:
        raise SystemExit(str(exc))
    except (WebError, ValueError, OSError) as exc:
        note = ' (nothing is lost; run again to check what the web received)' if getattr(exc, 'after_push', False) else ''
        raise SystemExit('Web sync stopped: ' + str(exc) + note)


if __name__ == '__main__':
    main()
