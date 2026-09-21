#!/usr/bin/env python3
"""Headless web inventory sync: `status` or `sync`. Asks for the password each run.

`sync` never resolves conflicts; use inventory_web/app.py to choose a side.
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
    password = getpass('Web inventory password: ')  # asked every run, never stored
    client = WebClient(args.server, password, args.dataset, client=web_client.client_name('CLI'))
    try:
        if args.command == 'status':
            print(web_status.summarize(args.database, client)[1])
            return
        result = web_sync.run(args.database, client, web_client.client_name('CLI'))
        if result['conflicts']:
            raise SystemExit('Nothing changed. Resolve conflicts in the Web Sync app: ' + ', '.join(result['conflicts']))
        print(f"Revision {result['revision']}: uploaded {len(result['upload'])}, "
              f"applied {len(result['download']) if result['applied'] else 0}, waiting {result['unapplied']}.")
        if result['unapplied']:
            print('Close the pairing and flashing apps, then sync again to apply the waiting web changes.')
    except (WebError, ValueError, OSError) as exc:
        raise SystemExit('Web sync stopped: ' + str(exc))


if __name__ == '__main__':
    main()
