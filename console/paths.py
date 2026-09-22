"""sys.path for the console. Import this first in every console module.

The existing apps are flat modules (no packages) that find each other through `sys.path.insert`.
The console reuses their pure modules, so it puts the same directories on the path once, in a
fixed order, before any of them run their own inserts. Every app directory also has an `app.py`;
the console never imports a module called `app` (its own script is `console/app.py`).

Name clashes to remember: `firmware` is zones/calibration/firmware.py (alias `pool_firmware`),
`build` is flashing_station/build.py (alias `cube_build`), `hardware_check` exists twice and is
never imported here.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONSOLE = ROOT / 'console'
ORDER = ['pairing_station', 'flashing_station', 'zones/tools', 'zones/flasher', 'zones/dbmanager',
         'zones/calibration', 'rangetest']


def setup():
    for relative in reversed(ORDER):
        path = str(ROOT / relative)
        while path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)
    if str(CONSOLE) not in sys.path:
        sys.path.insert(0, str(CONSOLE))


setup()


def load_app_module(alias, relative):
    """Load an app's `app.py` under `alias` (for modules that only live in an app file)."""
    if alias in sys.modules:
        return sys.modules[alias]
    spec = importlib.util.spec_from_file_location(alias, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module
