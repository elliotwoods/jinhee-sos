#!/usr/bin/env python3
"""Run with both desktop apps closed, before committing and after pulling."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'pairing_station'))
from database import Database
from inventory_sync import AppsOpen, app_locks, sync


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=ROOT/'pairing_station/data/devices.sqlite3')
    parser.add_argument('--inventory', type=Path, default=ROOT/'inventory/devices')
    args = parser.parse_args()
    args.database.parent.mkdir(parents=True, exist_ok=True)
    try:
        with app_locks(args.database):
            db = Database(args.database, recover_pending=False)
            try:
                print(f'Synchronized {sync(db, args.inventory)} inventory records.')
            finally:
                db.close()
    except AppsOpen:
        raise SystemExit('Close the pairing and flashing apps before synchronizing inventory.')
    except (ValueError, OSError) as exc:
        raise SystemExit('Inventory sync stopped: ' + str(exc))


if __name__ == '__main__':
    main()
