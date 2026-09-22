#!/usr/bin/env python3
"""NCT Console: every operator tool in one window.

  python console/app.py [--database PATH] [--api-port N] [--browser] [--debug] [--simulate]

The owner thread (hub.py) holds SQLite, every serial session and the jobs; pywebview owns the
process main thread for the native window. --browser serves the same page to the default browser.
--simulate runs against fake boards (no hardware) so the whole interface can be exercised.
"""
import paths  # noqa: F401
import argparse
import sys
import time
from pathlib import Path

import hostos

from api import Api
from hub import Hub
from locks import AlreadyOpen, InstanceLocks

DEFAULT_DATABASE = paths.ROOT / 'pairing_station' / 'data' / 'devices.sqlite3'


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--database', type=Path, default=DEFAULT_DATABASE)
    parser.add_argument('--api-port', type=int, default=None, help='loopback Python API port (default 8765; off in --simulate unless given; 0 disables)')
    parser.add_argument('--browser', action='store_true', help='open in the default browser instead of a native window')
    parser.add_argument('--debug', action='store_true', help='developer tools in the native window')
    parser.add_argument('--simulate', action='store_true', help='fake boards instead of USB (uses a temporary database copy)')
    parser.add_argument('--scenario', default='default', choices=['default', 'docs', 'empty'], help='with --simulate: which fake boards')
    parser.add_argument('--no-open', action='store_true', help='with --browser: print the URL instead of opening it')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    database = args.database
    if args.simulate:
        import shutil
        import tempfile
        folder = Path(tempfile.mkdtemp(prefix='nct-console-sim-'))
        database = folder / 'devices.sqlite3'
        if args.database.exists():
            shutil.copyfile(args.database, database)
    database.parent.mkdir(parents=True, exist_ok=True)
    try:
        locks = InstanceLocks(database)
    except AlreadyOpen as exc:
        print(str(exc), file=sys.stderr)
        return refuse(str(exc), args)
    api_port = args.api_port if args.api_port is not None else (0 if args.simulate else 8765)
    hub = Hub(database, api_port=api_port, simulate=args.simulate)
    hub.own_locks = locks.held
    if args.simulate:
        if args.scenario == 'docs':
            import simdocs
            simdocs.install(hub)
        else:
            from simulate import install
            install(hub, args.scenario)
    api = Api(hub)
    hub.start_thread()
    try:
        deadline = time.monotonic() + 15
        while not hub.booted and time.monotonic() < deadline and hub.thread.is_alive():
            time.sleep(0.05)
        if args.browser or not native_available():
            from httpbridge import Bridge
            bridge = Bridge(api)
            url = bridge.start(open_browser=not args.no_open)
            print(f'NCT Console: {url}', flush=True)
            if hub.api:
                print(f'NCT Console API: {hub.api.url} · token {hub.api.config}', flush=True)
            try:
                while hub.thread.is_alive() and not hub.stopping.is_set():
                    time.sleep(0.5)
            except KeyboardInterrupt:
                pass
            finally:
                try:
                    hub.call(hub.shutdown, True).result(timeout=20)
                except Exception:
                    pass
                bridge.stop()
        else:
            from window import run_native
            run_native(hub, api, debug=args.debug)
            if not hub.stopping.is_set():
                try:
                    hub.call(hub.shutdown, True).result(timeout=20)
                except Exception:
                    pass
    finally:
        hub.stopping.set()
        locks.close()
    return 0


def native_available():
    if not hostos.webview2_available():
        return False
    try:
        import webview  # noqa: F401
    except Exception:
        return False
    return True


def refuse(message, args):
    if args.browser:
        return 1
    try:
        import webview
        webview.create_window('NCT Console', html=f'<body style="font-family:sans-serif;padding:2em;background:#101720;color:#e9f0f7">'
                                                  f'<h2>Cannot start</h2><p>{message}</p></body>', width=640, height=240)
        webview.start()
    except Exception:
        pass
    return 1


if __name__ == '__main__':
    sys.exit(main())
