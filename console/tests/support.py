"""Shared helpers for the console tests: path setup, a temporary database and a simulated hub."""
import os
import sys
import tempfile
import time
from pathlib import Path

CONSOLE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONSOLE))
import paths  # noqa: E402,F401

os.environ.setdefault('NCT_INVENTORY_PASSWORD_FILE', str(Path(tempfile.mkdtemp()) / 'web_password'))


def temp_database():
    return Path(tempfile.mkdtemp(prefix='nct-console-test-')) / 'devices.sqlite3'


def simulated_hub(scenario='default', seed=True, auto_firmware=False):
    """`auto_firmware`: leave automatic builds and USB firmware upgrades on (autoupgrade.py). Off by default so
    other tests are not raced by a simulated upgrade of the station or the General Radio."""
    from hub import Hub
    import simulate
    simulate.BOARDS.clear()
    hub = Hub(temp_database(), api_port=0, simulate=True)
    simulate.install(hub, scenario)
    hub.boot()
    if not auto_firmware:
        hub.settings.update(auto_build=False, auto_firmware_usb=False)
    if seed and scenario == 'default':
        hub._sim_seed()
    return hub


def docs_hub():
    """The documentation bench (simdocs), booted and seeded, for scenario tests."""
    from hub import Hub
    import simulate
    import simdocs
    simulate.BOARDS.clear()
    hub = Hub(temp_database(), api_port=0, simulate=True)
    simdocs.install(hub)
    hub.boot()
    return hub


def run_ticks(hub, n=30, dt=0.02):
    for _ in range(n):
        hub.tick()
        time.sleep(dt)


def tick_until(hub, predicate, timeout=6.0, dt=0.02):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        hub.tick()
        if predicate():
            return True
        time.sleep(dt)
    return predicate()


def section(hub, name):
    return hub.pull()['sections'].get(name, {}).get('data')
